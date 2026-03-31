from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from burph5.models import CollectionRunRequest, CollectionWrite, ReplayExecutePayload, ReplayRequest
from burph5.service import get_service

mcp = FastMCP("burph5")


@mcp.tool()
async def replay_request(
    raw_request: str | None = None,
    request: dict | None = None,
    default_scheme: str = "http",
) -> dict:
    service = get_service()
    payload = ReplayExecutePayload(
        raw_request=raw_request,
        request=ReplayRequest.model_validate(request) if request else None,
        source="mcp",
        default_scheme=default_scheme,
    )
    response = await service.replay(payload)
    return response.model_dump(mode="json")


@mcp.tool()
def parse_raw_request(
    raw_request: str,
    default_scheme: str = "http",
) -> dict:
    service = get_service()
    return service.parse_raw(raw_request, default_scheme=default_scheme).model_dump(mode="json")


@mcp.tool()
def list_history(limit: int = 50) -> list[dict]:
    service = get_service()
    return [item.model_dump(mode="json") for item in service.list_history(limit=limit)]


@mcp.tool()
def get_history_item(history_id: str) -> dict | None:
    service = get_service()
    item = service.get_history(history_id)
    return item.model_dump(mode="json") if item else None


@mcp.tool()
def save_collection(collection: dict, collection_id: str | None = None) -> dict:
    service = get_service()
    saved = service.save_collection(CollectionWrite.model_validate(collection), collection_id=collection_id)
    return saved.model_dump(mode="json")


@mcp.tool()
async def run_collection(
    collection_id: str,
    variables: dict[str, str] | None = None,
    concurrency: int = 1,
) -> dict:
    service = get_service()
    result = await service.run_collection(
        collection_id,
        CollectionRunRequest(
            variables=variables or {},
            concurrency=concurrency,
            source="mcp",
        ),
    )
    return result.model_dump(mode="json")


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
