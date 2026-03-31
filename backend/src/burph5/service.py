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
    ProxyFlowDetail,
    ProxyFlowSummary,
    ProxySettings,
    ProxyStatus,
    ReplayExecutePayload,
    ReplayExecuteResponse,
    ReplayRequest,
)
from burph5.services.certificates import CertificateAuthority
from burph5.services.proxy_capture import ProxyCaptureStore
from burph5.services.parser import parse_raw_request
from burph5.services.proxy import ProxyController
from burph5.services.proxy_transport import ProxyTransport
from burph5.services.replay import ExecutionArtifacts, ReplayEngine
from burph5.services.storage import SQLiteRepository


class BurpH5Service:
    def __init__(self, settings: AppSettings | None = None) -> None:
        self.settings = settings or get_settings()
        self.repository = SQLiteRepository(self.settings.db_path)
        self.replay_engine = ReplayEngine()
        self.certificate_authority = CertificateAuthority(self.settings.certs_dir)
        self.capture_store = ProxyCaptureStore(self.settings.captures_dir)
        self.proxy_transport = ProxyTransport(self.capture_store)
        self.proxy_controller = ProxyController(
            transport=self.proxy_transport,
            on_flow_complete=self.record_proxy_flow,
            settings=self.repository.get_proxy_settings(),
            certificate_authority=self.certificate_authority,
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
        history_item = self.repository.get_history(history_id)
        deleted = self.repository.delete_history(history_id)
        if deleted and history_item and history_item.source == "proxy":
            flow = self.repository.get_proxy_flow_by_history_id(history_id)
            if flow:
                self.capture_store.delete_flow_files(flow)
                self.repository.delete_proxy_flow(flow.id)
        return deleted

    def clear_history(self, source: str | None = None) -> int:
        if source in {None, "proxy"}:
            flows = self.repository.clear_proxy_flows() if source is None else [
                flow for flow in self.repository.list_proxy_flows(limit=100000)
            ]
            if source == "proxy":
                for flow in flows:
                    self.repository.delete_proxy_flow(flow.id)
            for flow in flows:
                self.capture_store.delete_flow_files(flow)
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
        if saved.capture_https:
            self.certificate_authority.ensure_ca()
        await self.proxy_controller.apply_settings(saved)
        return self._build_proxy_status(saved)

    def get_proxy_status(self) -> ProxyStatus:
        settings = self.repository.get_proxy_settings()
        return self._build_proxy_status(settings)

    def ensure_proxy_certificate(self) -> ProxyStatus:
        self.certificate_authority.ensure_ca()
        return self.get_proxy_status()

    def install_proxy_certificate(self) -> ProxyStatus:
        self.certificate_authority.install_to_windows()
        return self.get_proxy_status()

    def clear_proxy_leaf_certificates(self) -> ProxyStatus:
        self.certificate_authority.clear_leaf_certificates()
        return self.get_proxy_status()

    async def delete_proxy_certificates(self) -> ProxyStatus:
        settings = self.repository.get_proxy_settings()
        if settings.capture_https:
            settings = settings.model_copy(update={"capture_https": False})
            settings = self.repository.save_proxy_settings(settings)
            if settings.enabled:
                await self.proxy_controller.apply_settings(settings)
        self.certificate_authority.delete_all()
        return self._build_proxy_status(settings)

    async def reset_proxy_certificate(self) -> ProxyStatus:
        self.certificate_authority.reset()
        settings = self.repository.get_proxy_settings()
        if settings.enabled:
            if settings.capture_https:
                self.certificate_authority.ensure_ca()
            await self.proxy_controller.apply_settings(settings)
        return self.get_proxy_status()

    def get_proxy_certificate_path(self):
        return self.certificate_authority.ca_cert_path

    def list_proxy_flows(self, limit: int = 200) -> list[ProxyFlowSummary]:
        return self.repository.list_proxy_flows(limit=limit)

    def get_proxy_flow(self, flow_id: str) -> ProxyFlowDetail | None:
        flow = self.repository.get_proxy_flow(flow_id)
        if flow is None:
            return None
        return self.capture_store.build_detail(flow)

    async def shutdown(self) -> None:
        await self.proxy_controller.stop()
        await self.proxy_transport.close()

    def _persist_history(self, source: str, artifacts: ExecutionArtifacts) -> HistoryItem:
        return self.repository.add_history(
            HistoryItem(
                source=cast(HistorySource, source),
                request=artifacts.request,
                result=artifacts.result,
                tags=artifacts.request.tags,
            )
        )

    async def record_proxy_flow(self, flow: ProxyFlowSummary) -> None:
        history_item = self.capture_store.build_history_item(flow)
        saved_history = self.repository.add_history(history_item)
        flow.history_id = saved_history.id
        self.repository.add_proxy_flow(flow)

    def _build_proxy_status(self, settings: ProxySettings) -> ProxyStatus:
        cert_status = self.certificate_authority.get_status()
        return ProxyStatus(
            **settings.model_dump(),
            running=self.proxy_controller.running,
            ca_ready=cert_status.ready,
            ca_installed=cert_status.installed,
            ca_subject=cert_status.subject,
            ca_thumbprint=cert_status.thumbprint,
            ca_cert_path=cert_status.cert_path,
            leaf_cert_count=cert_status.leaf_cert_count,
            last_error=self.proxy_controller.last_error or cert_status.last_error,
        )


_service: BurpH5Service | None = None


def get_service() -> BurpH5Service:
    global _service
    if _service is None:
        _service = BurpH5Service()
    return _service
