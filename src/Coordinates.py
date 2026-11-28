"""CoordMode: what the Mouse and Pixel coordinates are relative to (the screen, the active window or its client
area). Global, where AHK keeps one per thread."""

from __future__ import annotations

import ctypes
from ctypes import wintypes

from yorha import Win32Api as api

SCREEN = "Screen"
WINDOW = "Window"
CLIENT = "Client"
_RELATIVE_TO = {"screen": SCREEN, "window": WINDOW, "client": CLIENT}
# AHK v2 starts every target relative to the active window's client area.
_modes = {"tooltip": CLIENT, "pixel": CLIENT, "mouse": CLIENT, "caret": CLIENT, "menu": CLIENT}


def CoordMode(targetType: str, relativeTo: str = SCREEN) -> str:
    """CoordMode(TargetType, RelativeTo := "Screen"); returns the previous setting."""
    target = targetType.lower()
    if (target not in _modes) or (relativeTo.lower() not in _RELATIVE_TO):
        raise ValueError(f"Invalid CoordMode: {targetType}, {relativeTo}")
    previous = _modes[target]
    _modes[target] = _RELATIVE_TO[relativeTo.lower()]
    return previous


def CoordModeMouse() -> str:
    """A_CoordModeMouse."""
    return _modes["mouse"]


def CoordModePixel() -> str:
    """A_CoordModePixel."""
    return _modes["pixel"]


def Origin(targetType: str) -> tuple[int, int]:
    """The screen point `targetType` coordinates count from; the screen's when no window is active."""
    mode = _modes[targetType.lower()]
    hwnd = api.GetForegroundWindow()
    if (mode == SCREEN) or (not hwnd):
        return 0, 0
    if mode == WINDOW:
        rect = wintypes.RECT()
        api.GetWindowRect(hwnd, ctypes.byref(rect))
        return rect.left, rect.top
    point = wintypes.POINT(0, 0)
    api.ClientToScreen(hwnd, ctypes.byref(point))
    return point.x, point.y
