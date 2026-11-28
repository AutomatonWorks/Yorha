"""MouseMove, MouseClick, Click, MouseClickDrag and MouseGetPos, in CoordMode Mouse coordinates, gliding at
SetDefaultMouseSpeed along an optional SetMouseCurvedMotion arc."""

from __future__ import annotations

import ctypes
import math
import re
import time
from ctypes import wintypes
from dataclasses import dataclass

from yorha import Coordinates, Input, KeyCodes, MouseMotion
from yorha import Win32Api as api
from yorha.SendParser import DOWN, PRESS, UP
from yorha.Timing import Random, Sleep

MOUSEEVENTF_MOVE = 0x0001
MOUSEEVENTF_ABSOLUTE = 0x8000
MOUSEEVENTF_VIRTUALDESK = 0x4000
SM_CXSCREEN = 0
SM_CYSCREEN = 1
SM_XVIRTUALSCREEN = 76
SM_YVIRTUALSCREEN = 77
SM_CXVIRTUALSCREEN = 78
SM_CYVIRTUALSCREEN = 79
CLICK_BUTTONS = {"left": "lbutton", "l": "lbutton", "right": "rbutton", "r": "rbutton", "middle": "mbutton",
                 "m": "mbutton", "x1": "xbutton1", "x2": "xbutton2", "wheelup": "wheelup", "wu": "wheelup",
                 "wheeldown": "wheeldown", "wd": "wheeldown", "wheelleft": "wheelleft", "wl": "wheelleft",
                 "wheelright": "wheelright", "wr": "wheelright"}
DOWN_WORDS = ("down", "d")
UP_WORDS = ("up", "u")
RELATIVE_WORDS = ("rel", "relative")
# How often a gliding MouseMove places the cursor; Windows' timer rounds it up to ~15 ms.
GLIDE_FRAME_MS = 8

_CLICK_SEPARATORS = re.compile(r"[\s,]+")
# (lowest, highest) picked from on every move, both included.
# "speed" 0-100: 0 jumps, 100 crosses the window diagonal in MouseMotion.SLOWEST_FULL_MOVE_MS.
# "curve" 0-100: 0 moves in a straight line, more bows the path to a random side.
_mouseMotion = {"speed": (2, 2), "curve": (0, 0)}
_Now = time.perf_counter


def SetDefaultMouseSpeed(highest: int, lowest: int | None = None) -> None:
    _mouseMotion["speed"] = _Range(highest, lowest)


def SetMouseCurvedMotion(highest: int, lowest: int | None = None) -> None:
    _mouseMotion["curve"] = _Range(highest, lowest)


def _Range(highest: int, lowest: int | None) -> tuple[int, int]:
    if lowest is None:
        return highest, highest
    return min(highest, lowest), max(highest, lowest)


def _Pick(setting: str) -> int:
    lowest, highest = _mouseMotion[setting]
    return Random(lowest, highest)


# ---- position ----


def _Origin() -> tuple[int, int]:
    return Coordinates.Origin("mouse")


def _ScreenCursor() -> tuple[int, int]:
    point = wintypes.POINT()
    api.GetCursorPos(ctypes.byref(point))
    return point.x, point.y


def MouseGetPos() -> tuple[int, int]:
    """The cursor position in CoordMode Mouse coordinates."""
    cursorX, cursorY = _ScreenCursor()
    originX, originY = _Origin()
    return (cursorX - originX), (cursorY - originY)


def _AbsoluteMove(screenX: int, screenY: int) -> None:
    left = api.GetSystemMetrics(SM_XVIRTUALSCREEN)
    top = api.GetSystemMetrics(SM_YVIRTUALSCREEN)
    width = max(1, api.GetSystemMetrics(SM_CXVIRTUALSCREEN))
    height = max(1, api.GetSystemMetrics(SM_CYVIRTUALSCREEN))
    # Rounded up so Windows' truncating back-conversion lands on the exact pixel.
    normalX = (((screenX - left) * 65536) + width - 1) // width
    normalY = (((screenY - top) * 65536) + height - 1) // height
    flags = MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_VIRTUALDESK
    Input.Inject(Input.MouseInput(normalX, normalY, flags))


def _WindowDiagonal() -> float:
    hwnd = api.GetForegroundWindow()
    rect = wintypes.RECT()
    if hwnd and api.GetClientRect(hwnd, ctypes.byref(rect)) and (rect.right > 0) and (rect.bottom > 0):
        return math.hypot(rect.right, rect.bottom)
    return math.hypot(api.GetSystemMetrics(SM_CXSCREEN), api.GetSystemMetrics(SM_CYSCREEN))


def _IsRelative(relative: str) -> bool:
    return relative.upper() == "R"


def MouseMove(x: float, y: float, speed: int | None = None, relative: str = "") -> None:
    """MouseMove(X, Y, Speed, Relative): "R" moves by X and Y from the cursor."""
    if speed is None:
        speed = _Pick("speed")
    start = _ScreenCursor()
    originX, originY = start if _IsRelative(relative) else _Origin()
    # AHK MouseMove truncates float coordinates (GetGameCenter() halves the client size).
    target = ((int(x) + originX), (int(y) + originY))
    durationMs = MouseMotion.DurationMs(start, target, speed, _WindowDiagonal())
    if durationMs > 0:
        _Glide(start, target, durationMs)
    _AbsoluteMove(*target)
    Input.CurrentEmitter().Delay("mouse")


