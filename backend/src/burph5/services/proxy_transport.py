from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import AsyncIterator

import httpx
from httpx import URL

from burph5.models import Header, ProxyFlowSummary
from burph5.services.parser import ensure_host_header, render_request_target, resolve_url
from burph5.services.proxy_capture import ProxyCaptureStore, ProxyFlowRecorder


REQUEST_HOP_BY_HOP_HEADERS = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "proxy-connection",
    "te",
    "trailer",
    "transfer-encoding",
    "upgrade",
}

RESPONSE_HOP_BY_HOP_HEADERS = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailer",
    "transfer-encoding",
    "upgrade",
}


@dataclass(slots=True)
class ProxyRequestMessage:
    method: str
    target: str
    version: str
    headers: list[Header]
    body: bytes
    authority: str | None = None


class ProxyRequestBodyStream:
    def __init__(
        self,
        *,
        reader: asyncio.StreamReader,
        initial_body: bytes,
        headers: list[Header],
        recorder: ProxyFlowRecorder,
    ) -> None:
        self._reader = reader
        self._buffer = initial_body
        self._headers = headers
        self._recorder = recorder

    def __aiter__(self) -> AsyncIterator[bytes]:
        return self._iterate()

    async def _iterate(self) -> AsyncIterator[bytes]:
        transfer_encoding = self._header("transfer-encoding")
        if transfer_encoding and "chunked" in transfer_encoding.lower():
            async for chunk in self._iterate_chunked():
                yield chunk
            return

        content_length = self._content_length()
        if content_length <= 0:
            return

        remaining = content_length
        if self._buffer:
            chunk = self._buffer[:remaining]
            self._buffer = self._buffer[len(chunk) :]
            remaining -= len(chunk)
            self._recorder.write_request_body(chunk)
            yield chunk

        while remaining > 0:
            chunk = await self._reader.read(min(65536, remaining))
            if not chunk:
                raise ValueError("Unexpected EOF while streaming request body.")
            remaining -= len(chunk)
            self._recorder.write_request_body(chunk)
            yield chunk

    async def _iterate_chunked(self) -> AsyncIterator[bytes]:
        buffer = self._buffer
        while True:
            size_line, buffer = await self._read_line(buffer)
            chunk_size = int(size_line.split(b";", 1)[0].strip() or b"0", 16)
            if chunk_size == 0:
                while True:
                    trailer_line, buffer = await self._read_line(buffer)
                    if trailer_line == b"":
                        return
            chunk, buffer = await self._read_exact(buffer, chunk_size)
            self._recorder.write_request_body(chunk)
            yield chunk
            _, buffer = await self._read_exact(buffer, 2)

    async def _read_line(self, buffer: bytes) -> tuple[bytes, bytes]:
        while b"\r\n" not in buffer:
            chunk = await self._reader.read(4096)
            if not chunk:
                raise ValueError("Unexpected EOF while reading chunked request body.")
            buffer += chunk
        line, _, rest = buffer.partition(b"\r\n")
        return line, rest

    async def _read_exact(self, buffer: bytes, size: int) -> tuple[bytes, bytes]:
        while len(buffer) < size:
            chunk = await self._reader.read(size - len(buffer))
            if not chunk:
                raise ValueError("Unexpected EOF while reading request body.")
            buffer += chunk
        return buffer[:size], buffer[size:]

    def _content_length(self) -> int:
        value = self._header("content-length")
        return int(value) if value else 0

    def _header(self, name: str) -> str | None:
        for header in self._headers:
            if header.name.lower() == name.lower():
                return header.value
        return None


