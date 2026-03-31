from __future__ import annotations

import base64
from dataclasses import dataclass
from time import perf_counter

import httpx

from burph5.models import Header, ReplayRequest, ReplayResult
from burph5.services.parser import apply_request_variables, decode_request_body, render_raw_request


TEXT_CONTENT_TYPES = (
    "application/json",
    "application/javascript",
    "application/problem+json",
    "application/x-www-form-urlencoded",
    "application/xml",
    "image/svg+xml",
)


@dataclass(slots=True)
class ExecutionArtifacts:
    request: ReplayRequest
    result: ReplayResult
    response_content: bytes
    response_wire_bytes: bytes


class ReplayEngine:
    async def execute(
        self,
        request: ReplayRequest,
        inherited_variables: dict[str, str] | None = None,
    ) -> ExecutionArtifacts:
        normalized = apply_request_variables(request, inherited_variables)
        request_headers = ensure_host_header(normalized.headers, normalized.url)
        raw_request = render_raw_request(normalized.model_copy(update={"headers": request_headers}))
        request_body = decode_request_body(normalized)

        start = perf_counter()
        try:
            timeout = httpx.Timeout(normalized.timeout_ms / 1000)
            async with httpx.AsyncClient(
                follow_redirects=normalized.follow_redirects,
                http2=True,
                timeout=timeout,
                trust_env=False,
            ) as client:
                response = await client.request(
                    method=normalized.method.upper(),
                    url=normalized.url,
                    headers=[(header.name, header.value) for header in request_headers],
                    content=request_body,
                )
        except Exception as exc:
            elapsed_ms = int((perf_counter() - start) * 1000)
            result = ReplayResult(
                elapsed_ms=elapsed_ms,
                raw_request=raw_request,
                raw_response="",
                error=str(exc),
            )
            return ExecutionArtifacts(
                request=normalized,
                result=result,
                response_content=b"",
                response_wire_bytes=b"",
            )

        elapsed_ms = int((perf_counter() - start) * 1000)
        response_headers = [Header(name=name, value=value) for name, value in response.headers.multi_items()]
        body_text, body_base64 = split_response_body(response.content, response.headers.get("content-type"))
        raw_response = render_raw_response(response.status_code, response.reason_phrase, response_headers, body_text, body_base64)
        result = ReplayResult(
            status_code=response.status_code,
            reason=response.reason_phrase,
            headers=response_headers,
            body_text=body_text,
            body_base64=body_base64,
            elapsed_ms=elapsed_ms,
            raw_request=raw_request,
            raw_response=raw_response,
        )
        return ExecutionArtifacts(
            request=normalized,
            result=result,
            response_content=response.content,
            response_wire_bytes=build_wire_response_bytes(
                response.status_code,
                response.reason_phrase,
                response_headers,
                response.content,
                sanitize_for_proxy=True,
            ),
        )


def ensure_host_header(headers: list[Header], url: str) -> list[Header]:
    if any(header.name.lower() == "host" for header in headers):
        return headers
    parsed = httpx.URL(url)
    host = parsed.host or ""
    if parsed.port is not None and parsed.port not in {80, 443}:
        host = f"{host}:{parsed.port}"
    return [Header(name="Host", value=host), *headers]


def split_response_body(content: bytes, content_type: str | None) -> tuple[str | None, str | None]:
    if not content:
        return None, None

    media_type = (content_type or "").split(";", 1)[0].strip().lower()
    if media_type.startswith("text/") or media_type in TEXT_CONTENT_TYPES or media_type.endswith("+json") or media_type.endswith("+xml"):
        charset = "utf-8"
        if content_type and "charset=" in content_type:
            charset = content_type.split("charset=", 1)[1].split(";", 1)[0].strip()
        return content.decode(charset, errors="replace"), None

    try:
        return content.decode("utf-8"), None
    except UnicodeDecodeError:
        return None, base64.b64encode(content).decode("ascii")


def render_raw_response(
    status_code: int,
    reason: str,
    headers: list[Header],
    body_text: str | None,
    body_base64: str | None,
) -> str:
    lines = [f"HTTP/1.1 {status_code} {reason}"]
    lines.extend(f"{header.name}: {header.value}" for header in headers)
    body = body_text if body_text is not None else (f"<base64:{body_base64}>" if body_base64 is not None else "")
    return "\r\n".join(lines) + "\r\n\r\n" + body


def build_wire_response_bytes(
    status_code: int,
    reason: str,
    headers: list[Header],
    body: bytes,
    sanitize_for_proxy: bool = False,
) -> bytes:
    response_headers = sanitize_proxy_response_headers(headers, len(body)) if sanitize_for_proxy else headers
    header_blob = [f"HTTP/1.1 {status_code} {reason}"]
    header_blob.extend(f"{header.name}: {header.value}" for header in response_headers)
    prefix = ("\r\n".join(header_blob) + "\r\n\r\n").encode("latin-1", errors="replace")
    return prefix + body


def sanitize_proxy_response_headers(headers: list[Header], body_length: int) -> list[Header]:
    hop_by_hop = {
        "connection",
        "content-encoding",
        "keep-alive",
        "proxy-authenticate",
        "proxy-authorization",
        "te",
        "trailer",
        "transfer-encoding",
        "upgrade",
        "content-length",
    }
    sanitized = [header for header in headers if header.name.lower() not in hop_by_hop]
    sanitized.append(Header(name="Content-Length", value=str(body_length)))
    return sanitized
