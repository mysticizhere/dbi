"""Exercise definitions and grading results (spec F4).

Exercises live on disk as plain files, not database rows, so they stay diffable
and hand-editable. This module is the contract those files have to satisfy --
a typo in an `exercise.yaml` should fail loudly at load time rather than
silently grade nothing.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field, model_validator


class AssertionType(StrEnum):
    HAS_NODE = "has_node"
    NO_NODE = "no_node"
    HEAP_FETCHES_MAX = "heap_fetches_max"
    MAX_ESTIMATE_ERROR = "max_estimate_error"
    MAX_SHARED_READ = "max_shared_read"
    # Not in the original spec list. shared_read alone is *not* machine
    # independent -- the hit/read split moves with whatever happens to be
    # cached, so the same good plan can read 200 blocks warm and 10,000 cold.
    # hit+read (blocks touched) is the quantity that actually stays put, so it
    # is what the exercises grade on.
    MAX_TOTAL_BLOCKS = "max_total_blocks"
    MAX_TOTAL_TIME_MS = "max_total_time_ms"
    NO_SORT_SPILL = "no_sort_spill"
    RETURNS_SAME_ROWS_AS_SOLUTION = "returns_same_rows_as_solution"


# Which extra fields each assertion type needs. Enforced at load time.
_NEEDS_VALUE = {
    AssertionType.HEAP_FETCHES_MAX,
    AssertionType.MAX_ESTIMATE_ERROR,
    AssertionType.MAX_SHARED_READ,
    AssertionType.MAX_TOTAL_BLOCKS,
    AssertionType.MAX_TOTAL_TIME_MS,
}
_NEEDS_NODE_TYPE = {AssertionType.HAS_NODE, AssertionType.NO_NODE}


class Assertion(BaseModel):
    """One gradeable condition on the resulting plan."""

    type: AssertionType

    # Threshold assertions.
    value: float | None = None

    # Node-shape assertions. relation/index_name narrow the match when given.
    node_type: str | None = None
    relation: str | None = None
    index_name: str | None = None

    # Optional author's note, shown alongside the result so a failure teaches
    # something rather than just going red.
    because: str | None = None

    @model_validator(mode="after")
    def check_required_fields(self) -> Assertion:
        if self.type in _NEEDS_VALUE and self.value is None:
            raise ValueError(f"assertion '{self.type}' requires a 'value'")
        if self.type in _NEEDS_NODE_TYPE and not self.node_type:
            raise ValueError(f"assertion '{self.type}' requires a 'node_type'")
        if self.type is AssertionType.MAX_TOTAL_TIME_MS:
            # Not rejected, but the spec is explicit that these are flaky across
            # machines and cache states. Buffer counts are deterministic.
            pass
        return self


class ExerciseMeta(BaseModel):
    """The parsed `exercise.yaml`, before the sibling .sql files are attached."""

    id: str
    title: str
    layer: int = Field(ge=1, le=7)
    difficulty: int = Field(ge=1, le=5)
    prompt: str
    starting_query: str = ""
    hints: list[str] = Field(default_factory=list)
    assertions: list[Assertion] = Field(min_length=1)

    # Some exercises cannot run inside BEGIN..ROLLBACK -- VACUUM is the usual
    # reason. Setting this lets the UI warn before the run fails.
    requires_persist: bool = False


class Exercise(ExerciseMeta):
    """An exercise plus the contents of its directory."""

    slug: str  # directory name, e.g. "05-index-only-scan"
    setup_sql: str = ""
    solution_sql: str = ""
    notes_md: str = ""


class ExerciseSummary(BaseModel):
    """Enough to render the exercise list without shipping every prompt."""

    id: str
    slug: str
    title: str
    layer: int
    difficulty: int
    requires_persist: bool
    assertion_count: int
    # Best result so far, from lab_meta.attempts.
    attempts: int = 0
    passed: bool = False


class AssertionResult(BaseModel):
    """One graded assertion.

    Carries the observed value as well as the verdict, so a failure says what
    actually happened rather than just 'no'.
    """

    type: AssertionType
    description: str
    passed: bool
    expected: str
    observed: str
    detail: str | None = None
    because: str | None = None
    # Plan nodes this verdict came from, so the UI can highlight them.
    node_ids: list[int] = Field(default_factory=list)


class GradeResult(BaseModel):
    exercise_id: str
    passed: bool
    results: list[AssertionResult] = Field(default_factory=list)
    # Set when grading could not run at all (query errored, no plan produced).
    error: str | None = None


class SubmitRequest(BaseModel):
    sql: str = Field(min_length=1)
    sandbox: bool = True
    repeat: int = Field(default=3, ge=1, le=50)
    statement_timeout_ms: int = Field(default=60_000, ge=100, le=600_000)
    settings_overrides: dict[str, str] = Field(default_factory=dict)


class SubmitResponse(BaseModel):
    run: Any  # RunResponse -- Any avoids a circular import; shape is stable.
    grade: GradeResult
    attempt_id: int | None = None
