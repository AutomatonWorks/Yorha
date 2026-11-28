"""Send, MouseMove, Click, MouseGetPos and GetKeyState (SendMode Event with SetKeyDelay/SetMouseDelay)."""

from __future__ import annotations

import ctypes
import math
import re
import threading
import time
from ctypes import wintypes
from dataclasses import dataclass

from yorha import KeyCodes, MouseMotion
from yorha import Win32Api as api
from yorha.KeyCodes import KeyCode
from yorha.Timing import Random, Sleep

KEYEVENTF_EXTENDEDKEY = 0x0001
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_UNICODE = 0x0004
KEYEVENTF_SCANCODE = 0x0008
MOUSEEVENTF_MOVE = 0x0001
MOUSEEVENTF_ABSOLUTE = 0x8000
MOUSEEVENTF_VIRTUALDESK = 0x4000
MOUSEEVENTF_WHEEL = 0x0800
MOUSEEVENTF_HWHEEL = 0x1000
WHEEL_DELTA = 120
XBUTTON1 = 1
XBUTTON2 = 2
SM_CXSCREEN = 0
SM_CYSCREEN = 1
SM_XVIRTUALSCREEN = 76
SM_YVIRTUALSCREEN = 77
SM_CXVIRTUALSCREEN = 78
SM_CYVIRTUALSCREEN = 79
# (down flag, up flag, mouseData) per button vk
MOUSE_BUTTON_FLAGS = {
    0x01: (0x0002, 0x0004, 0), 0x02: (0x0008, 0x0010, 0), 0x04: (0x0020, 0x0040, 0),
    0x05: (0x0080, 0x0100, XBUTTON1), 0x06: (0x0080, 0x0100, XBUTTON2),
}
# vk -> (wheel flag, notch sign)
WHEEL_FLAGS = {0x9F: (MOUSEEVENTF_WHEEL, 1), 0x9E: (MOUSEEVENTF_WHEEL, -1),
               0x9D: (MOUSEEVENTF_HWHEEL, 1), 0x9C: (MOUSEEVENTF_HWHEEL, -1)}
CLICK_BUTTONS = {"left": "lbutton", "l": "lbutton", "right": "rbutton", "r": "rbutton", "middle": "mbutton",
                 "m": "mbutton", "x1": "xbutton1", "x2": "xbutton2", "wheelup": "wheelup", "wu": "wheelup",
                 "wheeldown": "wheeldown", "wd": "wheeldown", "wheelleft": "wheelleft", "wl": "wheelleft",
                 "wheelright": "wheelright", "wr": "wheelright"}
# How often a gliding MouseMove places the cursor; Windows' timer rounds it up to ~15 ms.
GLIDE_FRAME_MS = 8

PRESS = "press"
DOWN = "down"
UP = "up"
_BRACE = re.compile(r"\{([^}]+|\})\}")
_BRACE_BODY = re.compile(r"^(?P<name>.+?)(?:\s+(?P<arg>\S+))?$")
_IGNORED_DIRECTIVES = {"blind"}

# "wheel" follows every notch so its scroll animation ends first: ZZZ merged notches 10 ms apart
# and cut a notch short at 150 ms
_delays = {"key": 10, "press": -1, "mouse": 10, "wheel": 250}
# (lowest, highest) picked from on every move, both included.
# "speed" 0-100: 0 jumps, 100 crosses the window diagonal in MouseMotion.SLOWEST_FULL_MOVE_MS.
# "curve" 0-100: 0 moves in a straight line, more bows the path to a random side.
_mouseMotion = {"speed": (2, 2), "curve": (0, 0)}
_Now = time.perf_counter


@dataclass(frozen=True)
class KeyAction:
    """One Send unit: a key pressed (down then up), held down or released; `char` is set for a Unicode packet."""
    key: KeyCode
    kind: str = PRESS
    char: str = ""


def SetKeyDelay(ms: int = 10, pressMs: int = -1) -> None:
    _delays["key"] = ms
    _delays["press"] = pressMs


def SetMouseDelay(ms: int = 10) -> None:
    _delays["mouse"] = ms


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


def ParseSend(keys: str) -> list[KeyAction]:
    """The key actions an AHK Send string stands for, modifiers wrapped around the key they precede."""
    actions: list[KeyAction] = []
    modifiers = ""
    index = 0
    while index < len(keys):
        char = keys[index]
        if (char in KeyCodes.MODIFIER_SEND_VK) and (index + 1 < len(keys)):
            modifiers += char
            index += 1
            continue
        brace = _BRACE.match(keys, index) if (char == "{") else None
        if brace is not None:
            actions.extend(_Wrap(modifiers, _BraceActions(brace[1])))
            index = brace.end()
        else:
            actions.extend(_Wrap(modifiers, _CharActions(char)))
            index += 1
        modifiers = ""
    return actions


