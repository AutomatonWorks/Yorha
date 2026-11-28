"""Send in its modes (SendMode Input or Event), SendText, SendLevel, SetKeyDelay and the bookkeeping of keys
this process holds down."""

from __future__ import annotations

import ctypes
import threading

from yorha import InputLevel, KeyCodes
from yorha import Win32Api as api
from yorha.KeyCodes import KeyCode
from yorha.SendParser import CLICK, DOWN, DOWN_KINDS, DOWN_REMEMBERED, PRESS, UP, BlindModifiers, KeyAction, ParseSend
from yorha.Timing import Sleep

KEYEVENTF_EXTENDEDKEY = 0x0001
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_UNICODE = 0x0004
MOUSEEVENTF_WHEEL = 0x0800
MOUSEEVENTF_HWHEEL = 0x1000
WHEEL_DELTA = 120
XBUTTON1 = 1
XBUTTON2 = 2
# (down flag, up flag, mouseData) per button vk
MOUSE_BUTTON_FLAGS = {
    0x01: (0x0002, 0x0004, 0), 0x02: (0x0008, 0x0010, 0), 0x04: (0x0020, 0x0040, 0),
    0x05: (0x0080, 0x0100, XBUTTON1), 0x06: (0x0080, 0x0100, XBUTTON2),
}
# vk -> (wheel flag, notch sign)
WHEEL_FLAGS = {0x9F: (MOUSEEVENTF_WHEEL, 1), 0x9E: (MOUSEEVENTF_WHEEL, -1),
               0x9D: (MOUSEEVENTF_HWHEEL, 1), 0x9C: (MOUSEEVENTF_HWHEEL, -1)}
# Tapped before Send lifts Alt or Win, so the release does not open the window menu or the Start menu.
MENU_MASK_KEY = KeyCode(0xE8)
ALT_AND_WIN_VKS = frozenset((0xA4, 0xA5, KeyCodes.VK_LWIN, KeyCodes.VK_RWIN))
# A generic modifier sent down shows up as its left side in the key state.
LEFT_SIDE_OF = {KeyCodes.VK_SHIFT: 0xA0, KeyCodes.VK_CONTROL: 0xA2, KeyCodes.VK_MENU: 0xA4}
RIGHT_SIDED_EXTENDED = frozenset((0xA3, 0xA5, KeyCodes.VK_LWIN, KeyCodes.VK_RWIN))

EVENT = "Event"
INPUT = "Input"
SEND_MODES = {"event": EVENT, "input": INPUT, "inputthenplay": "InputThenPlay", "play": "Play"}

_settings = {"mode": INPUT, "level": 0}
# "wheel" follows every notch so its scroll animation ends first: ZZZ merged notches 10 ms apart
# and cut a notch short at 150 ms
_delays = {"key": 10, "press": -1, "mouse": 10, "wheel": 250}


def SendMode(mode: str) -> None:
    """SendMode: Input (the default), Event, InputThenPlay or Play. SendPlay does not work on Windows 11, so
    Play and InputThenPlay send like Input."""
    if mode.lower() not in SEND_MODES:
        raise ValueError(f"Invalid SendMode: {mode}")
    _settings["mode"] = SEND_MODES[mode.lower()]


def _Buffered(mode: str) -> bool:
    return mode != EVENT


def SendLevel(level: int) -> None:
    """SendLevel(0-100): input sent at a level above 0 can fire this process's hotkeys of a lower input level."""
    if not (0 <= level <= InputLevel.MAX_SEND_LEVEL):
        raise ValueError(f"Invalid SendLevel: {level}")
    _settings["level"] = level


def SetKeyDelay(delay: int | None = None, pressDuration: int | None = None, play: str = "") -> None:
    """SetKeyDelay for SendEvent; an omitted value keeps the current one. The "Play" delays are accepted and
    dropped: SendPlay sends like SendInput, which has no delays."""
    if play.lower() == "play":
        return
    if delay is not None:
        _delays["key"] = delay
    if pressDuration is not None:
        _delays["press"] = pressDuration


