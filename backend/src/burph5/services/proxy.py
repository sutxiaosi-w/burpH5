from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

from burph5.models import ProxySettings


class ProxyController:
    def __init__(
        self,
        handler: Callable[[str], Awaitable[bytes]],
        settings: ProxySettings | None = None,
    ) -> None:
        self._handler = handler
        self._settings = settings or ProxySettings()
        self._server: asyncio.base_events.Server | None = None
        self._server_task: asyncio.Task[None] | None = None

    @property
    def settings(self) -> ProxySettings:
        return self._settings

    @property
    def running(self) -> bool:
        return self._server is not None

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
            head = await self._read_head(reader)
            if not head:
                return
            request_line = head.split(b"\r\n", 1)[0].decode("latin-1", errors="replace")
            if request_line.upper().startswith("CONNECT "):
                await self._handle_connect(request_line, reader, writer)
                return

            header_blob, separator, _ = head.partition(b"\r\n\r\n")
            body = await self._read_body(reader, head)
            raw_request = (header_blob + separator + body).decode("latin-1", errors="replace")
            response_bytes = await self._handler(raw_request)
            writer.write(response_bytes)
            await writer.drain()
        finally:
            writer.close()
            await writer.wait_closed()

    async def _handle_connect(
        self,
        request_line: str,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        target = request_line.split(" ", 2)[1]
        host, _, port_text = target.partition(":")
        port = int(port_text or "443")
        upstream_reader, upstream_writer = await asyncio.open_connection(host, port)
        writer.write(b"HTTP/1.1 200 Connection Established\r\n\r\n")
        await writer.drain()

        async def relay(source: asyncio.StreamReader, sink: asyncio.StreamWriter) -> None:
            try:
                while not source.at_eof():
                    data = await source.read(65536)
                    if not data:
                        break
                    sink.write(data)
                    await sink.drain()
            finally:
                sink.close()

        await asyncio.gather(
            relay(reader, upstream_writer),
            relay(upstream_reader, writer),
        )

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

    async def _read_body(self, reader: asyncio.StreamReader, head: bytes) -> bytes:
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
        return body
