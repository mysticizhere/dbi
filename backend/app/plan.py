"""Plan-tree arithmetic over raw ``EXPLAIN (FORMAT JSON)`` output.

Kept deliberately dict-based and dependency-free: the exercise assertion
evaluator (F4) and the plan visualizer (F2) both consume these helpers, so the
arithmetic lives in exactly one place.

The one thing to get right here is self time. ``Actual Total Time`` is
**cumulative** (it includes children) and **per-loop** (it is an average over
``Actual Loops``). Getting this wrong makes every timing view silently wrong.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from app.models.plan import Buffers

PlanNode = dict[str, Any]

_BUFFER_FIELDS: dict[str, str] = {
    "shared_hit": "Shared Hit Blocks",
    "shared_read": "Shared Read Blocks",
    "shared_dirtied": "Shared Dirtied Blocks",
    "shared_written": "Shared Written Blocks",
    "local_hit": "Local Hit Blocks",
    "local_read": "Local Read Blocks",
    "temp_read": "Temp Read Blocks",
    "temp_written": "Temp Written Blocks",
}


def root_node(explain_json: Any) -> PlanNode | None:
    """Pull the root plan node out of whatever EXPLAIN handed back.

    ``EXPLAIN (FORMAT JSON)`` returns a one-element array of objects, each with a
    ``Plan`` key -- but psycopg may hand it to us already unwrapped.
    """
    obj = explain_json
    if isinstance(obj, list):
        if not obj:
            return None
        obj = obj[0]
    if isinstance(obj, dict):
        plan = obj.get("Plan")
        if isinstance(plan, dict):
            return plan
        if "Node Type" in obj:
            return obj
    return None


def explain_envelope(explain_json: Any) -> PlanNode | None:
    """The object wrapping the root plan -- it carries Planning/Execution Time."""
    obj = explain_json
    if isinstance(obj, list):
        if not obj:
            return None
        obj = obj[0]
    return obj if isinstance(obj, dict) else None


def children(node: PlanNode) -> list[PlanNode]:
    """Direct child plans, including CTE / InitPlan / SubPlan subtrees."""
    kids = node.get("Plans")
    return [k for k in kids if isinstance(k, dict)] if isinstance(kids, list) else []


def walk(node: PlanNode) -> Iterator[PlanNode]:
    """Depth-first over every node in the tree, root first."""
    yield node
    for child in children(node):
        yield from walk(child)


def total_ms(node: PlanNode) -> float | None:
    """Wall time this node and its children consumed across *all* loops.

    ``Actual Total Time`` is an average per loop, so it must be multiplied out.
    Returns None when the plan was not ANALYZEd, or ran with TIMING OFF.
    """
    t = node.get("Actual Total Time")
    if not isinstance(t, (int, float)):
        return None
    loops = node.get("Actual Loops", 1)
    if not isinstance(loops, (int, float)):
        loops = 1
    return float(t) * float(loops)


_GATHER_TYPES = frozenset({"Gather", "Gather Merge"})


def child_divisor(node: PlanNode, inherited: float) -> float:
    """How many processes will run this node's children, concurrently.

    Below a Gather, ``Actual Loops`` counts *participating processes* rather than
    iterations, and those processes ran at the same time. So their summed time is
    CPU time, not elapsed time, and has to be divided back down or a child ends
    up "slower" than the parent that waited on it.

    The immediate child of a Gather reports exactly the participant count, which
    is more reliable than ``Workers Launched`` -- that excludes the leader, and
    whether the leader helps is decided at runtime.
    """
    if node.get("Node Type") in _GATHER_TYPES:
        kids = children(node)
        if kids:
            loops = kids[0].get("Actual Loops")
            if isinstance(loops, (int, float)) and loops > 0:
                return float(loops)
    return inherited


def elapsed_ms(node: PlanNode, divisor: float = 1.0) -> float | None:
    """Wall-clock contribution of this node and its children.

    Identical to ``total_ms`` outside a parallel subtree, where divisor is 1.
    """
    total = total_ms(node)
    return None if total is None else total / divisor


def self_ms(node: PlanNode, divisor: float = 1.0) -> float | None:
    """Elapsed time spent in this node alone, excluding children.

    Clamped at zero: InitPlan/SubPlan accounting can legitimately push the
    subtraction slightly negative, and a negative "self time" is worse than
    useless in a flame view.
    """
    own = elapsed_ms(node, divisor)
    if own is None:
        return None
    inner = child_divisor(node, divisor)
    kids = 0.0
    for child in children(node):
        child_total = elapsed_ms(child, inner)
        if child_total is not None:
            kids += child_total
    return max(0.0, own - kids)


def estimate_error(node: PlanNode) -> float | None:
    """max(actual/estimated, estimated/actual), per loop. 1.0 means spot on.

    ``Actual Rows`` is per-loop and so is ``Plan Rows``, so they compare directly.
    """
    est = node.get("Plan Rows")
    act = node.get("Actual Rows")
    if not isinstance(est, (int, float)) or not isinstance(act, (int, float)):
        return None
    # Zero rows on either side would divide by zero; treat "fewer than one row"
    # as one row, which is also how the planner clamps its own estimates.
    e = max(float(est), 1.0)
    a = max(float(act), 1.0)
    return max(a / e, e / a)


def node_buffers(node: PlanNode) -> Buffers:
    """Buffer counters recorded on a single node (already cumulative)."""
    values = {key: int(node.get(field, 0) or 0) for key, field in _BUFFER_FIELDS.items()}
    return Buffers(**values)


def plan_buffers(explain_json: Any) -> Buffers | None:
    """Whole-query buffer totals, read off the root node.

    Buffer counters in EXPLAIN are cumulative up the tree, so the root already
    holds the total -- summing every node would multiply-count badly.
    """
    root = root_node(explain_json)
    return node_buffers(root) if root is not None else None


def plan_times(explain_json: Any) -> tuple[float | None, float | None]:
    """(planning_ms, execution_ms) as reported by the server."""
    env = explain_envelope(explain_json)
    if env is None:
        return None, None
    planning = env.get("Planning Time")
    execution = env.get("Execution Time")
    return (
        float(planning) if isinstance(planning, (int, float)) else None,
        float(execution) if isinstance(execution, (int, float)) else None,
    )
