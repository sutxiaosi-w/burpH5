from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware

from burph5.config import AppSettings, get_settings
from burph5.models import CollectionRunRequest, CollectionWrite, ProxySettings, ReplayExecutePayload
from burph5.service import BurpH5Service, get_service


def _resolve_frontend_path(frontend_dist_dir: Path, requested_path: str) -> Path | None:
    normalized = requested_path.lstrip("/")
    candidate = (frontend_dist_dir / normalized).resolve()
    try:
        candidate.relative_to(frontend_dist_dir.resolve())
    except ValueError:
        return None
    if candidate.is_file():
        return candidate
    return None


def create_app(
    service: BurpH5Service | None = None,
    settings: AppSettings | None = None,
) -> FastAPI:
    resolved_settings = settings or get_settings()
    app_service = service or BurpH5Service(settings=resolved_settings)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        yield
        await app_service.shutdown()

    app = FastAPI(title="burph5 API", version="0.1.0", lifespan=lifespan)
    app.state.service = app_service
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://127.0.0.1:5173",
            "http://localhost:5173",
        ],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/api/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/api/replay")
    async def replay(payload: ReplayExecutePayload):
        return await app_service.replay(payload)

    @app.post("/api/replay/parse-raw")
    async def parse_raw(payload: dict[str, str]):
        raw_request = payload.get("raw_request", "")
        default_scheme = payload.get("default_scheme", "http")
        return app_service.parse_raw(raw_request, default_scheme=default_scheme)

    @app.get("/api/history")
    async def list_history(
        limit: int = Query(default=200, ge=1, le=1000),
        source: str | None = Query(default=None),
    ):
        return app_service.list_history(limit=limit, source=source)

    @app.get("/api/history/{history_id}")
    async def get_history(history_id: str):
        item = app_service.get_history(history_id)
        if item is None:
            raise HTTPException(status_code=404, detail="History item not found.")
        return item

    @app.delete("/api/history/{history_id}")
    async def delete_history(history_id: str):
        deleted = app_service.delete_history(history_id)
        if not deleted:
            raise HTTPException(status_code=404, detail="History item not found.")
        return {"deleted": True, "id": history_id}

    @app.delete("/api/history")
    async def clear_history(source: str | None = Query(default=None)):
        deleted_count = app_service.clear_history(source=source)
        return {"deleted_count": deleted_count, "source": source}

    @app.get("/api/collections")
    async def list_collections():
        return app_service.list_collections()

    @app.get("/api/collections/{collection_id}")
    async def get_collection(collection_id: str):
        item = app_service.get_collection(collection_id)
        if item is None:
            raise HTTPException(status_code=404, detail="Collection not found.")
        return item

    @app.post("/api/collections")
    async def create_collection(payload: CollectionWrite):
        return app_service.save_collection(payload)

    @app.put("/api/collections/{collection_id}")
    async def update_collection(collection_id: str, payload: CollectionWrite):
        return app_service.save_collection(payload, collection_id=collection_id)

    @app.post("/api/collections/{collection_id}/run")
    async def run_collection(collection_id: str, payload: CollectionRunRequest):
        try:
            return await app_service.run_collection(collection_id, payload)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/api/proxy")
    async def get_proxy():
        return app_service.get_proxy_status()

    @app.put("/api/proxy")
    async def update_proxy(payload: ProxySettings):
        return await app_service.update_proxy(payload)

    frontend_dist_dir = app_service.settings.frontend_dist_dir
    if frontend_dist_dir.joinpath("index.html").exists():
        index_file = frontend_dist_dir / "index.html"

        @app.get("/", include_in_schema=False)
        async def frontend_index():
            return FileResponse(index_file)

        @app.get("/{full_path:path}", include_in_schema=False)
        async def frontend_entry(full_path: str):
            asset = _resolve_frontend_path(frontend_dist_dir, full_path)
            if asset is not None:
                return FileResponse(asset)
            if "." not in Path(full_path).name:
                return FileResponse(index_file)
            raise HTTPException(status_code=404, detail="Frontend asset not found.")

    return app


app = create_app()
