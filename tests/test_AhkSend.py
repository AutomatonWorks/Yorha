import sys

import pytest

from yorha import Input as ahk_input
from yorha import InputLevel
from yorha.KeyCodes import GetKeyCode, KeyCode
from yorha.SendParser import CLICK, DOWN, DOWN_REMEMBERED, DOWN_TEMP, PRESS, UP, BlindModifiers, ParseSend

CTRL = 0x11
SHIFT = 0x10
LCTRL = 0xA2
LSHIFT = 0xA0
LALT = 0xA4
ENTER = 0x0D
MENU_MASK = 0xE8
KEYEVENTF_KEYUP = 0x0002


def _Summary(keys: str) -> list[tuple[int, str]]:
    return [(action.key.vk, action.kind) for action in ParseSend(keys)]


def test_NamedKeysAreCaseInsensitive():
    assert _Summary("{Esc}{ENTER}{tab}") == [(0x1B, PRESS), (0x0D, PRESS), (0x09, PRESS)]


def test_ModifierSymbolWrapsOnlyTheNextKey():
    assert _Summary("^ab") == [(CTRL, DOWN_TEMP), (0x41, PRESS), (CTRL, UP), (0x42, PRESS)]


def test_ModifiersWrapABraceKeyInReverseReleaseOrder():
    assert _Summary("^+{Tab}") == [(CTRL, DOWN_TEMP), (SHIFT, DOWN_TEMP), (0x09, PRESS), (SHIFT, UP), (CTRL, UP)]


def test_DownUpAndRepeat():
    assert _Summary("{Space down}{Space up}") == [(0x20, DOWN), (0x20, UP)]
    assert _Summary("{Space 3}") == [(0x20, PRESS)] * 3


def test_DownTempAndDownRAreTheirOwnKinds():
    assert _Summary("{Shift DownTemp}{Ctrl DownR}") == [(SHIFT, DOWN_TEMP), (CTRL, DOWN_REMEMBERED)]


def test_UppercaseLetterAddsShift():
    assert _Summary("A") == [(SHIFT, DOWN_TEMP), (0x41, PRESS), (SHIFT, UP)]


def test_ExtendedFlagsFollowTheKey():
    up, enter, numpadEnter = ParseSend("{Up}{Enter}{NumpadEnter}")
    assert up.key.isExtended and numpadEnter.key.isExtended
    assert not enter.key.isExtended


def test_RawVkAndScanCode():
    (action,) = ParseSend("{vk41sc01E}")
    assert (action.key.vk, action.key.sc) == (0x41, 0x1E)


def test_MouseNamesAndWheelRepeat():
    assert _Summary("{LButton}{WheelUp 2}") == [(0x01, PRESS), (0x9F, PRESS), (0x9F, PRESS)]


def test_BlindIsIgnoredAndUnknownNamesRaise():
    assert _Summary("{Blind}x") == [(0x58, PRESS)]
    with pytest.raises(ValueError):
        ParseSend("{NotAKey}")


def test_BlindOnlyCountsAtTheStartAndNamesWhatItStillReleases():
    assert BlindModifiers("{Blind}a") == ""
    assert BlindModifiers("{Blind^+}a") == "^+"
    assert BlindModifiers("a{Blind}") is None
    assert _Summary("{Blind^}a") == [(0x41, PRESS)]


def test_TextModeSendsCharactersAsUnicodeButLineBreaksAsEnter():
    actions = ParseSend("x{Text}^a{b}\r\n\t")
    assert [(action.key.vk, action.char) for action in actions] == [
        (0x58, ""), (0, "^"), (0, "a"), (0, "{"), (0, "b"), (0, "}"), (ENTER, ""), (0x09, "")]


@pytest.mark.skipif(sys.platform != "win32", reason="needs the Windows keyboard layout")
def test_RawModeKeepsSymbolsLiteralAndRawLineBreaksAreTwoEnters():
    actions = ParseSend("{Raw}{a}\r\n")
    vks = [action.key.vk for action in actions]
    assert vks.count(0x41) == 1
    assert vks.count(ENTER) == 2
    assert CLICK not in [action.kind for action in actions]


def test_ClickInsideSendCarriesItsOptions():
    (click,) = ParseSend("{Click 100 200 Right}")
    assert (click.kind, click.click) == (CLICK, "100 200 Right")
    assert ParseSend("{Click}")[0].click == ""


def test_KeyNameAliases():
    assert GetKeyCode("BS") == GetKeyCode("Backspace")
    assert GetKeyCode("Del").vk == 0x2E
    assert GetKeyCode("RCtrl") == KeyCode(0xA3, 0, True)
    assert GetKeyCode("XButton2").isMouse