def _Glide(start: tuple[int, int], target: tuple[int, int], durationMs: float) -> None:
    control = MouseMotion.ControlPoint(start, target, _Pick("curve"))
    began = _Now()
    while True:
        # Placed by the clock, not by a step count, so a late Sleep never slows the move down.
        progress = ((_Now() - began) * 1000) / durationMs
        if progress >= 1:
            return
        _AbsoluteMove(*MouseMotion.PointAt(start, control, target, progress))
        Sleep(GLIDE_FRAME_MS)


def MouseEventMove(dx: int, dy: int) -> None:
    """DllCall("mouse_event", "UInt", 0x01, "Int", dx, "Int", dy): a raw relative move for camera turns."""
    api.mouseEvent(MOUSEEVENTF_MOVE, dx, dy, 0, 0)


# ---- clicks ----


def _ButtonVk(button: str) -> int:
    name = CLICK_BUTTONS.get(button.lower(), button.lower())
    if name not in KeyCodes.MOUSE_VKS:
        raise ValueError(f"Invalid mouse button: {button}")
    return KeyCodes.MOUSE_VKS[name]


def _Kind(downOrUp: str) -> str:
    word = downOrUp.lower()
    if word in DOWN_WORDS:
        return DOWN
    if word in UP_WORDS:
        return UP
    if word == "":
        return PRESS
    raise ValueError(f"Invalid DownOrUp: {downOrUp}")


def _Press(vk: int, count: int, kind: str, mode: str | None = None) -> None:
    emitter = Input.CurrentEmitter() if (mode is None) else Input.Emitter(mode)
    if vk in KeyCodes.WHEEL_VKS:
        Input.SendWheelNotches(emitter, vk, count)
    else:
        for _ in range(count):
            Input.PerformButton(emitter, vk, kind)
    emitter.Flush()


def MouseClick(button: str = "left", x: float | None = None, y: float | None = None, count: int = 1,
               speed: int | None = None, downOrUp: str = "", relative: str = "") -> None:
    """MouseClick(WhichButton, X, Y, ClickCount, Speed, DownOrUp, Relative); a wheel button turns `count`
    notches. With only one of X and Y, the cursor keeps its place on the other axis."""
    vk = _ButtonVk(button)
    kind = _Kind(downOrUp)
    if (x is not None) or (y is not None):
        _MoveFilling(x, y, speed, relative)
    _Press(vk, count, kind)


def _MoveFilling(x: float | None, y: float | None, speed: int | None, relative: str) -> None:
    if _IsRelative(relative):
        MouseMove(x or 0, y or 0, speed, relative)
        return
    currentX, currentY = MouseGetPos()
    MouseMove(currentX if (x is None) else x, currentY if (y is None) else y, speed)


def MouseClickDrag(button: str, x1: float | None, y1: float | None, x2: float, y2: float,
                   speed: int | None = None, relative: str = "") -> None:
    """MouseClickDrag: X1/Y1 omitted start where the cursor is; with "R", X1/Y1 count from the cursor and
    X2/Y2 from X1/Y1."""
    vk = _ButtonVk(button)
    if (x1 is not None) or (y1 is not None):
        _MoveFilling(x1, y1, speed, relative)
    _Press(vk, 1, DOWN)
    _MoveFilling(x2, y2, speed, relative)
    _Press(vk, 1, UP)


@dataclass(frozen=True)
class ClickOptions:
    x: float | None = None
    y: float | None = None
    button: str = "left"
    count: int = 1
    downOrUp: str = ""
    relative: bool = False


def ParseClick(*options: object) -> ClickOptions:
    """Click's options in any order: X Y [count], a button, Down/D, Up/U, Rel/Relative. A lone number is the
    count. Several parameters are joined as if written in one string."""
    text = " ".join(str(option) for option in options if option not in ("", None))
    numbers: list[float] = []
    fields: dict[str, object] = {}
    for word in _CLICK_SEPARATORS.split(text.strip()):
        lowered = word.lower()
        if lowered == "":
            continue
        if lowered in CLICK_BUTTONS:
            fields["button"] = lowered
        elif lowered in DOWN_WORDS + UP_WORDS:
            fields["downOrUp"] = lowered[0]
        elif lowered in RELATIVE_WORDS:
            fields["relative"] = True
        else:
            numbers.append(_Number(word))
    if len(numbers) == 1:
        fields["count"] = int(numbers[0])
    elif len(numbers) >= 2:
        fields["x"], fields["y"] = numbers[0], numbers[1]
        if len(numbers) >= 3:
            fields["count"] = int(numbers[2])
    return ClickOptions(**fields)


def _Number(word: str) -> float:
    try:
        return float(word)
    except ValueError:
        raise ValueError(f"Invalid Click option: {word}") from None


def Click(*options: object) -> None:
    """Click("100 200 Right 2"), Click(100, 200), Click("WheelUp 3"), Click("D"), Click("50 0 Rel 0")...;
    count 0 only moves."""
    ClickIn(None, *options)


def ClickIn(mode: str | None, *options: object) -> None:
    """Click in SendMode `mode` (None: the current one): a {Click} inside SendEvent or SendInput follows that Send."""
    parsed = ParseClick(*options)
    if parsed.x is not None:
        MouseMove(parsed.x, parsed.y, None, "R" if parsed.relative else "")
    if parsed.count > 0:
        _Press(_ButtonVk(parsed.button), parsed.count, _Kind(parsed.downOrUp), mode)
