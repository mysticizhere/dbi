"""Exercise engine endpoints (spec F4)."""

from __future__ import annotations

import json
from typing import Any, cast

import psycopg
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app import exercises as store
from app.db import data_conn, meta_conn
from app.grader import grade
from app.models.exercise import (
    Exercise,
    ExerciseSummary,
    GradeResult,
    SubmitRequest,
    SubmitResponse,
)
from app.models.run import RunMode, RunRequest, RunResponse
from app.runner import run_query
from app.sql import split_statements

router = APIRouter(prefix="/exercises", tags=["exercises"])


async def _attempt_stats() -> dict[str, tuple[int, bool]]:
    """(attempts, ever_passed) per exercise, for the list view."""
    async with meta_conn() as conn:
        rows = await (
            await conn.execute(
                """
                SELECT exercise_id,
                       count(*)          AS attempts,
                       bool_or(passed)   AS ever_passed
                FROM attempts
                GROUP BY exercise_id
                """
            )
        ).fetchall()
    return {
        str(r["exercise_id"]): (int(cast(int, r["attempts"])), bool(r["ever_passed"]))
        for r in rows
    }


def _load_or_404(exercise_id: str) -> Exercise:
    try:
        exercise = store.get(exercise_id)
    except store.ExerciseLoadError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    if exercise is None:
        raise HTTPException(status_code=404, detail=f"no exercise '{exercise_id}'")
    return exercise


@router.get("", response_model=list[ExerciseSummary])
async def list_exercises() -> list[ExerciseSummary]:
    try:
        found = store.load_all()
    except store.ExerciseLoadError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    stats = await _attempt_stats()
    return [
        ExerciseSummary(
            id=e.id,
            slug=e.slug,
            title=e.title,
            layer=e.layer,
            difficulty=e.difficulty,
            requires_persist=e.requires_persist,
            assertion_count=len(e.assertions),
            attempts=stats.get(e.id, (0, False))[0],
            passed=stats.get(e.id, (0, False))[1],
        )
        for e in found
    ]


@router.get("/{exercise_id}", response_model=Exercise)
async def get_exercise(exercise_id: str) -> Exercise:
    return _load_or_404(exercise_id)


class SetupResponse(BaseModel):
    ok: bool
    statements: int
    notices: list[str] = []
    error: str | None = None


@router.post("/{exercise_id}/setup", response_model=SetupResponse)
async def run_setup(exercise_id: str) -> SetupResponse:
    """Apply the exercise's setup.sql to the playground.

    Runs in persist mode by necessity -- the whole point is to leave the
    playground in a known state, and several setups need VACUUM, which cannot
    run inside a transaction block.
    """
    exercise = _load_or_404(exercise_id)
    statements = split_statements(exercise.setup_sql)
    if not statements:
        return SetupResponse(ok=True, statements=0)

    notices: list[str] = []
    async with data_conn() as conn:
        conn.add_notice_handler(
            lambda diag: notices.append(f"{diag.severity}: {diag.message_primary}")
        )
        # Setup can rebuild indexes on a 10M-row table; the workbench default of
        # 30s is not enough.
        await conn.execute("SET statement_timeout = '600s'")
        for stmt in statements:
            try:
                await conn.execute(stmt)
            except psycopg.Error as exc:
                return SetupResponse(
                    ok=False,
                    statements=len(statements),
                    notices=notices,
                    error=f"{(exc.diag.message_primary or str(exc)).strip()}\n\nin: {stmt[:200]}",
                )
    return SetupResponse(ok=True, statements=len(statements), notices=notices)


async def _record_attempt(
    exercise_id: str, sql: str, run: RunResponse, result: GradeResult
) -> int | None:
    plan_json = json.dumps(run.plan) if run.plan else None
    buffers = run.buffers
    async with meta_conn() as conn:
        row = await (
            await conn.execute(
                """
                INSERT INTO attempts
                    (exercise_id, sql, plan_json, passed, assertions,
                     median_ms, shared_hit, shared_read)
                VALUES (%s, %s, %s::jsonb, %s, %s::jsonb, %s, %s, %s)
                RETURNING id
                """,
                (
                    exercise_id,
                    sql,
                    plan_json,
                    result.passed,
                    result.model_dump_json(),
                    run.timings.median_ms if run.timings else None,
                    buffers.shared_hit if buffers else None,
                    buffers.shared_read if buffers else None,
                ),
            )
        ).fetchone()
    return int(cast(int, row["id"])) if row else None


@router.post("/{exercise_id}/submit", response_model=SubmitResponse)
async def submit(exercise_id: str, req: SubmitRequest) -> SubmitResponse:
    exercise = _load_or_404(exercise_id)

    needs_solution = any(
        a.type == "returns_same_rows_as_solution" for a in exercise.assertions
    )
    reference = None
    if needs_solution:
        solution_statements = split_statements(exercise.solution_sql)
        if not solution_statements:
            raise HTTPException(
                status_code=500,
                detail=f"exercise '{exercise_id}' asserts against solution.sql, but it is empty",
            )
        reference = solution_statements[-1]

    run = await run_query(
        RunRequest(
            sql=req.sql,
            # Grading always needs actuals: buffers, row counts and heap fetches
            # only exist on an ANALYZE run.
            mode=RunMode.ANALYZE,
            sandbox=req.sandbox,
            repeat=req.repeat,
            statement_timeout_ms=req.statement_timeout_ms,
            settings_overrides=req.settings_overrides,
            compare_sql=reference,
        )
    )

    result = grade(exercise, run.analyzed_plan, run)
    attempt_id = await _record_attempt(exercise_id, req.sql, run, result)
    return SubmitResponse(run=run, grade=result, attempt_id=attempt_id)


class AttemptSummary(BaseModel):
    id: int
    passed: bool
    median_ms: float | None
    shared_hit: int | None
    shared_read: int | None
    created_at: Any
    sql: str


@router.get("/{exercise_id}/attempts", response_model=list[AttemptSummary])
async def list_attempts(exercise_id: str, limit: int = 20) -> list[AttemptSummary]:
    async with meta_conn() as conn:
        rows = await (
            await conn.execute(
                """
                SELECT id, passed, median_ms, shared_hit, shared_read, created_at, sql
                FROM attempts
                WHERE exercise_id = %s
                ORDER BY created_at DESC
                LIMIT %s
                """,
                (exercise_id, min(limit, 100)),
            )
        ).fetchall()
    return [
        AttemptSummary(
            id=int(cast(int, r["id"])),
            passed=bool(r["passed"]),
            median_ms=cast(float | None, r["median_ms"]),
            shared_hit=cast(int | None, r["shared_hit"]),
            shared_read=cast(int | None, r["shared_read"]),
            created_at=r["created_at"],
            sql=str(r["sql"]),
        )
        for r in rows
    ]
