"""ControlSend, ControlSendText and ControlClick: keys and clicks posted as window messages, so the target
does not need to be in front. Games that read raw input ignore them; launchers and ordinary windows do not."""

from __future__ import annotations

import ctypes
import re
from ctypes import wintypes

from yorha import Input, KeyCodes
from yorha import Win32Api as api
from yorha.Errors import TargetError
from yorha.SendParser import CLICK, DOWN, DOWN_KINDS, PRESS, UP, KeyAction, ParseSend
from yorha.Timing import Sleep
from yorha.Window import RequireWindow

WM_KEYDOWN = 0x0100
WM_KEYUP = 0x0101
WM_CHAR = 0x0102
WM_SYSKEYDOWN = 0x0104
WM_SYSKEYUP = 0x0105
WM_MOUSEWHEEL = 0x020A
WM_MOUSEHWHEEL = 0x020E
CWP_SKIPINVISIBLE = 0x0001
WHEEL_DELTA = 120
# lParam bits of a key message
KEY_EXTENDED_BIT = 1 << 24
KEY_ALT_CONTEXT_BIT = 1 << 29
KEY_RELEASE_BITS = (1 << 30) | (1 << 31)
ALT_VKS = frozenset((KeyCodes.VK_MENU, 0xA4, 0xA5))
# button vk -> (down message, up message, wParam key flag, XBUTTON number)
BUTTON_MESSAGES = {
    0x01: (0x0201, 0x0202, 0x0001, 0), 0x02: (0x0204, 0x0205, 0x0002, 0), 0x04: (0x0207, 0x0208, 0x0010, 0),
    0x05: (0x020B, 0x020C, 0x0020, 1), 0x06: (0x020B, 0x020C, 0x0040, 2),
}
# wheel vk -> (message, notch sign)
WHEEL_MESSAGES = {0x9F: (WM_MOUSEWHEEL, 1), 0x9E: (WM_MOUSEWHEEL, -1), 0x9D: (WM_MOUSEHWHEEL, 1),
                  0x9C: (WM_MOUSEHWHEEL, -1)}
CONTROL_CLICK_BUTTONS = {"left": "lbutton", "l": "lbutton", "right": "rbutton", "r": "rbutton", "middle": "mbutton",
                         "m": "mbutton", "x1": "xbutton1", "x2": "xbutton2", "wheelup": "wheelup", "wu": "wheelup",
                         "wheeldown": "wheeldown", "wd": "wheeldown", "wheelleft": "wheelleft", "wl": "wheelleft",
                         "wheelright": "wheelright", "wr": "wheelright"}

_POSITION = re.compile(r"^\s*x\s*(-?\d+)\s+y\s*(-?\d+)\s*$", re.IGNORECASE)
_CLICK_OPTION = re.compile(r"\b(NA|Pos|D|U|X\s*-?\d+|Y\s*-?\d+)\b", re.IGNORECASE)
_CLASS_NN = re.compile(r"^(.+?)(\d+)$")
# AHK's defaults: SetControlDelay 20; ControlSend follows SetKeyDelay's Event delays
_settings = {"control_delay": 20}


def SetControlDelay(delay: int) -> None:
    _settings["control_delay"] = delay


# ---- finding the control ----


def _Children(hwnd: int) -> list[int]:
    found: list[int] = []

    def Collect(child, _param):
        found.append(child)
        return True

    api.EnumChildWindows(hwnd, api.WNDENUMPROC(Collect), 0)
    return found


def _ClassName(hwnd: int) -> str:
    buffer = ctypes.create_unicode_buffer(256)
    api.GetClassNameW(hwnd, buffer, len(buffer))
    return buffer.value


def _Text(hwnd: int) -> str:
    buffer = ctypes.create_unicode_buffer(api.GetWindowTextLengthW(hwnd) + 1)
    api.GetWindowTextW(hwnd, buffer, len(buffer))
    return buffer.value


def _ByClassNN(children: list[int], classNN: str) -> int:
    match = _CLASS_NN.match(classNN)
    if match is None:
        return 0
    wantedClass, wantedNumber = match[1], int(match[2])
    seen = 0
    for child in children:
        if _ClassName(child) == wantedClass:
            seen += 1
            if seen == wantedNumber:
                return child
    return 0


def FindControl(control: str | int, winTitle: str | int = "") -> int:
    """The control's HWND: an HWND, a ClassNN ("Edit1"), or text the control's text contains. An omitted
    control is the window itself."""
    window = RequireWindow(winTitle)
    if isinstance(control, int):
        if not api.IsWindow(control):
            raise TargetError(f"Target control not found: {control}")
        return control
    if control == "":
        return window
    children = _Children(window)
    found = _ByClassNN(children, control) or next((child for child in children if control in _Text(child)), 0)
    if not found:
        raise TargetError(f"Target control not found: {control}")
    return found


# ---- ControlSend ----


def ControlSend(keys: str, control: str | int = "", winTitle: str | int = "") -> None:
    """ControlSend(Keys, Control, WinTitle): posts WM_KEYDOWN/WM_KEYUP (WM_SYS* while Alt is down), and
    WM_CHAR for a character the layout has no key for. Mouse keys and {Click} are not supported."""
    _PostKeys(FindControl(control, winTitle), ParseSend(keys))


def ControlSendText(text: str, control: str | int = "", winTitle: str | int = "") -> None:
    """ControlSend in Text mode: every character a WM_CHAR, but `r `n `t `b as keys."""
    _PostKeys(FindControl(control, winTitle), ParseSend("{Text}" + text))


