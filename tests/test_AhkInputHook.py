import pytest

from yorha import InputCapture
from yorha.InputCapture import InputHook

ENTER = 0x0D
ESCAPE = 0x1B
BACKSPACE = 0x08
LCTRL = 0xA2
LSHIFT = 0xA0
NO_KEYS = frozenset()


@pytest.fixture
def typing(monkeypatch):
    """Keys type the lowercase letter of their vk (Shift for uppercase); the hook and dispatcher are stubbed."""
    dispatched = []

    def CharOf(vk, sc, held):
        if vk == BACKSPACE:
            return "\b"
        if vk == ENTER:
            return "\r"
        if 0x41 <= vk <= 0x5A:
            letter = chr(vk)
            return letter if (LSHIFT in held) else letter.lower()
        return ""

    monkeypatch.setattr(InputCapture, "_CharOf", CharOf)
    monkeypatch.setattr(InputCapture, "_Dispatch", lambda callback: (dispatched.append(callback), callback()))
    monkeypatch.setattr(InputCapture, "_active", [])
    monkeypatch.setattr(InputCapture, "_hiddenDowns", set())
    monkeypatch.setattr(InputCapture, "_heldModifiers", set())
    from yorha import Hotkeys
    monkeypatch.setattr(Hotkeys, "Start", lambda: None)
    return dispatched


def _Type(text: str, held: frozenset = NO_KEYS, level=None) -> list[bool]:
    hidden = []
    for char in text:
        vk = ord(char.upper())
        hidden.append(InputCapture.Feed(vk, 0, False, False, level, held))
        InputCapture.Feed(vk, 0, False, True, level, held)
    return hidden


def _Press(vk: int, held: frozenset = NO_KEYS) -> bool:
    hidden = InputCapture.Feed(vk, 0, False, False, None, held)
    InputCapture.Feed(vk, 0, False, True, None, held)
    return hidden


def test_AnEndKeyEndsTheInputWithItsNameAndModifiers(typing):
    hook = InputHook("", "{Enter}{Esc}")
    hook.Start()
    assert hook.InProgress and (hook.EndReason == "")
    _Type("hi")
    _Press(ESCAPE, frozenset({LCTRL}))
    assert (hook.Input, hook.EndReason, hook.EndKey, hook.EndMods) == ("hi", "EndKey", "Escape", "<^")
    assert not hook.InProgress
    assert hook.Wait() == "EndKey"


def test_TextIsHiddenUnlessVisibleAndNonTextPasses(typing):
    hook = InputHook()
    hook.Start()
    assert _Type("ab") == [True, True]
    assert not _Press(0x70)
    hook.Stop()
    visible = InputHook("V")
    visible.Start()
    assert _Type("ab") == [False, False]
    visible.Stop()


def test_TheLengthLimitEndsWithMax(typing):
    hook = InputHook("L3")
    hook.Start()
    _Type("abcd")
    assert (hook.Input, hook.EndReason) == ("abc", "Max")


def test_AMatchEndsTheInput(typing):
    hook = InputHook("", "", "yes,no")
    hook.Start()
    _Type("n")
    assert hook.InProgress
    _Type("o")
    assert (hook.EndReason, hook.Match) == ("Match", "no")
    anywhere = InputHook("*", "", "go")
    anywhere.Start()
    _Type("letsgo")
    assert (anywhere.EndReason, anywhere.Input) == ("Match", "letsgo")


def test_MatchingIgnoresCaseUnlessC(typing):
    hook = InputHook("C", "", "Go")
    hook.Start()
    _Type("go")
    assert hook.InProgress
    hook.Stop()
    assert hook.EndReason == "Stopped"


def test_BackspaceUndoesUnlessB(typing):
    hook = InputHook()
    hook.Start()
    _Type("ab")
    _Press(BACKSPACE)
    assert hook.Input == "a"
    hook.Stop()
    keep = InputHook("B")
    keep.Start()
    _Type("ab")
    _Press(BACKSPACE)
    assert keep.Input == "ab\b"
    keep.Stop()


def test_CtrlCombosAreNotTextWithoutM(typing):
    hook = InputHook()
    hook.Start()
    _Type("a", frozenset({LCTRL}))
    assert hook.Input == ""
    hook.Stop()


def test_ModifiersAreNeverHidden(typing):
    hook = InputHook()
    hook.Start()
    assert not _Press(LSHIFT)
    hook.Stop()


def test_EEndsOnACharacter(typing):
    hook = InputHook("E", "q")
    hook.Start()
    _Type("aq")
    assert (hook.Input, hook.EndKey) == ("a", "q")


def test_MinSendLevelIgnoresLowerGeneratedInput(typing):
    hook = InputHook("I2")
    hook.Start()
    _Type("a", level=1)
    _Type("b", level=2)
    _Type("c")
    assert hook.Input == "bc"
    hook.Stop()


def test_OnCharAndOnEndRunOnTheDispatcher(typing):
    seen = []
    hook = InputHook("L2")
    hook.OnChar = lambda ih, char: seen.append(char)
    hook.OnEnd = lambda ih: seen.append(ih.EndReason)
    hook.Start()
    _Type("xy")
    assert seen == ["x", "y", "Max"]
    assert len(typing) == 3


def test_TimeoutEndsTheInput(typing):
    hook = InputHook("T0.05")
    hook.Start()
    assert hook.Wait(2) == "Timeout"


def test_WaitWithAMaxTimeLeavesTheInputRunning(typing):
    hook = InputHook()
    hook.Start()
    assert hook.Wait(0.05) == ""
    assert hook.InProgress
    hook.Stop()


def test_StartTwiceDoesNothingAndRestartClearsTheResult(typing):
    hook = InputHook()
    hook.Start()
    _Type("a")
    hook.Start()
    assert hook.Input == "a"
    hook.Stop()
    hook.Start()
    assert (hook.Input, hook.EndReason) == ("", "")
    hook.Stop()


def test_UnknownEndKeysRaise():
    with pytest.raises(ValueError):
        InputHook("", "{NotAKey}")


def test_EndReasonIsStoppedBeforeTheFirstStart():
    hook = InputHook()
    assert (hook.EndReason, hook.Wait(0)) == ("Stopped", "Stopped")


def test_AHiddenEndKeyStaysHiddenOnItsRelease(typing):
    hook = InputHook("", "{Enter}")
    hook.Start()
    assert InputCapture.Feed(ENTER, 0, False, False, None, NO_KEYS)
    assert not hook.InProgress
    assert InputCapture.Feed(ENTER, 0, False, True, None, NO_KEYS)
    assert not InputCapture.Feed(ENTER, 0, False, True, None, NO_KEYS)


def test_ModifiersFromEveryFedEventCountForTheText(typing):
    hook = InputHook()
    hook.Start()
    InputCapture.Feed(LSHIFT, 0, False, False, 0, NO_KEYS)
    _Type("a", level=0)
    InputCapture.Feed(LSHIFT, 0, False, True, 0, NO_KEYS)
    _Type("b", level=0)
    assert hook.Input == "Ab"
    hook.Stop()
