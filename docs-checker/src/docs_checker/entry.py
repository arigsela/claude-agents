"""The ``docs-checker`` console entry point.

Kept free of heavy imports on purpose: in a Substrate sandbox only stdout reaches
the logs, and importing the server (LangGraph, the Anthropic SDK, gRPC) takes
seconds. This module says the process started before that import, reports how
long it took, and puts an import failure's traceback, or a fatal signal's stack
(``faulthandler``), on stdout, so a golden actor that never answers /readyz says why.
"""

from __future__ import annotations

import faulthandler
import os
import sys
import time
import traceback


def main() -> None:
    started = time.monotonic()
    print(
        f"docs-checker: starting (pid {os.getpid()}, uid {os.getuid()}, "
        f"python {sys.version.split()[0]})",
        flush=True,
    )
    for stream in (sys.stdout, sys.__stdout__):  # the first one with a file descriptor
        try:
            faulthandler.enable(file=stream, all_threads=True)
            break
        except (OSError, ValueError, AttributeError):
            continue
    try:
        from docs_checker import server
    except BaseException:  # noqa: BLE001 - any import failure is reported, then exit 1
        print("docs-checker: importing the server failed", flush=True)
        traceback.print_exc(file=sys.stdout)
        sys.stdout.flush()
        raise SystemExit(1) from None
    print(f"docs-checker: imports done in {time.monotonic() - started:.1f}s", flush=True)
    server.main()


if __name__ == "__main__":
    main()
