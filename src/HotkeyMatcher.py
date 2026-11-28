"""AHK hotkey names and the pure decision the keyboard/mouse hook makes for each event."""

from __future__ import annotations

from dataclasses import dataclass, field

from yorha import KeyCodes
from yorha.KeyCodes import KeyCode

PASSTHROUGH = "~"
WILDCARD = "*"
# $ forces the hook and < > pick a modifier side; the hook is always used and sides are not told apart.
IGNORED_FLAGS = "$<>"
MODIFIER_SYMBOLS = "^!+#"
COMBO_SEPARATOR = "&"
RELEASE_SUFFIX = " up"
MENU_MASK_KEY = KeyCode(0xE8)


@dataclass(frozen=True)
class HotkeySpec:
    name: str
    key: KeyCode
    modifiers: frozenset[str] = frozenset()
    wildcard: bool = False
    passthrough: bool = False
    prefix: KeyCode | None = None
    onRelease: bool = False

    def MatchesKey(self, vk: int, extended: bool) -> bool:
        return KeyCodes.Matches(self.key, vk, extended)

    def MatchesPrefix(self, vk: int) -> bool:
        return (self.prefix is not None) and (vk in KeyCodes.MatchingVks(self.prefix))


def _Resolve(name: str, hotkey: str) -> KeyCode:
    key = KeyCodes.GetKeyCode(name)
    if key is None:
        raise ValueError(f"Invalid hotkey: {hotkey}")
    return key


def ParseHotkey(name: str) -> HotkeySpec:
    """The parts of an AHK hotkey name: "~*^F5", "!F8", "~Tab & 1", "XButton1", "F7 up"."""
    text = name.strip()
    # "Up" is also the arrow key: "~Alt & Up" and a bare "Up" are not release hotkeys.
    released = text[:-len(RELEASE_SUFFIX)].rstrip()
    onRelease = text.lower().endswith(RELEASE_SUFFIX) and (released != "") and not released.endswith(COMBO_SEPARATOR)
    if onRelease:
        text = released
    flags, rest = _SplitFlags(text)
    if f" {COMBO_SEPARATOR} " in rest:
        left, _, right = (part.strip() for part in rest.partition(COMBO_SEPARATOR))
        return HotkeySpec(name, _Resolve(right, name), frozenset(), True, PASSTHROUGH in flags,
                          _Resolve(left, name), onRelease)
    modifiers = frozenset(symbol for symbol in flags if symbol in MODIFIER_SYMBOLS)
    return HotkeySpec(name, _Resolve(rest, name), modifiers, WILDCARD in flags, PASSTHROUGH in flags, None,
                      onRelease)


def _SplitFlags(text: str) -> tuple[str, str]:
    index = 0
    while (index < len(text) - 1) and (text[index] in (PASSTHROUGH + WILDCARD + IGNORED_FLAGS + MODIFIER_SYMBOLS)):
        index += 1
    return text[:index], text[index:]


def IsMouseHotkey(spec: HotkeySpec) -> bool:
    return spec.key.isMouse or ((spec.prefix is not None) and spec.prefix.isMouse)


@dataclass
class Decision:
    fire: list[str] = field(default_factory=list)
    suppress: bool = False
    replay: KeyCode | None = None
    mask: bool = False


@dataclass
class _PrefixState:
    key: KeyCode
    extended: bool
    passthrough: bool
    used: bool = False


