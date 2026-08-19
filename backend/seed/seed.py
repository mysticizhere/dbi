"""Seed the playground database (spec section 6).

    python -m seed.seed --scale 10m
    python -m seed.seed --scale 1m --force

Small data hides every mistake, so 10M rows (~1.5GB) is the default. Rows go in
through ``COPY ... FROM STDIN`` in chunks; there is not a single row-by-row
INSERT in here.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from datetime import UTC, datetime, timedelta
from typing import cast

import numpy as np
import psycopg
from psycopg import AsyncConnection
from psycopg.rows import dict_row

from app.aio import loop_factory
from app.config import settings
from seed.generators import (
    STATUS_DONE,
    STATUS_PENDING,
    Vocabulary,
    build_vocabulary,
    sample_zipf,
    zipf_cdf,
)

SCALES: dict[str, int] = {
    "1m": 1_000_000,
    "10m": 10_000_000,
    "100m": 100_000_000,
}

CHUNK_ROWS = 250_000
N_USERS = 50_000
SCORE_MAX = 1_000_000
EPOCH = datetime(2024, 1, 1, tzinfo=UTC)
SPAN_SECONDS = int(timedelta(days=730).total_seconds())

# One wide table carries exercises 1, 2, 3, 4, 5, 7, 8 and 13. Every column below
# exists to break something specific -- see seed/generators.py.
DDL = """
CREATE TABLE events (
    id          bigint       NOT NULL,
    user_id     bigint       NOT NULL,   -- zipfian: a handful of very heavy users
    score       integer      NOT NULL,   -- uniform 0..1e6: drives selectivity sweeps
    status      text         NOT NULL,   -- 99% DONE / 1% PENDING: histogram skew
    city        text         NOT NULL,   -- correlated 1:1 with pincode
    pincode     integer      NOT NULL,
    email       text         NOT NULL,   -- mixed case: needs lower() to match
    sku         varchar(32)  NOT NULL,   -- digits in a varchar: implicit-cast trap
    payload     text         NOT NULL,   -- filler, to make the row realistically wide
    created_at  timestamptz  NOT NULL
);
"""

COPY_SQL = """
COPY events (id, user_id, score, status, city, pincode, email, sku, payload, created_at)
FROM STDIN
"""


def _chunk_lines(
    rng: np.random.Generator,
    vocab: Vocabulary,
    user_cdf: np.ndarray,
    start_id: int,
    n: int,
) -> str:
    """Build one COPY payload of ``n`` rows in text format.

    Nothing generated here can contain a tab, newline or backslash, so no
    escaping pass is needed -- the pools are built from a safe alphabet.
    """
    ids = np.arange(start_id, start_id + n, dtype=np.int64)
    user_ids = sample_zipf(rng, user_cdf, n)
    scores = rng.integers(0, SCORE_MAX, size=n, dtype=np.int64)
    city_idx = rng.integers(0, vocab.n_cities, size=n)
    pincodes = vocab.pincodes[city_idx]
    # 99 / 1 split -- exercise 8 raises default_statistics_target to see the tail.
    pending = rng.random(n) < 0.01
    name_idx = rng.integers(0, len(vocab.names), size=n)
    payload_idx = rng.integers(0, len(vocab.payloads), size=n)
    offsets = rng.integers(0, SPAN_SECONDS, size=n, dtype=np.int64)

    cities = vocab.cities
    names = vocab.names
    payloads = vocab.payloads

    rows: list[str] = []
    append = rows.append
    for i, uid, score, ci, pin, is_pending, ni, pi, off in zip(
        ids.tolist(),
        user_ids.tolist(),
        scores.tolist(),
        city_idx.tolist(),
        pincodes.tolist(),
        pending.tolist(),
        name_idx.tolist(),
        payload_idx.tolist(),
        offsets.tolist(),
        strict=True,
    ):
        status = STATUS_PENDING if is_pending else STATUS_DONE
        email = f"{names[ni]}.{i}@example.com"
        sku = f"{i % 10_000_000:010d}"  # digits, but stored as varchar
        created = EPOCH + timedelta(seconds=off)
        append(
            f"{i}\t{uid}\t{score}\t{status}\t{cities[ci]}\t{pin}\t{email}\t{sku}\t"
            f"{payloads[pi]}\t{created.isoformat()}"
        )
    return "\n".join(rows) + "\n"


async def _table_row_count(conn: AsyncConnection[dict[str, object]]) -> int | None:
    row = await (
        await conn.execute("SELECT to_regclass('public.events') AS oid")
    ).fetchone()
    if row is None or row["oid"] is None:
        return None
    count_row = await (await conn.execute("SELECT count(*) AS n FROM events")).fetchone()
    return int(cast(int, count_row["n"])) if count_row else None


async def _relation_stats(conn: AsyncConnection[dict[str, object]]) -> list[dict[str, object]]:
    rows = await (
        await conn.execute(
            """
            SELECT c.relname                              AS relation,
                   c.reltuples::bigint                    AS est_rows,
                   pg_total_relation_size(c.oid)          AS total_bytes,
                   pg_indexes_size(c.oid)                 AS index_bytes,
                   pg_size_pretty(pg_total_relation_size(c.oid)) AS total_pretty
            FROM pg_class c
            JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE n.nspname = 'public' AND c.relkind = 'r'
            ORDER BY pg_total_relation_size(c.oid) DESC
            """
        )
    ).fetchall()
    return [dict(r) for r in rows]


async def seed(scale: str, force: bool, seed_value: int) -> int:
    target_rows = SCALES[scale]
    started = time.perf_counter()

    async with await psycopg.AsyncConnection.connect(
        settings.data_dsn, row_factory=dict_row, autocommit=True
    ) as conn:
        existing = await _table_row_count(conn)
        if existing is not None and not force:
            if existing == target_rows:
                print(f"events already holds {existing:,} rows at scale {scale}; nothing to do.")
                print("Pass --force to drop and rebuild.")
                return 0
            print(
                f"events exists with {existing:,} rows, but scale {scale} wants "
                f"{target_rows:,}. Pass --force to drop and rebuild.",
                file=sys.stderr,
            )
            return 1

        print(f"seeding events at scale {scale} ({target_rows:,} rows), seed={seed_value}")
        await conn.execute("DROP TABLE IF EXISTS events")
        await conn.execute(DDL)

        rng = np.random.default_rng(seed_value)
        vocab = build_vocabulary(rng)
        user_cdf = zipf_cdf(N_USERS)

        copy_started = time.perf_counter()
        written = 0
        async with conn.cursor() as cur:
            async with cur.copy(COPY_SQL) as copy:
                while written < target_rows:
                    n = min(CHUNK_ROWS, target_rows - written)
                    await copy.write(_chunk_lines(rng, vocab, user_cdf, written + 1, n))
                    written += n
                    elapsed = time.perf_counter() - copy_started
                    rate = written / elapsed if elapsed > 0 else 0
                    pct = 100 * written / target_rows
                    print(
                        f"  {written:>12,} / {target_rows:,} rows  "
                        f"({pct:5.1f}%)  {rate:,.0f} rows/s",
                        end="\r",
                        flush=True,
                    )
        print()
        print(f"  COPY done in {time.perf_counter() - copy_started:.1f}s")

        # The PK goes on after the load: building the index once beats maintaining
        # it across 10M inserts. Exercises create every other index themselves.
        print("  building primary key on events(id)...")
        pk_started = time.perf_counter()
        await conn.execute("ALTER TABLE events ADD CONSTRAINT events_pkey PRIMARY KEY (id)")
        print(f"  primary key built in {time.perf_counter() - pk_started:.1f}s")

        # VACUUM, not just ANALYZE. Without it the visibility map is unset, every
        # index-only scan pays a heap fetch per row, and exercise 5 -- which is
        # *about* a stale visibility map -- has no clean baseline to start from.
        print("  VACUUM ANALYZE...")
        await conn.execute("VACUUM ANALYZE events")

        relations = await _relation_stats(conn)
        for r in relations:
            print(f"  {r['relation']}: {r['est_rows']:,} rows, {r['total_pretty']} total")

    duration = time.perf_counter() - started

    # Spec section 6: record row counts and relation sizes to lab_meta.
    async with await psycopg.AsyncConnection.connect(
        settings.meta_dsn, row_factory=dict_row, autocommit=True
    ) as meta:
        await meta.execute(
            """
            INSERT INTO seed_runs (scale, seed, relations, duration_s)
            VALUES (%s, %s, %s, %s)
            """,
            (scale, seed_value, json.dumps(relations, default=str), duration),
        )

    print(f"done in {duration:.1f}s")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Seed the lab_data playground.")
    parser.add_argument("--scale", choices=sorted(SCALES), default="10m")
    parser.add_argument("--force", action="store_true", help="drop and recreate")
    parser.add_argument(
        "--seed", type=int, default=1729, help="RNG seed, so a scale is reproducible"
    )
    args = parser.parse_args()
    # Windows needs a selector loop for psycopg -- see app/aio.py.
    with asyncio.Runner(loop_factory=loop_factory) as runner:
        return runner.run(seed(args.scale, args.force, args.seed))


if __name__ == "__main__":
    raise SystemExit(main())
