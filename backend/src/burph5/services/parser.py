from __future__ import annotations

import base64
import re
from urllib.parse import urlparse

from burph5.models import Header, ReplayRequest


TEMPLATE_PATTERN = re.compile(r"\{\{\s*([a-zA-Z0-9_\-]+)\s*\}\}")
HEADER_LINE_PATTERN = re.compile(r"^[!#$%&'*+\-.^_`|~0-9A-Za-z]+\s*:")


def apply_variables(text: str | None, variables: dict[str, str]) -> str | None:
    if text is None or not variables:
        return text

    def replace(match: re.Match[str]) -> str:
        key = match.group(1)
        return variables.get(key, match.group(0))

    return TEMPLATE_PATTERN.sub(replace, text)


def merge_variables(*sources: dict[str, str]) -> dict[str, str]:
    merged: dict[str, str] = {}
    for source in sources:
        merged.update(source)
    return merged


def parse_raw_request(raw_request: str, default_scheme: str = "http") -> ReplayRequest:
    cleaned = raw_request.replace("\r\n", "\n").replace("\r", "\n")
    header_part, body = split_raw_request(cleaned)
    lines = header_part.split("\n")
    if not lines or not lines[0].strip():
        raise ValueError("Raw request is missing the request line.")

    method, target = parse_request_line(lines[0])
    headers = parse_header_lines(lines[1:])
    url = resolve_url(target, headers, default_scheme=default_scheme)
    return ReplayRequest(
        method=method,
        url=url,
        headers=headers,
        body_text=body if body != "" else None,
    )


def split_raw_request(raw_request: str) -> tuple[str, str]:
    lines = raw_request.split("\n")
    if not lines:
        return raw_request, ""

    header_lines = [lines[0]]
    index = 1
    while index < len(lines):
        line = lines[index]
        if line.strip():
            header_lines.append(line)
            index += 1
            continue

        lookahead = index + 1
        while lookahead < len(lines) and not lines[lookahead].strip():
            lookahead += 1

        if lookahead >= len(lines):
            return "\n".join(header_lines), ""

        if HEADER_LINE_PATTERN.match(lines[lookahead]):
            index = lookahead
            continue

        return "\n".join(header_lines), "\n".join(lines[lookahead:])

    return "\n".join(header_lines), ""


def parse_request_line(line: str) -> tuple[str, str]:
    parts = line.strip().split()
    if len(parts) < 2:
        raise ValueError("Request line must include method and URL/path.")
    return parts[0].upper(), parts[1]


def parse_header_lines(lines: list[str]) -> list[Header]:
    headers: list[Header] = []
    for line in lines:
        if not line.strip() or ":" not in line:
            continue
        name, value = line.split(":", 1)
        headers.append(Header(name=name.strip(), value=value.lstrip()))
    return headers


def resolve_url(target: str, headers: list[Header], default_scheme: str = "http") -> str:
    parsed = urlparse(target)
    if parsed.scheme and parsed.netloc:
        return target

    host = next((header.value for header in headers if header.name.lower() == "host"), "")
    if not host:
        raise ValueError("Relative request targets require a Host header.")
    path = target if target.startswith("/") else f"/{target}"
    scheme = default_scheme or "http"
    return f"{scheme}://{host}{path}"


def render_request_target(url: str) -> str:
    parsed = urlparse(url)
    path = parsed.path or "/"
    if parsed.query:
        path = f"{path}?{parsed.query}"
    return path


def ensure_host_header(headers: list[Header], url: str) -> list[Header]:
    parsed = urlparse(url)
    host_value = parsed.netloc
    if any(header.name.lower() == "host" for header in headers):
        return headers
    return [Header(name="Host", value=host_value), *headers]


def render_raw_request(request: ReplayRequest) -> str:
    headers = ensure_host_header(request.headers, request.url)
    target = render_request_target(request.url)
    lines = [f"{request.method.upper()} {target} HTTP/1.1"]
    lines.extend(f"{header.name}: {header.value}" for header in headers)
    body = request.body_text
    if body is None and request.body_base64:
        body = f"<base64:{request.body_base64}>"
    if body:
        return "\r\n".join(lines) + "\r\n\r\n" + body
    return "\r\n".join(lines) + "\r\n\r\n"


def apply_request_variables(
    request: ReplayRequest,
    inherited_variables: dict[str, str] | None = None,
) -> ReplayRequest:
    merged = merge_variables(inherited_variables or {}, request.variables)
    headers = [
        Header(
            name=apply_variables(header.name, merged) or header.name,
            value=apply_variables(header.value, merged) or header.value,
        )
        for header in request.headers
    ]
    return request.model_copy(
        update={
            "url": apply_variables(request.url, merged) or request.url,
            "headers": headers,
            "body_text": apply_variables(request.body_text, merged),
            "body_base64": apply_variables(request.body_base64, merged),
            "variables": merged,
        }
    )


def decode_request_body(request: ReplayRequest) -> bytes | None:
    if request.body_base64:
        return base64.b64decode(request.body_base64)
    if request.body_text is None:
        return None
    return request.body_text.encode("utf-8")
