from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from burph5.models import BatchRun, Collection, CollectionEntry, CollectionWrite, HistoryItem, ProxyFlowSummary, ProxySettings, ReplayRequest, ReplayResult


class SQLiteRepository:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.initialize()

    def initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS history (
                    id TEXT PRIMARY KEY,
                    source TEXT NOT NULL,
                    request_json TEXT NOT NULL,
                    result_json TEXT NOT NULL,
                    tags_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS collections (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    description TEXT NOT NULL,
                    variables_json TEXT NOT NULL,
                    entries_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS batch_runs (
                    id TEXT PRIMARY KEY,
                    collection_id TEXT NOT NULL,
                    concurrency INTEGER NOT NULL,
                    variables_json TEXT NOT NULL,
                    results_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value_json TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS proxy_flows (
                    id TEXT PRIMARY KEY,
                    history_id TEXT,
                    created_at TEXT NOT NULL,
                    flow_json TEXT NOT NULL
                );
                """
            )

    def add_history(self, item: HistoryItem) -> HistoryItem:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO history (id, source, request_json, result_json, tags_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    item.id,
                    item.source,
                    item.request.model_dump_json(),
                    item.result.model_dump_json(),
                    json.dumps(item.tags),
                    item.created_at.isoformat(),
                ),
            )
        return item

    def list_history(self, limit: int = 200, source: str | None = None) -> list[HistoryItem]:
        query = "SELECT * FROM history"
        params: list[object] = []
        if source:
            query += " WHERE source = ?"
            params.append(source)
        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        with self._connect() as connection:
            rows = connection.execute(query, params).fetchall()
        return [self._row_to_history(row) for row in rows]

    def get_history(self, history_id: str) -> HistoryItem | None:
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM history WHERE id = ?", (history_id,)).fetchone()
        return self._row_to_history(row) if row else None

    def delete_history(self, history_id: str) -> bool:
        with self._connect() as connection:
            cursor = connection.execute("DELETE FROM history WHERE id = ?", (history_id,))
        return cursor.rowcount > 0

    def clear_history(self, source: str | None = None) -> int:
        with self._connect() as connection:
            if source:
                cursor = connection.execute("DELETE FROM history WHERE source = ?", (source,))
            else:
                cursor = connection.execute("DELETE FROM history")
        return cursor.rowcount

    def list_collections(self) -> list[Collection]:
        with self._connect() as connection:
            rows = connection.execute("SELECT * FROM collections ORDER BY updated_at DESC").fetchall()
        return [self._row_to_collection(row) for row in rows]

    def get_collection(self, collection_id: str | None) -> Collection | None:
        if collection_id is None:
            return None
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM collections WHERE id = ?", (collection_id,)).fetchone()
        return self._row_to_collection(row) if row else None

    def save_collection(self, payload: CollectionWrite, collection_id: str | None = None) -> Collection:
        now = datetime.now(UTC)
        existing = self.get_collection(collection_id)
        collection = Collection(
            id=existing.id if existing else (collection_id or Collection(name=payload.name).id),
            name=payload.name,
            description=payload.description,
            variables=payload.variables,
            entries=payload.entries,
            created_at=existing.created_at if existing else now,
            updated_at=now,
        )
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO collections (id, name, description, variables_json, entries_json, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    name = excluded.name,
                    description = excluded.description,
                    variables_json = excluded.variables_json,
                    entries_json = excluded.entries_json,
                    updated_at = excluded.updated_at
                """,
                (
                    collection.id,
                    collection.name,
                    collection.description,
                    json.dumps(collection.variables),
                    json.dumps([entry.model_dump(mode="json") for entry in collection.entries]),
                    collection.created_at.isoformat(),
                    collection.updated_at.isoformat(),
                ),
            )
        return collection

    def save_batch_run(self, batch_run: BatchRun) -> BatchRun:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO batch_runs (id, collection_id, concurrency, variables_json, results_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    batch_run.id,
                    batch_run.collection_id,
                    batch_run.concurrency,
                    json.dumps(batch_run.variables),
                    json.dumps([result.model_dump(mode="json") for result in batch_run.results]),
                    batch_run.created_at.isoformat(),
                ),
            )
        return batch_run

    def get_proxy_settings(self) -> ProxySettings:
        with self._connect() as connection:
            row = connection.execute("SELECT value_json FROM settings WHERE key = 'proxy'").fetchone()
        if not row:
            return ProxySettings()
        return ProxySettings.model_validate_json(row["value_json"])

    def save_proxy_settings(self, settings: ProxySettings) -> ProxySettings:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO settings (key, value_json)
                VALUES ('proxy', ?)
                ON CONFLICT(key) DO UPDATE SET value_json = excluded.value_json
                """,
                (settings.model_dump_json(),),
            )
        return settings

    def add_proxy_flow(self, flow: ProxyFlowSummary) -> ProxyFlowSummary:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO proxy_flows (id, history_id, created_at, flow_json)
                VALUES (?, ?, ?, ?)
                """,
                (
                    flow.id,
                    flow.history_id,
                    flow.created_at.isoformat(),
                    flow.model_dump_json(),
                ),
            )
        return flow

    def update_proxy_flow(self, flow: ProxyFlowSummary) -> ProxyFlowSummary:
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE proxy_flows
                SET history_id = ?, created_at = ?, flow_json = ?
                WHERE id = ?
                """,
                (
                    flow.history_id,
                    flow.created_at.isoformat(),
                    flow.model_dump_json(),
                    flow.id,
                ),
            )
        return flow

    def list_proxy_flows(self, limit: int = 200) -> list[ProxyFlowSummary]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT flow_json FROM proxy_flows ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [ProxyFlowSummary.model_validate_json(row["flow_json"]) for row in rows]

    def get_proxy_flow(self, flow_id: str) -> ProxyFlowSummary | None:
        with self._connect() as connection:
            row = connection.execute("SELECT flow_json FROM proxy_flows WHERE id = ?", (flow_id,)).fetchone()
        return ProxyFlowSummary.model_validate_json(row["flow_json"]) if row else None

    def get_proxy_flow_by_history_id(self, history_id: str) -> ProxyFlowSummary | None:
        with self._connect() as connection:
            row = connection.execute("SELECT flow_json FROM proxy_flows WHERE history_id = ?", (history_id,)).fetchone()
        return ProxyFlowSummary.model_validate_json(row["flow_json"]) if row else None

    def delete_proxy_flow(self, flow_id: str) -> bool:
        with self._connect() as connection:
            cursor = connection.execute("DELETE FROM proxy_flows WHERE id = ?", (flow_id,))
        return cursor.rowcount > 0

    def clear_proxy_flows(self) -> list[ProxyFlowSummary]:
        flows = self.list_proxy_flows(limit=100000)
        with self._connect() as connection:
            connection.execute("DELETE FROM proxy_flows")
        return flows

    def _row_to_history(self, row: sqlite3.Row) -> HistoryItem:
        return HistoryItem(
            id=row["id"],
            source=row["source"],
            request=ReplayRequest.model_validate_json(row["request_json"]),
            result=ReplayResult.model_validate_json(row["result_json"]),
            tags=json.loads(row["tags_json"]),
            created_at=datetime.fromisoformat(row["created_at"]),
        )

    def _row_to_collection(self, row: sqlite3.Row) -> Collection:
        entries = [CollectionEntry.model_validate(entry) for entry in json.loads(row["entries_json"])]
        return Collection(
            id=row["id"],
            name=row["name"],
            description=row["description"],
            variables=json.loads(row["variables_json"]),
            entries=entries,
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
        )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        return connection
