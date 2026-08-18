"""uvicorn Config subclass that pins the event loop psycopg needs.

This lives in its own importable module rather than in `serve.py` on purpose.
uvicorn's reloader spawns the worker with multiprocessing 'spawn', which pickles
the Server (and therefore this Config class) by qualified name. A class defined
in `__main__` cannot be resolved in the child -- the reload then dies silently
and the *old* worker keeps serving, so edits appear to do nothing.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable

import uvicorn

from app.aio import loop_factory


class SelectorLoopConfig(uvicorn.Config):
    """Always yields a selector loop, whatever uvicorn would otherwise pick.

    uvicorn 0.52 chooses ProactorEventLoop on Windows unless it happens to be
    spawning a subprocess -- so `--reload` works by accident and a plain run does
    not. This removes the accident.
    """

    def get_loop_factory(self) -> Callable[[], asyncio.AbstractEventLoop] | None:
        return loop_factory
