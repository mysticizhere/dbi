"""Executes a workbench run (spec F1).

A run is a small SQL script. Every statement but the last is treated as setup;
the last one is the *target* -- the statement that gets explained, repeated and
measured. In sandbox mode the whole thing sits inside BEGIN..ROLLBACK, which is
what makes `CREATE INDEX` experiments free: Postgres DDL is transactional, so
the planner sees the index and then it vanishes.
"""

from __future__ import annotations

import re
import statistics
import time
from typing import Any, cast

import psycopg
from psycopg import AsyncConnection, sql

from app.db import data_conn
from app.models.plan import Buffers
from app.models.run import (
    ResultSet,
    RunError,
    RunMode,
    RunRequest,
    RunResponse,
    StatementInfo,
    Timings,
)
from app.plan import plan_buffers, plan_times
from app.plan_builder import build_plan, relation_names
from app.sql import is_explainable, non_transactional_reason, split_statements

_GUC_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)?$")

_ANALYZE_OPTIONS = "ANALYZE, BUFFERS, VERBOSE, SETTINGS, FORMAT JSON"
_EXPLAIN_OPTIONS = "VERBOSE, COSTS, SETTINGS, FORMAT JSON"


def _percentiles(values: list[float]) -> tuple[float | None, float | None, float | None]:
    """(p25, median, p75). Small N is the norm here, so no interpolation games."""
    if not values:
        return None, None, None
    ordered = sorted(values)
    median = statistics.median(ordered)
    if len(ordered) == 1:
        return ordered[0], median, ordered[0]
    p25 = ordered[max(0, round(0.25 * (len(ordered) - 1)))]
    p75 = ordered[min(len(ordered) - 1, round(0.75 * (len(ordered) - 1)))]
    return p25, median, p75


def _error_from_psycopg(
    exc: psycopg.Error, statement_index: int | None, position_offset: int = 0
) -> RunError:
    """Map a psycopg error onto RunError.

    `position_offset` backs out the length of any wrapper we added -- the server
    reports a position into the string *it* parsed, so an EXPLAIN prefix would
    otherwise point the editor's caret well past the real mistake.
    """
    diag = exc.diag
    position = None
    if diag.statement_position is not None:
        try:
            position = max(1, int(diag.statement_position) - position_offset)
        except ValueError:
            position = None
    return RunError(
        message=(diag.message_primary or str(exc)).strip(),
        sqlstate=diag.sqlstate,
        detail=diag.message_detail,
        hint=diag.message_hint,
        position=position,
        statement_index=statement_index,
    )


def _set_stmt(name: str, value: str, *, local: bool) -> sql.Composed:
    parts = [sql.Identifier(p) for p in name.split(".")]
    scope = sql.SQL("SET LOCAL ") if local else sql.SQL("SET ")
    return scope + sql.SQL(".").join(parts) + sql.SQL(" = ") + sql.Literal(value)


def _precheck(req: RunRequest, statements: list[str]) -> RunResponse | None:
    """Reject runs that cannot work, with an explanation rather than a raw error."""
    if not statements:
        return RunResponse(
            ok=False,
            mode=req.mode,
            sandbox=req.sandbox,
            error=RunError(message="No SQL statement found."),
        )

    if req.sandbox:
        for index, stmt in enumerate(statements):
            reason = non_transactional_reason(stmt)
            if reason is not None:
                return RunResponse(
                    ok=False,
                    mode=req.mode,
                    sandbox=req.sandbox,
                    error=RunError(
                        message=(
                            f"{reason} cannot run inside a transaction block, and sandbox "
                            f"mode wraps the whole run in BEGIN..ROLLBACK. Turn sandbox off "
                            f"(persist mode) to run this -- note that its effects will stick."
                        ),
                        sqlstate="25001",
                        statement_index=index,
                    ),
                )

    if req.mode in (RunMode.EXPLAIN, RunMode.ANALYZE) and not is_explainable(statements[-1]):
        return RunResponse(
            ok=False,
            mode=req.mode,
            sandbox=req.sandbox,
            error=RunError(
                message=(
                    "EXPLAIN only accepts SELECT / INSERT / UPDATE / DELETE / MERGE / "
                    "VALUES / CREATE TABLE AS. The last statement in the script is not one "
                    "of those -- switch to Execute mode, or put the query last."
                ),
                statement_index=len(statements) - 1,
            ),
        )

    for name in req.settings_overrides:
        if not _GUC_NAME.match(name):
            return RunResponse(
                ok=False,
                mode=req.mode,
                sandbox=req.sandbox,
                error=RunError(message=f"Not a valid setting name: {name!r}"),
            )
    return None


