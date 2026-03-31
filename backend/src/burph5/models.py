from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, Field, model_validator


HistorySource = Literal["ui", "api", "cli", "mcp", "proxy"]


class Header(BaseModel):
    name: str
    value: str


class ReplayRequest(BaseModel):
    method: str
    url: str
    headers: list[Header] = Field(default_factory=list)
    body_text: str | None = None
    body_base64: str | None = None
    timeout_ms: int = Field(default=15000, ge=1, le=120000)
    follow_redirects: bool = True
    tags: list[str] = Field(default_factory=list)
    variables: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_body(self) -> "ReplayRequest":
        if self.body_text and self.body_base64:
            raise ValueError("Only one of body_text or body_base64 can be set.")
        return self


class ReplayResult(BaseModel):
    status_code: int | None = None
    reason: str | None = None
    headers: list[Header] = Field(default_factory=list)
    body_text: str | None = None
    body_base64: str | None = None
    elapsed_ms: int | None = None
    raw_request: str = ""
    raw_response: str = ""
    error: str | None = None


class ReplayExecutePayload(BaseModel):
    raw_request: str | None = None
    request: ReplayRequest | None = None
    source: HistorySource = "api"
    persist: bool = True
    default_scheme: str = "http"

    @model_validator(mode="after")
    def validate_input(self) -> "ReplayExecutePayload":
        if not self.raw_request and not self.request:
            raise ValueError("Either raw_request or request must be provided.")
        return self


class ReplayExecuteResponse(BaseModel):
    request: ReplayRequest
    result: ReplayResult
    history_id: str | None = None


class HistoryItem(BaseModel):
    id: str = Field(default_factory=lambda: uuid4().hex)
    source: HistorySource
    request: ReplayRequest
    result: ReplayResult
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    tags: list[str] = Field(default_factory=list)


class CollectionEntry(BaseModel):
    id: str = Field(default_factory=lambda: uuid4().hex)
    name: str
    request: ReplayRequest


class CollectionWrite(BaseModel):
    name: str
    description: str = ""
    variables: dict[str, str] = Field(default_factory=dict)
    entries: list[CollectionEntry] = Field(default_factory=list)


class Collection(BaseModel):
    id: str = Field(default_factory=lambda: uuid4().hex)
    name: str
    description: str = ""
    variables: dict[str, str] = Field(default_factory=dict)
    entries: list[CollectionEntry] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class CollectionRunRequest(BaseModel):
    variables: dict[str, str] = Field(default_factory=dict)
    concurrency: int = Field(default=1, ge=1, le=5)
    source: HistorySource = "api"
    persist: bool = True


class BatchRunEntryResult(BaseModel):
    entry_id: str
    entry_name: str
    request: ReplayRequest
    result: ReplayResult
    history_id: str | None = None


class BatchRun(BaseModel):
    id: str = Field(default_factory=lambda: uuid4().hex)
    collection_id: str
    concurrency: int
    variables: dict[str, str] = Field(default_factory=dict)
    results: list[BatchRunEntryResult] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class ProxySettings(BaseModel):
    enabled: bool = False
    host: str = "127.0.0.1"
    port: int = Field(default=8899, ge=1, le=65535)
    capture_https: bool = False


class ProxyStatus(ProxySettings):
    running: bool = False
