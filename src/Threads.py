"""Stop and pause for the macro thread.

Cancellation is cooperative: a thread cannot be killed safely, so every wait in
ported code goes through `sleep()` or another wait that calls `checkpoint()`.
On the macro thread a requested stop raises MacroStopped there, and a pause
blocks there until resumed. Other threads (GUI, hotkeys, timers) are never
stopped or paused by it.
"""

from __future__ import annotations

import threading


class MacroStopped(BaseException):
    """Raised on the macro thread at its next wait after a stop. A BaseException so the
    `except Exception` blocks of ported code do not swallow it."""


_stop = threading.Event()
_running = threading.Event()
_running.set()
_local = threading.local()


def MarkMacroThread() -> None:
    _local.is_macro = True


def IsMacroThread() -> bool:
    return getattr(_local, "is_macro", False)


def RequestStop() -> None:
    _stop.set()
    _running.set()


def ClearStop() -> None:
    _stop.clear()


def StopRequested() -> bool:
    return _stop.is_set()


def SetPaused(paused: bool) -> None:
    if paused:
        _running.clear()
    else:
        _running.set()


def IsPaused() -> bool:
    return not _running.is_set()


def Checkpoint() -> None:
    if not IsMacroThread():
        return
    while not _running.wait(0.05):
        if _stop.is_set():
            break
    if _stop.is_set():
        raise MacroStopped()


def WaitEvent(event: threading.Event, timeoutMs: float | None = None) -> bool:
    """Waits for `event` like Event.wait, but in short slices so a stop or pause on the
    macro thread applies while it waits. A pause does not count towards the timeout."""
    remaining = None if (timeoutMs is None) else (timeoutMs / 1000)
    while True:
        Checkpoint()
        slices = 0.05 if (remaining is None) else min(0.05, remaining)
        if event.wait(slices):
            return True
        if remaining is not None:
            remaining -= slices
            if remaining <= 0:
                return False
