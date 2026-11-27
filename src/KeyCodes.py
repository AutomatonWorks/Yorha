"""AHK key names to virtual keys and scan codes, shared by Send, GetKeyState and the hotkey hook."""

from __future__ import annotations

import re
from dataclasses import dataclass

from yorha import Win32Api as api

MAPVK_VK_TO_VSC = 0
MAPVK_VSC_TO_VK_EX = 3
EXTENDED_SCAN_FLAG = 0x100

VK_SHIFT = 0x10
VK_CONTROL = 0x11
VK_MENU = 0x12
VK_LWIN = 0x5B
VK_RWIN = 0x5C
# The LL hook reports sided modifiers; a generic name matches either side.
SIDED_MODIFIERS = {VK_SHIFT: (0xA0, 0xA1), VK_CONTROL: (0xA2, 0xA3), VK_MENU: (0xA4, 0xA5)}
MODIFIER_VKS = {
    "^": (VK_CONTROL, 0xA2, 0xA3),
    "!": (VK_MENU, 0xA4, 0xA5),
    "+": (VK_SHIFT, 0xA0, 0xA1),
    "#": (VK_LWIN, VK_RWIN),
}
MODIFIER_SEND_VK = {"^": VK_CONTROL, "!": VK_MENU, "+": VK_SHIFT, "#": VK_LWIN}

MOUSE_VKS = {
    "lbutton": 0x01, "rbutton": 0x02, "mbutton": 0x04, "xbutton1": 0x05, "xbutton2": 0x06,
    "wheeldown": 0x9E, "wheelup": 0x9F, "wheelleft": 0x9C, "wheelright": 0x9D,
}
WHEEL_VKS = frozenset((0x9C, 0x9D, 0x9E, 0x9F))

# AHK key name -> (vk, extended); extended None = either. automaton_gui.framework.Hotkeys has the GUI's
# own copy on purpose: Yorha depends on no GUI, and the GUI depends on no Yorha.
_NAMED_KEYS: dict[str, tuple[int, bool | None]] = {
    "space": (0x20, None), "tab": (0x09, None), "enter": (0x0D, False), "backspace": (0x08, None),
    "capslock": (0x14, None), "scrolllock": (0x91, None), "pause": (0x13, None),
    "insert": (0x2D, True), "delete": (0x2E, True), "home": (0x24, True), "end": (0x23, True),
    "pgup": (0x21, True), "pgdn": (0x22, True), "up": (0x26, True), "down": (0x28, True),
    "left": (0x25, True), "right": (0x27, True),
    "numpadins": (0x2D, False), "numpaddel": (0x2E, False), "numpadhome": (0x24, False),
    "numpadend": (0x23, False), "numpadpgup": (0x21, False), "numpadpgdn": (0x22, False),
    "numpadup": (0x26, False), "numpaddown": (0x28, False), "numpadleft": (0x25, False),
    "numpadright": (0x27, False), "numpadclear": (0x0C, False),
    "numpadmult": (0x6A, None), "numpadadd": (0x6B, None), "numpadsub": (0x6D, None), "numpaddot": (0x6E, None),
    "numpaddiv": (0x6F, True), "numpadenter": (0x0D, True), "numlock": (0x90, True),
    "printscreen": (0x2C, True), "appskey": (0x5D, True),
    "volume_down": (0xAE, None), "volume_up": (0xAF, None), "volume_mute": (0xAD, None),
    "media_next": (0xB0, None), "media_prev": (0xB1, None), "media_stop": (0xB2, None),
    "media_play_pause": (0xB3, None), "launch_mail": (0xB4, None), "launch_media": (0xB5, None),
    "launch_app1": (0xB6, None), "launch_app2": (0xB7, None), "browser_back": (0xA6, None),
    "browser_forward": (0xA7, None), "browser_refresh": (0xA8, None), "browser_stop": (0xA9, None),
    "browser_search": (0xAA, None), "browser_favorites": (0xAB, None), "browser_home": (0xAC, None),
    **{chr(letter).lower(): (letter, None) for letter in range(ord("A"), ord("Z") + 1)},
    **{str(digit): (ord("0") + digit, None) for digit in range(10)},
    **{f"numpad{digit}": (0x60 + digit, None) for digit in range(10)},
    **{f"f{number}": (0x6F + number, None) for number in range(1, 25)},
}
_ALIASES: dict[str, tuple[int, bool | None]] = {
    "esc": (0x1B, None), "escape": (0x1B, None), "return": (0x0D, False),
    "ins": (0x2D, True), "del": (0x2E, True), "bs": (0x08, None),
    "shift": (VK_SHIFT, None), "lshift": (0xA0, False), "rshift": (0xA1, False),
    "ctrl": (VK_CONTROL, None), "control": (VK_CONTROL, None),
    "lctrl": (0xA2, False), "lcontrol": (0xA2, False), "rctrl": (0xA3, True), "rcontrol": (0xA3, True),
    "alt": (VK_MENU, None), "lalt": (0xA4, False), "ralt": (0xA5, True),
    "lwin": (VK_LWIN, True), "rwin": (VK_RWIN, True), "sleep": (0x5F, None),
}
_EXTENDED_VKS = frozenset((0x21, 0x22, 0x23, 0x24, 0x25, 0x26, 0x27, 0x28, 0x2C, 0x2D, 0x2E, 0x5B, 0x5C, 0x5D,
                           0x6F, 0x90, 0xA3, 0xA5))