def _BraceActions(body: str) -> list[KeyAction]:
    if body.lower() in _IGNORED_DIRECTIVES:
        return []
    match = _BRACE_BODY.match(body.strip()) if (len(body) > 1) else None
    if match is None:
        return _CharActions(body)
    name, arg = match["name"], (match["arg"] or "").lower()
    key = KeyCodes.GetKeyCode(name)
    if key is None:
        if len(name) == 1:
            return _WithArg(_CharActions(name), arg)
        raise ValueError(f"Unknown key name in Send: {{{body}}}")
    return _WithArg([KeyAction(key)], arg)


def _WithArg(actions: list[KeyAction], arg: str) -> list[KeyAction]:
    if arg == "":
        return actions
    if arg in ("down", "downr", "downtemp"):
        return [KeyAction(action.key, DOWN, action.char) for action in actions]
    if arg == "up":
        return [KeyAction(action.key, UP, action.char) for action in actions]
    if arg.isdigit():
        return actions * int(arg)
    raise ValueError(f"Unknown Send key argument: {arg}")


def _CharActions(char: str) -> list[KeyAction]:
    resolved = KeyCodes.CharKey(char)
    if resolved is None:
        return [KeyAction(KeyCode(0), PRESS, char)]
    key, modifiers = resolved
    return _Wrap(modifiers, [KeyAction(key)])


def _Wrap(modifiers: str, actions: list[KeyAction]) -> list[KeyAction]:
    if (not modifiers) or (not actions):
        return actions
    held = [KeyCode(KeyCodes.MODIFIER_SEND_VK[symbol], 0, symbol == "#") for symbol in modifiers]
    downs = [KeyAction(key, DOWN) for key in held]
    ups = [KeyAction(key, UP) for key in reversed(held)]
    return downs + actions + ups


def Send(keys: str) -> None:
    for action in ParseSend(keys):
        _Perform(action)


def _Perform(action: KeyAction) -> None:
    if action.key.vk in KeyCodes.WHEEL_VKS:
        _SendWheelNotches(action.key.vk, 1)
        return
    if action.key.isMouse:
        _PerformButton(action.key.vk, action.kind)
        return
    if action.kind != UP:
        _SendKey(action, up=False)
        if action.kind == PRESS:
            _Delay("press")
    if action.kind != DOWN:
        _SendKey(action, up=True)
    _Delay("key")


def _PerformButton(vk: int, kind: str) -> None:
    if kind != UP:
        _SendInputs(_ButtonInput(vk, up=False))
        with _heldLock:
            _heldButtons.add(vk)
        if kind == PRESS:
            _Delay("mouse")
    if kind != DOWN:
        _SendInputs(_ButtonInput(vk, up=True))
        with _heldLock:
            _heldButtons.discard(vk)
    _Delay("mouse")


# Keys and buttons this process sent down and not up yet. A stop can land on the wait between the two
# (or a macro held one on purpose), and Windows never lets go of an injected key by itself.
_heldLock = threading.Lock()
_heldKeys: dict[int, KeyAction] = {}
_heldButtons: set[int] = set()


def ReleaseHeldInputs() -> int:
    """Sends the up of every key and mouse button still held down by this process; returns how many."""
    with _heldLock:
        keys = list(_heldKeys.values())
        buttons = list(_heldButtons)
        _heldKeys.clear()
        _heldButtons.clear()
    for action in keys:
        _SendKey(action, up=True)
    for vk in buttons:
        _SendInputs(_ButtonInput(vk, up=True))
    return len(keys) + len(buttons)


def _Delay(kind: str) -> None:
    if _delays[kind] >= 0:
        Sleep(_delays[kind])


def _SendKey(action: KeyAction, up: bool) -> None:
    event = api.INPUT(type=api.INPUT_KEYBOARD)
    if action.char:
        event.u.ki = api.KEYBDINPUT(0, ord(action.char), KEYEVENTF_UNICODE | (KEYEVENTF_KEYUP if up else 0), 0, 0)
    else:
        flags = (KEYEVENTF_KEYUP if up else 0) | (KEYEVENTF_EXTENDEDKEY if action.key.isExtended else 0)
        event.u.ki = api.KEYBDINPUT(action.key.vk, KeyCodes.ScanCode(action.key), flags, 0, 0)
    _SendInputs(event)
    if not action.char:
        with _heldLock:
            if up:
                _heldKeys.pop(action.key.vk, None)
            else:
                _heldKeys[action.key.vk] = action


def TapKey(key: KeyCode) -> None:
    """Down and up with no delay: the hook's replay of a prefix key's native press and its menu mask."""
    if key.isMouse:
        _SendInputs(_ButtonInput(key.vk, up=False))
        _SendInputs(_ButtonInput(key.vk, up=True))
        return
    _SendKey(KeyAction(key), up=False)
    _SendKey(KeyAction(key), up=True)


def _ButtonInput(vk: int, up: bool) -> api.INPUT:
    downFlag, upFlag, data = MOUSE_BUTTON_FLAGS[vk]
    event = api.INPUT(type=api.INPUT_MOUSE)
    event.u.mi = api.MOUSEINPUT(0, 0, data, upFlag if up else downFlag, 0, 0)
    return event


