"""Request/response models for the query workbench (spec F1)."""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

from app.config import settings
from app.models.plan import AnalyzedPlan, Buffers


class RunMode(StrEnum):
    EXECUTE = "execute"  # run it, return capped rows
    EXPLAIN = "explain"  # plan only, nothing executed
    ANALYZE = "analyze"  # EXPLAIN (ANALYZE, BUFFERS, VERBOSE, SETTINGS, FORMAT JSON)


class RunRequest(BaseModel):
    sql: str = Field(min_length=1)
    mode: RunMode = RunMode.ANALYZE

    # Sandbox wraps the whole run in BEGIN..ROLLBACK. Postgres DDL is
    # transactional, so a CREATE INDEX is visible to the planner and then
    # discarded -- which is what makes index experimentation free.
    sandbox: bool = True

    statement_timeout_ms: int = Field(
        default=settings.statement_timeout_ms, ge=100, le=settings.max_statement_timeout_ms
    )
    # Repeat-N: the first run is discarded (cold caches, cold plan cache) and the
    # median of the rest is reported.
    repeat: int = Field(default=1, ge=1, le=50)
    row_cap: int = Field(default=settings.result_row_cap, ge=1, le=10_000)

    # Per-run planner knobs, e.g. {"enable_seqscan": "off"}. Applied with SET LOCAL
    # in sandbox mode, SET otherwise.
    settings_overrides: dict[str, str] = Field(default_factory=dict)


class Timings(BaseModel):
    """Per-repetition timings, in milliseconds."""

    runs_ms: list[float] = Field(default_factory=list)
    discarded_first_ms: float | None = None
    median_ms: float | None = None
    p25_ms: float | None = None
    p75_ms: float | None = None
    min_ms: float | None = None
    max_ms: float | None = None
    # Server-reported, from the plan. Excludes network and client overhead.
    planning_ms: float | None = None
    execution_ms: float | None = None


class ResultSet(BaseModel):
    columns: list[str] = Field(default_factory=list)
    rows: list[list[Any]] = Field(default_factory=list)
    row_count: int = 0
    truncated: bool = False


class RunError(BaseModel):
    message: str
    sqlstate: str | None = None
    detail: str | None = None
    hint: str | None = None
    position: int | None = None
    # Which statement of the script failed (0-based), when we know.
    statement_index: int | None = None


class StatementInfo(BaseModel):
    index: int
    sql: str
    is_target: bool  # the last statement -- the one that gets explained/measured
    duration_ms: float | None = None


class RunResponse(BaseModel):
    ok: bool
    mode: RunMode
    sandbox: bool
    statements: list[StatementInfo] = Field(default_factory=list)

    plan: dict[str, Any] | None = None  # raw EXPLAIN FORMAT JSON, kept for the JSON tab
    analyzed_plan: AnalyzedPlan | None = None  # typed tree the visualizer renders
    result: ResultSet | None = None
    timings: Timings | None = None
    buffers: Buffers | None = None

    notices: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    error: RunError | None = None
