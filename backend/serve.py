r"""Dev server entrypoint.

    python serve.py              start the API
    python serve.py --reload     opt in to autoreload (see the warning below)

Run this rather than `uvicorn app.main:app` -- see app/uvicorn_config.py for why
the event loop has to be pinned.

**Autoreload is off by default, deliberately.** uvicorn's reloader does not work
on this machine: WatchFiles detects the edit and logs "Reloading...", but the
supervisor then stalls in `process.join()` and never spawns a replacement, while
the *old* worker keeps answering requests. The result is a server silently
serving stale code -- which, in a tool whose whole purpose is measuring query
behaviour, means measuring a build you are no longer looking at. That cost real
debugging time twice before it was pinned down.

It is not our shutdown path: opening and closing the connection pools directly
takes ~0ms and exits cleanly, and the same stall happened with a stock
`uvicorn.run(..., reload=True)` before any of this file's customisation existed.

So: restart explicitly. `.\lab.ps1 api` takes about a second.
"""

from __future__ import annotations

import argparse
import os
import sys

# WatchFiles' native Windows backend also stopped reporting edits mid-session.
# Polling ~25 files a second is free at this size. Must be set before uvicorn
# imports watchfiles.
if sys.platform == "win32":
    os.environ.setdefault("WATCHFILES_FORCE_POLLING", "true")

import uvicorn  # noqa: E402

from app.config import settings  # noqa: E402
from app.uvicorn_config import SelectorLoopConfig  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--reload",
        action="store_true",
        help="autoreload on edit -- known to stall on Windows, see module docstring",
    )
    args = parser.parse_args()

    config = SelectorLoopConfig(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        reload=args.reload,
        reload_dirs=["app"] if args.reload else None,
        log_level="info",
    )
    server = uvicorn.Server(config)

    if config.should_reload:
        print(
            "warning: autoreload stalls on Windows and can leave the old worker "
            "serving stale code. Verify a change took effect before trusting a number.",
            file=sys.stderr,
        )
        # Mirrors uvicorn.run()'s reload path. We cannot call uvicorn.run()
        # itself because it would build a stock Config and lose the loop pin.
        from uvicorn.supervisors import ChangeReload

        sock = config.bind_socket()
        ChangeReload(config, target=server.run, sockets=[sock]).run()
    else:
        server.run()


if __name__ == "__main__":
    main()
