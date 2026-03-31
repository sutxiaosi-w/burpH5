from __future__ import annotations

import asyncio
import httpx
import json
import socketserver
import ssl
import subprocess
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from urllib.parse import parse_qs, urlparse

from fastapi.testclient import TestClient

from burph5.config import AppSettings
from burph5.main import create_app
from burph5.models import (
    CollectionEntry,
    CollectionRunRequest,
    CollectionWrite,
    Header,
    ProxySettings,
    ReplayExecutePayload,
    ReplayRequest,
    ReplayResult,
)
from burph5.service import BurpH5Service
from burph5.services.certificates import CertificateAuthority
from burph5.services.parser import render_raw_request
from burph5.services import proxy_transport
from burph5.services.replay import ExecutionArtifacts, build_wire_response_bytes, render_raw_response


class EchoHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        query = parse_qs(parsed.query)
        payload = {
            "method": "GET",
            "path": parsed.path,
            "query": query,
        }
        body = json.dumps(payload).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self) -> None:  # noqa: N802
        content_length = int(self.headers.get("Content-Length", "0"))
        body_text = self.rfile.read(content_length).decode("utf-8")
        payload = {
            "method": "POST",
            "path": self.path,
            "body": body_text,
        }
        body = json.dumps(payload).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:  # noqa: A003
        return