def SetMouseDelay(delay: int, play: str = "") -> None:
    if play.lower() == "play":
        return
    _delays["mouse"] = delay


def Delay(kind: str) -> None:
    if _delays[kind] >= 0:
        Sleep(_delays[kind])


class Emitter:
    """Where one Send's events go: straight out with the Event delays, or gathered into a single SendInput."""

    def __init__(self, mode: str) -> None:
        self.buffered = _Buffered(mode)
        self.events: list[api.INPUT] = []

    def Emit(self, event: api.INPUT) -> None:
        if self.buffered:
            self.events.append(event)
        else:
            Inject(event)

    def Delay(self, kind: str) -> None:
        if not self.buffered:
            Delay(kind)

    def Flush(self) -> None:
        if self.events:
            Inject(*self.events)
            self.events.clear()


def CurrentEmitter() -> Emitter:
    return Emitter(_settings["mode"])


# ---- Send ----


def Send(keys: str) -> None:
    _SendIn(_settings["mode"], keys)


def SendInput(keys: str) -> None:
    _SendIn(INPUT, keys)


def SendEvent(keys: str) -> None:
    _SendIn(EVENT, keys)


def SendPlay(keys: str) -> None:
    """SendPlay does not work on Windows 11: SendInput stands in for it."""
    _SendIn(INPUT, keys)


def SendText(text: str) -> None:
    Send("{Text}" + text)


def _SendIn(mode: str, keys: str) -> None:
    actions = ParseSend(keys)
    blind = BlindModifiers(keys)
    emitter = Emitter(mode)
    lifted, alreadyDown = _LiftModifiers(emitter, blind)
    skipped: set[int] = set()
    for action in actions:
        if _AlreadyDown(action, alreadyDown, skipped):
            continue
        _Perform(emitter, action)
    _RestoreModifiers(emitter, lifted)
    emitter.Flush()


def _AlreadyDown(action: KeyAction, alreadyDown: set[str], skipped: set[int]) -> bool:
    """A wrapped modifier that is down already (a {Shift down} earlier, or held under {Blind}) is neither pressed
    nor released, like AHK: Send "{Shift down}" then Send "A" leaves Shift down."""
    if not action.wrapped:
        return False
    if action.kind == UP:
        return action.key.vk in skipped
    if KeyCodes.SIDED_MODIFIER_SYMBOLS.get(_SidedVk(action.key.vk)) in alreadyDown:
        skipped.add(action.key.vk)
        return True
    return False


def _Perform(emitter: Emitter, action: KeyAction) -> None:
    if action.kind == CLICK:
        emitter.Flush()
        # Imported here: the mouse module sends its buttons through this one.
        from yorha import Mouse
        Mouse.ClickIn(EVENT if (not emitter.buffered) else INPUT, action.click)
        return
    if action.key.vk in KeyCodes.WHEEL_VKS:
        SendWheelNotches(emitter, action.key.vk, 1)
        return
    if action.key.isMouse:
        PerformButton(emitter, action.key.vk, action.kind)
        return
    if action.kind != UP:
        _EmitKey(emitter, action, up=False)
        if action.kind == PRESS:
            emitter.Delay("press")
    if action.kind not in DOWN_KINDS:
        _EmitKey(emitter, action, up=True)
    emitter.Delay("key")


# ---- modifiers a non-blind Send lifts ----

# Keys and buttons this process sent down and not up yet. A stop can land on the wait between the two
# (or a macro held one on purpose), and Windows never lets go of an injected key by itself.
_heldLock = threading.Lock()
_heldKeys: dict[int, KeyAction] = {}
_heldButtons: set[int] = set()
# Sided modifier vks a {Key down} put down (a later Send leaves them alone) and a {Key DownR} put down
# (a later Send lifts them and puts them back).
_persistentModifiers: set[int] = set()
_rememberedModifiers: set[int] = set()


