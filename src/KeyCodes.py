"""AHK key names to virtual keys and scan codes, shared by Send, GetKeyState and the hotkey hook."""

from __future__ import annotations

import re
from dataclasses import dataclass

from yorha import Win32Api as api

MAPVK_VK_TO_VSC = 0
MAPVK_VK_TO_CHAR = 2
MAPVK_VSC_TO_VK_EX = 3
MAPVK_VK_TO_VSC_EX = 4
EXTENDED_SCAN_FLAG = 0x100
# MapVirtualKey's VSC_EX marks an extended scan code with one of these prefixes in its high byte
EXTENDED_PREFIXES = (0xE0, 0xE1)

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
# The sided modifier vks a key state query can report down, with the symbol each stands for.
SIDED_MODIFIER_SYMBOLS = {0xA0: "+", 0xA1: "+", 0xA2: "^", 0xA3: "^", 0xA4: "!", 0xA5: "!", VK_LWIN: "#", VK_RWIN: "#"}

# Mouse names in the spelling GetKeyName returns.
MOUSE_KEY_NAMES = {
    "LButton": 0x01, "RButton": 0x02, "MButton": 0x04, "XButton1": 0x05, "XButton2": 0x06,
    "WheelDown": 0x9E, "WheelUp": 0x9F, "WheelLeft": 0x9C, "WheelRight": 0x9D,
}
MOUSE_VKS = {name.lower(): vk for name, vk in MOUSE_KEY_NAMES.items()}
WHEEL_VKS = frozenset((0x9C, 0x9D, 0x9E, 0x9F))

# AHK key name -> (vk, extended); extended None = either. The first name of each key is the one GetKeyName
# returns. automaton_gui.framework.Hotkeys has the GUI's own copy on purpose: Yorha depends on no GUI, and
# the GUI depends on no Yorha.
_KEY_NAMES: tuple[tuple[str, int, bool | None], ...] = (
    ("Space", 0x20, None), ("Tab", 0x09, None), ("Enter", 0x0D, False), ("Escape", 0x1B, None),
    ("Backspace", 0x08, None), ("CapsLock", 0x14, None), ("ScrollLock", 0x91, None), ("Pause", 0x13, None),
    ("Insert", 0x2D, True), ("Delete", 0x2E, True), ("Home", 0x24, True), ("End", 0x23, True),
    ("PgUp", 0x21, True), ("PgDn", 0x22, True), ("Up", 0x26, True), ("Down", 0x28, True),
    ("Left", 0x25, True), ("Right", 0x27, True),
    ("NumpadIns", 0x2D, False), ("NumpadDel", 0x2E, False), ("NumpadHome", 0x24, False),
    ("NumpadEnd", 0x23, False), ("NumpadPgUp", 0x21, False), ("NumpadPgDn", 0x22, False),
    ("NumpadUp", 0x26, False), ("NumpadDown", 0x28, False), ("NumpadLeft", 0x25, False),
    ("NumpadRight", 0x27, False), ("NumpadClear", 0x0C, False),
    ("NumpadMult", 0x6A, None), ("NumpadAdd", 0x6B, None), ("NumpadSub", 0x6D, None), ("NumpadDot", 0x6E, None),
    ("NumpadDiv", 0x6F, True), ("NumpadEnter", 0x0D, True), ("NumLock", 0x90, True),
    ("PrintScreen", 0x2C, True), ("AppsKey", 0x5D, True), ("CtrlBreak", 0x03, None), ("Help", 0x2F, None),
    ("Sleep", 0x5F, None),
    ("Shift", VK_SHIFT, None), ("LShift", 0xA0, False), ("RShift", 0xA1, False),
    ("Control", VK_CONTROL, None), ("LControl", 0xA2, False), ("RControl", 0xA3, True),
    ("Alt", VK_MENU, None), ("LAlt", 0xA4, False), ("RAlt", 0xA5, True),
    ("LWin", VK_LWIN, True), ("RWin", VK_RWIN, True),
    ("Volume_Down", 0xAE, None), ("Volume_Up", 0xAF, None), ("Volume_Mute", 0xAD, None),
    ("Media_Next", 0xB0, None), ("Media_Prev", 0xB1, None), ("Media_Stop", 0xB2, None),
    ("Media_Play_Pause", 0xB3, None), ("Launch_Mail", 0xB4, None), ("Launch_Media", 0xB5, None),
    ("Launch_App1", 0xB6, None), ("Launch_App2", 0xB7, None), ("Browser_Back", 0xA6, None),
    ("Browser_Forward", 0xA7, None), ("Browser_Refresh", 0xA8, None), ("Browser_Stop", 0xA9, None),
    ("Browser_Search", 0xAA, None), ("Browser_Favorites", 0xAB, None), ("Browser_Home", 0xAC, None),
    *((chr(letter).lower(), letter, None) for letter in range(ord("A"), ord("Z") + 1)),
    *((str(digit), ord("0") + digit, None) for digit in range(10)),
    *((f"Numpad{digit}", 0x60 + digit, None) for digit in range(10)),
    *((f"F{number}", 0x6F + number, None) for number in range(1, 25)),
)
_ALIASES: dict[str, tuple[int, bool | None]] = {
    "esc": (0x1B, None), "return": (0x0D, False), "ins": (0x2D, True), "del": (0x2E, True), "bs": (0x08, None),
    "ctrl": (VK_CONTROL, None), "lctrl": (0xA2, False), "rctrl": (0xA3, True),
}
_NAMED_KEYS = {name.lower(): (vk, extended) for name, vk, extended in _KEY_NAMES}
_CANONICAL_NAMES: dict[tuple[int, bool | None], str] = {}
for _name, _vk, _extended in _KEY_NAMES:
    _CANONICAL_NAMES.setdefault((_vk, _extended), _name)
