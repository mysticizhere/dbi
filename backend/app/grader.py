"""Evaluates exercise assertions against a plan (spec F4).

Grading reads the same typed tree the visualizer renders, so what the UI shows
and what the grader decided can never disagree.

Every result carries the *observed* value, not just a verdict. "Failed" teaches
nothing; "expected no Seq Scan, found one on events reading 145,705 blocks"
tells you what to do next.
"""

from __future__ import annotations

from collections.abc import Iterator

from app.models.exercise import (
    Assertion,
    AssertionResult,
    AssertionType,
    Exercise,
    GradeResult,
)
from app.models.plan import AnalyzedPlan, PlanNodeModel
from app.models.run import RunResponse


def _walk(node: PlanNodeModel) -> Iterator[PlanNodeModel]:
    yield node
    for child in node.children:
        yield from _walk(child)


def _matches_type(node_type: str, target: str) -> bool:
    """Does this node's type match the asserted one?

    Exact, or the parallel variant: asserting "Seq Scan" should also match
    "Parallel Seq Scan", because they are the same access method. Deliberately
    not a substring test -- "Index Scan" must not quietly match
    "Index Only Scan", which is a different thing with different costs.
    """
    actual = node_type.strip().casefold()
    wanted = target.strip().casefold()
    return actual == wanted or actual == f"parallel {wanted}"


def _describe(node: PlanNodeModel) -> str:
    bits = [node.node_type]
    if node.index_name:
        bits.append(f"using {node.index_name}")
    if node.relation:
        bits.append(f"on {node.relation}")
    return " ".join(bits)


def _find_nodes(plan: AnalyzedPlan, a: Assertion) -> list[PlanNodeModel]:
    out = []
    for node in _walk(plan.root):
        if a.node_type and not _matches_type(node.node_type, a.node_type):
            continue
        if a.relation and node.relation != a.relation:
            continue
        if a.index_name and node.index_name != a.index_name:
            continue
        out.append(node)
    return out


def _scope(a: Assertion) -> str:
    """Human-readable description of what the assertion is scoped to."""
    bits = [f"'{a.node_type}'"]
    if a.relation:
        bits.append(f"on {a.relation}")
    if a.index_name:
        bits.append(f"using {a.index_name}")
    return " ".join(bits)


def _has_node(plan: AnalyzedPlan, a: Assertion) -> AssertionResult:
    found = _find_nodes(plan, a)
    present = [n.node_type for n in _walk(plan.root)]
    return AssertionResult(
        type=a.type,
        description=f"plan contains a {_scope(a)} node",
        passed=bool(found),
        expected=f"at least one {_scope(a)}",
        observed=(
            ", ".join(_describe(n) for n in found[:3])
            if found
            else f"not found — plan has: {', '.join(dict.fromkeys(present))}"
        ),
        node_ids=[n.id for n in found],
    )


def _no_node(plan: AnalyzedPlan, a: Assertion) -> AssertionResult:
    found = _find_nodes(plan, a)
    detail = None
    if found:
        blocks = max(
            n.self_buffers.shared_hit + n.self_buffers.shared_read for n in found
        )
        detail = f"the worst one touched {blocks:,} blocks"
    return AssertionResult(
        type=a.type,
        description=f"plan contains no {_scope(a)} node",
        passed=not found,
        expected=f"no {_scope(a)}",
        observed=(
            f"found {len(found)}: {', '.join(_describe(n) for n in found[:3])}"
            if found
            else "none"
        ),
        detail=detail,
        node_ids=[n.id for n in found],
    )


def _heap_fetches_max(plan: AnalyzedPlan, a: Assertion) -> AssertionResult:
    limit = int(a.value or 0)
    scans = [n for n in _walk(plan.root) if "index only scan" in n.node_type.casefold()]
    worst = 0
    culprits: list[int] = []
    for node in scans:
        fetches = int(node.metrics.get("heap_fetches", 0) or 0)
        if fetches > worst:
            worst = fetches
        if fetches > limit:
            culprits.append(node.id)

    if not scans:
        return AssertionResult(
            type=a.type,
            description=f"index-only scans do at most {limit:,} heap fetches",
            passed=False,
            expected=f"<= {limit:,} heap fetches",
            observed="no Index Only Scan in the plan at all",
            detail="Heap fetches only apply to index-only scans; this plan has none.",
        )

    return AssertionResult(
        type=a.type,
        description=f"index-only scans do at most {limit:,} heap fetches",
        passed=worst <= limit,
        expected=f"<= {limit:,}",
        observed=f"{worst:,}",
        detail=(
            "The visibility map is stale, so the scan still had to check the heap. "
            "VACUUM the table."
            if worst > limit
            else None
        ),
        node_ids=culprits,
    )


