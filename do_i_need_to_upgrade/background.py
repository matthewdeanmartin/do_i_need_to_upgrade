"""Background refresh runner with atexit exit-message support.

Uses a daemon thread so it never blocks interpreter shutdown. Callers are
expected to be fine with fire-and-forget: the result is written to the cache
and picked up on the next startup.

An optional atexit handler prints an update message when the program exits.
"""

from __future__ import annotations

import atexit
import contextlib
import sys
import threading
from collections.abc import Callable

_EXIT_STATE: dict[str, str | bool | None] = {"message": None, "registered": False}


def _exit_handler() -> None:
    """Print the pending update message on program exit, if any."""
    message = _EXIT_STATE["message"]
    if isinstance(message, str) and message:
        print(f"\n{message}", file=sys.stderr)


def register_exit_message(message: str) -> None:
    """Schedule message to be printed to stderr on program exit.

    Args:
        message: The message string to display on exit.
    """
    _EXIT_STATE["message"] = message
    if not _EXIT_STATE["registered"]:
        atexit.register(_exit_handler)
        _EXIT_STATE["registered"] = True


def spawn(target: Callable[[], None], name: str = "do-i-need-to-upgrade-refresh") -> threading.Thread:
    """Spawn a background daemon thread for a fire-and-forget task.

    Args:
        target: Callable to run in the background.
        name: Thread name for debugging.

    Returns:
        The started Thread.
    """
    thread = threading.Thread(target=_wrap(target), name=name, daemon=True)
    thread.start()
    return thread


def _wrap(target: Callable[[], None]) -> Callable[[], None]:
    """Wrap a callable to suppress all exceptions silently.

    Args:
        target: The callable to wrap.

    Returns:
        A wrapped callable that swallows exceptions silently.
    """

    def runner() -> None:
        with contextlib.suppress(Exception):
            target()

    return runner


__all__ = ["register_exit_message", "spawn"]
