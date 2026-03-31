from __future__ import annotations

import asyncio
import json
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from urllib.parse import parse_qs, urlparse

from fastapi.testclient import TestClient

from burph5.config import AppSettings
from burph5.main import create_app
from burph5.models import CollectionEntry, CollectionRunRequest, CollectionWrite, ProxySettings, ReplayExecutePayload, ReplayRequest
from burph5.service import BurpH5Service


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


def make_service(tmp_path: Path) -> BurpH5Service:
    settings = AppSettings(backend_root=tmp_path)
    return BurpH5Service(settings=settings)


def find_free_port() -> int:
    import socket

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


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
        assert "override" in (result.results[0].request.url)
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
                response = await reader.read()
                writer.close()
                await writer.wait_closed()

                assert b"200 OK" in response
                history = service.list_history(source="proxy")
                assert len(history) == 1
                assert history[0].request.url.endswith("/proxy-test")
            finally:
                await service.shutdown()

        asyncio.run(run_proxy_flow())


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

    index_response = client.get("/")
    assert index_response.status_code == 200
    assert "burph5" in index_response.text

    spa_response = client.get("/settings")
    assert spa_response.status_code == 200
    assert "burph5" in spa_response.text