def _PostKeys(hwnd: int, actions: list[KeyAction]) -> None:
    altDown = False
    for action in actions:
        if (action.kind == CLICK) or action.key.isMouse:
            raise ValueError("ControlSend does not send mouse buttons")
        if action.char:
            for unit in Input.Utf16Units(action.char):
                api.PostMessageW(hwnd, WM_CHAR, ord(unit), 1)
        else:
            if action.key.vk in ALT_VKS:
                altDown = action.kind in DOWN_KINDS
            _PostKey(hwnd, action, altDown)
        Input.Delay("key")


def _PostKey(hwnd: int, action: KeyAction, altDown: bool) -> None:
    key = action.key
    lParam = 1 | (KeyCodes.ScanCode(key) << 16) | (KEY_EXTENDED_BIT if key.isExtended else 0)
    system = altDown or (key.vk in ALT_VKS)
    if action.kind != UP:
        api.PostMessageW(hwnd, WM_SYSKEYDOWN if system else WM_KEYDOWN, key.vk,
                         lParam | (KEY_ALT_CONTEXT_BIT if altDown else 0))
        if action.kind == PRESS:
            Input.Delay("press")
    if action.kind not in DOWN_KINDS:
        released = altDown and (key.vk not in ALT_VKS)
        api.PostMessageW(hwnd, WM_SYSKEYUP if system else WM_KEYUP, key.vk,
                         lParam | KEY_RELEASE_BITS | (KEY_ALT_CONTEXT_BIT if released else 0))


# ---- ControlClick ----


def _ClickOptions(options: str) -> dict[str, object]:
    parsed: dict[str, object] = {"na": False, "pos": False, "kind": PRESS, "x": None, "y": None}
    for word in _CLICK_OPTION.findall(options):
        lowered = word.lower().replace(" ", "")
        if lowered in ("na", "pos"):
            parsed[lowered] = True
        elif lowered == "d":
            parsed["kind"] = DOWN
        elif lowered == "u":
            parsed["kind"] = UP
        else:
            parsed[lowered[0]] = int(lowered[1:])
    return parsed


def _ClientSize(hwnd: int) -> tuple[int, int]:
    rect = wintypes.RECT()
    api.GetClientRect(hwnd, ctypes.byref(rect))
    return rect.right, rect.bottom


def _TargetAndPoint(controlOrPos: str | int, winTitle: str | int, options: dict) -> tuple[int, int, int]:
    """(hwnd, x, y): the control and the point in its client area the click lands on."""
    position = _POSITION.match(controlOrPos) if isinstance(controlOrPos, str) else None
    if (position is not None) and (options["pos"] or not _ControlExists(controlOrPos, winTitle)):
        window = RequireWindow(winTitle)
        x, y = int(position[1]), int(position[2])
        child = api.ChildWindowFromPointEx(window, wintypes.POINT(x, y), CWP_SKIPINVISIBLE) or window
        point = wintypes.POINT(x, y)
        if child != window:
            api.ClientToScreen(window, ctypes.byref(point))
            api.ScreenToClient(child, ctypes.byref(point))
        return child, point.x, point.y
    hwnd = RequireWindow(winTitle) if (controlOrPos == "") else FindControl(controlOrPos, winTitle)
    width, height = _ClientSize(hwnd)
    x = (width // 2) if (options["x"] is None) else options["x"]
    y = (height // 2) if (options["y"] is None) else options["y"]
    return hwnd, x, y


def _ControlExists(control: str, winTitle: str | int) -> bool:
    try:
        FindControl(control, winTitle)
    except TargetError:
        return False
    return True


def ControlClick(controlOrPos: str | int = "", winTitle: str | int = "", winText: str = "", whichButton: str = "left",
                 clickCount: int = 1, options: str = "") -> None:
    """ControlClick(Control-or-Pos, WinTitle, WinText, WhichButton, ClickCount, Options): posts the button
    messages to the control. "X# Y#" coordinates count from the window's client area and click the control
    under them; options NA, D, U, Pos, X#, Y# (X#/Y# from the control's corner, its centre by default)."""
    if winText:
        raise ValueError("ControlClick does not support WinText")
    parsed = _ClickOptions(options)
    hwnd, x, y = _TargetAndPoint(controlOrPos, winTitle, parsed)
    vk = KeyCodes.MOUSE_VKS[CONTROL_CLICK_BUTTONS.get(whichButton.lower(), whichButton.lower())]
    if vk in WHEEL_MESSAGES:
        _PostWheel(hwnd, vk, x, y, clickCount)
        return
    for _ in range(clickCount):
        _PostButton(hwnd, vk, x, y, parsed["kind"])


def _PointParam(x: int, y: int) -> int:
    return (x & 0xFFFF) | ((y & 0xFFFF) << 16)


def _ControlDelay() -> None:
    if _settings["control_delay"] >= 0:
        Sleep(_settings["control_delay"])


def _PostButton(hwnd: int, vk: int, x: int, y: int, kind: str) -> None:
    downMessage, upMessage, keyFlag, xButton = BUTTON_MESSAGES[vk]
    lParam = _PointParam(x, y)
    if kind != UP:
        api.PostMessageW(hwnd, downMessage, keyFlag | (xButton << 16), lParam)
        _ControlDelay()
    if kind == DOWN:
        return
    api.PostMessageW(hwnd, upMessage, xButton << 16, lParam)
    _ControlDelay()


def _PostWheel(hwnd: int, vk: int, x: int, y: int, notches: int) -> None:
    message, sign = WHEEL_MESSAGES[vk]
    # wheel messages carry screen coordinates
    point = wintypes.POINT(x, y)
    api.ClientToScreen(hwnd, ctypes.byref(point))
    for _ in range(notches):
        api.PostMessageW(hwnd, message, (ctypes.c_uint16(sign * WHEEL_DELTA).value << 16), _PointParam(point.x, point.y))
        _ControlDelay()
