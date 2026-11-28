"""GetKeyState and KeyWait: logical, physical (the hook's view) and toggle state of keys and mouse buttons."""

from __future__ import annotations

import re

from yorha import KeyCodes
from yorha import Win32Api as api
from yorha.KeyCodes import KeyCode
from yorha.Timing import Sleep, TickCount

# AHK's KeyWait checks about every 10 ms
KEY_WAIT_POLL_MS = 10
_KEY_WAIT_OPTION = re.compile(r"([DLT])\s*(\d*\.?\d*)", re.IGNORECASE)


def _Key(name: str) -> KeyCode:
    key = KeyCodes.GetKeyCode(name)
    if key is None:
        raise ValueError(f"Unknown key name: {name}")
    return key


def _IsDown(key: KeyCode, physical: bool) -> bool:
    if physical:
        # Imported here: the hotkey module imports the input module this one sits next to.
        from yorha import Hotkeys
        state = Hotkeys.PhysicalKeyDown(key)
        if state is not None:
            return state
    return (api.GetAsyncKeyState(key.vk) & 0x8000) != 0


def GetKeyState(name: str, mode: str = "") -> bool:
    """GetKeyState(name, mode): "P" physical (hook state when the hotkey hook runs), "T" toggle, "" logical."""
    key = _Key(name)
    mode = mode.upper()
    if mode == "T":
        return (api.GetKeyState(key.vk) & 1) != 0
    return _IsDown(key, physical=(mode == "P"))


def KeyWait(name: str, options: str = "") -> int:
    """KeyWait(KeyName, Options): waits for the key's release, or with "D" for its press. "L" checks the logical
    state instead of the physical one, "T<seconds>" gives up after that long. Returns 1, or 0 on a timeout."""
    key = _Key(name)
    wantDown, logical, timeoutS = _KeyWaitOptions(options)
    deadline = None if (timeoutS is None) else (TickCount() + (timeoutS * 1000))
    while _IsDown(key, physical=not logical) != wantDown:
        if (deadline is not None) and (TickCount() >= deadline):
            return 0
        Sleep(KEY_WAIT_POLL_MS)
    return 1


def _KeyWaitOptions(options: str) -> tuple[bool, bool, float | None]:
    letters = _KEY_WAIT_OPTION.findall(options)
    timeouts = [number for letter, number in letters if letter.upper() == "T"]
    wantDown = any(letter.upper() == "D" for letter, _number in letters)
    logical = any(letter.upper() == "L" for letter, _number in letters)
    timeoutS = float(timeouts[-1] or 0) if timeouts else None
    return wantDown, logical, timeoutS