_MOUSE_NAMES_BY_VK = {vk: name for name, vk in MOUSE_KEY_NAMES.items()}
_EXTENDED_VKS = frozenset((0x21, 0x22, 0x23, 0x24, 0x25, 0x26, 0x27, 0x28, 0x2C, 0x2D, 0x2E, 0x5B, 0x5C, 0x5D,
                           0x6F, 0x90, 0xA3, 0xA5))
# Keys whose scan code MapVirtualKey reports wrong: it gives PrintScreen Alt+SysRq's and Pause Ctrl+NumLock's.
_SPECIAL_SCAN_CODES = {0x2C: 0x137, 0x13: 0x045, 0x03: 0x146}
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
    if len(name) == 1:
        resolved = _LayoutCharKey(name)
        return None if (resolved is None) else resolved[0]
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


def Matches(key: KeyCode, vk: int, extended: bool) -> bool:
    """Whether a hook event (vk, extended flag) is `key`."""
    if vk not in MatchingVks(key):
        return False
    return (key.extended is None) or (key.extended == extended)


# ---- GetKeyName, GetKeyVK, GetKeySC ----


def KeyName(key: KeyCode) -> str:
    """The AHK name of `key`: its canonical spelling, the character it types on the layout, or vkXX."""
    if key.isMouse:
        return _MOUSE_NAMES_BY_VK[key.vk]
    extended = key.isExtended if ((key.vk, key.isExtended) in _CANONICAL_NAMES) else None
    name = _CANONICAL_NAMES.get((key.vk, extended))
    if name is not None:
        return name
    char = api.MapVirtualKeyW(key.vk, MAPVK_VK_TO_CHAR) & 0xFFFF
    if char:
        return chr(char).lower()
    return f"vk{key.vk:02X}"


def KeyScanCode(key: KeyCode) -> int:
    """The AHK scan code of `key`: 0x100 added for an extended key."""
    if key.sc:
        return key.sc
    if key.vk in _SPECIAL_SCAN_CODES:
        return _SPECIAL_SCAN_CODES[key.vk]
    mapped = api.MapVirtualKeyW(key.vk, MAPVK_VK_TO_VSC_EX)
    extended = key.isExtended or ((mapped >> 8) in EXTENDED_PREFIXES)
    return (mapped & 0xFF) | (EXTENDED_SCAN_FLAG if extended else 0)


def GetKeyName(name: str) -> str:
    """GetKeyName(key): "" for an unknown key name."""
    key = GetKeyCode(name)
    return "" if (key is None) else KeyName(key)


def GetKeyVK(name: str) -> int:
    """GetKeyVK(key): 0 for an unknown key name."""
    key = GetKeyCode(name)
    return 0 if (key is None) else key.vk


def GetKeySC(name: str) -> int:
    """GetKeySC(key): 0 for an unknown key name or a mouse button, 0x100 added for an extended key."""
    key = GetKeyCode(name)
    if (key is None) or key.isMouse:
        return 0
    return KeyScanCode(key)
