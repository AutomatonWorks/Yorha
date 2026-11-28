import pytest

from yorha.HotkeyMatcher import HotkeyMatcher, ParseHotkey
from yorha.KeyCodes import KeyCode

LCTRL = 0xA2
LSHIFT = 0xA0
LALT = 0xA4
TAB = 0x09
ONE = 0x31
F5 = 0x74
F7 = 0x76
F8 = 0x77
HOME = 0x24
XBUTTON1 = 0x05
A = 0x41
WHEEL_UP = 0x9F


def _Matcher(*names: str) -> HotkeyMatcher:
    matcher = HotkeyMatcher()
    for name in names:
        matcher.hotkeys[name.lower()] = ParseHotkey(name)
        matcher.enabled.add(name.lower())
    return matcher


def _Press(matcher: HotkeyMatcher, vk: int, extended: bool = False):
    return matcher.event(vk, extended, up=False), matcher.event(vk, extended, up=True)


def test_ParseHotkeyParts():
    spec = ParseHotkey("~*^F5")
    assert (spec.key.vk, spec.modifiers, spec.wildcard, spec.passthrough) == (F5, frozenset("^"), True, True)
    combo = ParseHotkey("~Tab & 1")
    assert (combo.prefix.vk, combo.key.vk, combo.passthrough) == (TAB, ONE, True)
    assert ParseHotkey("$x").key.vk == 0x58
    assert ParseHotkey("F7 up").onRelease
    with pytest.raises(ValueError):
        ParseHotkey("^NotAKey")


def test_UpArrowIsAKeyNotARelease():
    combo = ParseHotkey("~Alt & Up")
    assert (combo.key.vk, combo.onRelease) == (0x26, False)
    assert not ParseHotkey("Up").onRelease
    assert ParseHotkey("Up up").onRelease


def test_ModifiersMustMatchExactlyWithoutWildcard():
    matcher = _Matcher("^F5")
    matcher.event(LCTRL, False, up=False)
    down, up = _Press(matcher, F5)
    assert (down.fire, down.suppress, up.suppress) == (["^F5"], True, True)
    matcher.event(LSHIFT, False, up=False)
    assert _Press(matcher, F5)[0].fire == []


def test_WildcardAllowsExtraModifiers():
    matcher = _Matcher("*^F5")
    matcher.event(LCTRL, False, up=False)
    matcher.event(LSHIFT, False, up=False)
    assert _Press(matcher, F5)[0].fire == ["*^F5"]


def test_NoModifierHotkeyIgnoresUnrelatedKeys():
    matcher = _Matcher("F5")
    assert _Press(matcher, F5)[0].fire == ["F5"]
    down, up = _Press(matcher, A)
    assert (down.fire, down.suppress, up.suppress) == ([], False, False)


def test_TildePassesTheNativeKey():
    down, up = _Press(_Matcher("~Home"), HOME, extended=True)
    assert (down.fire, down.suppress, up.suppress) == (["~Home"], False, False)


def test_ExtendedKeyDoesNotMatchItsNumpadTwin():
    assert _Press(_Matcher("Home"), HOME, extended=False)[0].fire == []


def test_PassthroughComboPassesPrefixAndSuffix():
    matcher = _Matcher("~Tab & 1")
    assert not matcher.event(TAB, False, up=False).suppress
    down, _ = _Press(matcher, ONE)
    assert (down.fire, down.suppress) == (["~Tab & 1"], False)
    assert not matcher.event(TAB, False, up=True).suppress


def test_UnusedPrefixReplaysItsNativePress():
    matcher = _Matcher("Tab & 1")
    assert matcher.event(TAB, False, up=False).suppress
    released = matcher.event(TAB, False, up=True)
    assert released.suppress and (released.replay.vk == TAB)


def test_UsedPrefixIsSwallowed():
    matcher = _Matcher("Tab & 1")
    matcher.event(TAB, False, up=False)
    assert _Press(matcher, ONE)[0].fire == ["Tab & 1"]
    released = matcher.event(TAB, False, up=True)
    assert released.suppress and (released.replay is None)


def test_PrefixWithItsOwnHotkeyFiresItOnRelease():
    matcher = _Matcher("XButton1 & a", "XButton1")
    assert matcher.event(XBUTTON1, False, up=False).fire == []
    assert matcher.event(XBUTTON1, False, up=True).fire == ["XButton1"]


def test_AltHotkeyMasksTheMenu():
    matcher = _Matcher("!F8")
    matcher.event(LALT, False, up=False)
    down, _ = _Press(matcher, F8)
    assert down.fire == ["!F8"] and down.mask


def test_ReleaseHotkeyFiresOnUp():
    down, up = _Press(_Matcher("F7 up"), F7)
    assert (down.fire, down.suppress, up.fire, up.suppress) == ([], True, ["F7 up"], True)


def test_WheelFiresWithoutHoldingState():
    matcher = _Matcher("WheelUp")
    assert matcher.event(WHEEL_UP, False, up=False).fire == ["WheelUp"]
    assert not matcher.held


def test_SuspendKeepsOnlyExemptHotkeys():
    matcher = _Matcher("F5", "F7")
    matcher.exempt.add("f7")
    matcher.suspended = True
    assert _Press(matcher, F5)[0].fire == []
    assert _Press(matcher, F7)[0].fire == ["F7"]


def test_DisabledHotkeyDoesNotFire():
    matcher = _Matcher("F5")
    matcher.enabled.discard("f5")
    down, _ = _Press(matcher, F5)
    assert (down.fire, down.suppress) == ([], False)


def test_PhysicalStateTracksSidedModifiers():
    matcher = _Matcher()
    matcher.event(LSHIFT, False, up=False)
    assert matcher.PhysicalDown(KeyCode(0x10)) and matcher.PhysicalDown(KeyCode(LSHIFT))
    matcher.event(LSHIFT, False, up=True)
    assert not matcher.PhysicalDown(KeyCode(0x10))


def test_SOptionKeepsAHotkeyWorkingWhileSuspendedAndClearDropsAll():
    from yorha import Hotkeys

    try:
        Hotkeys.Hotkey("F7", lambda *_: None, "P10 T1 S")
        Hotkeys.Hotkey("F8", lambda *_: None, "P0 T1")
        Hotkeys.Suspend(True)
        assert _Press(Hotkeys._matcher, F7)[0].fire == ["F7"]
        assert _Press(Hotkeys._matcher, F8)[0].fire == []
        Hotkeys.ClearHotkeys()
        assert _Press(Hotkeys._matcher, F7)[0].fire == []
        assert Hotkeys._callbacks == {}
    finally:
        Hotkeys.ClearHotkeys()
        Hotkeys.Suspend(False)


def test_APressedHotkeyQueuesItsCallbackWithTheRegisteredName():
    from yorha import Hotkeys, ThisHotkey

    seen = []
    try:
        Hotkeys.Hotkey("~Insert", lambda name: seen.append((name, ThisHotkey())), "P10 T1")
        Hotkeys._Decide(0x2D, True, False, None)
        Hotkeys._queue.get_nowait()()
        assert seen == [("~Insert", "~Insert")]
    finally:
        Hotkeys.ClearHotkeys()