def _SidedVk(vk: int) -> int:
    return LEFT_SIDE_OF.get(vk, vk)


def _LogicalModifiersDown() -> list[int]:
    return [vk for vk in KeyCodes.SIDED_MODIFIER_SYMBOLS if (api.GetAsyncKeyState(vk) & 0x8000) != 0]


def _LiftModifiers(emitter: Emitter, blind: str | None) -> tuple[list[int], set[str]]:
    """Releases the modifiers held down when Send starts (AHK: Send "a" with Ctrl held sends {Ctrl up}a{Ctrl down}),
    except those a {Key down} put down. {Blind} only lifts the ones it names, without the menu mask. Returns the
    lifted vks and the modifier symbols that stay down."""
    with _heldLock:
        kept = set(_persistentModifiers)
    down = _LogicalModifiersDown()
    lift = [vk for vk in down if vk not in kept]
    if blind is not None:
        lift = [vk for vk in lift if KeyCodes.SIDED_MODIFIER_SYMBOLS[vk] in blind]
    if (blind is None) and any(vk in ALT_AND_WIN_VKS for vk in lift):
        _EmitRaw(emitter, MENU_MASK_KEY, up=False)
        _EmitRaw(emitter, MENU_MASK_KEY, up=True)
    for vk in lift:
        _EmitRaw(emitter, KeyCode(vk, 0, vk in RIGHT_SIDED_EXTENDED), up=True)
    stayDown = (set(down) | kept) - set(lift)
    return lift, {KeyCodes.SIDED_MODIFIER_SYMBOLS[vk] for vk in stayDown}


def _RestoreModifiers(emitter: Emitter, lifted: list[int]) -> None:
    with _heldLock:
        remembered = set(_rememberedModifiers)
    for vk in lifted:
        if (vk in remembered) or _StillPhysicallyDown(vk):
            _EmitRaw(emitter, KeyCode(vk, 0, vk in RIGHT_SIDED_EXTENDED), up=False)


def _StillPhysicallyDown(vk: int) -> bool:
    # Imported here: the hotkey module imports this one to replay native key presses.
    from yorha import Hotkeys
    physical = Hotkeys.PhysicalKeyDown(KeyCode(vk))
    # Without the hook there is no telling: assume the user still holds it, like AHK.
    return True if (physical is None) else physical


# ---- key events ----


def _KeyInput(key: KeyCode, char: str, up: bool, level: int | None = None) -> api.INPUT:
    event = api.INPUT(type=api.INPUT_KEYBOARD)
    extra = InputLevel.ExtraInfo(_settings["level"] if (level is None) else level)
    if char:
        event.u.ki = api.KEYBDINPUT(0, ord(char), KEYEVENTF_UNICODE | (KEYEVENTF_KEYUP if up else 0), 0, extra)
    else:
        flags = (KEYEVENTF_KEYUP if up else 0) | (KEYEVENTF_EXTENDEDKEY if key.isExtended else 0)
        event.u.ki = api.KEYBDINPUT(key.vk, KeyCodes.ScanCode(key), flags, 0, extra)
    return event


def _EmitRaw(emitter: Emitter, key: KeyCode, up: bool) -> None:
    """A modifier lift, restore or menu mask: level 0 at any SendLevel, so no hotkey ever reacts to it."""
    emitter.Emit(_KeyInput(key, "", up, level=0))


def _EmitKey(emitter: Emitter, action: KeyAction, up: bool) -> None:
    for unit in Utf16Units(action.char):
        emitter.Emit(_KeyInput(action.key, unit, up))
    if action.char:
        return
    emitter.Emit(_KeyInput(action.key, "", up))
    _Track(action, up)