class ProxyTransport:
    def __init__(self, capture_store: ProxyCaptureStore) -> None:
        self._capture_store = capture_store
        self._client = httpx.AsyncClient(http2=True, timeout=None, trust_env=False)

    async def close(self) -> None:
        await self._client.aclose()

    async def forward_request(
        self,
        *,
        message: ProxyRequestMessage,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
        default_scheme: str,
        is_tls_mitm: bool,
    ) -> ProxyFlowSummary:
        url = self._resolve_message_url(message, default_scheme)
        is_sse = "text/event-stream" in ((self._header(message.headers, "accept") or "").lower())
        recorder = self._capture_store.create_recorder(
            method=message.method,
            url=url,
            protocol_mode="https-mitm" if is_tls_mitm else ("sse" if is_sse else "http"),
            client_http_version=message.version,
            is_tls_mitm=is_tls_mitm,
            is_passthrough=False,
            is_websocket=False,
            is_sse=is_sse,
            request_content_type=self._header(message.headers, "content-type"),
        )
        recorder.write_request_headers(self._render_request_head(message))

        headers = self._sanitize_forward_headers(message.headers, url)
        body_stream = ProxyRequestBodyStream(
            reader=reader,
            initial_body=message.body,
            headers=message.headers,
            recorder=recorder,
        )

        response_started = False
        try:
            async with self._client.stream(
                message.method,
                url,
                headers=[(header.name, header.value) for header in headers],
                content=body_stream,
            ) as response:
                response_started = True
                recorder.summary.response_content_type = response.headers.get("content-type")
                head_bytes, chunked = self._build_response_head(message, response, recorder)
                writer.write(head_bytes)
                await writer.drain()

                async for chunk in response.aiter_raw():
                    recorder.write_response_body(chunk)
                    if chunked:
                        writer.write(f"{len(chunk):X}\r\n".encode("ascii") + chunk + b"\r\n")
                    else:
                        writer.write(chunk)
                    await writer.drain()

                if chunked:
                    writer.write(b"0\r\n\r\n")
                    await writer.drain()

                return recorder.finish(
                    status_code=response.status_code,
                    reason=response.reason_phrase,
                    upstream_http_version=response.http_version,
                )
        except Exception as exc:
            if not response_started:
                writer.write(b"HTTP/1.1 502 Bad Gateway\r\nContent-Length: 0\r\nConnection: close\r\n\r\n")
                await writer.drain()
                recorder.write_response_headers("HTTP/1.1 502 Bad Gateway\r\nContent-Length: 0\r\nConnection: close\r\n\r\n")
            return recorder.finish(error=str(exc))

    async def passthrough_upgrade(
        self,
        *,
        message: ProxyRequestMessage,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
        default_scheme: str,
        is_tls_mitm: bool,
    ) -> ProxyFlowSummary:
        url = self._resolve_message_url(message, default_scheme)
        parsed = httpx.URL(url)
        recorder = self._capture_store.create_recorder(
            method=message.method,
            url=url,
            protocol_mode="upgrade",
            client_http_version=message.version,
            is_tls_mitm=is_tls_mitm,
            is_passthrough=True,
            is_websocket=self._header(message.headers, "sec-websocket-key") is not None,
            is_sse=False,
            request_content_type=self._header(message.headers, "content-type"),
        )
        recorder.write_request_headers(self._render_request_head(message))
        if message.body:
            recorder.write_request_body(message.body)

        upstream_reader, upstream_writer = await asyncio.open_connection(
            parsed.host or "",
            parsed.port or (443 if parsed.scheme == "https" else 80),
            ssl=parsed.scheme == "https",
            server_hostname=parsed.host or None,
        )
        try:
            upstream_writer.write(self._render_passthrough_request(message, url))
            await upstream_writer.drain()
            response_head = await self._read_head(upstream_reader)
            recorder.write_response_headers(response_head.decode("latin-1", errors="replace"))
            writer.write(response_head)
            await writer.drain()

            status_code, reason = self._parse_status_line(response_head)
            await asyncio.gather(
                self._relay(reader, upstream_writer, recorder.write_request_body),
                self._relay(upstream_reader, writer, recorder.write_response_body),
                return_exceptions=True,
            )
            return recorder.finish(status_code=status_code, reason=reason, upstream_http_version="HTTP/1.1")
        except Exception as exc:
            return recorder.finish(error=str(exc))
        finally:
            upstream_writer.close()
            try:
                await upstream_writer.wait_closed()
            except Exception:
                pass

    async def relay_tunnel(
        self,
        *,
        connect_message: ProxyRequestMessage,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
        host: str,
        port: int,
    ) -> ProxyFlowSummary:
        url = f"https://{host}:{port}"
        recorder = self._capture_store.create_recorder(
            method=connect_message.method,
            url=url,
            protocol_mode="tunnel",
            client_http_version=connect_message.version,
            is_tls_mitm=False,
            is_passthrough=True,
            is_websocket=False,
            is_sse=False,
            request_content_type=None,
        )
        recorder.write_request_headers(self._render_request_head(connect_message))
        recorder.write_response_headers("HTTP/1.1 200 Connection Established\r\n\r\n")

        upstream_reader, upstream_writer = await asyncio.open_connection(host, port)
        writer.write(b"HTTP/1.1 200 Connection Established\r\n\r\n")
        await writer.drain()
        try:
            await asyncio.gather(
                self._relay(reader, upstream_writer, recorder.write_request_body),
                self._relay(upstream_reader, writer, recorder.write_response_body),
                return_exceptions=True,
            )
            return recorder.finish(status_code=200, reason="Connection Established")
        except Exception as exc:
            return recorder.finish(error=str(exc))
        finally:
            upstream_writer.close()
            try:
                await upstream_writer.wait_closed()
            except Exception:
                pass

    async def _relay(
        self,
        source: asyncio.StreamReader,
        sink: asyncio.StreamWriter,
        capture_callback,
    ) -> None:
        try:
            while not source.at_eof():
                data = await source.read(65536)
                if not data:
                    break
                capture_callback(data)
                sink.write(data)
                await sink.drain()
        finally:
            if not sink.is_closing():
                sink.close()
            try:
                await sink.wait_closed()
            except Exception:
                pass

    def _build_response_head(
        self,
        message: ProxyRequestMessage,
        response: httpx.Response,
        recorder: ProxyFlowRecorder,
    ) -> tuple[bytes, bool]:
        status_line = f"HTTP/1.1 {response.status_code} {response.reason_phrase}\r\n"
        headers = self._sanitize_response_headers(response.headers)
        should_have_body = self._response_has_body(message.method, response.status_code)
        chunked = False
        if should_have_body and "content-length" not in {name.lower() for name, _ in headers}:
            if message.version.upper() != "HTTP/1.0":
                headers.append(("Transfer-Encoding", "chunked"))
                chunked = True
        header_lines = "".join(f"{name}: {value}\r\n" for name, value in headers)
        raw_head = status_line + header_lines + "\r\n"
        recorder.write_response_headers(raw_head)
        return raw_head.encode("latin-1", errors="replace"), chunked

    def _sanitize_forward_headers(self, headers: list[Header], url: str) -> list[Header]:
        filtered = [header for header in headers if header.name.lower() not in REQUEST_HOP_BY_HOP_HEADERS]
        return ensure_host_header(filtered, url)

    def _resolve_message_url(self, message: ProxyRequestMessage, default_scheme: str) -> str:
        parsed = URL(message.target)
        if parsed.scheme and parsed.host:
            return message.target

        authority = self._header(message.headers, "host") or message.authority or ""
        if message.authority and authority and ":" not in authority and message.authority.startswith(f"{authority}:"):
            authority = message.authority
        path = message.target if message.target.startswith("/") else f"/{message.target}"
        return f"{default_scheme}://{authority}{path}"

    def _sanitize_response_headers(self, headers: httpx.Headers) -> list[tuple[str, str]]:
        return [(name, value) for name, value in headers.multi_items() if name.lower() not in RESPONSE_HOP_BY_HOP_HEADERS]

    def _render_request_head(self, message: ProxyRequestMessage) -> str:
        lines = [f"{message.method} {message.target} {message.version}"]
        lines.extend(f"{header.name}: {header.value}" for header in message.headers)
        return "\r\n".join(lines) + "\r\n\r\n"

    def _render_passthrough_request(self, message: ProxyRequestMessage, url: str) -> bytes:
        headers = [header for header in message.headers if header.name.lower() not in {"proxy-authorization", "proxy-connection"}]
        headers = ensure_host_header(headers, url)
        target = render_request_target(url)
        lines = [f"{message.method} {target} {message.version}"]
        lines.extend(f"{header.name}: {header.value}" for header in headers)
        return ("\r\n".join(lines) + "\r\n\r\n").encode("latin-1", errors="replace") + message.body

    async def _read_head(self, reader: asyncio.StreamReader) -> bytes:
        data = b""
        while b"\r\n\r\n" not in data:
            chunk = await reader.read(4096)
            if not chunk:
                break
            data += chunk
            if len(data) > 1024 * 1024:
                raise ValueError("Response head exceeded 1MB.")
        return data

    def _parse_status_line(self, raw_head: bytes) -> tuple[int | None, str | None]:
        lines = raw_head.decode("latin-1", errors="replace").split("\r\n")
        parts = lines[0].split(" ", 2) if lines and lines[0] else []
        if len(parts) < 2:
            return None, None
        return int(parts[1]), parts[2] if len(parts) > 2 else None

    def _header(self, headers: list[Header], name: str) -> str | None:
        for header in headers:
            if header.name.lower() == name.lower():
                return header.value
        return None

    def _response_has_body(self, method: str, status_code: int) -> bool:
        if method.upper() == "HEAD":
            return False
        return status_code not in {101, 204, 304}