# ---- sending ----


class _Sent:
    """Every SendInput call, as lists of (vk or char, up, extraInfo)."""

    def __init__(self) -> None:
        self.calls: list[list[tuple[object, bool, int]]] = []

    def __call__(self, *events) -> None:
        self.calls.append([self._Describe(event) for event in events])

    @staticmethod
    def _Describe(event) -> tuple[object, bool, int]:
        if event.type == 1:
            key = event.u.ki
            return (key.wVk or chr(key.wScan)), bool(key.dwFlags & KEYEVENTF_KEYUP), key.dwExtraInfo
        mouse = event.u.mi
        return f"mouse{mouse.dwFlags:#x}", False, mouse.dwExtraInfo

    @property
    def flat(self) -> list[tuple[object, bool]]:
        return [(key, up) for call in self.calls for key, up, _extra in call]


@pytest.fixture
def sent(monkeypatch):
    recorder = _Sent()
    monkeypatch.setattr(ahk_input, "Inject", recorder)
    monkeypatch.setattr(ahk_input, "Delay", lambda kind: None)
    monkeypatch.setattr(ahk_input.KeyCodes, "ScanCode", lambda key: 0)
    monkeypatch.setattr(ahk_input, "_LogicalModifiersDown", list)
    monkeypatch.setattr(ahk_input, "_StillPhysicallyDown", lambda vk: True)
    monkeypatch.setitem(ahk_input._settings, "mode", ahk_input.INPUT)
    monkeypatch.setitem(ahk_input._settings, "level", 0)
    ahk_input.ReleaseHeldInputs()
    recorder.calls.clear()
    yield recorder
    ahk_input.ReleaseHeldInputs()


def test_SendInputGathersTheWholeStringIntoOneCall(sent):
    ahk_input.SendInput("ab{Enter}")
    assert len(sent.calls) == 1
    assert sent.flat == [(0x41, False), (0x41, True), (0x42, False), (0x42, True), (ENTER, False), (ENTER, True)]


def test_SendEventSendsEveryEventOnItsOwnWithTheKeyDelays(sent, monkeypatch):
    delays = []
    monkeypatch.setattr(ahk_input, "Delay", delays.append)
    ahk_input.SendEvent("ab")
    assert len(sent.calls) == 4
    assert delays == ["press", "key", "press", "key"]


def test_SendFollowsSendMode(sent):
    ahk_input.SendMode("Event")
    ahk_input.Send("ab")
    assert len(sent.calls) == 4
    ahk_input.SendMode("Play")
    sent.calls.clear()
    ahk_input.Send("ab")
    assert len(sent.calls) == 1
    with pytest.raises(ValueError):
        ahk_input.SendMode("Fast")


def test_SendTextTypesUnicodePackets(sent):
    ahk_input.SendText("^ñ")
    assert sent.flat == [("^", False), ("^", True), ("ñ", False), ("ñ", True)]


def test_SetKeyDelayKeepsWhatIsOmitted(monkeypatch):
    monkeypatch.setattr(ahk_input, "_delays", dict(ahk_input._delays))
    ahk_input.SetKeyDelay(30, 5)
    ahk_input.SetKeyDelay(40)
    ahk_input.SetKeyDelay(None, 7)
    ahk_input.SetKeyDelay(99, 99, "Play")
    assert (ahk_input._delays["key"], ahk_input._delays["press"]) == (40, 7)


def test_SendLevelMarksEveryEventTheAhkWay(sent):
    ahk_input.SendLevel(3)
    ahk_input.SendInput("a")
    extras = [extra for _key, _up, extra in sent.calls[0]]
    assert extras == [InputLevel.ExtraInfo(3)] * 2
    assert InputLevel.LevelOf(extras[0]) == 3
    assert InputLevel.LevelOf(InputLevel.ExtraInfo(0)) == 0
    assert InputLevel.LevelOf(0) is None
    with pytest.raises(ValueError):
        ahk_input.SendLevel(101)


def test_ModifierLiftsStayAtLevelZeroSoNoHotkeyReactsToThem(sent, monkeypatch):
    monkeypatch.setattr(ahk_input, "_LogicalModifiersDown", lambda: [LCTRL])
    ahk_input.SendLevel(3)
    ahk_input.SendInput("a")
    extras = [extra for _key, _up, extra in sent.calls[0]]
    assert extras == [InputLevel.ExtraInfo(0), InputLevel.ExtraInfo(3), InputLevel.ExtraInfo(3),
                      InputLevel.ExtraInfo(0)]


