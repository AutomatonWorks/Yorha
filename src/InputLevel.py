"""SendLevel's mark on generated input: the dwExtraInfo AHK puts on its own events, so AHK scripts and this
package's hook tell generated input apart from real input the same way."""

from __future__ import annotations

# AHK's keyboard_mouse.h: KEY_IGNORE, then KEY_IGNORE_LEVEL(L) = KEY_IGNORE_ALL_EXCEPT_MODIFIER - L
KEY_IGNORE = 0xFFC3D44F
KEY_IGNORE_ALL_EXCEPT_MODIFIER = KEY_IGNORE - 2
MAX_SEND_LEVEL = 100
KEY_IGNORE_MIN = KEY_IGNORE_ALL_EXCEPT_MODIFIER - MAX_SEND_LEVEL
# AHK's highest mark (KEY_BLOCK_THIS) sits just above KEY_IGNORE
KEY_IGNORE_MAX = KEY_IGNORE + 1


def ExtraInfo(level: int) -> int:
    return KEY_IGNORE_ALL_EXCEPT_MODIFIER - level


def LevelOf(extraInfo: int) -> int | None:
    """The send level of an injected event an AHK-style sender marked, or None for one nobody marked."""
    if not (KEY_IGNORE_MIN <= extraInfo <= KEY_IGNORE_MAX):
        return None
    return max(0, KEY_IGNORE_ALL_EXCEPT_MODIFIER - extraInfo)
