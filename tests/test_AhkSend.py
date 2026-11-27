import pytest

from yorha import Input as ahk_input
from yorha.Input import DOWN, PRESS, UP, IncrementalPath, ParseSend
from yorha.KeyCodes import GetKeyCode, KeyCode

CTRL = 0x11
SHIFT = 0x10


def _Summary(keys: str) -> list[tuple[int, str]]:
    return [(action.key.vk, action.kind) for action in ParseSend(keys)]


def test_NamedKeysAreCaseInsensitive():
    assert _Summary("{Esc}{ENTER}{tab}") == [(0x1B, PRESS), (0x0D, PRESS), (0x09, PRESS)]


def test_ModifierSymbolWrapsOnlyTheNextKey():
    assert _Summary("^ab") == [(CTRL, DOWN), (0x41, PRESS), (CTRL, UP), (0x42, PRESS)]


def test_ModifiersWrapABraceKeyInReverseReleaseOrder():
    assert _Summary("^+{Tab}") == [(CTRL, DOWN), (SHIFT, DOWN), (0x09, PRESS), (SHIFT, UP), (CTRL, UP)]


def test_DownUpAndRepeat():
    assert _Summary("{Space down}{Space up}") == [(0x20, DOWN), (0x20, UP)]
    assert _Summary("{Space 3}") == [(0x20, PRESS)] * 3


def test_UppercaseLetterAddsShift():
    assert _Summary("A") == [(SHIFT, DOWN), (0x41, PRESS), (SHIFT, UP)]


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


def test_KeyNameAliases():
    assert GetKeyCode("BS") == GetKeyCode("Backspace")
    assert GetKeyCode("Del").vk == 0x2E
    assert GetKeyCode("RCtrl") == KeyCode(0xA3, 0, True)
    assert GetKeyCode("XButton2").isMouse


def test_IncrementalPathEndsOnTargetAndNeverOvershoots():
    path = IncrementalPath((0, 0), (300, -100), 10)
    assert path[-1] == (300, -100)
    assert all((0 <= x <= 300) and (-100 <= y <= 0) for x, y in path)
    assert len(path) > 1


def test_MouseMoveTruncatesFloatCoordinatesLikeAhk(monkeypatch):
    moves = []
    monkeypatch.setattr(ahk_input, "_ClientOrigin", lambda: (100, 50))
    monkeypatch.setattr(ahk_input, "_AbsoluteMove", lambda x, y: moves.append((x, y)))
    monkeypatch.setattr(ahk_input, "_Delay", lambda kind: None)
    ahk_input.MouseMove(960.5, 540.5, 0)
    assert moves == [(1060, 590)]
    assert all(isinstance(value, int) for value in moves[0])


def _RecordMoves(monkeypatch) -> list:
    moves = []
    monkeypatch.setattr(ahk_input, "_ClientOrigin", lambda: (0, 0))
    monkeypatch.setattr(ahk_input, "_ScreenCursor", lambda: (0, 0))
    monkeypatch.setattr(ahk_input, "_AbsoluteMove", lambda x, y: moves.append((x, y)))
    monkeypatch.setattr(ahk_input, "_Delay", lambda kind: None)
    monkeypatch.setitem(ahk_input._mouseSpeed, "default", 2)
    return moves


def test_MouseMoveWithoutSpeedUsesTheDefaultMouseSpeed(monkeypatch):
    moves = _RecordMoves(monkeypatch)
    ahk_input.SetDefaultMouseSpeed(3)
    ahk_input.MouseMove(900, 0)
    assert moves == IncrementalPath((0, 0), (900, 0), 3)
    assert len(moves) > 1


def test_AnExplicitSpeedZeroStillJumps(monkeypatch):
    moves = _RecordMoves(monkeypatch)
    ahk_input.SetDefaultMouseSpeed(3)
    ahk_input.MouseMove(900, 0, 0)
    assert moves == [(900, 0)]


def test_KeysAndButtonsLeftDownAreReleasedOnce(monkeypatch):
    sent = []
    monkeypatch.setattr(ahk_input, "_SendInputs", lambda event: sent.append(event))
    monkeypatch.setattr(ahk_input, "_Delay", lambda kind: None)
    monkeypatch.setattr(ahk_input.KeyCodes, "ScanCode", lambda key: 0)
    ahk_input.ReleaseHeldInputs()
    ahk_input.Send("a{w down}{LButton down}")
    sent.clear()
    assert ahk_input.ReleaseHeldInputs() == 2
    assert len(sent) == 2
    assert ahk_input.ReleaseHeldInputs() == 0