def test_AHeldModifierIsLiftedAndRestoredAroundTheSend(sent, monkeypatch):
    monkeypatch.setattr(ahk_input, "_LogicalModifiersDown", lambda: [LCTRL])
    ahk_input.SendInput("a")
    assert sent.flat == [(LCTRL, True), (0x41, False), (0x41, True), (LCTRL, False)]


def test_ALiftedModifierTheUserLetGoOfStaysUp(sent, monkeypatch):
    monkeypatch.setattr(ahk_input, "_LogicalModifiersDown", lambda: [LCTRL])
    monkeypatch.setattr(ahk_input, "_StillPhysicallyDown", lambda vk: False)
    ahk_input.SendInput("a")
    assert sent.flat[-1] == (0x41, True)


def test_LiftingAltTapsTheMenuMaskKeyFirst(sent, monkeypatch):
    monkeypatch.setattr(ahk_input, "_LogicalModifiersDown", lambda: [LALT])
    ahk_input.SendInput("a")
    assert sent.flat[:3] == [(MENU_MASK, False), (MENU_MASK, True), (LALT, True)]


def test_BlindLeavesHeldModifiersAloneUnlessNamed(sent, monkeypatch):
    monkeypatch.setattr(ahk_input, "_LogicalModifiersDown", lambda: [LCTRL, LSHIFT])
    ahk_input.SendInput("{Blind}a")
    assert sent.flat == [(0x41, False), (0x41, True)]
    sent.calls.clear()
    ahk_input.SendInput("{Blind^}a")
    assert sent.flat == [(LCTRL, True), (0x41, False), (0x41, True), (LCTRL, False)]


def test_BlindDoesNotPressAModifierTheUserAlreadyHolds(sent, monkeypatch):
    monkeypatch.setattr(ahk_input, "_LogicalModifiersDown", lambda: [LSHIFT])
    ahk_input.SendInput("{Blind}+a")
    assert sent.flat == [(0x41, False), (0x41, True)]


def test_AModifierSentDownStaysDownThroughLaterSends(sent, monkeypatch):
    ahk_input.SendInput("{Shift down}")
    monkeypatch.setattr(ahk_input, "_LogicalModifiersDown", lambda: [LSHIFT])
    sent.calls.clear()
    ahk_input.SendInput("a")
    assert sent.flat == [(0x41, False), (0x41, True)]


def test_AShiftedKeyLeavesAShiftSentDownAlone(sent, monkeypatch):
    ahk_input.SendInput("{Shift down}")
    sent.calls.clear()
    ahk_input.SendInput("A+b")
    assert sent.flat == [(0x41, False), (0x41, True), (0x42, False), (0x42, True)]
    sent.calls.clear()
    ahk_input.SendInput("{Shift up}")
    assert sent.flat == [(SHIFT, True)]


@pytest.mark.skipif(sys.platform != "win32", reason="needs the Windows keyboard layout")
def test_ABracedShiftedCharacterKeepsItsShift():
    actions = ParseSend("{$ 2}")
    assert [action.wrapped for action in actions].count(True) == 4
    assert [action.kind for action in ParseSend("{! down}") if not action.wrapped] == [DOWN]


def test_AClickInsideSendEventFollowsEventMode(sent, monkeypatch):
    from yorha import Mouse
    modes = []
    monkeypatch.setattr(Mouse, "_Press", lambda vk, count, kind, mode=None: modes.append(mode))
    ahk_input.SendEvent("{Click}")
    ahk_input.SendInput("{Click}")
    assert modes == [ahk_input.EVENT, ahk_input.INPUT]


def test_DownRIsLiftedForTheSendAndPutBack(sent, monkeypatch):
    monkeypatch.setattr(ahk_input, "_StillPhysicallyDown", lambda vk: False)
    ahk_input.SendInput("{Shift DownR}")
    monkeypatch.setattr(ahk_input, "_LogicalModifiersDown", lambda: [LSHIFT])
    sent.calls.clear()
    ahk_input.SendInput("a")
    assert sent.flat == [(LSHIFT, True), (0x41, False), (0x41, True), (LSHIFT, False)]


def test_KeysAndButtonsLeftDownAreReleasedOnce(sent):
    ahk_input.Send("a{w down}{LButton down}")
    sent.calls.clear()
    assert ahk_input.ReleaseHeldInputs() == 2
    assert len(sent.flat) == 2
    assert ahk_input.ReleaseHeldInputs() == 0