@contextmanager
def run_echo_server():
    server = ThreadingHTTPServer(("127.0.0.1", 0), EchoHandler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server.server_port
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


@contextmanager
def run_tls_echo_server(cert_path: Path, key_path: Path):
    server = ThreadingHTTPServer(("127.0.0.1", 0), EchoHandler)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(str(cert_path), str(key_path))
    server.socket = context.wrap_socket(server.socket, server_side=True)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server.server_port
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


class UpgradeHandler(socketserver.BaseRequestHandler):
    def handle(self) -> None:
        data = b""
        while b"\r\n\r\n" not in data:
            chunk = self.request.recv(4096)
            if not chunk:
                return
            data += chunk
        response = (
            b"HTTP/1.1 101 Switching Protocols\r\n"
            b"Connection: Upgrade\r\n"
            b"Upgrade: websocket\r\n\r\n"
        )
        self.request.sendall(response)


@contextmanager
def run_tls_upgrade_server(cert_path: Path, key_path: Path):
    server = socketserver.ThreadingTCPServer(("127.0.0.1", 0), UpgradeHandler)
    server.daemon_threads = True
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(str(cert_path), str(key_path))
    server.socket = context.wrap_socket(server.socket, server_side=True)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server.server_address[1]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def make_service(tmp_path: Path) -> BurpH5Service:
    settings = AppSettings(backend_root=tmp_path)
    return BurpH5Service(settings=settings)


def find_free_port() -> int:
    import socket

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def make_execution_artifacts(
    request: ReplayRequest,
    *,
    body: bytes = b"hello proxy",
    headers: list[Header] | None = None,
) -> ExecutionArtifacts:
    response_headers = headers or [
        Header(name="Content-Type", value="text/plain; charset=utf-8"),
        Header(name="Content-Encoding", value="gzip"),
        Header(name="Transfer-Encoding", value="chunked"),
        Header(name="Connection", value="keep-alive"),
    ]
    body_text = body.decode("utf-8", errors="replace")
    result = ReplayResult(
        status_code=200,
        reason="OK",
        headers=response_headers,
        body_text=body_text,
        elapsed_ms=1,
        raw_request=render_raw_request(request),
        raw_response=render_raw_response(200, "OK", response_headers, body_text, None),
    )
    return ExecutionArtifacts(
        request=request,
        result=result,
        response_content=body,
        response_wire_bytes=build_wire_response_bytes(200, "OK", response_headers, body, sanitize_for_proxy=True),
    )


async def read_http_response(reader: asyncio.StreamReader) -> bytes:
    head = await reader.readuntil(b"\r\n\r\n")
    header_blob, _, initial_body = head.partition(b"\r\n\r\n")
    content_length = 0
    for line in header_blob.decode("latin-1", errors="replace").split("\r\n")[1:]:
        if line.lower().startswith("content-length:"):
            content_length = int(line.split(":", 1)[1].strip() or "0")
            break
    body = initial_body
    remaining = max(content_length - len(body), 0)
    if remaining:
        body += await reader.readexactly(remaining)
    return header_blob + b"\r\n\r\n" + body


def test_parse_relative_request(tmp_path: Path) -> None:
    service = make_service(tmp_path)
    request = service.parse_raw(
        "POST /submit?ok=1 HTTP/1.1\r\nHost: example.com\r\nContent-Type: application/json\r\n\r\n{\"a\":1}"
    )
    assert request.method == "POST"
    assert request.url == "http://example.com/submit?ok=1"
    assert request.body_text == '{"a":1}'


def test_replay_raw_request_and_history(tmp_path: Path) -> None:
    with run_echo_server() as port:
        service = make_service(tmp_path)
        raw_request = (
            f"GET http://127.0.0.1:{port}/hello?name=test HTTP/1.1\r\n"
            f"Host: 127.0.0.1:{port}\r\n"
            "Accept: application/json\r\n\r\n"
        )
        response = asyncio.run(service.replay(ReplayExecutePayload(raw_request=raw_request, source="api")))
        assert response.result.status_code == 200
        assert '"path": "/hello"' in (response.result.body_text or "")
        history = service.list_history()
        assert len(history) == 1
        assert history[0].result.status_code == 200
        assert service.delete_history(history[0].id) is True
        assert service.get_history(history[0].id) is None
        assert service.delete_history("missing-id") is False


def test_clear_history_by_source_and_all(tmp_path: Path) -> None:
    with run_echo_server() as port:
        service = make_service(tmp_path)
        raw_request = (
            f"GET http://127.0.0.1:{port}/hello HTTP/1.1\r\n"
            f"Host: 127.0.0.1:{port}\r\n\r\n"
        )
        asyncio.run(service.replay(ReplayExecutePayload(raw_request=raw_request, source="api")))
        asyncio.run(service.replay(ReplayExecutePayload(raw_request=raw_request, source="ui")))

        deleted_api = service.clear_history(source="api")
        assert deleted_api == 1
        remaining = service.list_history()
        assert len(remaining) == 1
        assert remaining[0].source == "ui"

        deleted_all = service.clear_history()
        assert deleted_all == 1
        assert service.list_history() == []


def test_collection_run_merges_variables(tmp_path: Path) -> None:
    with run_echo_server() as port:
        service = make_service(tmp_path)
        collection = service.save_collection(
            CollectionWrite(
                name="vars",
                variables={"name": "collection-default"},
                entries=[
                    CollectionEntry(
                        name="echo",
                        request=ReplayRequest(
                            method="GET",
                            url=f"http://127.0.0.1:{port}/vars?name={{{{name}}}}",
                            headers=[],
                            timeout_ms=15000,
                            follow_redirects=True,
                            tags=[],
                            variables={},
                        ),
                    )
                ],
            )
        )
        result = asyncio.run(
            service.run_collection(
                collection.id,
                CollectionRunRequest(variables={"name": "override"}, source="api"),
            )
        )
        assert result.results[0].result.status_code == 200
        assert "override" in result.results[0].request.url
        assert "override" in (result.results[0].result.body_text or "")


def test_http_proxy_captures_and_forwards(tmp_path: Path) -> None:
    with run_echo_server() as target_port:
        service = make_service(tmp_path)
        proxy_port = find_free_port()

        async def run_proxy_flow() -> None:
            await service.update_proxy(
                ProxySettings(enabled=True, host="127.0.0.1", port=proxy_port, capture_https=False)
            )
            try:
                reader, writer = await asyncio.open_connection("127.0.0.1", proxy_port)
                request = (
                    f"GET http://127.0.0.1:{target_port}/proxy-test HTTP/1.1\r\n"
                    f"Host: 127.0.0.1:{target_port}\r\n"
                    "Connection: close\r\n\r\n"
                )
                writer.write(request.encode("latin-1"))
                await writer.drain()
                response = await read_http_response(reader)
                writer.close()
                await writer.wait_closed()

                assert b"200 OK" in response
                history = service.list_history(source="proxy")
                assert len(history) == 1
                assert history[0].request.url.endswith("/proxy-test")
            finally:
                await service.shutdown()

        asyncio.run(run_proxy_flow())


def test_certificate_authority_generates_caches_and_resets(tmp_path: Path) -> None:
    authority = CertificateAuthority(tmp_path / "certs")

    first_status = authority.ensure_ca()
    assert first_status.ready is True
    assert first_status.thumbprint is not None
    assert authority.ca_cert_path.exists()

    leaf_one = authority.issue_leaf_certificate("example.com")
    leaf_two = authority.issue_leaf_certificate("example.com")
    assert leaf_one.cert_path == leaf_two.cert_path
    assert leaf_one.key_path == leaf_two.key_path

    cached_status = authority.get_status()
    assert cached_status.leaf_cert_count == 1

    reset_status = authority.reset()
    assert reset_status.ready is True
    assert reset_status.thumbprint != first_status.thumbprint


def test_https_proxy_mitm_captures_and_sanitizes_response(tmp_path: Path, monkeypatch) -> None:
    certificate_authority = CertificateAuthority(tmp_path / "target-certs")
    leaf = certificate_authority.issue_leaf_certificate("localhost")
    with run_tls_echo_server(leaf.cert_path, leaf.key_path) as target_port:
        service = make_service(tmp_path)
        proxy_port = find_free_port()
        monkeypatch.setattr("burph5.services.proxy.DEFAULT_BYPASS_HOSTS", set())
        service.proxy_transport._client = httpx.AsyncClient(http2=True, timeout=None, trust_env=False, verify=False)

        async def run_proxy_flow() -> None:
            await service.update_proxy(
                ProxySettings(enabled=True, host="127.0.0.1", port=proxy_port, capture_https=True)
            )
            try:
                reader, writer = await asyncio.open_connection("127.0.0.1", proxy_port)
                writer.write(f"CONNECT localhost:{target_port} HTTP/1.1\r\nHost: localhost:{target_port}\r\n\r\n".encode("latin-1"))
                await writer.drain()
                connect_response = await reader.readuntil(b"\r\n\r\n")
                assert b"200 Connection Established" in connect_response

                client_context = ssl.create_default_context(cafile=str(service.certificate_authority.ca_cert_path))
                await writer.start_tls(client_context, server_hostname="localhost", ssl_handshake_timeout=10.0)
                writer.write(b"GET /mitm HTTP/1.1\r\nHost: localhost\r\nConnection: close\r\n\r\n")
                await writer.drain()
                response = await read_http_response(reader)
                writer.close()
                await writer.wait_closed()

                assert b"200 OK" in response
                assert b"Content-Encoding" not in response
                assert b"Transfer-Encoding" not in response
                history = service.list_history(source="proxy")
                assert len(history) == 1
                assert history[0].request.url.endswith("/mitm")
            finally:
                await service.shutdown()

        asyncio.run(run_proxy_flow())


def test_https_proxy_tunnels_when_capture_disabled(tmp_path: Path) -> None:
    certificate_authority = CertificateAuthority(tmp_path / "target-certs")
    leaf = certificate_authority.issue_leaf_certificate("localhost")
    with run_tls_echo_server(leaf.cert_path, leaf.key_path) as target_port:
        service = make_service(tmp_path)
        proxy_port = find_free_port()

        async def run_proxy_flow() -> None:
            await service.update_proxy(
                ProxySettings(enabled=True, host="127.0.0.1", port=proxy_port, capture_https=False)
            )
            try:
                reader, writer = await asyncio.open_connection("127.0.0.1", proxy_port)
                request = (
                    f"CONNECT localhost:{target_port} HTTP/1.1\r\n"
                    f"Host: localhost:{target_port}\r\n\r\n"
                )
                writer.write(request.encode("latin-1"))
                await writer.drain()
                connect_response = await reader.readuntil(b"\r\n\r\n")
                assert b"200 Connection Established" in connect_response

                await writer.start_tls(ssl._create_unverified_context(), server_hostname="localhost", ssl_handshake_timeout=10.0)
                writer.write(b"GET /tunnel HTTP/1.1\r\nHost: localhost\r\nConnection: close\r\n\r\n")
                await writer.drain()
                response = await read_http_response(reader)
                writer.close()
                try:
                    await writer.wait_closed()
                except TimeoutError:
                    pass

                assert b"200 OK" in response
                assert service.list_history(source="proxy") == []
            finally:
                await service.shutdown()

        asyncio.run(run_proxy_flow())


def test_https_proxy_tunnels_bypass_hosts(tmp_path: Path) -> None:
    certificate_authority = CertificateAuthority(tmp_path / "target-certs")
    leaf = certificate_authority.issue_leaf_certificate("localhost")
    with run_tls_echo_server(leaf.cert_path, leaf.key_path) as target_port:
        service = make_service(tmp_path)
        proxy_port = find_free_port()

        async def run_proxy_flow() -> None:
            await service.update_proxy(
                ProxySettings(
                    enabled=True,
                    host="127.0.0.1",
                    port=proxy_port,
                    capture_https=True,
                    bypass_hosts=["localhost"],
                )
            )
            try:
                reader, writer = await asyncio.open_connection("127.0.0.1", proxy_port)
                request = (
                    f"CONNECT localhost:{target_port} HTTP/1.1\r\n"
                    f"Host: localhost:{target_port}\r\n\r\n"
                )
                writer.write(request.encode("latin-1"))
                await writer.drain()
                connect_response = await reader.readuntil(b"\r\n\r\n")
                assert b"200 Connection Established" in connect_response

                await writer.start_tls(ssl._create_unverified_context(), server_hostname="localhost", ssl_handshake_timeout=10.0)
                writer.write(b"GET /bypass HTTP/1.1\r\nHost: localhost\r\nConnection: close\r\n\r\n")
                await writer.drain()
                response = await read_http_response(reader)
                writer.close()
                try:
                    await writer.wait_closed()
                except TimeoutError:
                    pass

                assert b"200 OK" in response
                assert service.list_history(source="proxy") == []
            finally:
                await service.shutdown()

        asyncio.run(run_proxy_flow())


def test_https_proxy_passthroughs_websocket_upgrade(tmp_path: Path, monkeypatch) -> None:
    certificate_authority = CertificateAuthority(tmp_path / "target-certs")
    leaf = certificate_authority.issue_leaf_certificate("localhost")
    with run_tls_upgrade_server(leaf.cert_path, leaf.key_path) as target_port:
        service = make_service(tmp_path)
        proxy_port = find_free_port()
        monkeypatch.setattr("burph5.services.proxy.DEFAULT_BYPASS_HOSTS", set())
        real_open_connection = asyncio.open_connection

        async def open_connection_unverified(host, port, *args, **kwargs):
            if kwargs.get("ssl") is True and host == "localhost":
                kwargs["ssl"] = ssl._create_unverified_context()
            return await real_open_connection(host, port, *args, **kwargs)

        monkeypatch.setattr(proxy_transport.asyncio, "open_connection", open_connection_unverified)

        async def run_proxy_flow() -> None:
            await service.update_proxy(
                ProxySettings(enabled=True, host="127.0.0.1", port=proxy_port, capture_https=True)
            )
            try:
                reader, writer = await asyncio.open_connection("127.0.0.1", proxy_port)
                writer.write(f"CONNECT localhost:{target_port} HTTP/1.1\r\nHost: localhost:{target_port}\r\n\r\n".encode("latin-1"))
                await writer.drain()
                connect_response = await reader.readuntil(b"\r\n\r\n")
                assert b"200 Connection Established" in connect_response

                client_context = ssl.create_default_context(cafile=str(service.certificate_authority.ca_cert_path))
                await writer.start_tls(client_context, server_hostname="localhost", ssl_handshake_timeout=10.0)
                writer.write(
                    b"GET /socket HTTP/1.1\r\n"
                    b"Host: localhost\r\n"
                    b"Connection: Upgrade\r\n"
                    b"Upgrade: websocket\r\n"
                    b"Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==\r\n"
                    b"Sec-WebSocket-Version: 13\r\n\r\n"
                )
                await writer.drain()
                response = await reader.readuntil(b"\r\n\r\n")
                writer.close()
                try:
                    await writer.wait_closed()
                except TimeoutError:
                    pass

                assert b"101 Switching Protocols" in response
                assert service.list_history(source="proxy") == []
            finally:
                await service.shutdown()

        asyncio.run(run_proxy_flow())


def test_certificate_install_and_reset_windows_paths(tmp_path: Path, monkeypatch) -> None:
    authority = CertificateAuthority(tmp_path / "certs")
    original_thumbprint = authority.ensure_ca().thumbprint
    calls: list[list[str]] = []

    def fake_run(command: list[str], capture_output: bool, text: bool, check: bool):
        calls.append(command)
        return subprocess.CompletedProcess(command, 0, stdout="MATCHED\n", stderr="")

    monkeypatch.setattr("burph5.services.certificates.subprocess.run", fake_run)
    monkeypatch.setattr("burph5.services.certificates.sys.platform", "win32")

    installed_status = authority.install_to_windows()
    assert installed_status.installed is True
    assert any("Import-Certificate" in part for part in calls[-2])

    uninstalled: list[str] = []
    monkeypatch.setattr(authority, "_uninstall_from_windows", lambda thumbprint: uninstalled.append(thumbprint))
    reset_status = authority.reset()
    assert uninstalled == [original_thumbprint]
    assert reset_status.thumbprint != original_thumbprint


def test_single_port_app_serves_spa_and_api(tmp_path: Path) -> None:
    backend_root = tmp_path / "backend"
    frontend_dist_dir = tmp_path / "frontend" / "dist"
    backend_root.mkdir(parents=True, exist_ok=True)
    frontend_dist_dir.mkdir(parents=True, exist_ok=True)
    (frontend_dist_dir / "index.html").write_text("<!doctype html><title>burph5</title><div id='app'></div>", encoding="utf-8")

    settings = AppSettings(backend_root=backend_root)
    service = BurpH5Service(settings=settings)
    client = TestClient(create_app(service=service))

    health_response = client.get("/api/health")
    assert health_response.status_code == 200
    assert health_response.json() == {"status": "ok"}

    proxy_response = client.get("/api/proxy")
    assert proxy_response.status_code == 200
    assert proxy_response.json()["ca_ready"] is False

    index_response = client.get("/")
    assert index_response.status_code == 200
    assert "burph5" in index_response.text

    spa_response = client.get("/settings")
    assert spa_response.status_code == 200
    assert "burph5" in spa_response.text
