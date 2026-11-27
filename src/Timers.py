"""SetTimer.

Timers set from the macro thread (combat loops, rotation watchers) belong to the macro: they run
on their own "macro-timers" thread, which a stop interrupts at its next wait (MacroStopped deletes
every macro timer) and a pause holds, like the macro itself. Every other timer runs on the
"ahk-timers" thread, one callback at a time, so a long rotation never holds up ExitOnGameClose
and the other background checks.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass

from yorha.Threads import IsMacroThread, MacroStopped, MarkMacroThread
from yorha.Timing import TickCount

DEFAULT_PERIOD_MS = 250

log = logging.getLogger(__name__)


@dataclass
class _Timer:
    fn: Callable[[], object]
    periodMs: int
    priority: int
    due: int
    sequence: int


class _Scheduler:
    def __init__(self, name: str, forMacro: bool) -> None:
        self.name = name
        self.forMacro = forMacro
        self.timers: dict[Callable[[], object], _Timer] = {}
        self.condition = threading.Condition()
        self.thread: threading.Thread | None = None
        self.sequence = 0

    def Set(self, fn: Callable[[], object], periodMs: int, priority: int) -> None:
        with self.condition:
            self.sequence += 1
            self.timers[fn] = _Timer(fn, periodMs, priority, TickCount() + abs(periodMs), self.sequence)
            if (self.thread is None) or (not self.thread.is_alive()):
                self.thread = threading.Thread(target=self._Run, name=self.name, daemon=True)
                self.thread.start()
            self.condition.notify_all()

    def Delete(self, fn: Callable[[], object]) -> bool:
        with self.condition:
            removed = self.timers.pop(fn, None) is not None
            self.condition.notify_all()
            return removed

    def Clear(self) -> None:
        with self.condition:
            self.timers.clear()
            self.condition.notify_all()

    def Has(self, fn: Callable[[], object]) -> bool:
        with self.condition:
            return fn in self.timers

    def _NextDue(self, now: int) -> tuple[_Timer | None, int | None]:
        """The timer to run now (higher priority first, then the oldest), else how long to wait."""
        due = [timer for timer in self.timers.values() if timer.due <= now]
        if due:
            return min(due, key=lambda timer: (-timer.priority, timer.due, timer.sequence)), None
        if not self.timers:
            return None, None
        return None, min(timer.due for timer in self.timers.values()) - now

    def _TakeNext(self) -> _Timer:
        with self.condition:
            while True:
                now = TickCount()
                timer, waitMs = self._NextDue(now)
                if timer is not None:
                    if timer.periodMs < 0:
                        del self.timers[timer.fn]
                    else:
                        timer.due = now + timer.periodMs
                    return timer
                self.condition.wait(None if (waitMs is None) else (waitMs / 1000))

    def _Run(self) -> None:
        if self.forMacro:
            MarkMacroThread()
        while True:
            timer = self._TakeNext()
            try:
                timer.fn()
            except MacroStopped:
                self.Clear()
            except Exception:
                log.exception("Timer callback %r raised", timer.fn)


_background = _Scheduler("ahk-timers", forMacro=False)
_macro = _Scheduler("macro-timers", forMacro=True)
# fn -> the scheduler that runs only fn, on its own thread
_own: dict[Callable[[], object], _Scheduler] = {}
_ownLock = threading.Lock()


def SetTimer(fn: Callable[[], object], periodMs: int = DEFAULT_PERIOD_MS, priority: int = 0) -> None:
    """SetTimer(fn, period, priority): > 0 repeats, < 0 runs once after abs(period), 0 deletes.
    Calling it again with the same fn updates that timer and restarts its countdown."""
    if periodMs == 0:
        _macro.Delete(fn)
        _background.Delete(fn)
        with _ownLock:
            own = _own.pop(fn, None)
        if own is not None:
            own.Delete(fn)
        return
    if _macro.Has(fn):
        scheduler = _macro
    elif _background.Has(fn):
        scheduler = _background
    else:
        scheduler = _macro if IsMacroThread() else _background
    scheduler.Set(fn, periodMs, priority)


def SetTimerOnOwnThread(fn: Callable[[], object], periodMs: int, threadName: str) -> None:
    """A repeating background timer with a thread to itself: a slow tick (a screen read, an OCR) never holds
    up the "ahk-timers" callbacks, and theirs never delay it. SetTimer(fn, 0) deletes it."""
    with _ownLock:
        scheduler = _own.get(fn)
        if scheduler is None:
            scheduler = _Scheduler(threadName, forMacro=False)
            _own[fn] = scheduler
    scheduler.Set(fn, periodMs, 0)


def ClearMacroTimers() -> None:
    """Drops the timers a previous macro left behind; MacroStack calls it when a macro starts."""
    _macro.Clear()