def _max_estimate_error(plan: AnalyzedPlan, a: Assertion) -> AssertionResult:
    limit = float(a.value or 0)
    worst = plan.summary.max_estimate_error
    node_id = plan.summary.max_estimate_error_node
    return AssertionResult(
        type=a.type,
        description=f"worst row estimate is within {limit:g}x of reality",
        passed=worst is not None and worst <= limit,
        expected=f"<= {limit:g}x",
        observed="no row counts (not an ANALYZE run)" if worst is None else f"{worst:,.1f}x",
        detail=(
            "Everything above that node was costed on a wrong row count."
            if worst is not None and worst > limit
            else None
        ),
        node_ids=[node_id] if node_id is not None else [],
    )


def _max_shared_read(plan: AnalyzedPlan, a: Assertion) -> AssertionResult:
    limit = int(a.value or 0)
    read = plan.summary.buffers.shared_read
    return AssertionResult(
        type=a.type,
        description=f"reads at most {limit:,} blocks from disk",
        passed=read <= limit,
        expected=f"<= {limit:,} blocks",
        observed=f"{read:,} blocks",
        detail=(
            "shared_read is the machine-independent measure of work. Cached runs "
            "can hide a bad plan behind a good wall time; this cannot."
        ),
    )


def _max_total_blocks(plan: AnalyzedPlan, a: Assertion) -> AssertionResult:
    limit = int(a.value or 0)
    b = plan.summary.buffers
    touched = b.shared_hit + b.shared_read
    return AssertionResult(
        type=a.type,
        description=f"touches at most {limit:,} blocks",
        passed=touched <= limit,
        expected=f"<= {limit:,} blocks",
        observed=f"{touched:,} blocks ({b.shared_hit:,} hit + {b.shared_read:,} read)",
        detail=(
            "Blocks touched is the honest measure of work: unlike wall time it does "
            "not move with machine speed, and unlike shared_read alone it does not "
            "move with what happened to already be cached."
        ),
    )


def _max_total_time_ms(run: RunResponse, a: Assertion) -> AssertionResult:
    limit = float(a.value or 0)
    median = run.timings.median_ms if run.timings else None
    return AssertionResult(
        type=a.type,
        description=f"median run is under {limit:g} ms",
        passed=median is not None and median <= limit,
        expected=f"<= {limit:g} ms",
        observed="not measured" if median is None else f"{median:.2f} ms",
        detail=(
            "Wall-clock assertions are machine- and cache-dependent. Treat a "
            "near miss here as noise, not a failure."
        ),
    )


def _no_sort_spill(plan: AnalyzedPlan, a: Assertion) -> AssertionResult:
    spilled = [
        n
        for n in _walk(plan.root)
        if "external" in str(n.metrics.get("sort_method", "")).casefold()
    ]
    used = [int(n.metrics.get("sort_space_used_kb", 0) or 0) for n in spilled]
    return AssertionResult(
        type=a.type,
        description="no sort spilled to disk",
        passed=not spilled,
        expected="every sort in memory",
        observed=(
            f"{len(spilled)} external merge sort(s), {max(used):,} kB at worst"
            if spilled
            else "none"
        ),
        detail="work_mem is too small for this sort." if spilled else None,
        node_ids=[n.id for n in spilled],
    )


def _returns_same_rows(run: RunResponse, a: Assertion) -> AssertionResult:
    match = run.rows_match
    return AssertionResult(
        type=a.type,
        description="returns the same rows as the reference solution",
        passed=match is True,
        expected="identical result set",
        observed={
            True: "identical",
            False: "different rows",
            None: "not compared",
        }[match],
        detail=(
            "A fast plan that returns the wrong answer is not a solution."
            if match is False
            else run.rows_match_error
        ),
    )


def grade(exercise: Exercise, plan: AnalyzedPlan | None, run: RunResponse) -> GradeResult:
    """Evaluate every assertion. Always returns one result per assertion."""
    if not run.ok:
        return GradeResult(
            exercise_id=exercise.id,
            passed=False,
            error=run.error.message if run.error else "the query did not run",
        )
    if plan is None:
        return GradeResult(
            exercise_id=exercise.id,
            passed=False,
            error="no plan was produced — grading needs an Analyze run",
        )

    results: list[AssertionResult] = []
    for a in exercise.assertions:
        if a.type is AssertionType.HAS_NODE:
            result = _has_node(plan, a)
        elif a.type is AssertionType.NO_NODE:
            result = _no_node(plan, a)
        elif a.type is AssertionType.HEAP_FETCHES_MAX:
            result = _heap_fetches_max(plan, a)
        elif a.type is AssertionType.MAX_ESTIMATE_ERROR:
            result = _max_estimate_error(plan, a)
        elif a.type is AssertionType.MAX_SHARED_READ:
            result = _max_shared_read(plan, a)
        elif a.type is AssertionType.MAX_TOTAL_BLOCKS:
            result = _max_total_blocks(plan, a)
        elif a.type is AssertionType.MAX_TOTAL_TIME_MS:
            result = _max_total_time_ms(run, a)
        elif a.type is AssertionType.NO_SORT_SPILL:
            result = _no_sort_spill(plan, a)
        else:
            result = _returns_same_rows(run, a)
        result.because = a.because
        results.append(result)

    return GradeResult(
        exercise_id=exercise.id,
        passed=all(r.passed for r in results),
        results=results,
    )
