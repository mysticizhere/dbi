"""Assertion evaluator tests (spec F4).

Every assertion type gets a passing case and a failing case. An assertion that
can only pass is decoration, not grading.
"""

from __future__ import annotations

from typing import Any

import pytest

from app.grader import grade
from app.models.exercise import Assertion, AssertionType, Exercise
from app.models.plan import AnalyzedPlan
from app.models.run import RunMode, RunResponse, Timings
from app.plan_builder import build_plan


def node(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "Node Type": "Seq Scan",
        "Relation Name": "events",
        "Plan Rows": 100,
        "Actual Rows": 100,
        "Actual Loops": 1,
        "Actual Total Time": 10.0,
        "Shared Hit Blocks": 500,
        "Shared Read Blocks": 100,
    }
    base.update(overrides)
    return base


def plan_of(root: dict[str, Any]) -> AnalyzedPlan:
    built = build_plan({"Plan": root, "Planning Time": 0.1, "Execution Time": 11.0})
    assert built is not None
    return built


def run_of(**overrides: Any) -> RunResponse:
    fields: dict[str, Any] = {"ok": True, "mode": RunMode.ANALYZE, "sandbox": True}
    fields.update(overrides)
    return RunResponse(**fields)


def exercise_with(*assertions: Assertion) -> Exercise:
    return Exercise(
        id="t",
        title="t",
        layer=3,
        difficulty=1,
        prompt="p",
        assertions=list(assertions),
        slug="00-test",
    )


def verdicts(
    *assertions: Assertion, root: dict[str, Any], run: RunResponse | None = None
) -> tuple[list[bool], Any]:
    result = grade(exercise_with(*assertions), plan_of(root), run or run_of())
    return [r.passed for r in result.results], result


# --- has_node / no_node -----------------------------------------------------


def test_has_node_finds_a_matching_node() -> None:
    passed, _ = verdicts(
        Assertion(type=AssertionType.HAS_NODE, node_type="Seq Scan"), root=node()
    )
    assert passed == [True]


def test_has_node_fails_and_lists_what_was_there() -> None:
    passed, result = verdicts(
        Assertion(type=AssertionType.HAS_NODE, node_type="Index Scan"), root=node()
    )
    assert passed == [False]
    # A failure has to say what the plan *did* contain, or it teaches nothing.
    assert "Seq Scan" in result.results[0].observed


def test_node_match_accepts_the_parallel_variant() -> None:
    passed, _ = verdicts(
        Assertion(type=AssertionType.HAS_NODE, node_type="Seq Scan"),
        root=node(**{"Node Type": "Parallel Seq Scan"}),
    )
    assert passed == [True]


def test_index_scan_does_not_match_index_only_scan() -> None:
    # These are different access methods with different costs. A substring match
    # would quietly conflate them and pass exercises that should fail.
    passed, _ = verdicts(
        Assertion(type=AssertionType.HAS_NODE, node_type="Index Scan"),
        root=node(**{"Node Type": "Index Only Scan"}),
    )
    assert passed == [False]


def test_has_node_can_be_scoped_to_a_relation() -> None:
    root = node(**{"Node Type": "Nested Loop", "Relation Name": None, "Plans": [
        node(**{"Node Type": "Index Scan", "Relation Name": "orders"}),
    ]})
    assert verdicts(
        Assertion(type=AssertionType.HAS_NODE, node_type="Index Scan", relation="events"),
        root=root,
    )[0] == [False]
    assert verdicts(
        Assertion(type=AssertionType.HAS_NODE, node_type="Index Scan", relation="orders"),
        root=root,
    )[0] == [True]


def test_has_node_can_be_scoped_to_an_index() -> None:
    root = node(**{"Node Type": "Index Scan", "Index Name": "idx_events_score"})
    assert verdicts(
        Assertion(
            type=AssertionType.HAS_NODE, node_type="Index Scan", index_name="idx_events_score"
        ),
        root=root,
    )[0] == [True]
    assert verdicts(
        Assertion(type=AssertionType.HAS_NODE, node_type="Index Scan", index_name="idx_other"),
        root=root,
    )[0] == [False]


def test_no_node_is_the_inverse() -> None:
    assert verdicts(
        Assertion(type=AssertionType.NO_NODE, node_type="Seq Scan"), root=node()
    )[0] == [False]
    assert verdicts(
        Assertion(type=AssertionType.NO_NODE, node_type="Seq Scan"),
        root=node(**{"Node Type": "Index Scan"}),
    )[0] == [True]


