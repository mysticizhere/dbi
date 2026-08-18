"""Plan arithmetic tests.

The self-time calculation is the one the spec singles out as easy to get
silently wrong, so it gets tested against a plan whose right answer is known by
construction -- and then against a real plan captured from Postgres.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from app.plan import (
    children,
    estimate_error,
    node_buffers,
    plan_buffers,
    plan_times,
    root_node,
    self_ms,
    total_ms,
    walk,
)

FIXTURES = Path(__file__).parent / "fixtures"


def plan_root(explain: Any) -> dict[str, Any]:
    """root_node() that fails the test instead of handing back None."""
    node = root_node(explain)
    assert node is not None
    return node


# A nested loop whose inner side runs 30 times. Every number here is chosen so
# the correct answer differs from the naive one:
#
#   naive  self = 100 - (10 + 2)  = 88     <- forgets Actual Loops
#   right  self = 100 - (10 + 60) = 30
#
# 'Actual Total Time' is cumulative AND per-loop. Both have to be undone.
KNOWN_PLAN: dict[str, Any] = {
    "Plan": {
        "Node Type": "Nested Loop",
        "Actual Total Time": 100.0,
        "Actual Loops": 1,
        "Plan Rows": 300,
        "Actual Rows": 30,
        "Shared Hit Blocks": 900,
        "Shared Read Blocks": 100,
        "Plans": [
            {
                "Node Type": "Seq Scan",
                "Relation Name": "a",
                "Actual Total Time": 10.0,
                "Actual Loops": 1,
                "Plan Rows": 30,
                "Actual Rows": 30,
                "Shared Hit Blocks": 400,
                "Shared Read Blocks": 100,
            },
            {
                "Node Type": "Index Scan",
                "Relation Name": "b",
                "Actual Total Time": 2.0,
                "Actual Loops": 30,
                "Plan Rows": 1,
                "Actual Rows": 1,
                "Shared Hit Blocks": 500,
                "Shared Read Blocks": 0,
            },
        ],
    },
    "Planning Time": 0.5,
    "Execution Time": 101.0,
}


def test_root_node_unwraps_the_explain_array() -> None:
    assert plan_root([KNOWN_PLAN])["Node Type"] == "Nested Loop"
    assert plan_root(KNOWN_PLAN)["Node Type"] == "Nested Loop"
    assert plan_root(KNOWN_PLAN["Plan"])["Node Type"] == "Nested Loop"
    assert root_node([]) is None
    assert root_node(None) is None


def test_total_ms_multiplies_out_loops() -> None:
    root = plan_root(KNOWN_PLAN)
    outer, inner = children(root)
    assert total_ms(root) == pytest.approx(100.0)
    assert total_ms(outer) == pytest.approx(10.0)
    # The whole point: 2ms per loop x 30 loops, not 2ms.
    assert total_ms(inner) == pytest.approx(60.0)


def test_self_ms_subtracts_children_total_not_per_loop() -> None:
    root = plan_root(KNOWN_PLAN)
    outer, inner = children(root)
    assert self_ms(root) == pytest.approx(30.0)
    assert self_ms(outer) == pytest.approx(10.0)
    assert self_ms(inner) == pytest.approx(60.0)
    # And the naive answer is genuinely different, so this test can fail.
    assert self_ms(root) != pytest.approx(88.0)


def test_self_times_sum_to_the_root_total() -> None:
    root = plan_root(KNOWN_PLAN)
    assert sum(self_ms(n) or 0.0 for n in walk(root)) == pytest.approx(total_ms(root))


def test_self_ms_never_goes_negative() -> None:
    # InitPlan accounting and parallel-worker averaging can push the subtraction
    # below zero; a negative self time would poison the flame colouring.
    weird: dict[str, Any] = {
        "Node Type": "Gather",
        "Actual Total Time": 5.0,
        "Actual Loops": 1,
        "Plans": [{"Node Type": "Seq Scan", "Actual Total Time": 9.0, "Actual Loops": 1}],
    }
    assert self_ms(weird) == 0.0


def test_timing_helpers_return_none_without_analyze() -> None:
    plain: dict[str, Any] = {"Node Type": "Seq Scan", "Plan Rows": 10}
    assert total_ms(plain) is None
    assert self_ms(plain) is None


def test_estimate_error_is_symmetric() -> None:
    assert estimate_error({"Plan Rows": 300, "Actual Rows": 30}) == pytest.approx(10.0)
    assert estimate_error({"Plan Rows": 30, "Actual Rows": 300}) == pytest.approx(10.0)
    assert estimate_error({"Plan Rows": 100, "Actual Rows": 100}) == pytest.approx(1.0)


def test_estimate_error_clamps_zero_rows() -> None:
    # Zero actual rows must not blow up; the planner clamps its own estimate to 1.
    assert estimate_error({"Plan Rows": 500, "Actual Rows": 0}) == pytest.approx(500.0)
    assert estimate_error({"Plan Rows": 0, "Actual Rows": 0}) == pytest.approx(1.0)
    assert estimate_error({"Node Type": "Seq Scan"}) is None


def test_buffers_come_from_the_root_only() -> None:
    # Buffer counters are already cumulative up the tree. Summing every node
    # would double-count badly -- 1800 hit instead of 900 here.
    buffers = plan_buffers(KNOWN_PLAN)
    assert buffers is not None
    assert buffers.shared_hit == 900
    assert buffers.shared_read == 100
    assert sum(node_buffers(n).shared_hit for n in walk(plan_root(KNOWN_PLAN))) == 1800


def test_plan_times_reads_the_envelope() -> None:
    planning, execution = plan_times(KNOWN_PLAN)
    assert planning == pytest.approx(0.5)
    assert execution == pytest.approx(101.0)
    assert plan_times({"Plan": {"Node Type": "Result"}}) == (None, None)


# --- against a plan Postgres actually produced ------------------------------


@pytest.fixture(scope="module")
def real_plan() -> dict[str, Any]:
    path = FIXTURES / "nested_loop_plan.json"
    if not path.exists():
        pytest.skip("run tests/fixtures/capture.py against a seeded lab_data first")
    loaded: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return loaded


def test_real_plan_fixture_has_a_multi_loop_node(real_plan: dict[str, Any]) -> None:
    """Guards the fixture. Without a multi-loop node it proves nothing."""
    root = plan_root(real_plan)
    assert any((n.get("Actual Loops") or 1) > 10 for n in walk(root))


def test_real_plan_self_times_reconcile(real_plan: dict[str, Any]) -> None:
    root = plan_root(real_plan)
    total = total_ms(root)
    assert total is not None
    # Necessary but NOT sufficient: this identity also holds if total_ms forgets
    # to multiply by loops, because the error cancels between parent and child.
    # test_real_plan_rejects_the_naive_self_time is the one that catches that.
    assert sum(self_ms(n) or 0.0 for n in walk(root)) == pytest.approx(total, rel=1e-6)


def test_real_plan_rejects_the_naive_self_time(real_plan: dict[str, Any]) -> None:
    """Pin the root's self time against the answer the per-loop bug produces."""
    root = plan_root(real_plan)
    kids = children(root)
    assert kids, "fixture should be a join, not a single scan"

    naive = float(root["Actual Total Time"]) - sum(
        float(k["Actual Total Time"]) for k in kids
    )
    correct = float(root["Actual Total Time"]) - sum(
        float(k["Actual Total Time"]) * float(k["Actual Loops"]) for k in kids
    )
    # The fixture is only useful if the two answers actually diverge.
    assert abs(naive - correct) > 1.0

    assert self_ms(root) == pytest.approx(correct, rel=1e-6)
    assert self_ms(root) != pytest.approx(naive, rel=1e-6)


def test_real_plan_multiplies_inner_loops_out(real_plan: dict[str, Any]) -> None:
    root = plan_root(real_plan)
    looped = next(n for n in walk(root) if (n.get("Actual Loops") or 1) > 10)
    per_loop = float(looped["Actual Total Time"])
    loops = float(looped["Actual Loops"])
    assert total_ms(looped) == pytest.approx(per_loop * loops)
    assert total_ms(looped) != pytest.approx(per_loop)
