from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Annotated

import typer
import uvicorn

from burph5.models import CollectionRunRequest, ProxySettings, ReplayExecutePayload, ReplayRequest
from burph5.service import get_service

app = typer.Typer(help="burph5 command line interface")
history_app = typer.Typer(help="History commands")
collection_app = typer.Typer(help="Collection commands")
proxy_app = typer.Typer(help="Proxy commands")

app.add_typer(history_app, name="history")
app.add_typer(collection_app, name="collection")
app.add_typer(proxy_app, name="proxy")


def print_json(data: object) -> None:
    typer.echo(json.dumps(data, indent=2, ensure_ascii=False, default=str))


@app.command()
def serve(
    host: str = "127.0.0.1",
    port: int = 8765,
) -> None:
    uvicorn.run("burph5.main:app", host=host, port=port, reload=False)


@app.command()
def replay(
    raw_file: Annotated[Path | None, typer.Option("--raw-file")] = None,
    json_file: Annotated[Path | None, typer.Option("--json-file")] = None,
    default_scheme: str = "http",
) -> None:
    if not raw_file and not json_file:
        raise typer.BadParameter("Provide either --raw-file or --json-file.")
    if raw_file and json_file:
        raise typer.BadParameter("Use only one of --raw-file or --json-file.")

    service = get_service()
    if raw_file:
        payload = ReplayExecutePayload(
            raw_request=raw_file.read_text(encoding="utf-8"),
            source="cli",
            default_scheme=default_scheme,
        )
    else:
        request = ReplayRequest.model_validate(json.loads(json_file.read_text(encoding="utf-8")))
        payload = ReplayExecutePayload(request=request, source="cli")

    response = asyncio.run(service.replay(payload))
    print_json(response.model_dump(mode="json"))


@history_app.command("list")
def history_list(limit: int = 50) -> None:
    service = get_service()
    print_json([item.model_dump(mode="json") for item in service.list_history(limit=limit)])


@collection_app.command("run")
def collection_run(
    collection_id: str,
    concurrency: int = 1,
) -> None:
    service = get_service()
    result = asyncio.run(
        service.run_collection(
            collection_id,
            CollectionRunRequest(concurrency=concurrency, source="cli"),
        )
    )
    print_json(result.model_dump(mode="json"))


@proxy_app.command("start")
def proxy_start(
    host: str = "127.0.0.1",
    port: int = 8899,
) -> None:
    service = get_service()

    async def runner() -> None:
        await service.update_proxy(ProxySettings(enabled=True, host=host, port=port, capture_https=False))
        typer.echo(f"Proxy listening on {host}:{port}")
        try:
            while True:
                await asyncio.sleep(3600)
        finally:
            await service.shutdown()

    try:
        asyncio.run(runner())
    except KeyboardInterrupt:
        typer.echo("Proxy stopped.")


def main() -> None:
    app()


if __name__ == "__main__":
    main()
