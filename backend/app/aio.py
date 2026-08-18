"""Event-loop selection.

psycopg's async mode cannot run on Windows' default ``ProactorEventLoop`` -- it
needs a selector loop to wait on the libpq socket. Every entrypoint that starts
an event loop (the server, the seeder, tests) has to go through here, or it dies
at the first connect with an InterfaceError.

No-op everywhere except Windows.
"""

from __future__ import annotations

import asyncio
import selectors
import sys


def loop_factory() -> asyncio.AbstractEventLoop:
    """A loop psycopg can actually use. Pass to ``asyncio.run(..., loop_factory=)``."""
    if sys.platform == "win32":
        return asyncio.SelectorEventLoop(selectors.SelectSelector())
    return asyncio.new_event_loop()


def install_policy() -> None:
    """Force the selector loop process-wide.

    Needed when something else owns loop creation -- uvicorn, pytest-asyncio --
    and there is no ``loop_factory`` hook to pass.
    """
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