async def _fetch_rows(cur: psycopg.AsyncCursor[Any], row_cap: int) -> ResultSet:
    if cur.description is None:
        # DDL / DML with no RETURNING: rowcount is the interesting number.
        return ResultSet(row_count=max(cur.rowcount, 0))
    columns = [d.name for d in cur.description]
    # Fetch one extra so we can tell "exactly at the cap" from "truncated".
    fetched = await cur.fetchmany(row_cap + 1)
    truncated = len(fetched) > row_cap
    rows = [list(r.values()) for r in fetched[:row_cap]]
    return ResultSet(columns=columns, rows=rows, row_count=len(rows), truncated=truncated)


async def _explain_target(
    conn: AsyncConnection[Any], target: str, options: str, repeat: int
) -> tuple[list[dict[str, Any]], list[float]]:
    """Run EXPLAIN over the target `repeat` times, returning each plan and wall time."""
    query = f"EXPLAIN ({options}) {target}"
    plans: list[dict[str, Any]] = []
    wall: list[float] = []
    for _ in range(repeat):
        started = time.perf_counter()
        async with conn.cursor() as cur:
            await cur.execute(query)
            row = await cur.fetchone()
        wall.append((time.perf_counter() - started) * 1000.0)
        payload = next(iter(row.values())) if row else None
        if isinstance(payload, list) and payload:
            plans.append(payload[0])
        elif isinstance(payload, dict):
            plans.append(payload)
    return plans, wall


async def _relation_pages(
    conn: AsyncConnection[Any], names: list[str]
) -> dict[str, int]:
    """Page counts for the relations in a plan.

    Without these a Seq Scan warning cannot distinguish a 4-page lookup table
    from a 200k-page fact table, so the F2 rule stays silent rather than crying
    wolf on every small scan.
    """
    if not names:
        return {}
    rows = await (
        await conn.execute(
            "SELECT relname, relpages FROM pg_class WHERE relname = ANY(%s)", (names,)
        )
    ).fetchall()
    return {str(r["relname"]): int(cast(int, r["relpages"])) for r in rows}


async def _compare_rows(
    conn: AsyncConnection[Any], target: str, reference: str
) -> tuple[bool | None, str | None]:
    """Do two queries return the same multiset of rows?

    Symmetric difference in SQL rather than fetching both sides into Python: the
    result sets are potentially huge, and `EXCEPT ALL` both ways also respects
    duplicate counts, which a set comparison would quietly ignore. Row *order*
    is deliberately not compared -- only an ORDER BY makes it meaningful, and an
    exercise that cares should assert on the plan instead.
    """
    check = f"""
        SELECT count(*) AS diff FROM (
            (SELECT * FROM ({target}) AS _submitted
             EXCEPT ALL
             SELECT * FROM ({reference}) AS _reference)
            UNION ALL
            (SELECT * FROM ({reference}) AS _reference
             EXCEPT ALL
             SELECT * FROM ({target}) AS _submitted)
        ) AS _diff
    """
    try:
        async with conn.cursor() as cur:
            await cur.execute(check)
            row = await cur.fetchone()
    except psycopg.Error as exc:
        # Mismatched column lists are the usual cause, and that is itself a
        # meaningful answer -- so report why rather than swallowing it.
        return None, (exc.diag.message_primary or str(exc)).strip()
    return (int(row["diff"]) == 0 if row else None), None


