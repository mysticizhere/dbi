"""Turn raw EXPLAIN JSON into the typed tree the UI and the grader both read.

Two jobs: rename Postgres' space-separated keys onto real fields, and derive the
numbers EXPLAIN does not give you -- self time, self buffers, estimate error,
and the warning chips from spec F2.
"""

from __future__ import annotations

from typing import Any

from app.config import settings
from app.models.plan import (
    AnalyzedPlan,
    Buffers,
    NodeCost,
    NodeRows,
    NodeTiming,
    PlanNodeModel,
    PlanSummary,
    PlanWarning,
    Severity,
    WarningCode,
)
from app.plan import (
    PlanNode,
    child_divisor,
    children,
    elapsed_ms,
    estimate_error,
    explain_envelope,
    node_buffers,
    root_node,
    self_ms,
    total_ms,
    walk,
)

# Predicates and keys. Sort/Group keys arrive as lists and get joined.
_CONDITION_KEYS = (
    "Filter",
    "Index Cond",
    "Join Filter",
    "Hash Cond",
    "Merge Cond",
    "Recheck Cond",
    "TID Cond",
    "One-Time Filter",
    "Sort Key",
    "Group Key",
    "Presorted Key",
    "Order By",
    "Cache Key",
)

# Node-type-specific measurements, snake_cased for the UI.
_METRIC_KEYS = {
    "Rows Removed by Filter": "rows_removed_by_filter",
    "Rows Removed by Join Filter": "rows_removed_by_join_filter",
    "Rows Removed by Index Recheck": "rows_removed_by_index_recheck",
    "Heap Fetches": "heap_fetches",
    "Sort Method": "sort_method",
    "Sort Space Used": "sort_space_used_kb",
    "Sort Space Type": "sort_space_type",
    "Hash Batches": "hash_batches",
    "Original Hash Batches": "original_hash_batches",
    "Hash Buckets": "hash_buckets",
    "Original Hash Buckets": "original_hash_buckets",
    "Peak Memory Usage": "peak_memory_kb",
    "Exact Heap Blocks": "exact_heap_blocks",
    "Lossy Heap Blocks": "lossy_heap_blocks",
    "Inner Unique": "inner_unique",
    "Function Name": "function_name",
    "Cache Hits": "cache_hits",
    "Cache Misses": "cache_misses",
    "Async Capable": "async_capable",
}


def _as_int(value: Any) -> int | None:
    return int(value) if isinstance(value, (int, float)) else None


def _as_float(value: Any) -> float | None:
    return float(value) if isinstance(value, (int, float)) else None


def _subtract(total: Buffers, parts: list[Buffers]) -> Buffers:
    """Buffer counters are cumulative up the tree, so children subtract out.

    Unlike timing these are already summed over all loops, so no multiplication
    is involved. Clamped at zero for the same reason self time is.
    """
    fields = total.model_dump()
    for part in parts:
        for key, value in part.model_dump().items():
            fields[key] -= value
    return Buffers(**{k: max(0, v) for k, v in fields.items()})


def _conditions(node: PlanNode) -> dict[str, str]:
    out: dict[str, str] = {}
    for key in _CONDITION_KEYS:
        value = node.get(key)
        if isinstance(value, list):
            if value:
                out[key] = ", ".join(str(v) for v in value)
        elif isinstance(value, str) and value:
            out[key] = value
    return out


def _metrics(node: PlanNode) -> dict[str, Any]:
    return {name: node[key] for key, name in _METRIC_KEYS.items() if key in node}


def _rows(node: PlanNode) -> NodeRows:
    planned = _as_int(node.get("Plan Rows"))
    actual = _as_int(node.get("Actual Rows"))
    loops = _as_int(node.get("Actual Loops")) or 1
    ratio = estimate_error(node)
    direction: str | None = None
    if ratio is not None and planned is not None and actual is not None:
        # "over" means the planner expected more rows than materialised, which
        # usually means it picked a heavier plan than it needed to.
        direction = "over" if planned > actual else "under" if planned < actual else "exact"
    return NodeRows(
        planned=planned,
        actual=actual,
        total_actual=float(actual * loops) if actual is not None else None,
        error_ratio=ratio,
        direction=direction,
    )


def _timing(
    node: PlanNode, query_total_ms: float | None, divisor: float
) -> NodeTiming | None:
    per_loop = _as_float(node.get("Actual Total Time"))
    if per_loop is None:
        return None  # plain EXPLAIN, or ANALYZE with TIMING OFF
    own = self_ms(node, divisor)
    fraction = (
        own / query_total_ms if own is not None and query_total_ms not in (None, 0) else None
    )
    return NodeTiming(
        startup_ms=_as_float(node.get("Actual Startup Time")),
        per_loop_ms=per_loop,
        total_ms=total_ms(node),
        elapsed_ms=elapsed_ms(node, divisor),
        self_ms=own,
        self_fraction=fraction,
        loops=_as_int(node.get("Actual Loops")) or 1,
        parallel_divisor=divisor,
    )


