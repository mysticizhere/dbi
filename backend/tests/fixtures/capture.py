"""Capture a real EXPLAIN plan from lab_data as a test fixture.

    python -m tests.fixtures.capture

Run this once against a seeded playground. The captured plan is committed, so
the plan tests stay fast and offline; re-run it if the query below changes.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import psycopg
from psycopg.rows import dict_row

from app.aio import loop_factory
from app.config import settings

HERE = Path(__file__).parent

# Deliberately shaped to produce a Nested Loop whose inner side runs many times:
# that is the plan shape where per-loop timing arithmetic goes wrong.
QUERY = """
EXPLAIN (ANALYZE, BUFFERS, VERBOSE, SETTINGS, FORMAT JSON)
SELECT e.id, e.city, s.score
FROM events e
JOIN LATERAL (
    SELECT score FROM events x WHERE x.id = e.id + 1
) s ON true
WHERE e.score < 200
"""


async def capture() -> None:
    async with await psycopg.AsyncConnection.connect(
        settings.data_dsn, row_factory=dict_row, autocommit=True
    ) as conn:
        await conn.execute("SET enable_hashjoin = off")
        await conn.execute("SET enable_mergejoin = off")
        await conn.execute("SET max_parallel_workers_per_gather = 0")
        row = await (await conn.execute(QUERY)).fetchone()
        assert row is not None
        payload = next(iter(row.values()))

    plan = payload[0] if isinstance(payload, list) else payload
    out = HERE / "nested_loop_plan.json"
    out.write_text(json.dumps(plan, indent=2), encoding="utf-8")
    print(f"wrote {out} ({out.stat().st_size:,} bytes)")


if __name__ == "__main__":
    with asyncio.Runner(loop_factory=loop_factory) as runner:
        runner.run(capture())
