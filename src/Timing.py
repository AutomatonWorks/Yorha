"""A_TickCount, Sleep, Random, A_Now, FormatTime and DateAdd."""

from __future__ import annotations

import random as _random
import threading
import time
from datetime import datetime, timedelta

from yorha.Threads import WaitEvent

_never = threading.Event()

AHK_TIMESTAMP = "%Y%m%d%H%M%S"
# Longest token first, so "MMMM" wins over "MM" and "M".
_FORMAT_TOKENS = (
    ("yyyy", lambda m: f"{m.year:04d}"), ("yy", lambda m: f"{m.year % 100:02d}"),
    ("MMMM", lambda m: m.strftime("%B")), ("MMM", lambda m: m.strftime("%b")),
    ("MM", lambda m: f"{m.month:02d}"), ("M", lambda m: str(m.month)),
    ("dddd", lambda m: m.strftime("%A")), ("ddd", lambda m: m.strftime("%a")),
    ("dd", lambda m: f"{m.day:02d}"), ("d", lambda m: str(m.day)),
    ("HH", lambda m: f"{m.hour:02d}"), ("H", lambda m: str(m.hour)),
    ("hh", lambda m: f"{((m.hour - 1) % 12) + 1:02d}"), ("h", lambda m: str(((m.hour - 1) % 12) + 1)),
    ("mm", lambda m: f"{m.minute:02d}"), ("m", lambda m: str(m.minute)),
    ("ss", lambda m: f"{m.second:02d}"), ("s", lambda m: str(m.second)),
    ("tt", lambda m: m.strftime("%p")),
)
_DATE_UNITS = {"seconds": "seconds", "s": "seconds", "minutes": "minutes", "m": "minutes",
               "hours": "hours", "h": "hours", "days": "days", "d": "days"}
_SECONDS_PER_UNIT = {"seconds": 1, "minutes": 60, "hours": 3600, "days": 86400}
_TIMESTAMP_DEFAULTS = "0101000000"


def TickCount() -> int:
    return int(time.monotonic() * 1000)


def Sleep(ms: float) -> None:
    """Sleep(ms). On the macro thread a stop raises MacroStopped and a pause holds it."""
    WaitEvent(_never, max(0.0, ms))


def Random(low: float, high: float) -> float:
    """Random(low, high): an int when both bounds are ints, both bounds included."""
    if isinstance(low, int) and isinstance(high, int):
        return _random.randint(min(low, high), max(low, high))
    return _random.uniform(low, high)


def ANow() -> str:
    return datetime.now().strftime(AHK_TIMESTAMP)


def ParseTimestamp(stamp: str) -> datetime:
    """A YYYYMMDDHH24MISS stamp; missing trailing parts default like AHK (month and day 1)."""
    stamp = str(stamp)
    if len(stamp) < 14:
        stamp = stamp + _TIMESTAMP_DEFAULTS[(len(stamp) - 4):]
    return datetime.strptime(stamp[:14], AHK_TIMESTAMP)


def FormatTime(stamp: str = "", fmt: str = "") -> str:
    """FormatTime(stamp, fmt) for the date and time tokens (no locale formats)."""
    moment = datetime.now() if (stamp == "") else ParseTimestamp(stamp)
    if fmt == "":
        fmt = "h:mm tt dddd, MMMM d, yyyy"
    out = []
    index = 0
    while index < len(fmt):
        for token, render in _FORMAT_TOKENS:
            if fmt.startswith(token, index):
                out.append(render(moment))
                index += len(token)
                break
        else:
            out.append(fmt[index])
            index += 1
    return "".join(out)


def DateAdd(stamp: str, amount: float, unit: str) -> str:
    moment = ParseTimestamp(stamp) + timedelta(**{_DATE_UNITS[unit.lower()]: amount})
    return moment.strftime(AHK_TIMESTAMP)


def DateDiff(stamp1: str, stamp2: str, unit: str) -> int:
    seconds = (ParseTimestamp(stamp1) - ParseTimestamp(stamp2)).total_seconds()
    return int(seconds / _SECONDS_PER_UNIT[_DATE_UNITS[unit.lower()]])