async def run_query(req: RunRequest) -> RunResponse:
    statements = split_statements(req.sql)
    rejected = _precheck(req, statements)
    if rejected is not None:
        return rejected

    target = statements[-1]
    infos = [
        StatementInfo(index=i, sql=s, is_target=(i == len(statements) - 1))
        for i, s in enumerate(statements)
    ]
    notices: list[str] = []
    warnings: list[str] = []
    current_index = 0
    # Backed out of any error position reported while running the target under
    # an EXPLAIN wrapper, so the caret lands on the user's own text.
    position_offset = 0

    async with data_conn() as conn:
        conn.add_notice_handler(
            lambda diag: notices.append(f"{diag.severity}: {diag.message_primary}")
        )
        try:
            if req.sandbox:
                await conn.execute("BEGIN")
            local = req.sandbox

            await conn.execute(
                _set_stmt("statement_timeout", f"{req.statement_timeout_ms}ms", local=local)
            )
            for name, value in req.settings_overrides.items():
                await conn.execute(_set_stmt(name, value, local=local))

            # Setup statements: everything before the target.
            for info in infos[:-1]:
                current_index = info.index
                started = time.perf_counter()
                await conn.execute(info.sql)
                info.duration_ms = (time.perf_counter() - started) * 1000.0

            current_index = len(statements) - 1
            plan: dict[str, Any] | None = None
            result: ResultSet | None = None
            timings: Timings | None = None
            buffers: Buffers | None = None

            if req.mode is RunMode.EXPLAIN:
                position_offset = len(f"EXPLAIN ({_EXPLAIN_OPTIONS}) ")
                plans, wall = await _explain_target(conn, target, _EXPLAIN_OPTIONS, 1)
                plan = plans[0] if plans else None
                infos[-1].duration_ms = wall[0] if wall else None

            elif req.mode is RunMode.ANALYZE:
                position_offset = len(f"EXPLAIN ({_ANALYZE_OPTIONS}) ")
                plans, _wall = await _explain_target(conn, target, _ANALYZE_OPTIONS, req.repeat)
                if not plans:
                    raise RuntimeError("EXPLAIN returned no plan")
                # Server-side time, not wall clock: it excludes network and psycopg.
                server_ms: list[float] = []
                for p in plans:
                    planning, execution = plan_times(p)
                    server_ms.append((planning or 0.0) + (execution or 0.0))

                # Discard the first run: cold caches and a cold plan cache make it
                # unrepresentative of steady state.
                multi = len(server_ms) > 1
                kept_indices = list(range(1, len(server_ms))) if multi else [0]
                kept = [server_ms[i] for i in kept_indices]
                p25, median, p75 = _percentiles(kept)

                # Show the plan from the run whose time *was* the median, so the
                # headline number and the numbers on the nodes agree.
                median_idx = min(kept_indices, key=lambda i: abs(server_ms[i] - (median or 0.0)))
                plan = plans[median_idx]
                planning, execution = plan_times(plan)
                timings = Timings(
                    runs_ms=[round(v, 3) for v in kept],
                    discarded_first_ms=round(server_ms[0], 3) if multi else None,
                    median_ms=median,
                    p25_ms=p25,
                    p75_ms=p75,
                    min_ms=min(kept) if kept else None,
                    max_ms=max(kept) if kept else None,
                    planning_ms=planning,
                    execution_ms=execution,
                )
                buffers = plan_buffers(plan)
                infos[-1].duration_ms = median

            else:  # RunMode.EXECUTE
                wall = []
                for _ in range(req.repeat):
                    started = time.perf_counter()
                    async with conn.cursor() as cur:
                        await cur.execute(target)
                        result = await _fetch_rows(cur, req.row_cap)
                    wall.append((time.perf_counter() - started) * 1000.0)
                multi = len(wall) > 1
                kept = wall[1:] if multi else wall
                p25, median, p75 = _percentiles(kept)
                timings = Timings(
                    runs_ms=[round(v, 3) for v in kept],
                    discarded_first_ms=round(wall[0], 3) if multi else None,
                    median_ms=median,
                    p25_ms=p25,
                    p75_ms=p75,
                    min_ms=min(kept) if kept else None,
                    max_ms=max(kept) if kept else None,
                )
                infos[-1].duration_ms = median
                warnings.append(
                    "Execute mode reports wall time only. Buffer counts -- the "
                    "machine-independent metric -- need Analyze mode."
                )

            rows_match: bool | None = None
            rows_match_error: str | None = None
            if req.compare_sql:
                # Still inside the transaction, so an index the submission
                # created is visible to both sides of the comparison.
                rows_match, rows_match_error = await _compare_rows(
                    conn, target, req.compare_sql
                )

            analyzed_plan = None
            if plan is not None:
                # Inside the sandbox transaction on purpose: an index created by
                # a setup statement still exists here, so its pages are visible.
                pages = await _relation_pages(conn, relation_names(plan))
                analyzed_plan = build_plan(plan, pages)

            if req.sandbox:
                await conn.execute("ROLLBACK")

            if req.mode is RunMode.ANALYZE and req.repeat == 1:
                warnings.append(
                    "Single run, so this number carries whatever cache state happened to "
                    "be in place. Raise repeat to 5 for a median."
                )

            return RunResponse(
                ok=True,
                mode=req.mode,
                sandbox=req.sandbox,
                statements=infos,
                plan=plan,
                analyzed_plan=analyzed_plan,
                result=result,
                timings=timings,
                buffers=buffers,
                notices=notices,
                warnings=warnings,
                rows_match=rows_match,
                rows_match_error=rows_match_error,
            )

        except psycopg.Error as exc:
            if req.sandbox:
                try:
                    await conn.execute("ROLLBACK")
                except psycopg.Error:
                    pass
            return RunResponse(
                ok=False,
                mode=req.mode,
                sandbox=req.sandbox,
                statements=infos,
                notices=notices,
                warnings=warnings,
                error=_error_from_psycopg(
                    exc,
                    current_index,
                    # Setup statements run unwrapped; only the target gets a prefix.
                    position_offset if current_index == len(statements) - 1 else 0,
                ),
            )
