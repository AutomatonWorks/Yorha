import pytest

from yorha import Input as ahk_input
from yorha.Input import DOWN, PRESS, UP, ParseSend
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


def test_MouseMoveTruncatesFloatCoordinatesLikeAhk(monkeypatch):
    moves = []
    monkeypatch.setattr(ahk_input, "_ClientOrigin", lambda: (100, 50))
    monkeypatch.setattr(ahk_input, "_AbsoluteMove", lambda x, y: moves.append((x, y)))
    monkeypatch.setattr(ahk_input, "_Delay", lambda kind: None)
    ahk_input.MouseMove(960.5, 540.5, 0)
    assert moves == [(1060, 590)]
    assert all(isinstance(value, int) for value in moves[0])


def _RecordMoves(monkeypatch, diagonal=1000.0) -> list:
    moves = []
    clock = {"ms": 0.0}

    def FakeSleep(ms):
        clock["ms"] += ms

    monkeypatch.setattr(ahk_input, "_ClientOrigin", lambda: (0, 0))
    monkeypatch.setattr(ahk_input, "_ScreenCursor", lambda: (0, 0))
    monkeypatch.setattr(ahk_input, "_WindowDiagonal", lambda: diagonal)
    monkeypatch.setattr(ahk_input, "_AbsoluteMove", lambda x, y: moves.append((x, y)))
    monkeypatch.setattr(ahk_input, "_Delay", lambda kind: None)
    monkeypatch.setattr(ahk_input, "Sleep", FakeSleep)
    monkeypatch.setattr(ahk_input, "_Now", lambda: clock["ms"] / 1000)
    monkeypatch.setitem(ahk_input._mouseMotion, "speed", (2, 2))
    monkeypatch.setitem(ahk_input._mouseMotion, "curve", (0, 0))
    return moves


def test_MouseMoveWithoutSpeedGlidesAtTheDefaultMouseSpeed(monkeypatch):
    moves = _RecordMoves(monkeypatch)
    ahk_input.SetDefaultMouseSpeed(60)
    ahk_input.MouseMove(900, 0)
    assert moves[-1] == (900, 0)
    assert len(moves) > 10
    assert all(0 <= x <= 900 for x, _y in moves)
    assert [x for x, _y in moves] == sorted(x for x, _y in moves)


def test_AnExplicitSpeedZeroStillJumps(monkeypatch):
    moves = _RecordMoves(monkeypatch)
    ahk_input.SetDefaultMouseSpeed(60)
    ahk_input.MouseMove(900, 0, 0)
    assert moves == [(900, 0)]


def test_TheSameShareOfTheWindowTakesTheSameStepsAtAnyResolution(monkeypatch):
    small = _RecordMoves(monkeypatch, diagonal=1000.0)
    ahk_input.MouseMove(400, 300, 50)
    large = _RecordMoves(monkeypatch, diagonal=4000.0)
    ahk_input.MouseMove(1600, 1200, 50)
    assert len(small) == len(large)


def test_ACurvedMoveLeavesTheStraightLineAndStillEndsOnTarget(monkeypatch):
    moves = _RecordMoves(monkeypatch)
    ahk_input.SetMouseCurvedMotion(100)
    ahk_input.MouseMove(900, 0, 60)
    assert moves[-1] == (900, 0)
    assert max(abs(y) for _x, y in moves) > 50


def test_EveryMovePicksItsSpeedFromTheRangeBothEndsIncluded(monkeypatch):
    _RecordMoves(monkeypatch)
    ahk_input.SetDefaultMouseSpeed(40, 20)
    picks = {ahk_input._Pick("speed") for _ in range(500)}
    assert picks == set(range(20, 41))


def test_ASingleValueAlwaysPicksThatValue(monkeypatch):
    _RecordMoves(monkeypatch)
    ahk_input.SetMouseCurvedMotion(30)
    assert {ahk_input._Pick("curve") for _ in range(50)} == {30}


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
