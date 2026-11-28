import random

from yorha import MouseMotion


def test_SpeedZeroIsAnInstantJump():
    assert MouseMotion.DurationMs((0, 0), (500, 0), 0, 1000) == 0


def test_SpeedHundredAcrossTheDiagonalTakesTheSlowestDuration():
    assert MouseMotion.DurationMs((0, 0), (600, 800), 100, 1000) == MouseMotion.SLOWEST_FULL_MOVE_MS


def test_DurationDependsOnTheShareOfTheWindowNotOnPixels():
    small = MouseMotion.DurationMs((0, 0), (200, 0), 40, 1000)
    large = MouseMotion.DurationMs((0, 0), (800, 0), 40, 4000)
    assert small == large


def test_AShortHopStillTakesAVisibleShareOfALongMove():
    hop = MouseMotion.DurationMs((0, 0), (100, 0), 60, 1000)
    full = MouseMotion.DurationMs((0, 0), (1000, 0), 60, 1000)
    assert hop > (full / 4)


def test_TheEasedPathStartsAndEndsOnItsPoints():
    control = MouseMotion.ControlPoint((0, 0), (900, 300), 0, random.Random(1))
    assert MouseMotion.PointAt((0, 0), control, (900, 300), 0) == (0, 0)
    assert MouseMotion.PointAt((0, 0), control, (900, 300), 1) == (900, 300)


def test_CurveZeroKeepsTheControlPointOnTheLine():
    control = MouseMotion.ControlPoint((0, 0), (900, 0), 0, random.Random(1))
    assert control[1] == 0


def test_MoreCurveBowsThePathFurther():
    gentle = MouseMotion.ControlPoint((0, 0), (900, 0), 20, random.Random(7))
    strong = MouseMotion.ControlPoint((0, 0), (900, 0), 100, random.Random(7))
    assert abs(strong[1]) > abs(gentle[1]) > 0
