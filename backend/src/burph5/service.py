from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import cast

from burph5.config import AppSettings, get_settings
from burph5.models import (
    BatchRun,
    BatchRunEntryResult,
    Collection,
    CollectionRunRequest,
    CollectionWrite,
    HistorySource,
    HistoryItem,
    ProxySettings,
    ProxyStatus,
    ReplayExecutePayload,
    ReplayExecuteResponse,
    ReplayRequest,
)
from burph5.services.parser import parse_raw_request
from burph5.services.proxy import ProxyController
from burph5.services.replay import ExecutionArtifacts, ReplayEngine
from burph5.services.storage import SQLiteRepository


class BurpH5Service:
    def __init__(self, settings: AppSettings | None = None) -> None:
        self.settings = settings or get_settings()
        self.repository = SQLiteRepository(self.settings.db_path)
        self.replay_engine = ReplayEngine()
        self.proxy_controller = ProxyController(
            handler=self._handle_proxy_request,
            settings=self.repository.get_proxy_settings(),
        )

    async def replay(self, payload: ReplayExecutePayload) -> ReplayExecuteResponse:
        request = payload.request or parse_raw_request(payload.raw_request or "", default_scheme=payload.default_scheme)
        artifacts = await self.replay_engine.execute(request)
        history_id = None
        if payload.persist:
            history_id = self._persist_history(payload.source, artifacts).id
        return ReplayExecuteResponse(
            request=artifacts.request,
            result=artifacts.result,
            history_id=history_id,
        )

    def parse_raw(self, raw_request: str, default_scheme: str = "http") -> ReplayRequest:
        return parse_raw_request(raw_request, default_scheme=default_scheme)

    def list_history(self, limit: int = 200, source: str | None = None) -> list[HistoryItem]:
        return self.repository.list_history(limit=limit, source=source)

    def get_history(self, history_id: str) -> HistoryItem | None:
        return self.repository.get_history(history_id)

    def delete_history(self, history_id: str) -> bool:
        return self.repository.delete_history(history_id)

    def clear_history(self, source: str | None = None) -> int:
        return self.repository.clear_history(source=source)

    def list_collections(self) -> list[Collection]:
        return self.repository.list_collections()

    def get_collection(self, collection_id: str) -> Collection | None:
        return self.repository.get_collection(collection_id)

    def save_collection(self, payload: CollectionWrite, collection_id: str | None = None) -> Collection:
        return self.repository.save_collection(payload, collection_id=collection_id)

    async def run_collection(self, collection_id: str, payload: CollectionRunRequest) -> BatchRun:
        collection = self.get_collection(collection_id)
        if collection is None:
            raise KeyError(f"Collection {collection_id} was not found.")

        concurrency = min(payload.concurrency, self.settings.max_concurrency)
        semaphore = asyncio.Semaphore(concurrency)
        inherited_variables = {**collection.variables, **payload.variables}
        results: list[BatchRunEntryResult] = []

        async def run_entry(entry_index: int) -> tuple[int, BatchRunEntryResult]:
            entry = collection.entries[entry_index]
            async with semaphore:
                response = await self.replay(
                    ReplayExecutePayload(
                        request=entry.request.model_copy(
                            update={"variables": {**inherited_variables, **entry.request.variables}},
                        ),
                        source=payload.source,
                        persist=payload.persist,
                    )
                )
            return (
                entry_index,
                BatchRunEntryResult(
                    entry_id=entry.id,
                    entry_name=entry.name,
                    request=response.request,
                    result=response.result,
                    history_id=response.history_id,
                ),
            )

        pairs = await asyncio.gather(*(run_entry(index) for index in range(len(collection.entries))))
        for _, result in sorted(pairs, key=lambda pair: pair[0]):
            results.append(result)

        batch_run = BatchRun(
            collection_id=collection.id,
            concurrency=concurrency,
            variables=inherited_variables,
            results=results,
            created_at=datetime.now(UTC),
        )
        self.repository.save_batch_run(batch_run)
        return batch_run

    async def update_proxy(self, settings: ProxySettings) -> ProxyStatus:
        saved = self.repository.save_proxy_settings(settings)
        await self.proxy_controller.apply_settings(saved)
        return ProxyStatus(**saved.model_dump(), running=self.proxy_controller.running)

    def get_proxy_status(self) -> ProxyStatus:
        settings = self.repository.get_proxy_settings()
        return ProxyStatus(**settings.model_dump(), running=self.proxy_controller.running)

    async def shutdown(self) -> None:
        await self.proxy_controller.stop()

    def _persist_history(self, source: str, artifacts: ExecutionArtifacts) -> HistoryItem:
        return self.repository.add_history(
            HistoryItem(
                source=cast(HistorySource, source),
                request=artifacts.request,
                result=artifacts.result,
                tags=artifacts.request.tags,
            )
        )

    async def _handle_proxy_request(self, raw_request: str) -> bytes:
        request = parse_raw_request(raw_request, default_scheme="http")
        artifacts = await self.replay_engine.execute(request)
        self._persist_history("proxy", artifacts)
        if artifacts.response_wire_bytes:
            return artifacts.response_wire_bytes
        return b"HTTP/1.1 502 Bad Gateway\r\nContent-Length: 0\r\n\r\n"


_service: BurpH5Service | None = None


def get_service() -> BurpH5Service:
    global _service
    if _service is None:
        _service = BurpH5Service()
    return _service
