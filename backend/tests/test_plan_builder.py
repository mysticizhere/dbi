"""Tests for the typed plan tree and the F2 warning rules.

Each warning rule gets a positive case and a negative case. A rule that fires on
everything is as useless as one that never fires -- the chips only mean
something if they are quiet on healthy plans.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from app.models.plan import Severity, WarningCode
from app.plan_builder import build_plan, relation_names

FIXTURES = Path(__file__).parent / "fixtures"


def node(**overrides: Any) -> dict[str, Any]:
    """A minimal healthy ANALYZEd node, to be spoiled one field at a time."""
    base: dict[str, Any] = {
        "Node Type": "Seq Scan",
        "Relation Name": "events",
        "Plan Rows": 100,
        "Actual Rows": 100,
        "Actual Loops": 1,
        "Actual Total Time": 10.0,
        "Actual Startup Time": 0.1,
        "Startup Cost": 0.0,
        "Total Cost": 100.0,
        "Shared Hit Blocks": 10,
        "Shared Read Blocks": 0,
    }
    base.update(overrides)
    return base


def wrap(root: dict[str, Any], **envelope: Any) -> dict[str, Any]:
    return {"Plan": root, "Planning Time": 0.2, "Execution Time": 11.0, **envelope}


def codes(plan: Any) -> set[WarningCode]:
    assert plan is not None
    return {w.code for w in plan.warnings}


# --- structure --------------------------------------------------------------


def test_returns_none_without_a_plan() -> None:
    assert build_plan(None) is None
    assert build_plan([]) is None


def test_ids_are_depth_first_and_stable() -> None:
    plan = build_plan(
        wrap(
            node(
                **{
                    "Node Type": "Nested Loop",
                    "Plans": [node(**{"Node Type": "Seq Scan"}), node(**{"Node Type": "Sort"})],
                }
            )
        )
    )
    assert plan is not None
    assert plan.root.id == 0
    assert [c.id for c in plan.root.children] == [1, 2]
    assert plan.summary.node_count == 3


def test_self_buffers_subtract_children() -> None:
    plan = build_plan(
        wrap(
            node(
                **{
                    "Node Type": "Aggregate",
                    "Shared Hit Blocks": 1000,
                    "Plans": [node(**{"Shared Hit Blocks": 900})],
                }
            )
        )
    )
    assert plan is not None
    # Cumulative on the node, but only 100 blocks were touched *here*.
    assert plan.root.buffers.shared_hit == 1000
    assert plan.root.self_buffers.shared_hit == 100
    assert plan.root.children[0].self_buffers.shared_hit == 900


def test_self_fractions_sum_to_one() -> None:
    plan = build_plan(
        wrap(
            {
                "Node Type": "Nested Loop",
                "Actual Total Time": 100.0,
                "Actual Loops": 1,
                "Plans": [
                    {"Node Type": "Seq Scan", "Actual Total Time": 10.0, "Actual Loops": 1},
                    {"Node Type": "Index Scan", "Actual Total Time": 2.0, "Actual Loops": 30},
                ],
            }
        )
    )
    assert plan is not None
    nodes = [plan.root, *plan.root.children]
    fractions = [n.timing.self_fraction for n in nodes if n.timing is not None]
    assert sum(f for f in fractions if f is not None) == pytest.approx(1.0)


def test_plain_explain_is_marked_not_analyzed() -> None:
    plan = build_plan({"Plan": {"Node Type": "Seq Scan", "Plan Rows": 10, "Total Cost": 5.0}})
    assert plan is not None
    assert plan.summary.analyzed is False
    assert plan.root.timing is None
    # No actuals means no estimate error and therefore no chips to show.
    assert plan.root.rows.error_ratio is None
    assert plan.warnings == []


def test_conditions_and_metrics_are_extracted() -> None:
    plan = build_plan(
        wrap(
            node(
                **{
                    "Filter": "(score < 100)",
                    "Sort Key": ["events.score", "events.id"],
                    "Rows Removed by Filter": 5,
                    "Heap Fetches": 0,
                }
            )
        )
    )
    assert plan is not None
    assert plan.root.conditions["Filter"] == "(score < 100)"
    assert plan.root.conditions["Sort Key"] == "events.score, events.id"
    assert plan.root.metrics["rows_removed_by_filter"] == 5


def test_relation_names_collects_the_whole_tree() -> None:
    tree = wrap(
        node(
            **{
                "Node Type": "Hash Join",
                "Relation Name": None,
                "Plans": [node(Relation_Name="x"), node(**{"Relation Name": "orders"})],
            }
        )
    )
    assert relation_names(tree) == ["events", "orders"]


# --- warning rules ----------------------------------------------------------


def test_healthy_plan_raises_nothing() -> None:
    assert codes(build_plan(wrap(node()), {"events": 10})) == set()


def test_estimate_error_fires_past_the_threshold() -> None:
    plan = build_plan(wrap(node(**{"Plan Rows": 10, "Actual Rows": 5000})))
    assert WarningCode.ESTIMATE_ERROR in codes(plan)
    assert plan is not None
    warning = next(w for w in plan.warnings if w.code == WarningCode.ESTIMATE_ERROR)
    assert warning.severity is Severity.CRITICAL  # 500x
    assert "under" in warning.label


def test_estimate_error_quiet_just_below_the_threshold() -> None:
    assert WarningCode.ESTIMATE_ERROR not in codes(build_plan(wrap(node(**{
        "Plan Rows": 100, "Actual Rows": 900,
    }))))


def test_seq_scan_warning_needs_page_counts() -> None:
    big = wrap(node(**{"Node Type": "Seq Scan", "Relation Name": "events"}))
    # Without pg_class data the rule must stay silent rather than guess.
    assert WarningCode.SEQ_SCAN_LARGE not in codes(build_plan(big))
    assert WarningCode.SEQ_SCAN_LARGE not in codes(build_plan(big, {"events": 12}))
    assert WarningCode.SEQ_SCAN_LARGE in codes(build_plan(big, {"events": 200_000}))


def test_parallel_seq_scan_also_counts() -> None:
    plan = wrap(node(**{"Node Type": "Parallel Seq Scan"}))
    assert WarningCode.SEQ_SCAN_LARGE in codes(build_plan(plan, {"events": 200_000}))


def test_heap_fetches_only_on_index_only_scans() -> None:
    ios = wrap(node(**{"Node Type": "Index Only Scan", "Heap Fetches": 4200}))
    assert WarningCode.HEAP_FETCHES in codes(build_plan(ios))
    clean = wrap(node(**{"Node Type": "Index Only Scan", "Heap Fetches": 0}))
    assert WarningCode.HEAP_FETCHES not in codes(build_plan(clean))


def test_sort_spill_detects_external_merge() -> None:
    spilled = wrap(node(**{
        "Node Type": "Sort", "Sort Method": "external merge", "Sort Space Used": 20480,
    }))
    assert WarningCode.SORT_SPILL in codes(build_plan(spilled))
    quick = wrap(node(**{"Node Type": "Sort", "Sort Method": "quicksort"}))
    assert WarningCode.SORT_SPILL not in codes(build_plan(quick))


def test_hash_spill_needs_more_than_one_batch() -> None:
    assert WarningCode.HASH_SPILL in codes(build_plan(wrap(node(**{"Hash Batches": 8}))))
    assert WarningCode.HASH_SPILL not in codes(build_plan(wrap(node(**{"Hash Batches": 1}))))


def test_nested_loop_warns_on_many_inner_loops() -> None:
    loopy = wrap({
        "Node Type": "Nested Loop",
        "Actual Total Time": 100.0,
        "Actual Loops": 1,
        "Plans": [
            {"Node Type": "Seq Scan", "Actual Total Time": 5.0, "Actual Loops": 1},
            {"Node Type": "Index Scan", "Actual Total Time": 0.01, "Actual Loops": 50_000},
        ],
    })
    assert WarningCode.NESTED_LOOP_LOOPS in codes(build_plan(loopy))


def test_nested_loop_quiet_with_few_loops() -> None:
    fine = wrap({
        "Node Type": "Nested Loop",
        "Actual Total Time": 10.0,
        "Actual Loops": 1,
        "Plans": [
            {"Node Type": "Seq Scan", "Actual Total Time": 5.0, "Actual Loops": 1},
            {"Node Type": "Index Scan", "Actual Total Time": 0.01, "Actual Loops": 20},
        ],
    })
    assert WarningCode.NESTED_LOOP_LOOPS not in codes(build_plan(fine))


def test_filter_discard_needs_both_volume_and_ratio() -> None:
    # Big ratio but tiny volume: not worth a chip.
    small = wrap(node(**{"Actual Rows": 1, "Rows Removed by Filter": 100}))
    assert WarningCode.FILTER_DISCARD not in codes(build_plan(small))
    # Big volume but a sane ratio: also fine.
    balanced = wrap(node(**{"Actual Rows": 90_000, "Rows Removed by Filter": 10_000}))
    assert WarningCode.FILTER_DISCARD not in codes(build_plan(balanced))
    # Both: worth flagging.
    wasteful = wrap(node(**{"Actual Rows": 100, "Rows Removed by Filter": 999_000}))
    assert WarningCode.FILTER_DISCARD in codes(build_plan(wasteful))


def test_lossy_bitmap_is_informational() -> None:
    plan = build_plan(wrap(node(**{"Node Type": "Bitmap Heap Scan", "Lossy Heap Blocks": 900})))
    assert plan is not None
    warning = next(w for w in plan.warnings if w.code == WarningCode.LOSSY_BITMAP)
    assert warning.severity is Severity.INFO


def test_warnings_sort_critical_first() -> None:
    plan = build_plan(
        wrap(node(**{
            "Node Type": "Index Only Scan",
            "Plan Rows": 1,
            "Actual Rows": 100_000,   # critical
            "Heap Fetches": 5,        # warn
        }))
    )
    assert plan is not None
    assert plan.warnings[0].severity is Severity.CRITICAL


def test_warnings_carry_their_node_id() -> None:
    plan = build_plan(
        wrap({
            "Node Type": "Aggregate",
            "Actual Total Time": 10.0,
            "Actual Loops": 1,
            "Plans": [node(**{"Plan Rows": 1, "Actual Rows": 90_000})],
        })
    )
    assert plan is not None
    assert plan.warnings[0].node_id == 1  # the child, not the root


# --- against a real captured plan -------------------------------------------


def test_builds_the_captured_plan() -> None:
    path = FIXTURES / "nested_loop_plan.json"
    if not path.exists():
        pytest.skip("run tests.fixtures.capture first")
    plan = build_plan(json.loads(path.read_text(encoding="utf-8")))
    assert plan is not None
    assert plan.summary.analyzed is True
    assert plan.summary.node_count >= 3
    assert plan.root.timing is not None
    # The inner side really did run many times, and total_ms reflects that.
    inner = plan.root.children[1]
    assert inner.timing is not None
    assert inner.timing.loops > 10
    assert inner.timing.total_ms == pytest.approx(
        inner.timing.per_loop_ms * inner.timing.loops  # type: ignore[operator]
    )


# --- parallel plans ---------------------------------------------------------


def parallel_plan() -> dict[str, Any]:
    """A Gather over 3 concurrent processes, each taking 195ms.

    The naive reading makes the Seq Scan 585ms inside a 220ms query -- 266% of
    the total, which is nonsense. The three loops are workers running at the
    same time, not iterations running one after another.
    """
    return wrap({
        "Node Type": "Aggregate",
        "Actual Total Time": 220.0,
        "Actual Loops": 1,
        "Plans": [{
            "Node Type": "Gather",
            "Actual Total Time": 219.0,
            "Actual Loops": 1,
            "Workers Planned": 2,
            "Workers Launched": 2,
            "Plans": [{
                "Node Type": "Partial Aggregate",
                "Actual Total Time": 200.0,
                "Actual Loops": 3,
                "Plans": [{
                    "Node Type": "Parallel Seq Scan",
                    "Relation Name": "events",
                    "Actual Total Time": 195.0,
                    "Actual Loops": 3,
                }],
            }],
        }],
    })


def test_parallel_self_fraction_never_exceeds_one() -> None:
    plan = build_plan(parallel_plan())
    assert plan is not None

    def every(n: Any) -> list[Any]:
        return [n, *[d for c in n.children for d in every(c)]]

    for n in every(plan.root):
        assert n.timing is not None
        assert n.timing.self_fraction is not None
        assert 0.0 <= n.timing.self_fraction <= 1.0, f"{n.node_type} at {n.timing.self_fraction}"


def test_parallel_self_fractions_still_sum_to_one() -> None:
    plan = build_plan(parallel_plan())
    assert plan is not None

    def every(n: Any) -> list[Any]:
        return [n, *[d for c in n.children for d in every(c)]]

    total = sum(n.timing.self_fraction for n in every(plan.root) if n.timing)
    assert total == pytest.approx(1.0)


def test_parallel_divisor_applies_below_the_gather_only() -> None:
    plan = build_plan(parallel_plan())
    assert plan is not None
    agg = plan.root
    gather = agg.children[0]
    partial = gather.children[0]
    scan = partial.children[0]

    assert agg.timing is not None and gather.timing is not None
    assert partial.timing is not None and scan.timing is not None

    # Above the Gather nothing is divided.
    assert agg.timing.parallel_divisor == 1.0
    assert gather.timing.parallel_divisor == 1.0
    # Below it, by the participant count reported on the Gather's child.
    assert partial.timing.parallel_divisor == 3.0
    assert scan.timing.parallel_divisor == 3.0

    # total_ms is CPU work across workers; elapsed_ms is the wall-clock share.
    assert scan.timing.total_ms == pytest.approx(585.0)
    assert scan.timing.elapsed_ms == pytest.approx(195.0)
    assert scan.timing.self_ms == pytest.approx(195.0)


def test_non_parallel_leaves_total_and_elapsed_equal() -> None:
    plan = build_plan(wrap({
        "Node Type": "Nested Loop",
        "Actual Total Time": 100.0,
        "Actual Loops": 1,
        "Plans": [{"Node Type": "Index Scan", "Actual Total Time": 2.0, "Actual Loops": 30}],
    }))
    assert plan is not None
    inner = plan.root.children[0]
    assert inner.timing is not None
    # 30 real iterations, one after another -- no division here.
    assert inner.timing.total_ms == pytest.approx(60.0)
    assert inner.timing.elapsed_ms == pytest.approx(60.0)
