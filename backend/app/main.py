"""FastAPI application entrypoint.

Local-only, single-user, bound to 127.0.0.1. There is no auth because there is
no exposure -- see spec section 2.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.db import apply_meta_schema, close_pools, open_pools
from app.routers import exercises, workbench

log = logging.getLogger("perflab")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    await open_pools()
    # The docker initdb scripts only run on a fresh volume, so the meta schema is
    # re-applied here on every boot. It is idempotent by construction.
    await apply_meta_schema()
    log.info("connected to lab_meta and lab_data")
    try:
        yield
    finally:
        await close_pools()


app = FastAPI(
    title="Postgres Performance Lab",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_origin, "http://localhost:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(workbench.router, prefix="/api")
app.include_router(exercises.router, prefix="/api")


@app.get("/")
async def root() -> dict[str, str]:
    return {"name": "Postgres Performance Lab", "docs": "/docs"}
