"""InputHook: collects what the user types on the hotkey hook's thread until an end key, a length limit,
a match, a timeout or Stop ends it."""

from __future__ import annotations

import ctypes
import re
import threading
from collections.abc import Callable

from yorha import KeyCodes
from yorha import Win32Api as api
from yorha.KeyCodes import KeyCode
from yorha.Threads import WaitEvent

DEFAULT_LENGTH_LIMIT = 1023
VK_CAPITAL = 0x14
# ToUnicodeEx flag: leave the keyboard state (dead keys) alone, Windows 10 1607 and later
TO_UNICODE_KEEP_STATE = 0x4
# Never hidden by an InputHook, like AHK: modifiers and the lock keys
NEVER_BLOCKED_VKS = frozenset((0x10, 0x11, 0x12, 0xA0, 0xA1, 0xA2, 0xA3, 0xA4, 0xA5, 0x5B, 0x5C, 0x14, 0x90, 0x91))
CTRL_VKS = frozenset((0xA2, 0xA3))
ALT_VKS = frozenset((0xA4, 0xA5))
# EndMods spelling, in AHK's order
END_MOD_SYMBOLS = ((0xA2, "<^"), (0xA3, ">^"), (0xA4, "<!"), (0xA5, ">!"), (0xA0, "<+"), (0xA1, ">+"),
                   (0x5B, "<#"), (0x5C, ">#"))
STOPPED = "Stopped"
MAX = "Max"
TIMEOUT = "Timeout"
MATCH = "Match"
END_KEY = "EndKey"

_OPTION = re.compile(r"([BCMVE*])|([ILT])(\d*\.?\d*)", re.IGNORECASE)
_END_KEY_BRACE = re.compile(r"\{([^}]+|\})\}")
_activeLock = threading.Lock()
_active: list[InputHook] = []
# Only the hook thread touches these. Hidden downs outlive the InputHook that hid them, so the up of an end key
# (or of any key still held when an input ends) is hidden too. Modifiers come from every event fed, this
# process's own sends included, which the hotkey matcher never sees.
_hiddenDowns: set[int] = set()
_heldModifiers: set[int] = set()


def Feed(vk: int, sc: int, extended: bool, up: bool, level: int | None, held: frozenset[int]) -> bool:
    """Runs on the hook thread for each key event; returns whether an InputHook hides it. `level` is the
    SendLevel of AHK-generated input, None for any other."""
    if vk in NEVER_BLOCKED_VKS:
        if up:
            _heldModifiers.discard(vk)
        else:
            _heldModifiers.add(vk)
    if up:
        hidden = vk in _hiddenDowns
        _hiddenDowns.discard(vk)
        return hidden
    with _activeLock:
        hooks = list(_active)
    allHeld = held | _heldModifiers
    hidden = False
    for hook in hooks:
        if (level is None) or (level >= hook.MinSendLevel):
            hidden = hook.HandleKey(vk, sc, extended, allHeld) or hidden
    if hidden:
        _hiddenDowns.add(vk)
    return hidden


def _Dispatch(callback: Callable[[], object]) -> None:
    # Imported here: the hotkey module imports this one to feed it.
    from yorha import Hotkeys
    Hotkeys.Dispatch(callback)


def _CharOf(vk: int, sc: int, held: frozenset[int]) -> str:
    """The text the key types with the modifiers held, on the layout of the window in front."""
    state = (ctypes.c_ubyte * 256)()
    for down in held:
        state[down] = 0x80
    for generic, sides in KeyCodes.SIDED_MODIFIERS.items():
        if held.intersection(sides):
            state[generic] = 0x80
    if api.GetKeyState(VK_CAPITAL) & 1:
        state[VK_CAPITAL] |= 1
    buffer = ctypes.create_unicode_buffer(8)
    layout = api.GetKeyboardLayout(api.GetWindowThreadProcessId(api.GetForegroundWindow(), None))
    count = api.ToUnicodeEx(vk, sc, state, buffer, len(buffer), TO_UNICODE_KEEP_STATE, layout)
    return buffer.value[:count] if (count > 0) else ""


def _EndMods(held: frozenset[int]) -> str:
    return "".join(symbol for vk, symbol in END_MOD_SYMBOLS if vk in held)


def _ParseEndKeys(endKeys: str, byChar: bool) -> tuple[list[KeyCode], set[str]]:
    keys: list[KeyCode] = []
    chars: set[str] = set()
    index = 0
    while index < len(endKeys):
        brace = _END_KEY_BRACE.match(endKeys, index)
        name = brace[1] if brace else endKeys[index]
        index = brace.end() if brace else (index + 1)
        if byChar and (len(name) == 1):
            chars.add(name)
            continue
        key = KeyCodes.GetKeyCode(name)
        if key is None:
            raise ValueError(f"Invalid InputHook end key: {name}")
        keys.append(key)
    return keys, chars


def _ParseMatchList(matchList: str) -> list[str]:
    """Comma-separated phrases; ",," is a literal comma."""
    if matchList == "":
        return []
    marker = "\0"
    return [phrase.replace(marker, ",") for phrase in matchList.replace(",,", marker).split(",")]


