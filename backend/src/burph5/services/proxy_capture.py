from __future__ import annotations

import base64
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from httpx import URL

from burph5.models import Header, HistoryItem, ProxyFlowDetail, ProxyFlowSummary, ProxyProtocolMode, ReplayRequest, ReplayResult
from burph5.services.parser import parse_header_lines


TEXT_CONTENT_TYPES = (
    "application/json",
    "application/javascript",
    "application/problem+json",
    "application/x-www-form-urlencoded",
    "application/xml",
    "image/svg+xml",
)

PREVIEW_LIMIT = 64 * 1024


@dataclass(slots=True)
class ProxyFlowRecorder:
    summary: ProxyFlowSummary
    _request_body_handle: object
    _response_body_handle: object

    def write_request_headers(self, raw_headers: str) -> None:
        Path(self.summary.request_headers_path).write_text(raw_headers, encoding="utf-8")

    def write_request_body(self, chunk: bytes) -> None:
        if not chunk:
            return
        self._request_body_handle.write(chunk)
        self.summary.request_body_size += len(chunk)

    def write_response_headers(self, raw_headers: str) -> None:
        Path(self.summary.response_headers_path).write_text(raw_headers, encoding="utf-8")

    def write_response_body(self, chunk: bytes) -> None:
        if not chunk:
            return
        self._response_body_handle.write(chunk)
        self.summary.response_body_size += len(chunk)

    def finish(
        self,
        *,
        status_code: int | None = None,
        reason: str | None = None,
        upstream_http_version: str | None = None,
        error: str | None = None,
    ) -> ProxyFlowSummary:
        self.summary.status_code = status_code
        self.summary.reason = reason
        self.summary.upstream_http_version = upstream_http_version
        self.summary.error = error
        self._request_body_handle.close()
        self._response_body_handle.close()
        return self.summary


class ProxyCaptureStore:
    def __init__(self, captures_dir: Path) -> None:
        self._captures_dir = captures_dir
        self._captures_dir.mkdir(parents=True, exist_ok=True)

    def create_recorder(
        self,
        *,
        method: str,
        url: str,
        protocol_mode: ProxyProtocolMode,
        client_http_version: str,
        is_tls_mitm: bool,
        is_passthrough: bool,
        is_websocket: bool,
        is_sse: bool,
        request_content_type: str | None,
    ) -> ProxyFlowRecorder:
        flow_id = uuid4().hex
        flow_dir = self._captures_dir / flow_id
        flow_dir.mkdir(parents=True, exist_ok=True)
        parsed = URL(url)
        path = parsed.path or "/"
        if parsed.query:
            path = f"{path}?{parsed.query.decode('ascii', errors='replace')}"
        summary = ProxyFlowSummary(
            id=flow_id,
            method=method,
            url=url,
            host=parsed.host or "",
            path=path,
            protocol_mode=protocol_mode,
            client_http_version=client_http_version,
            is_tls_mitm=is_tls_mitm,
            is_passthrough=is_passthrough,
            is_websocket=is_websocket,
            is_sse=is_sse,
            request_headers_path=str(flow_dir / "request-head.txt"),
            request_body_path=str(flow_dir / "request-body.bin"),
            response_headers_path=str(flow_dir / "response-head.txt"),
            response_body_path=str(flow_dir / "response-body.bin"),
            request_content_type=request_content_type,
        )
        return ProxyFlowRecorder(
            summary=summary,
            _request_body_handle=open(summary.request_body_path, "wb"),
            _response_body_handle=open(summary.response_body_path, "wb"),
        )

    def build_history_item(self, flow: ProxyFlowSummary) -> HistoryItem:
        raw_request_head = self._read_text(Path(flow.request_headers_path))
        raw_response_head = self._read_text(Path(flow.response_headers_path))
        request_headers = parse_header_lines(raw_request_head.splitlines()[1:]) if raw_request_head else []
        response_headers = parse_header_lines(raw_response_head.splitlines()[1:]) if raw_response_head else []
        request_body_text, request_body_base64, request_body_render = self._read_body_preview(Path(flow.request_body_path), flow.request_content_type)
        response_body_text, response_body_base64, response_body_render = self._read_body_preview(Path(flow.response_body_path), flow.response_content_type)

        request = ReplayRequest(
            method=flow.method,
            url=flow.url,
            headers=request_headers,
            body_text=request_body_text,
            body_base64=request_body_base64,
        )
        result = ReplayResult(
            status_code=flow.status_code,
            reason=flow.reason,
            headers=response_headers,
            body_text=response_body_text,
            body_base64=response_body_base64,
            raw_request=self._join_head_and_body(raw_request_head, request_body_render),
            raw_response=self._join_head_and_body(raw_response_head, response_body_render),
            error=flow.error,
        )
        return HistoryItem(id=flow.history_id or flow.id, source="proxy", request=request, result=result)

    def build_detail(self, flow: ProxyFlowSummary) -> ProxyFlowDetail:
        request_body_text, _, request_body_render = self._read_body_preview(Path(flow.request_body_path), flow.request_content_type)
        response_body_text, _, response_body_render = self._read_body_preview(Path(flow.response_body_path), flow.response_content_type)
        raw_request_head = self._read_text(Path(flow.request_headers_path))
        raw_response_head = self._read_text(Path(flow.response_headers_path))
        return ProxyFlowDetail(
            **flow.model_dump(),
            raw_request=self._join_head_and_body(raw_request_head, request_body_render),
            raw_response=self._join_head_and_body(raw_response_head, response_body_render),
        )

    def delete_flow_files(self, flow: ProxyFlowSummary) -> None:
        for path in (
            flow.request_headers_path,
            flow.request_body_path,
            flow.response_headers_path,
            flow.response_body_path,
        ):
            file_path = Path(path)
            if file_path.exists():
                file_path.unlink()
        flow_dir = Path(flow.request_headers_path).parent
        if flow_dir.exists():
            try:
                flow_dir.rmdir()
            except OSError:
                pass

    def _read_text(self, path: Path) -> str:
        if not path.exists():
            return ""
        return path.read_text(encoding="utf-8")

    def _read_body_preview(self, path: Path, content_type: str | None) -> tuple[str | None, str | None, str]:
        if not path.exists():
            return None, None, ""
        data = path.read_bytes()
        if not data:
            return None, None, ""

        prefix = data[:PREVIEW_LIMIT]
        truncated = len(data) > PREVIEW_LIMIT
        media_type = (content_type or "").split(";", 1)[0].strip().lower()
        if media_type.startswith("text/") or media_type in TEXT_CONTENT_TYPES or media_type.endswith("+json") or media_type.endswith("+xml"):
            charset = "utf-8"
            if content_type and "charset=" in content_type:
                charset = content_type.split("charset=", 1)[1].split(";", 1)[0].strip()
            text = prefix.decode(charset, errors="replace")
            render = text + ("\n<captured body truncated>" if truncated else "")
            return (None if truncated else text), None, render

        try:
            text = prefix.decode("utf-8")
            render = text + ("\n<captured body truncated>" if truncated else "")
            return (None if truncated else text), None, render
        except UnicodeDecodeError:
            encoded = base64.b64encode(prefix).decode("ascii")
            render = f"<base64:{encoded}>"
            if truncated:
                render += "\n<captured body truncated>"
            return None, (None if truncated else encoded), render

    def _join_head_and_body(self, head: str, body: str) -> str:
        if not head:
            return body
        if not body:
            return head
        return head + body