_VK_SC = re.compile(r"^(?:vk([0-9a-f]{1,2}))?(?:sc([0-9a-f]{1,3}))?$", re.IGNORECASE)


@dataclass(frozen=True)
class KeyCode:
    vk: int
    sc: int = 0
    extended: bool | None = None

    @property
    def isMouse(self) -> bool:
        return self.vk in MOUSE_VKS.values()

    @property
    def isExtended(self) -> bool:
        if self.extended is None:
            return (self.sc & EXTENDED_SCAN_FLAG) != 0
        return self.extended


def GetKeyCode(name: str) -> KeyCode | None:
    """The key an AHK key name stands for, or None when the name is unknown."""
    lowered = name.lower()
    if lowered in MOUSE_VKS:
        return KeyCode(MOUSE_VKS[lowered])
    entry = _ALIASES.get(lowered) or _NAMED_KEYS.get(lowered)
    if entry is not None:
        return KeyCode(entry[0], 0, entry[1])
    return _RawKeyCode(name)


def _RawKeyCode(name: str) -> KeyCode | None:
    match = _VK_SC.match(name)
    if (match is None) or not (match[1] or match[2]):
        return None
    vk = int(match[1], 16) if match[1] else 0
    sc = int(match[2], 16) if match[2] else 0
    if sc:
        return KeyCode(vk or api.MapVirtualKeyW(sc, MAPVK_VSC_TO_VK_EX), sc, (sc & EXTENDED_SCAN_FLAG) != 0)
    return KeyCode(vk, 0, vk in _EXTENDED_VKS)


def ScanCode(key: KeyCode) -> int:
    """The 8-bit scan code SendInput needs for `key`."""
    if key.sc:
        return key.sc & 0xFF
    return api.MapVirtualKeyW(key.vk, MAPVK_VK_TO_VSC) & 0xFF


def CharKey(char: str) -> tuple[KeyCode, str] | None:
    """The key and modifier symbols that type `char` on the current layout, None when it has none."""
    if char == "\n":
        return KeyCode(0x0D, 0, False), ""
    if char == "\t":
        return KeyCode(0x09), ""
    if char == " ":
        return KeyCode(0x20), ""
    if char.isascii() and char.isalpha():
        return KeyCode(ord(char.upper())), ("+" if char.isupper() else "")
    if char.isascii() and char.isdigit():
        return KeyCode(ord(char)), ""
    return _LayoutCharKey(char)


def _LayoutCharKey(char: str) -> tuple[KeyCode, str] | None:
    result = api.VkKeyScanW(char)
    if result == -1:
        return None
    vk = result & 0xFF
    shiftState = (result >> 8) & 0xFF
    modifiers = ("+" if (shiftState & 1) else "") + ("^" if (shiftState & 2) else "") + (
        "!" if (shiftState & 4) else "")
    return KeyCode(vk), modifiers


def MatchingVks(key: KeyCode) -> frozenset[int]:
    """Every vk the LL hook may report for `key` (a generic modifier matches both sides)."""
    return frozenset((key.vk, *SIDED_MODIFIERS.get(key.vk, ())))