class InputHook:
    """InputHook(Options, EndKeys, MatchList). Options: B (Backspace does not undo), C (case-sensitive match),
    I[level] (MinSendLevel, 1 when bare), L<n> (length limit, L0 collects no text), M (Ctrl+A..Z as Chr(1-26)),
    T<seconds>, V (keys stay visible), * (a match anywhere in the input), E (single-character end keys
    match by character)."""

    def __init__(self, options: str = "", endKeys: str = "", matchList: str = "") -> None:
        self.BackspaceIsUndo = True
        self.CaseSensitive = False
        self.FindAnywhere = False
        self.MinSendLevel = 0
        self.Timeout = 0.0
        self.VisibleText = False
        self.VisibleNonText = True
        self.OnEnd: Callable[[InputHook], object] | None = None
        self.OnChar: Callable[[InputHook, str], object] | None = None
        self._lengthLimit = DEFAULT_LENGTH_LIMIT
        self._modified = False
        endByChar = self._ApplyOptions(options)
        self._endKeys, self._endChars = _ParseEndKeys(endKeys, endByChar)
        self._matches = _ParseMatchList(matchList)
        self._lock = threading.Lock()
        self._ended = threading.Event()
        self._timer: threading.Timer | None = None
        self._Reset()
        # AHK: "Stopped" until Start is first called
        self.EndReason = STOPPED
        self._ended.set()

    def _ApplyOptions(self, options: str) -> bool:
        endByChar = False
        for flag, letter, number in _OPTION.findall(options):
            flag, letter = flag.upper(), letter.upper()
            if flag == "B":
                self.BackspaceIsUndo = False
            elif flag == "C":
                self.CaseSensitive = True
            elif flag == "M":
                self._modified = True
            elif flag == "V":
                self.VisibleText = True
            elif flag == "*":
                self.FindAnywhere = True
            elif flag == "E":
                endByChar = True
            elif letter == "I":
                self.MinSendLevel = int(number or 1)
            elif letter == "L":
                self._lengthLimit = int(number or 0)
            elif letter == "T":
                self.Timeout = float(number or 0)
        return endByChar

    def _Reset(self) -> None:
        self.Input = ""
        self.EndKey = ""
        self.EndMods = ""
        self.EndReason = ""
        self.Match = ""
        self.InProgress = False

    # ---- methods ----

    def Start(self) -> None:
        """Starts collecting; does nothing while already in progress. Starts the hotkey hook if needed."""
        with self._lock:
            if self.InProgress:
                return
            self._Reset()
            self.InProgress = True
            self._ended.clear()
        # Imported here: the hotkey module imports this one to feed it.
        from yorha import Hotkeys
        Hotkeys.Start()
        with _activeLock:
            _active.append(self)
        if self.Timeout > 0:
            self._timer = threading.Timer(self.Timeout, self._End, (TIMEOUT,))
            self._timer.daemon = True
            self._timer.start()

    def Stop(self) -> None:
        self._End(STOPPED)

    def Wait(self, maxTime: float | None = None) -> str:
        """Waits up to `maxTime` seconds (forever when None) for the input to end; returns EndReason, "" when
        it is still in progress."""
        WaitEvent(self._ended, None if (maxTime is None) else (maxTime * 1000))
        return self.EndReason

    # ---- the hook thread ----

    def _End(self, reason: str, endKey: str = "", endMods: str = "", match: str = "") -> None:
        with self._lock:
            if not self.InProgress:
                return
            self.EndReason, self.EndKey, self.EndMods, self.Match = reason, endKey, endMods, match
            self.InProgress = False
        with _activeLock:
            if self in _active:
                _active.remove(self)
        if self._timer is not None:
            self._timer.cancel()
            self._timer = None
        self._ended.set()
        if self.OnEnd is not None:
            onEnd = self.OnEnd
            _Dispatch(lambda: onEnd(self))

    def HandleKey(self, vk: int, sc: int, extended: bool, held: frozenset[int]) -> bool:
        """A key down on the hook thread; returns whether to hide it."""
        if vk in NEVER_BLOCKED_VKS:
            return False
        char = self._Text(vk, sc, held)
        if any(KeyCodes.Matches(key, vk, extended) for key in self._endKeys) or (char and (char in self._endChars)):
            name = char if (char in self._endChars) else KeyCodes.KeyName(KeyCode(vk, 0, extended))
            self._End(END_KEY, name, _EndMods(held))
            return self._Hides(bool(char))
        if char:
            self._Collect(char)
        return self._Hides(bool(char))

    def _Text(self, vk: int, sc: int, held: frozenset[int]) -> str:
        if self._lengthLimit == 0:
            return ""
        ctrl = bool(held.intersection(CTRL_VKS))
        # Ctrl with Alt is AltGr, which types text; Ctrl alone types text only with the M option
        if ctrl and (not held.intersection(ALT_VKS)) and (not self._modified):
            return ""
        return _CharOf(vk, sc, held)

    def _Hides(self, isText: bool) -> bool:
        return not (self.VisibleText if isText else self.VisibleNonText)

    def _Collect(self, char: str) -> None:
        if (char == "\b") and self.BackspaceIsUndo:
            self.Input = self.Input[:-1]
            return
        self.Input += char
        if self.OnChar is not None:
            onChar = self.OnChar
            _Dispatch(lambda: onChar(self, char))
        if len(self.Input) >= self._lengthLimit:
            self.Input = self.Input[:self._lengthLimit]
            self._End(MAX)
            return
        match = self._FindMatch()
        if match is not None:
            self._End(MATCH, match=match)

    def _FindMatch(self) -> str | None:
        typed = self.Input if self.CaseSensitive else self.Input.lower()
        for phrase in self._matches:
            wanted = phrase if self.CaseSensitive else phrase.lower()
            if (wanted in typed) if self.FindAnywhere else (wanted == typed):
                return phrase
        return None