class HotkeyMatcher:
    """Decides, for each physical event, which hotkeys fire and whether the event is hidden from the system.
    Not thread-safe: the owner serialises calls."""

    def __init__(self) -> None:
        self.hotkeys: dict[str, HotkeySpec] = {}
        self.enabled: set[str] = set()
        self.exempt: set[str] = set()
        self.suspended = False
        # hotkey name -> input level (Hotkey option I<n>); generated input fires a hotkey only from a higher SendLevel
        self.levels: dict[str, int] = {}
        # every key down, physical or generated at a SendLevel (modifier matching), and the physical ones alone
        self.held: set[int] = set()
        self.physicalHeld: set[int] = set()
        self._eventLevel: int | None = None
        self._suppressedDown: set[int] = set()
        self._prefixes: dict[int, _PrefixState] = {}
        self._pendingRelease: dict[int, list[HotkeySpec]] = {}

    # Forgets prefix and release state that points at hotkeys about to be dropped.
    def ClearPending(self) -> None:
        self._prefixes.clear()
        self._pendingRelease.clear()

    def _Active(self) -> list[HotkeySpec]:
        return [spec for name, spec in self.hotkeys.items()
                if (name in self.enabled) and ((not self.suspended) or (name in self.exempt))
                and ((self._eventLevel is None) or (self.levels.get(name, 0) < self._eventLevel))]

    def _Modifiers(self, excluding: int) -> set[str]:
        held = self.held - {excluding}
        return {symbol for symbol, vks in KeyCodes.MODIFIER_VKS.items() if held.intersection(vks)}

    def event(self, vk: int, extended: bool, up: bool, level: int | None = None) -> Decision:
        """`level` is the SendLevel of generated input, None for physical input."""
        self._eventLevel = level
        if up:
            if level is None:
                self.physicalHeld.discard(vk)
            return self._KeyUp(vk)
        if vk in KeyCodes.WHEEL_VKS:
            return self._KeyDown(vk, extended, repeat=False)
        repeat = vk in self.held
        self.held.add(vk)
        if level is None:
            self.physicalHeld.add(vk)
        return self._KeyDown(vk, extended, repeat)

    def _KeyDown(self, vk: int, extended: bool, repeat: bool) -> Decision:
        active = self._Active()
        combo = self._ComboDown(active, vk, extended)
        if combo is not None:
            return combo
        prefix = self._PrefixDown(active, vk, extended, repeat)
        if prefix is not None:
            return prefix
        return self._PlainDown(active, vk, extended)

    def _ComboDown(self, active: list[HotkeySpec], vk: int, extended: bool) -> Decision | None:
        for prefixVk, state in self._prefixes.items():
            if prefixVk == vk:
                continue
            fired = [spec for spec in active if spec.MatchesPrefix(prefixVk) and spec.MatchesKey(vk, extended)]
            if not fired:
                continue
            state.used = True
            return self._HideOrPass(vk, fired, [spec.name for spec in fired if not spec.onRelease])
        return None

    def _PrefixDown(self, active: list[HotkeySpec], vk: int, extended: bool, repeat: bool) -> Decision | None:
        combos = [spec for spec in active if spec.MatchesPrefix(vk)]
        if not combos:
            return None
        if repeat and (vk in self._prefixes):
            return Decision(suppress=not self._prefixes[vk].passthrough)
        passthrough = any(spec.passthrough for spec in combos)
        self._prefixes[vk] = _PrefixState(combos[0].prefix, extended, passthrough)
        decision = Decision(suppress=not passthrough)
        if passthrough:
            decision.fire = [spec.name for spec in self._PlainMatches(active, vk, extended)]
        return decision

    def _PlainMatches(self, active: list[HotkeySpec], vk: int, extended: bool) -> list[HotkeySpec]:
        current = self._Modifiers(excluding=vk)
        return [spec for spec in active
                if (spec.prefix is None) and spec.MatchesKey(vk, extended) and _ModifiersMatch(spec, current)]

    def _PlainDown(self, active: list[HotkeySpec], vk: int, extended: bool) -> Decision:
        matches = self._PlainMatches(active, vk, extended)
        if not matches:
            return Decision()
        decision = self._HideOrPass(vk, matches, [spec.name for spec in matches if not spec.onRelease])
        if decision.suppress and self._Modifiers(excluding=vk).intersection("!#"):
            decision.mask = True
        return decision

    def _HideOrPass(self, vk: int, matches: list[HotkeySpec], fire: list[str]) -> Decision:
        releases = [spec for spec in matches if spec.onRelease]
        if releases and (vk not in KeyCodes.WHEEL_VKS):
            self._pendingRelease[vk] = releases
        suppress = not all(spec.passthrough for spec in matches)
        if suppress and (vk not in KeyCodes.WHEEL_VKS):
            self._suppressedDown.add(vk)
        return Decision(fire=fire, suppress=suppress)

    def _KeyUp(self, vk: int) -> Decision:
        self.held.discard(vk)
        state = self._prefixes.pop(vk, None)
        if state is not None:
            return self._PrefixUp(vk, state)
        releases = self._pendingRelease.pop(vk, [])
        suppressed = vk in self._suppressedDown
        self._suppressedDown.discard(vk)
        return Decision(fire=[spec.name for spec in releases], suppress=suppressed)

    def _PrefixUp(self, vk: int, state: _PrefixState) -> Decision:
        if state.passthrough or state.used:
            return Decision(suppress=not state.passthrough)
        own = [spec.name for spec in self._PlainMatches(self._Active(), vk, state.extended)]
        if own:
            return Decision(fire=own, suppress=True)
        return Decision(suppress=True, replay=state.key)

    def PhysicalDown(self, key: KeyCode) -> bool:
        return bool(self.physicalHeld.intersection(KeyCodes.MatchingVks(key)))


def _ModifiersMatch(spec: HotkeySpec, current: set[str]) -> bool:
    if spec.wildcard:
        return spec.modifiers.issubset(current)
    return spec.modifiers == current
