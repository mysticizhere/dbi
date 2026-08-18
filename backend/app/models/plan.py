"""Typed model of an execution plan (spec F2).

`EXPLAIN (FORMAT JSON)` gives back nested dicts with space-separated keys and
values that mean different things depending on the node type. This module turns
that into something with names, and attaches the derived numbers -- self time,
estimate error, self buffers, warnings -- that the raw output does not carry.

Deriving them here rather than in the browser is deliberate: M2's assertion
evaluator grades against exactly these fields, so grading and rendering can
never disagree about what a plan says.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class Buffers(BaseModel):
    """Block counters. The honest metric -- machine-independent, unlike time.

    Postgres reports these cumulatively up the plan tree and already summed over
    every loop, so a parent's number includes all its children's.
    """

    shared_hit: int = 0
    shared_read: int = 0
    shared_dirtied: int = 0
    shared_written: int = 0
    local_hit: int = 0
    local_read: int = 0
    temp_read: int = 0
    temp_written: int = 0


class Severity(StrEnum):
    INFO = "info"
    WARN = "warn"
    CRITICAL = "critical"


class WarningCode(StrEnum):
    """The auto-derived diagnostics from spec F2."""

    ESTIMATE_ERROR = "estimate_error"
    SEQ_SCAN_LARGE = "seq_scan_large"
    HEAP_FETCHES = "heap_fetches"
    SORT_SPILL = "sort_spill"
    HASH_SPILL = "hash_spill"
    NESTED_LOOP_LOOPS = "nested_loop_loops"
    FILTER_DISCARD = "filter_discard"
    LOSSY_BITMAP = "lossy_bitmap"


class PlanWarning(BaseModel):
    code: WarningCode
    severity: Severity
    # Short enough to sit on a chip, e.g. "163x under".
    label: str
    # One sentence saying what it means and what to do about it.
    detail: str
    node_id: int = -1


class NodeRows(BaseModel):
    """Row counts. Both figures are per-loop, so they compare directly."""

    planned: int | None = None
    actual: int | None = None
    # actual x loops -- the number of rows this node really produced.
    total_actual: float | None = None
    # max(actual/planned, planned/actual). 1.0 is perfect.
    error_ratio: float | None = None
    # "over" = planner expected more than it got.
    direction: str | None = None


class NodeTiming(BaseModel):
    """Milliseconds. Everything but `per_loop_ms` is already multiplied out by loops.

    `total_ms` and `elapsed_ms` differ only inside a parallel subtree: N workers
    running concurrently contribute N x their time to `total_ms` (which is CPU
    work) but only 1x to `elapsed_ms` (which is wall clock). Outside a Gather
    they are equal.
    """

    startup_ms: float | None = None
    per_loop_ms: float | None = None
    # ATT x loops -- total work done across every loop and worker.
    total_ms: float | None = None
    # total_ms divided back down by concurrent workers: wall-clock contribution.
    elapsed_ms: float | None = None
    self_ms: float | None = None
    # self_ms as a fraction of the whole query, for flame colouring. Sums to 1.
    self_fraction: float | None = None
    loops: int = 1
    # Concurrent processes running this node. >1 only under a Gather.
    parallel_divisor: float = 1.0


class NodeCost(BaseModel):
    startup: float | None = None
    total: float | None = None
    width: int | None = None


class PlanNodeModel(BaseModel):
    """One node of the plan tree."""

    # Stable depth-first index. The UI selects by it; assertions report it.
    id: int
    node_type: str
    depth: int = 0

    # How this node hangs off its parent: Outer / Inner / Member / InitPlan /
    # SubPlan. CTEs and subplans arrive as named InitPlan children.
    parent_relationship: str | None = None
    subplan_name: str | None = None
    cte_name: str | None = None

    relation: str | None = None
    alias: str | None = None
    index_name: str | None = None
    join_type: str | None = None
    scan_direction: str | None = None
    strategy: str | None = None

    parallel_aware: bool = False
    workers_planned: int | None = None
    workers_launched: int | None = None

    cost: NodeCost = Field(default_factory=NodeCost)
    rows: NodeRows = Field(default_factory=NodeRows)
    timing: NodeTiming | None = None

    # Cumulative, as Postgres reports them.
    buffers: Buffers = Field(default_factory=Buffers)
    # Cumulative minus children: which node actually did the I/O.
    self_buffers: Buffers = Field(default_factory=Buffers)

    # Filter / Index Cond / Join Filter / Hash Cond / Recheck Cond / ...
    conditions: dict[str, str] = Field(default_factory=dict)
    # Node-type-specific numbers: heap_fetches, sort_method, hash_batches, ...
    metrics: dict[str, Any] = Field(default_factory=dict)
    output: list[str] = Field(default_factory=list)

    warnings: list[PlanWarning] = Field(default_factory=list)
    children: list[PlanNodeModel] = Field(default_factory=list)


class PlanSummary(BaseModel):
    """Whole-query figures, for the header strip."""

    planning_ms: float | None = None
    execution_ms: float | None = None
    total_ms: float | None = None
    node_count: int = 0
    max_estimate_error: float | None = None
    # Node id carrying that worst estimate, so the UI can jump straight to it.
    max_estimate_error_node: int | None = None
    slowest_node: int | None = None
    buffers: Buffers = Field(default_factory=Buffers)
    # False for plain EXPLAIN: there are no actuals, so timing and error views
    # have nothing to show and the UI should say so rather than render zeros.
    analyzed: bool = False
    parallel: bool = False
    triggers: list[dict[str, Any]] = Field(default_factory=list)
    settings: dict[str, str] = Field(default_factory=dict)
    jit: dict[str, Any] | None = None


class AnalyzedPlan(BaseModel):
    root: PlanNodeModel
    summary: PlanSummary
    # Every node's warnings, flattened and sorted worst-first.
    warnings: list[PlanWarning] = Field(default_factory=list)