def Utf16Units(char: str) -> list[str]:
    """A character outside the BMP goes as its two surrogate packets."""
    if not char:
        return []
    raw = char.encode("utf-16-le")
    return [chr(int.from_bytes(raw[index:index + 2], "little")) for index in range(0, len(raw), 2)]


def _Track(action: KeyAction, up: bool) -> None:
    sided = _SidedVk(action.key.vk)
    with _heldLock:
        if up:
            _heldKeys.pop(action.key.vk, None)
            _persistentModifiers.discard(sided)
            _rememberedModifiers.discard(sided)
            return
        _heldKeys[action.key.vk] = action
        if sided in KeyCodes.SIDED_MODIFIER_SYMBOLS:
            if action.kind == DOWN:
                _persistentModifiers.add(sided)
            elif action.kind == DOWN_REMEMBERED:
                _rememberedModifiers.add(sided)


def ReleaseHeldInputs() -> int:
    """Sends the up of every key and mouse button still held down by this process; returns how many."""
    with _heldLock:
        keys = list(_heldKeys.values())
        buttons = list(_heldButtons)
        _heldKeys.clear()
        _heldButtons.clear()
        _persistentModifiers.clear()
        _rememberedModifiers.clear()
    for action in keys:
        Inject(_KeyInput(action.key, "", up=True))
    for vk in buttons:
        Inject(_ButtonInput(vk, up=True))
    return len(keys) + len(buttons)


def TapKey(key: KeyCode) -> None:
    """Down and up with no delay: the hook's replay of a prefix key's native press and its menu mask. Always
    level 0, so the hook never takes its own replay for a new press."""
    if key.isMouse:
        Inject(_ButtonInput(key.vk, up=False, level=0), _ButtonInput(key.vk, up=True, level=0))
        return
    Inject(_KeyInput(key, "", up=False, level=0), _KeyInput(key, "", up=True, level=0))


# ---- mouse button events ----


def PerformButton(emitter: Emitter, vk: int, kind: str) -> None:
    if kind != UP:
        emitter.Emit(_ButtonInput(vk, up=False))
        with _heldLock:
            _heldButtons.add(vk)
        if kind == PRESS:
            emitter.Delay("mouse")
    if kind not in DOWN_KINDS:
        emitter.Emit(_ButtonInput(vk, up=True))
        with _heldLock:
            _heldButtons.discard(vk)
    emitter.Delay("mouse")


def _ButtonInput(vk: int, up: bool, level: int | None = None) -> api.INPUT:
    downFlag, upFlag, data = MOUSE_BUTTON_FLAGS[vk]
    event = api.INPUT(type=api.INPUT_MOUSE)
    extra = InputLevel.ExtraInfo(_settings["level"] if (level is None) else level)
    event.u.mi = api.MOUSEINPUT(0, 0, data, upFlag if up else downFlag, 0, extra)
    return event


def SendWheelNotches(emitter: Emitter, vk: int, notches: int) -> None:
    for _ in range(notches):
        emitter.Emit(_WheelInput(vk))
        emitter.Delay("wheel")


def _WheelInput(vk: int) -> api.INPUT:
    flag, sign = WHEEL_FLAGS[vk]
    event = api.INPUT(type=api.INPUT_MOUSE)
    extra = InputLevel.ExtraInfo(_settings["level"])
    event.u.mi = api.MOUSEINPUT(0, 0, ctypes.c_uint32(sign * WHEEL_DELTA).value, flag, 0, extra)
    return event


def MouseInput(dx: int, dy: int, flags: int) -> api.INPUT:
    event = api.INPUT(type=api.INPUT_MOUSE)
    event.u.mi = api.MOUSEINPUT(dx, dy, 0, flags, 0, InputLevel.ExtraInfo(_settings["level"]))
    return event


def Inject(*events: api.INPUT) -> None:
    array = (api.INPUT * len(events))(*events)
    api.SendInput(len(events), array, ctypes.sizeof(api.INPUT))
