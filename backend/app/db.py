"""Connection pools for the two databases.

`lab_meta` holds app state; `lab_data` is the playground where user SQL runs.
They are kept in separate pools so that a wedged playground query can never
starve the app of its own connections.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass

from psycopg import AsyncConnection
from psycopg.pq import TransactionStatus
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from app.config import settings


@dataclass
class Pools:
    meta: AsyncConnectionPool[AsyncConnection[dict[str, object]]]
    data: AsyncConnectionPool[AsyncConnection[dict[str, object]]]


_pools: Pools | None = None


def _make_pool(dsn: str, max_size: int) -> AsyncConnectionPool[AsyncConnection[dict[str, object]]]:
    return AsyncConnectionPool(
        conninfo=dsn,
        min_size=1,
        max_size=max_size,
        open=False,
        # Every lab connection returns dicts; the plan JSON path depends on it.
        kwargs={"row_factory": dict_row, "autocommit": True},
    )


async def open_pools() -> Pools:
    global _pools
    if _pools is not None:
        return _pools
    pools = Pools(
        meta=_make_pool(settings.meta_dsn, max_size=4),
        # Playground runs are serial per request but benchmarks fan out.
        data=_make_pool(settings.data_dsn, max_size=8),
    )
    await pools.meta.open(wait=True, timeout=30)
    await pools.data.open(wait=True, timeout=30)
    _pools = pools
    return pools


async def close_pools() -> None:
    global _pools
    if _pools is None:
        return
    await _pools.meta.close()
    await _pools.data.close()
    _pools = None


def get_pools() -> Pools:
    if _pools is None:
        raise RuntimeError("connection pools are not open; is the app lifespan running?")
    return _pools


@asynccontextmanager
async def meta_conn() -> AsyncIterator[AsyncConnection[dict[str, object]]]:
    async with get_pools().meta.connection() as conn:
        yield conn


@asynccontextmanager
async def data_conn() -> AsyncIterator[AsyncConnection[dict[str, object]]]:
    """A playground connection.

    Reset on release so that no per-run GUC (statement_timeout, enable_seqscan,
    ...) leaks into the next request that borrows this connection. A run that
    died mid-transaction has to be rolled back first -- RESET ALL is rejected
    inside a failed transaction block.
    """
    async with get_pools().data.connection() as conn:
        try:
            yield conn
        finally:
            if conn.info.transaction_status != TransactionStatus.IDLE:
                await conn.execute("ROLLBACK")
            await conn.execute("RESET ALL")


async def apply_meta_schema() -> None:
    """Re-apply the idempotent lab_meta schema on startup.

    Docker's initdb only runs on a fresh volume, so without this a schema change
    would mean wiping the playground.
    """
    sql = settings.meta_schema_path.read_text(encoding="utf-8")
    async with meta_conn() as conn:
        await conn.execute(sql)