def _SendWheelNotches(vk: int, notches: int) -> None:
    for _ in range(notches):
        _SendInputs(_WheelInput(vk))
        _Delay("wheel")


def _WheelInput(vk: int) -> api.INPUT:
    flag, sign = WHEEL_FLAGS[vk]
    event = api.INPUT(type=api.INPUT_MOUSE)
    event.u.mi = api.MOUSEINPUT(0, 0, ctypes.c_uint32(sign * WHEEL_DELTA).value, flag, 0, 0)
    return event


def _SendInputs(event: api.INPUT) -> None:
    api.SendInput(1, ctypes.byref(event), ctypes.sizeof(api.INPUT))


# ---- mouse ----


def _ClientOrigin() -> tuple[int, int]:
    hwnd = api.GetForegroundWindow()
    point = wintypes.POINT(0, 0)
    if hwnd:
        api.ClientToScreen(hwnd, ctypes.byref(point))
    return point.x, point.y


def MouseGetPos() -> tuple[int, int]:
    """The cursor position in client coordinates of the active window (CoordMode Client)."""
    point = wintypes.POINT()
    api.GetCursorPos(ctypes.byref(point))
    originX, originY = _ClientOrigin()
    return (point.x - originX), (point.y - originY)


def _ScreenCursor() -> tuple[int, int]:
    point = wintypes.POINT()
    api.GetCursorPos(ctypes.byref(point))
    return point.x, point.y


def _AbsoluteMove(screenX: int, screenY: int) -> None:
    left = api.GetSystemMetrics(SM_XVIRTUALSCREEN)
    top = api.GetSystemMetrics(SM_YVIRTUALSCREEN)
    width = max(1, api.GetSystemMetrics(SM_CXVIRTUALSCREEN))
    height = max(1, api.GetSystemMetrics(SM_CYVIRTUALSCREEN))
    # Rounded up so Windows' truncating back-conversion lands on the exact pixel.
    normalX = (((screenX - left) * 65536) + width - 1) // width
    normalY = (((screenY - top) * 65536) + height - 1) // height
    event = api.INPUT(type=api.INPUT_MOUSE)
    flags = MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_VIRTUALDESK
    event.u.mi = api.MOUSEINPUT(normalX, normalY, 0, flags, 0, 0)
    _SendInputs(event)


def _WindowDiagonal() -> float:
    hwnd = api.GetForegroundWindow()
    rect = wintypes.RECT()
    if hwnd and api.GetClientRect(hwnd, ctypes.byref(rect)) and (rect.right > 0) and (rect.bottom > 0):
        return math.hypot(rect.right, rect.bottom)
    return math.hypot(api.GetSystemMetrics(SM_CXSCREEN), api.GetSystemMetrics(SM_CYSCREEN))


def MouseMove(x: float, y: float, speed: int | None = None) -> None:
    if speed is None:
        speed = _Pick("speed")
    originX, originY = _ClientOrigin()
    # AHK MouseMove truncates float coordinates (GetGameCenter() halves the client size).
    target = ((int(x) + originX), (int(y) + originY))
    start = _ScreenCursor()
    durationMs = MouseMotion.DurationMs(start, target, speed, _WindowDiagonal())
    if durationMs > 0:
        _Glide(start, target, durationMs)
    _AbsoluteMove(*target)
    _Delay("mouse")


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


def MouseClick(button: str = "left", x: int | None = None, y: int | None = None, count: int = 1,
                speed: int | None = None) -> None:
    if (x is not None) and (y is not None):
        MouseMove(x, y, speed)
    vk = KeyCodes.MOUSE_VKS[CLICK_BUTTONS.get(button.lower(), button.lower())]
    if vk in KeyCodes.WHEEL_VKS:
        _SendWheelNotches(vk, count)
        return
    for _ in range(count):
        _PerformButton(vk, PRESS)


def MouseEventMove(dx: int, dy: int) -> None:
    """DllCall("mouse_event", "UInt", 0x01, "Int", dx, "Int", dy): a raw relative move for camera turns."""
    api.mouseEvent(MOUSEEVENTF_MOVE, dx, dy, 0, 0)


# ---- key state ----


def GetKeyState(name: str, mode: str = "") -> bool:
    """GetKeyState(name, mode): "P" physical (hook state when the hotkey hook runs), "T" toggle, "" logical."""
    key = KeyCodes.GetKeyCode(name)
    if key is None:
        raise ValueError(f"Unknown key name: {name}")
    mode = mode.upper()
    if mode == "T":
        return (api.GetKeyState(key.vk) & 1) != 0
    if mode == "P":
        # Imported here: hotkeys imports this module to replay native key presses.
        from yorha import Hotkeys
        physical = Hotkeys.PhysicalKeyDown(key)
        if physical is not None:
            return physical
    return (api.GetAsyncKeyState(key.vk) & 0x8000) != 0