def test_no_node_failure_reports_the_damage() -> None:
    _, result = verdicts(
        Assertion(type=AssertionType.NO_NODE, node_type="Seq Scan"),
        root=node(**{"Shared Hit Blocks": 1000, "Shared Read Blocks": 900}),
    )
    assert "1,900 blocks" in (result.results[0].detail or "")


# --- thresholds -------------------------------------------------------------


def test_heap_fetches_max() -> None:
    ios = node(**{"Node Type": "Index Only Scan", "Heap Fetches": 0})
    assert verdicts(
        Assertion(type=AssertionType.HEAP_FETCHES_MAX, value=0), root=ios
    )[0] == [True]
    dirty = node(**{"Node Type": "Index Only Scan", "Heap Fetches": 4200})
    passed, result = verdicts(Assertion(type=AssertionType.HEAP_FETCHES_MAX, value=0), root=dirty)
    assert passed == [False]
    assert "4,200" in result.results[0].observed


def test_heap_fetches_on_a_plan_with_no_index_only_scan_fails_clearly() -> None:
    # Silently passing would let someone "solve" the exercise by removing the
    # index-only scan entirely.
    passed, result = verdicts(
        Assertion(type=AssertionType.HEAP_FETCHES_MAX, value=0), root=node()
    )
    assert passed == [False]
    assert "no Index Only Scan" in result.results[0].observed


def test_heap_fetches_counts_the_parallel_variant() -> None:
    root = node(**{"Node Type": "Parallel Index Only Scan", "Heap Fetches": 9})
    assert verdicts(
        Assertion(type=AssertionType.HEAP_FETCHES_MAX, value=0), root=root
    )[0] == [False]


def test_max_estimate_error() -> None:
    good = node(**{"Plan Rows": 100, "Actual Rows": 120})
    assert verdicts(
        Assertion(type=AssertionType.MAX_ESTIMATE_ERROR, value=3.0), root=good
    )[0] == [True]
    bad = node(**{"Plan Rows": 100, "Actual Rows": 16000})
    passed, result = verdicts(
        Assertion(type=AssertionType.MAX_ESTIMATE_ERROR, value=3.0), root=bad
    )
    assert passed == [False]
    assert "160" in result.results[0].observed


def test_max_shared_read_uses_only_the_read_half() -> None:
    root = node(**{"Shared Hit Blocks": 900_000, "Shared Read Blocks": 10})
    assert verdicts(
        Assertion(type=AssertionType.MAX_SHARED_READ, value=100), root=root
    )[0] == [True]


def test_max_total_blocks_counts_hit_plus_read() -> None:
    # The point of this assertion existing: the same plan reads a different
    # number of blocks depending on what was cached, but touches the same total.
    warm = node(**{"Shared Hit Blocks": 199_000, "Shared Read Blocks": 803})
    cold = node(**{"Shared Hit Blocks": 65_850, "Shared Read Blocks": 133_953})
    limit = Assertion(type=AssertionType.MAX_TOTAL_BLOCKS, value=150_000)
    assert verdicts(limit, root=warm)[0] == [False]
    assert verdicts(limit, root=cold)[0] == [False]

    small = node(**{"Shared Hit Blocks": 9_786, "Shared Read Blocks": 22})
    assert verdicts(limit, root=small)[0] == [True]


def test_max_total_time_ms_reads_the_median() -> None:
    fast = run_of(timings=Timings(median_ms=12.0))
    slow = run_of(timings=Timings(median_ms=900.0))
    a = Assertion(type=AssertionType.MAX_TOTAL_TIME_MS, value=100)
    assert verdicts(a, root=node(), run=fast)[0] == [True]
    assert verdicts(a, root=node(), run=slow)[0] == [False]


def test_max_total_time_ms_without_timings_fails_rather_than_erroring() -> None:
    a = Assertion(type=AssertionType.MAX_TOTAL_TIME_MS, value=100)
    passed, result = verdicts(a, root=node(), run=run_of())
    assert passed == [False]
    assert result.results[0].observed == "not measured"


def test_no_sort_spill() -> None:
    clean = node(**{"Node Type": "Sort", "Sort Method": "quicksort"})
    assert verdicts(Assertion(type=AssertionType.NO_SORT_SPILL), root=clean)[0] == [True]
    spilled = node(
        **{"Node Type": "Sort", "Sort Method": "external merge", "Sort Space Used": 63720}
    )
    passed, result = verdicts(Assertion(type=AssertionType.NO_SORT_SPILL), root=spilled)
    assert passed == [False]
    assert "63,720 kB" in result.results[0].observed