def _detect_warnings(
    node: PlanNode,
    model: PlanNodeModel,
    kids: list[PlanNodeModel],
    relation_pages: dict[str, int],
) -> list[PlanWarning]:
    """The auto-derived diagnostics from spec F2, in severity order."""
    found: list[PlanWarning] = []
    node_type = model.node_type
    metrics = model.metrics

    # 1. Estimate off by more than 10x -- the headline number.
    ratio = model.rows.error_ratio
    if ratio is not None and ratio >= settings.estimate_error_threshold:
        critical = ratio >= settings.estimate_error_critical
        found.append(
            PlanWarning(
                code=WarningCode.ESTIMATE_ERROR,
                severity=Severity.CRITICAL if critical else Severity.WARN,
                label=f"{ratio:,.0f}x {model.rows.direction}",
                detail=(
                    f"Planner expected {model.rows.planned:,} rows, got {model.rows.actual:,}. "
                    "Everything above this node was costed on a wrong number -- fix the "
                    "estimate before touching indexes."
                ),
            )
        )

    # 2. Seq Scan on a big relation. Pages come from pg_class; without them we
    #    cannot tell a 4-page table from a 200k-page one, so we stay quiet.
    if node_type.endswith("Seq Scan") and model.relation:
        pages = relation_pages.get(model.relation)
        if pages is not None and pages > settings.seq_scan_pages_threshold:
            mb = pages * 8 / 1024
            found.append(
                PlanWarning(
                    code=WarningCode.SEQ_SCAN_LARGE,
                    severity=Severity.WARN,
                    label=f"seq scan {mb:,.0f} MB",
                    detail=(
                        f"Full scan of {model.relation} ({pages:,} pages, ~{mb:,.0f} MB). "
                        "Fine if you need most of the table; expensive if the predicate is "
                        "selective and unindexed."
                    ),
                )
            )

    # 3. Index Only Scan still visiting the heap -> visibility map is stale.
    heap_fetches = _as_int(metrics.get("heap_fetches"))
    if "Index Only Scan" in node_type and heap_fetches:
        found.append(
            PlanWarning(
                code=WarningCode.HEAP_FETCHES,
                severity=Severity.WARN,
                label=f"{heap_fetches:,} heap fetches",
                detail=(
                    "An index-only scan that still reads the heap. The visibility map is "
                    "out of date -- VACUUM the table and this should drop to zero."
                ),
            )
        )

    # 4. Sort spilled to disk.
    sort_method = metrics.get("sort_method")
    if isinstance(sort_method, str) and "external" in sort_method.lower():
        used = _as_int(metrics.get("sort_space_used_kb"))
        found.append(
            PlanWarning(
                code=WarningCode.SORT_SPILL,
                severity=Severity.WARN,
                label="external merge",
                detail=(
                    f"Sort spilled to disk ({used:,} kB) because work_mem was too small. "
                    "Raise work_mem for this query, or avoid the sort with an ordered index."
                    if used
                    else "Sort spilled to disk: work_mem is too small for this query."
                ),
            )
        )

    # 5. Hash spilled to multiple batches.
    batches = _as_int(metrics.get("hash_batches"))
    if batches is not None and batches > 1:
        found.append(
            PlanWarning(
                code=WarningCode.HASH_SPILL,
                severity=Severity.WARN,
                label=f"{batches} hash batches",
                detail=(
                    f"The hash table did not fit in work_mem and was split into {batches} "
                    "batches, each written to and re-read from disk."
                ),
            )
        )

    # 6. Nested loop driving a huge number of inner rescans.
    if node_type == "Nested Loop":
        inner_loops = max(
            (k.timing.loops for k in kids if k.timing is not None),
            default=0,
        )
        if inner_loops > settings.nested_loop_loops_threshold:
            found.append(
                PlanWarning(
                    code=WarningCode.NESTED_LOOP_LOOPS,
                    severity=Severity.WARN,
                    label=f"{inner_loops:,} loops",
                    detail=(
                        f"The inner side ran {inner_loops:,} times. Cheap per loop, but the "
                        "total adds up -- a hash or merge join may win at this row count."
                    ),
                )
            )

    # 7. Predicate throwing away far more rows than it keeps.
    removed = _as_int(metrics.get("rows_removed_by_filter")) or 0
    kept = model.rows.actual or 0
    if (
        removed >= settings.filter_discard_min_rows
        and removed > settings.filter_discard_ratio * max(kept, 1)
    ):
        found.append(
            PlanWarning(
                code=WarningCode.FILTER_DISCARD,
                severity=Severity.WARN,
                label=f"{removed:,} discarded",
                detail=(
                    f"Read and threw away {removed:,} rows to keep {kept:,}. The rows were "
                    "fetched before being filtered -- an index on the predicate would skip "
                    "them instead."
                ),
            )
        )

    # 8. Bitmap went lossy -- work_mem too small to track individual tuples.
    lossy = _as_int(metrics.get("lossy_heap_blocks"))
    if lossy:
        found.append(
            PlanWarning(
                code=WarningCode.LOSSY_BITMAP,
                severity=Severity.INFO,
                label=f"{lossy:,} lossy blocks",
                detail=(
                    "The bitmap exceeded work_mem and degraded to whole-page granularity, "
                    "so every row on those pages must be rechecked."
                ),
            )
        )

    for warning in found:
        warning.node_id = model.id
    return found


