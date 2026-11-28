import pytest

from yorha import Coordinates
from yorha import Input as ahk_input
from yorha import Mouse as ahk_mouse
from yorha.SendParser import DOWN, PRESS, UP


def test_MouseMoveTruncatesFloatCoordinatesLikeAhk(monkeypatch):
    moves = []
    monkeypatch.setattr(ahk_mouse, "_Origin", lambda: (100, 50))
    monkeypatch.setattr(ahk_mouse, "_ScreenCursor", lambda: (0, 0))
    monkeypatch.setattr(ahk_mouse, "_AbsoluteMove", lambda x, y: moves.append((x, y)))
    monkeypatch.setattr(ahk_input, "Delay", lambda kind: None)
    ahk_mouse.MouseMove(960.5, 540.5, 0)
    assert moves == [(1060, 590)]
    assert all(isinstance(value, int) for value in moves[0])


def _RecordMoves(monkeypatch, diagonal=1000.0, cursor=(0, 0)) -> list:
    moves = []
    clock = {"ms": 0.0}

    def FakeSleep(ms):
        clock["ms"] += ms

    monkeypatch.setattr(ahk_mouse, "_Origin", lambda: (0, 0))
    monkeypatch.setattr(ahk_mouse, "_ScreenCursor", lambda: cursor)
    monkeypatch.setattr(ahk_mouse, "_WindowDiagonal", lambda: diagonal)
    monkeypatch.setattr(ahk_mouse, "_AbsoluteMove", lambda x, y: moves.append((x, y)))
    monkeypatch.setattr(ahk_input, "Delay", lambda kind: None)
    monkeypatch.setattr(ahk_mouse, "Sleep", FakeSleep)
    monkeypatch.setattr(ahk_mouse, "_Now", lambda: clock["ms"] / 1000)
    monkeypatch.setitem(ahk_mouse._mouseMotion, "speed", (2, 2))
    monkeypatch.setitem(ahk_mouse._mouseMotion, "curve", (0, 0))
    return moves


def test_MouseMoveWithoutSpeedGlidesAtTheDefaultMouseSpeed(monkeypatch):
    moves = _RecordMoves(monkeypatch)
    ahk_mouse.SetDefaultMouseSpeed(60)
    ahk_mouse.MouseMove(900, 0)
    assert moves[-1] == (900, 0)
    assert len(moves) > 10
    assert all(0 <= x <= 900 for x, _y in moves)
    assert [x for x, _y in moves] == sorted(x for x, _y in moves)


def test_AnExplicitSpeedZeroStillJumps(monkeypatch):
    moves = _RecordMoves(monkeypatch)
    ahk_mouse.SetDefaultMouseSpeed(60)
    ahk_mouse.MouseMove(900, 0, 0)
    assert moves == [(900, 0)]


def test_RelativeMoveCountsFromTheCursor(monkeypatch):
    moves = _RecordMoves(monkeypatch, cursor=(300, 200))
    ahk_mouse.MouseMove(-50, 10, 0, "R")
    assert moves == [(250, 210)]


def test_TheSameShareOfTheWindowTakesTheSameStepsAtAnyResolution(monkeypatch):
    small = _RecordMoves(monkeypatch, diagonal=1000.0)
    ahk_mouse.MouseMove(400, 300, 50)
    large = _RecordMoves(monkeypatch, diagonal=4000.0)
    ahk_mouse.MouseMove(1600, 1200, 50)
    assert len(small) == len(large)


def test_ACurvedMoveLeavesTheStraightLineAndStillEndsOnTarget(monkeypatch):
    moves = _RecordMoves(monkeypatch)
    ahk_mouse.SetMouseCurvedMotion(100)
    ahk_mouse.MouseMove(900, 0, 60)
    assert moves[-1] == (900, 0)
    assert max(abs(y) for _x, y in moves) > 50


def test_EveryMovePicksItsSpeedFromTheRangeBothEndsIncluded(monkeypatch):
    _RecordMoves(monkeypatch)
    ahk_mouse.SetDefaultMouseSpeed(40, 20)
    picks = {ahk_mouse._Pick("speed") for _ in range(500)}
    assert picks == set(range(20, 41))


def test_ASingleValueAlwaysPicksThatValue(monkeypatch):
    _RecordMoves(monkeypatch)
    ahk_mouse.SetMouseCurvedMotion(30)
    assert {ahk_mouse._Pick("curve") for _ in range(50)} == {30}