def test_returns_same_rows_as_solution() -> None:
    a = Assertion(type=AssertionType.RETURNS_SAME_ROWS_AS_SOLUTION)
    assert verdicts(a, root=node(), run=run_of(rows_match=True))[0] == [True]
    assert verdicts(a, root=node(), run=run_of(rows_match=False))[0] == [False]
    # Never compared -- must not silently pass.
    assert verdicts(a, root=node(), run=run_of())[0] == [False]


def test_row_comparison_error_is_surfaced() -> None:
    run = run_of(
        rows_match=None,
        rows_match_error="each EXCEPT query must have the same number of columns",
    )
    _, result = verdicts(
        Assertion(type=AssertionType.RETURNS_SAME_ROWS_AS_SOLUTION), root=node(), run=run
    )
    assert "same number of columns" in (result.results[0].detail or "")


# --- overall verdict --------------------------------------------------------


def test_all_must_pass() -> None:
    passed, result = verdicts(
        Assertion(type=AssertionType.NO_NODE, node_type="Index Scan"),  # passes
        Assertion(type=AssertionType.MAX_TOTAL_BLOCKS, value=10),  # fails
        root=node(),
    )
    assert passed == [True, False]
    assert result.passed is False


def test_because_is_carried_into_the_result() -> None:
    _, result = verdicts(
        Assertion(type=AssertionType.NO_NODE, node_type="Seq Scan", because="reads 1.5 GB"),
        root=node(),
    )
    assert result.results[0].because == "reads 1.5 GB"


def test_a_failed_run_is_not_graded() -> None:
    from app.models.run import RunError

    run = run_of(ok=False, error=RunError(message="syntax error at or near \"slect\""))
    result = grade(exercise_with(Assertion(type=AssertionType.NO_SORT_SPILL)), None, run)
    assert result.passed is False
    assert result.results == []
    assert "syntax error" in (result.error or "")


def test_a_missing_plan_is_reported_not_crashed() -> None:
    result = grade(exercise_with(Assertion(type=AssertionType.NO_SORT_SPILL)), None, run_of())
    assert result.passed is False
    assert "Analyze" in (result.error or "")


def test_every_assertion_type_is_handled() -> None:
    """Guards against adding a type to the enum and forgetting the branch."""
    samples = {
        AssertionType.HAS_NODE: Assertion(type=AssertionType.HAS_NODE, node_type="Seq Scan"),
        AssertionType.NO_NODE: Assertion(type=AssertionType.NO_NODE, node_type="Sort"),
        AssertionType.HEAP_FETCHES_MAX: Assertion(type=AssertionType.HEAP_FETCHES_MAX, value=0),
        AssertionType.MAX_ESTIMATE_ERROR: Assertion(
            type=AssertionType.MAX_ESTIMATE_ERROR, value=2
        ),
        AssertionType.MAX_SHARED_READ: Assertion(type=AssertionType.MAX_SHARED_READ, value=1),
        AssertionType.MAX_TOTAL_BLOCKS: Assertion(type=AssertionType.MAX_TOTAL_BLOCKS, value=1),
        AssertionType.MAX_TOTAL_TIME_MS: Assertion(type=AssertionType.MAX_TOTAL_TIME_MS, value=1),
        AssertionType.NO_SORT_SPILL: Assertion(type=AssertionType.NO_SORT_SPILL),
        AssertionType.RETURNS_SAME_ROWS_AS_SOLUTION: Assertion(
            type=AssertionType.RETURNS_SAME_ROWS_AS_SOLUTION
        ),
    }
    assert set(samples) == set(AssertionType), "an assertion type has no test sample"

    result = grade(exercise_with(*samples.values()), plan_of(node()), run_of())
    assert len(result.results) == len(samples)
    # Each one produced a real description rather than falling through.
    for r in result.results:
        assert r.description
        assert r.expected


# --- validation -------------------------------------------------------------


def test_threshold_assertions_require_a_value() -> None:
    with pytest.raises(ValueError, match="requires a 'value'"):
        Assertion(type=AssertionType.MAX_TOTAL_BLOCKS)


def test_node_assertions_require_a_node_type() -> None:
    with pytest.raises(ValueError, match="requires a 'node_type'"):
        Assertion(type=AssertionType.HAS_NODE)