class _Builder:
    """Walks the raw tree once, assigning stable depth-first ids."""

    def __init__(self, relation_pages: dict[str, int], query_total_ms: float | None) -> None:
        self.relation_pages = relation_pages
        self.query_total_ms = query_total_ms
        self.next_id = 0
        self.warnings: list[PlanWarning] = []

    def build(self, node: PlanNode, depth: int = 0, divisor: float = 1.0) -> PlanNodeModel:
        node_id = self.next_id
        self.next_id += 1

        # Children of a Gather run concurrently; everything else inherits.
        inner = child_divisor(node, divisor)
        kids = [self.build(child, depth + 1, inner) for child in children(node)]
        buffers = node_buffers(node)

        model = PlanNodeModel(
            id=node_id,
            depth=depth,
            node_type=str(node.get("Node Type", "?")),
            parent_relationship=node.get("Parent Relationship"),
            subplan_name=node.get("Subplan Name"),
            cte_name=node.get("CTE Name"),
            relation=node.get("Relation Name"),
            alias=node.get("Alias"),
            index_name=node.get("Index Name"),
            join_type=node.get("Join Type"),
            scan_direction=node.get("Scan Direction"),
            strategy=node.get("Strategy"),
            parallel_aware=bool(node.get("Parallel Aware", False)),
            workers_planned=_as_int(node.get("Workers Planned")),
            workers_launched=_as_int(node.get("Workers Launched")),
            cost=NodeCost(
                startup=_as_float(node.get("Startup Cost")),
                total=_as_float(node.get("Total Cost")),
                width=_as_int(node.get("Plan Width")),
            ),
            rows=_rows(node),
            timing=_timing(node, self.query_total_ms, divisor),
            buffers=buffers,
            self_buffers=_subtract(buffers, [k.buffers for k in kids]),
            conditions=_conditions(node),
            metrics=_metrics(node),
            output=[str(o) for o in node.get("Output", [])]
            if isinstance(node.get("Output"), list)
            else [],
            children=kids,
        )

        model.warnings = _detect_warnings(node, model, kids, self.relation_pages)
        self.warnings.extend(model.warnings)
        return model


_SEVERITY_ORDER = {Severity.CRITICAL: 0, Severity.WARN: 1, Severity.INFO: 2}


def relation_names(explain_json: Any) -> list[str]:
    """Relations mentioned anywhere in the plan, for the pg_class lookup."""
    root = root_node(explain_json)
    if root is None:
        return []
    names = {
        str(n["Relation Name"]) for n in walk(root) if isinstance(n.get("Relation Name"), str)
    }
    return sorted(names)


def build_plan(
    explain_json: Any, relation_pages: dict[str, int] | None = None
) -> AnalyzedPlan | None:
    """Build the typed tree. Returns None if there is no plan in the payload."""
    root = root_node(explain_json)
    if root is None:
        return None
    envelope = explain_envelope(explain_json) or {}

    # Self fractions are relative to the root's total, not to Execution Time --
    # the two differ slightly and node fractions should sum to 1.
    query_total = total_ms(root)

    builder = _Builder(relation_pages or {}, query_total)
    tree = builder.build(root)

    nodes = [tree]
    stack = list(tree.children)
    while stack:
        current = stack.pop()
        nodes.append(current)
        stack.extend(current.children)

    analyzed = tree.timing is not None
    worst = max(
        (n for n in nodes if n.rows.error_ratio is not None),
        key=lambda n: n.rows.error_ratio or 0.0,
        default=None,
    )
    slowest = max(
        (n for n in nodes if n.timing is not None),
        key=lambda n: n.timing.self_ms or 0.0 if n.timing else 0.0,
        default=None,
    )

    summary = PlanSummary(
        planning_ms=_as_float(envelope.get("Planning Time")),
        execution_ms=_as_float(envelope.get("Execution Time")),
        total_ms=query_total,
        node_count=len(nodes),
        max_estimate_error=worst.rows.error_ratio if worst else None,
        max_estimate_error_node=worst.id if worst else None,
        slowest_node=slowest.id if slowest else None,
        buffers=tree.buffers,
        analyzed=analyzed,
        parallel=any(n.workers_launched for n in nodes),
        triggers=[t for t in envelope.get("Triggers", []) if isinstance(t, dict)],
        settings={k: str(v) for k, v in (envelope.get("Settings") or {}).items()},
        jit=envelope.get("JIT") if isinstance(envelope.get("JIT"), dict) else None,
    )

    builder.warnings.sort(key=lambda w: (_SEVERITY_ORDER[w.severity], -_warning_rank(w)))
    return AnalyzedPlan(root=tree, summary=summary, warnings=builder.warnings)


def _warning_rank(warning: PlanWarning) -> float:
    """Rough magnitude, so the biggest offender of a severity sorts first."""
    digits = "".join(c for c in warning.label if c.isdigit())
    return float(digits) if digits else 0.0