# ---- Click ----


def test_ClickOptionsInAnyOrder():
    parsed = ahk_mouse.ParseClick("Right 100 200 2 D")
    assert (parsed.x, parsed.y, parsed.button, parsed.count, parsed.downOrUp) == (100, 200, "right", 2, "d")
    assert ahk_mouse.ParseClick(100, 200, "R U").button == "r"
    assert ahk_mouse.ParseClick("100, 200").x == 100


def test_ALoneNumberIsTheCountAndRelIsRelative():
    assert ahk_mouse.ParseClick("2").count == 2
    assert ahk_mouse.ParseClick("2").x is None
    parsed = ahk_mouse.ParseClick("-10 5 Rel 0")
    assert (parsed.x, parsed.y, parsed.relative, parsed.count) == (-10, 5, True, 0)
    with pytest.raises(ValueError):
        ahk_mouse.ParseClick("Sideways")


@pytest.fixture
def actions(monkeypatch):
    """(what, ...) of every press, wheel and move the mouse functions make."""
    log = []
    monkeypatch.setattr(ahk_mouse, "MouseMove", lambda x, y, speed=None, relative="": log.append(("move", x, y, relative)))
    monkeypatch.setattr(ahk_mouse, "MouseGetPos", lambda: (7, 8))
    monkeypatch.setattr(ahk_input, "PerformButton", lambda emitter, vk, kind: log.append(("button", vk, kind)))
    monkeypatch.setattr(ahk_input, "SendWheelNotches", lambda emitter, vk, notches: log.append(("wheel", vk, notches)))
    return log


def test_ClickMovesThenClicksAndCountZeroOnlyMoves(actions):
    ahk_mouse.Click("10 20 Right 2")
    assert actions == [("move", 10, 20, ""), ("button", 0x02, PRESS), ("button", 0x02, PRESS)]
    actions.clear()
    ahk_mouse.Click("10 20 0")
    assert actions == [("move", 10, 20, "")]


def test_ClickWheelTurnsCountNotchesAndDownHoldsTheButton(actions):
    ahk_mouse.Click("WD 3")
    ahk_mouse.Click("D")
    ahk_mouse.Click("Up")
    assert actions == [("wheel", 0x9E, 3), ("button", 0x01, DOWN), ("button", 0x01, UP)]


def test_MouseClickFillsAMissingAxisFromTheCursor(actions):
    ahk_mouse.MouseClick("left", None, 50, 1, 0, "U")
    assert actions == [("move", 7, 50, ""), ("button", 0x01, UP)]


def test_MouseClickDragHoldsTheButtonAcrossTheMove(actions):
    ahk_mouse.MouseClickDrag("left", 1, 2, 30, 40)
    assert actions == [("move", 1, 2, ""), ("button", 0x01, DOWN), ("move", 30, 40, ""), ("button", 0x01, UP)]
    actions.clear()
    ahk_mouse.MouseClickDrag("right", None, None, 5, 5, 0, "R")
    assert actions == [("button", 0x02, DOWN), ("move", 5, 5, "R"), ("button", 0x02, UP)]


def test_MouseClickInSendInputModeGoesOutInOneCall(monkeypatch):
    calls = []
    monkeypatch.setattr(ahk_input, "Inject", lambda *events: calls.append(len(events)))
    monkeypatch.setitem(ahk_input._settings, "mode", ahk_input.INPUT)
    ahk_mouse.MouseClick("left", None, None, 2)
    assert calls == [4]
    ahk_input.ReleaseHeldInputs()


# ---- CoordMode ----


def test_CoordModeDefaultsToClientAndOmittedRelativeToIsScreen(monkeypatch):
    monkeypatch.setattr(Coordinates, "_modes", dict(Coordinates._modes))
    assert Coordinates.CoordModeMouse() == "Client"
    assert Coordinates.CoordMode("Mouse") == "Client"
    assert Coordinates.CoordModeMouse() == "Screen"
    Coordinates.CoordMode("pixel", "window")
    assert Coordinates.CoordModePixel() == "Window"
    assert Coordinates.Origin("mouse") == (0, 0)
    with pytest.raises(ValueError):
        Coordinates.CoordMode("Mouse", "Desktop")
