"""Untrusted browser telemetry: strict bounded schema and shared rate budget."""

import logging
import sqlite3
import time
from contextlib import closing
from typing import Literal

from fastapi import Request
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from app.logging_config import get_logger, safe

from .errors import BackendError


class ClientError(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    type: str = Field(max_length=100)
    message: str = Field(max_length=1000)
    code: str | None = Field(default=None, max_length=100)
    stack: str | None = Field(default=None, max_length=2000)


class ClientEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")
    timestamp: AwareDatetime
    level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
    service: Literal["frontend"]
    module: str = Field(pattern=r"^[a-zA-Z0-9_.-]{1,100}$")
    event: str = Field(pattern=r"^[a-z][a-z0-9_]{0,79}$")
    message: str = Field(min_length=1, max_length=1000)
    request_id: str | None = Field(default=None, pattern=r"^[a-zA-Z0-9_-]{1,64}$")
    job_id: str | None = Field(default=None, pattern=r"^[a-zA-Z0-9_-]{1,64}$")
    run_id: str | None = Field(default=None, pattern=r"^[a-zA-Z0-9_-]{1,64}$")
    duration_ms: float | None = Field(
        default=None, ge=0, le=86400000, allow_inf_nan=False
    )
    context: dict[str, str | int | float | bool | None] | None = Field(
        default=None, max_length=20
    )
    error: ClientError | None = None


class ClientBatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    events: list[ClientEvent] = Field(min_length=1, max_length=20)


def install_frontend_logs(app, settings):
    # One global budget across ASGI workers; no attacker-controlled key cardinality.
    database = settings.root / "jobs" / "telemetry.sqlite3"

    @app.post("/api/v1/logs", status_code=204)
    def receive_logs(body: ClientBatch, request: Request):
        origin = request.headers.get("origin")
        if origin and origin not in (
            *settings.cors_origins,
            str(request.base_url).rstrip("/"),
        ):
            raise BackendError("UNAUTHORIZED", "Origin is not allowed", 403)
        try:
            with closing(sqlite3.connect(database, timeout=0.2)) as db:
                db.execute(
                    "CREATE TABLE IF NOT EXISTS budget (id INTEGER PRIMARY KEY, window INTEGER, count INTEGER)"
                )
                db.execute("BEGIN IMMEDIATE")
                window = int(time.time() // 60)
                row = db.execute(
                    "SELECT window,count FROM budget WHERE id=1"
                ).fetchone()
                count = row[1] if row and row[0] == window else 0
                if count >= 60:
                    raise BackendError(
                        "RATE_LIMITED", "Telemetry rate limit exceeded", 429
                    )
                db.execute(
                    "INSERT OR REPLACE INTO budget VALUES (1,?,?)", (window, count + 1)
                )
                db.commit()
        except sqlite3.Error:
            raise BackendError("TELEMETRY_BUSY", "Telemetry unavailable", 503) from None
        for item in body.events:
            data = item.model_dump(exclude_none=True, mode="json")
            # Server timestamp is authoritative; the browser time is untrusted context.
            context = safe(data.pop("context", {}))
            context["client_timestamp"] = data.pop("timestamp")
            context["untrusted_client"] = True
            module, level = data.pop("module"), data.pop("level")
            data.pop("service")
            message = data.pop("message")
            data["context"] = context
            data["source_module"] = "app.frontend." + module
            get_logger("app.frontend").log(getattr(logging, level), message, extra=data)
