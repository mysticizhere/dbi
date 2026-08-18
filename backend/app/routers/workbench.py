"""Workbench endpoints (spec F1)."""

from __future__ import annotations

from typing import Any

import psycopg
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.db import data_conn, meta_conn
from app.models.run import RunRequest, RunResponse
from app.runner import run_query

router = APIRouter(tags=["workbench"])


@router.post("/run", response_model=RunResponse)
async def post_run(req: RunRequest) -> RunResponse:
    """Run a SQL script. Failures come back as ok=false, not as HTTP errors --
    a syntax error is a normal outcome in a lab, not a server fault."""
    return await run_query(req)


class HealthResponse(BaseModel):
    ok: bool
    server_version: str | None = None
    databases: dict[str, bool] = Field(default_factory=dict)
    extensions: dict[str, str] = Field(default_factory=dict)
    missing_extensions: list[str] = Field(default_factory=list)
    settings: dict[str, str] = Field(default_factory=dict)


REQUIRED_EXTENSIONS = [
    "pg_stat_statements",
    "pageinspect",
    "pgstattuple",
    "pg_prewarm",
    "pg_buffercache",
    "hypopg",
]

# Reported on the health page because every measurement in the app is relative
# to them -- a surprising number here explains a surprising number everywhere.
REPORTED_SETTINGS = [
    "server_version",
    "shared_buffers",
    "work_mem",
    "effective_cache_size",
    "random_page_cost",
    "seq_page_cost",
    "default_statistics_target",
    "max_parallel_workers_per_gather",
    "track_io_timing",
]


@router.get("/health", response_model=HealthResponse)
async def get_health() -> HealthResponse:
    try:
        async with data_conn() as conn:
            ext_rows = await (
                await conn.execute("SELECT extname, extversion FROM pg_extension")
            ).fetchall()
            setting_rows = await (
                await conn.execute(
                    "SELECT name, setting, unit FROM pg_settings WHERE name = ANY(%s)",
                    (REPORTED_SETTINGS,),
                )
            ).fetchall()
            version_row = await (await conn.execute("SHOW server_version")).fetchone()

        async with meta_conn() as conn:
            await conn.execute("SELECT 1")
    except (psycopg.Error, RuntimeError) as exc:
        raise HTTPException(status_code=503, detail=f"database unavailable: {exc}") from exc

    extensions = {str(r["extname"]): str(r["extversion"]) for r in ext_rows}
    settings_map: dict[str, str] = {}
    for row in setting_rows:
        unit = row.get("unit")
        settings_map[str(row["name"])] = f"{row['setting']}{unit or ''}"

    return HealthResponse(
        ok=True,
        server_version=str(version_row["server_version"]) if version_row else None,
        databases={"lab_data": True, "lab_meta": True},
        extensions=extensions,
        missing_extensions=[e for e in REQUIRED_EXTENSIONS if e not in extensions],
        settings=settings_map,
    )


class MaintenanceRequest(BaseModel):
    relation: str | None = None


@router.post("/maintenance/prewarm")
async def post_prewarm(req: MaintenanceRequest) -> dict[str, Any]:
    """Pull a relation into shared_buffers, for honest warm-cache comparisons."""
    if not req.relation:
        raise HTTPException(status_code=400, detail="relation is required")
    async with data_conn() as conn:
        try:
            row = await (
                await conn.execute("SELECT pg_prewarm(%s::regclass) AS blocks", (req.relation,))
            ).fetchone()
        except psycopg.Error as exc:
            raise HTTPException(status_code=400, detail=str(exc).strip()) from exc
    return {"ok": True, "relation": req.relation, "blocks": row["blocks"] if row else None}


@router.post("/maintenance/discard")
async def post_discard() -> dict[str, Any]:
    """DISCARD ALL on the playground connection.

    Note this only clears *session* state. It cannot evict shared_buffers, and it
    certainly cannot touch the OS page cache -- for a genuinely cold run the only
    honest option is restarting the container.
    """
    async with data_conn() as conn:
        await conn.execute("DISCARD ALL")
    return {"ok": True, "note": "Session state cleared. shared_buffers and OS cache are untouched."}
