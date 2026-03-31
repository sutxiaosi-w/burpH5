from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

from burph5.models import Header, ProxyFlowSummary, ProxySettings
from burph5.services.certificates import CertificateAuthority
from burph5.services.proxy_transport import ProxyRequestMessage, ProxyTransport


DEFAULT_BYPASS_HOSTS = {
    "localhost",
    "127.0.0.1",
    "::1",
}


class ProxyController:
    def __init__(
        self,
        transport: ProxyTransport,
        on_flow_complete: Callable[[ProxyFlowSummary], Awaitable[None]],
        settings: ProxySettings | None = None,
        certificate_authority: CertificateAuthority | None = None,
    ) -> None:
        self._transport = transport
        self._on_flow_complete = on_flow_complete
        self._settings = settings or ProxySettings()
        self._certificate_authority = certificate_authority
        self._server: asyncio.base_events.Server | None = None
        self._server_task: asyncio.Task[None] | None = None
        self._last_error: str | None = None

    @property
    def settings(self) -> ProxySettings:
        return self._settings

    @property
    def running(self) -> bool:
        return self._server is not None

    @property
    def last_error(self) -> str | None:
        return self._last_error

    async def apply_settings(self, settings: ProxySettings) -> ProxySettings:
        self._settings = settings
        if self.running:
            await self.stop()
        if settings.enabled:
            await self.start()
        return settings

    async def start(self) -> None:
        if self._server is not None:
            return
        self._last_error = None
        self._server = await asyncio.start_server(
            self._handle_client,
            host=self._settings.host,
            port=self._settings.port,
        )
        self._server_task = asyncio.create_task(self._server.serve_forever())

    async def stop(self) -> None:
        if self._server is None:
            return
        self._server.close()
        await self._server.wait_closed()
        self._server = None
        if self._server_task:
            self._server_task.cancel()
            try:
                await self._server_task
            except asyncio.CancelledError:
                pass
            self._server_task = None

    async def _handle_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            await self._serve_client(reader, writer)
        except Exception as exc:
            self._last_error = str(exc)
            if not writer.is_closing():
                writer.write(b"HTTP/1.1 502 Bad Gateway\r\nContent-Length: 0\r\nConnection: close\r\n\r\n")
                await writer.drain()
        finally:
            if not writer.is_closing():
                writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass

    async def _serve_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        while True:
            message = await self._read_request(reader)
            if message is None:
                return

            if message.method == "CONNECT":
                await self._handle_connect(message, reader, writer)
                return

            if self._requires_passthrough(message):
                flow = await self._transport.passthrough_upgrade(
                    message=message,
                    reader=reader,
                    writer=writer,
                    default_scheme="http",
                    is_tls_mitm=False,
                )
            else:
                flow = await self._transport.forward_request(
                    message=message,
                    reader=reader,
                    writer=writer,
                    default_scheme="http",
                    is_tls_mitm=False,
                )
            await self._on_flow_complete(flow)

            if self._should_close_after_response(message):
                return

    async def _handle_connect(
        self,
        message: ProxyRequestMessage,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        host, port = self._parse_connect_target(message.target)
        if not self._settings.capture_https or self._matches_bypass_host(host):
            flow = await self._transport.relay_tunnel(
                connect_message=message,
                reader=reader,
                writer=writer,
                host=host,
                port=port,
            )
            await self._on_flow_complete(flow)
            return

        if self._certificate_authority is None:
            raise RuntimeError("HTTPS capture requires a certificate authority.")

        writer.write(b"HTTP/1.1 200 Connection Established\r\n\r\n")
        await writer.drain()
        await writer.start_tls(self._certificate_authority.create_server_context(host), ssl_handshake_timeout=10.0)

        while True:
            tunneled_message = await self._read_request(reader)
            if tunneled_message is None:
                return
            tunneled_message.authority = f"{host}:{port}" if port not in {80, 443} else host

            if self._requires_passthrough(tunneled_message):
                flow = await self._transport.passthrough_upgrade(
                    message=tunneled_message,
                    reader=reader,
                    writer=writer,
                    default_scheme="https",
                    is_tls_mitm=True,
                )
            else:
                flow = await self._transport.forward_request(
                    message=tunneled_message,
                    reader=reader,
                    writer=writer,
                    default_scheme="https",
                    is_tls_mitm=True,
                )
            await self._on_flow_complete(flow)

            if self._should_close_after_response(tunneled_message):
                return

    async def _read_request(self, reader: asyncio.StreamReader) -> ProxyRequestMessage | None:
        head = await self._read_head(reader)
        if not head:
            return None

        header_blob, _, initial_body = head.partition(b"\r\n\r\n")
        lines = header_blob.decode("latin-1", errors="replace").split("\r\n")
        if not lines or not lines[0]:
            return None

        request_line = lines[0].strip()
        parts = request_line.split(" ", 2)
        if len(parts) < 2:
            raise ValueError("Proxy request line is invalid.")

        method = parts[0].upper()
        target = parts[1]
        version = parts[2] if len(parts) > 2 else "HTTP/1.1"
        headers = self._parse_headers(lines[1:])
        return ProxyRequestMessage(method=method, target=target, version=version, headers=headers, body=initial_body)

    async def _read_head(self, reader: asyncio.StreamReader) -> bytes:
        data = b""
        while b"\r\n\r\n" not in data:
            chunk = await reader.read(4096)
            if not chunk:
                break
            data += chunk
            if len(data) > 1024 * 1024:
                raise ValueError("Request head exceeded 1MB.")
        return data

    def _parse_headers(self, lines: list[str]) -> list:
        headers: list[Header] = []
        for line in lines:
            if not line.strip() or ":" not in line:
                continue
            name, value = line.split(":", 1)
            headers.append(Header(name=name.strip(), value=value.lstrip()))
        return headers

    def _should_close_after_response(self, message: ProxyRequestMessage) -> bool:
        connection = self._get_header(message.headers, "connection")
        if connection and "close" in connection.lower():
            return True
        return message.version.upper() == "HTTP/1.0"

    def _requires_passthrough(self, message: ProxyRequestMessage) -> bool:
        connection = (self._get_header(message.headers, "connection") or "").lower()
        upgrade = (self._get_header(message.headers, "upgrade") or "").lower()
        return "upgrade" in connection or bool(upgrade) or self._get_header(message.headers, "sec-websocket-key") is not None

    def _get_header(self, headers: list[Header], name: str) -> str | None:
        for header in headers:
            if header.name.lower() == name.lower():
                return header.value
        return None

    def _matches_bypass_host(self, host: str) -> bool:
        normalized_host = self._normalize_host(host)
        for pattern in [*DEFAULT_BYPASS_HOSTS, *self._settings.bypass_hosts]:
            normalized_pattern = self._normalize_host(pattern)
            if not normalized_pattern:
                continue
            if normalized_host == normalized_pattern or normalized_host.endswith(f".{normalized_pattern}"):
                return True
        return False

    def _parse_connect_target(self, target: str) -> tuple[str, int]:
        normalized = target.strip()
        if normalized.startswith("["):
            closing = normalized.find("]")
            if closing == -1:
                raise ValueError(f"CONNECT target is invalid: {target}")
            host = normalized[1:closing]
            remainder = normalized[closing + 1 :]
            if remainder.startswith(":"):
                return host, int(remainder[1:] or "443")
            return host, 443

        host, separator, port_text = normalized.rpartition(":")
        if separator:
            return host, int(port_text or "443")
        return normalized, 443

    def _normalize_host(self, host: str) -> str:
        normalized = host.strip().lower()
        if normalized.startswith("[") and normalized.endswith("]"):
            normalized = normalized[1:-1]
        return normalized.rstrip(".")
