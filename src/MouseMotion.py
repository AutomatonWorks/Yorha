"""The path of a MouseMove: how long it takes, its eased progress and its optional arc."""

from __future__ import annotations

import math
import random

MAX_MOUSE_SPEED = 100
# Speed 100 across the whole window diagonal; any other move scales from it.
SLOWEST_FULL_MOVE_MS = 5000
MAX_CURVE = 100
# Curve 100 bows the path sideways by up to this share of its length.
MAX_BOW_RATIO = 0.3
BOW_POSITION_RANGE = (0.35, 0.65)

Point = tuple[float, float]


def DurationMs(start: Point, target: Point, speed: int, diagonal: float) -> float:
    """0 for an instant jump. Measured against the window diagonal so every resolution takes the same time,
    and by its square root so a short hop still glides visibly."""
    if (speed <= 0) or (diagonal <= 0):
        return 0.0
    share = min(1.0, math.dist(start, target) / diagonal)
    return (min(speed, MAX_MOUSE_SPEED) / MAX_MOUSE_SPEED) * SLOWEST_FULL_MOVE_MS * math.sqrt(share)


def ControlPoint(start: Point, target: Point, curve: int, rng: random.Random | None = None) -> Point:
    """The quadratic Bezier control point: on the straight line for curve 0, pushed to a random side otherwise."""
    rng = rng or random
    along = rng.uniform(*BOW_POSITION_RANGE)
    base = (start[0] + ((target[0] - start[0]) * along), start[1] + ((target[1] - start[1]) * along))
    length = math.dist(start, target)
    if (curve <= 0) or (length == 0):
        return base
    bow = length * MAX_BOW_RATIO * (min(curve, MAX_CURVE) / MAX_CURVE)
    side = rng.choice((-1, 1))
    normalX = -(target[1] - start[1]) / length
    normalY = (target[0] - start[0]) / length
    # A quadratic Bezier peaks at half its control point's offset.
    return (base[0] + (normalX * bow * 2 * side), base[1] + (normalY * bow * 2 * side))


def PointAt(start: Point, control: Point, target: Point, progress: float) -> tuple[int, int]:
    """Where the cursor is at `progress` (0-1 of the duration): eased in and out along the Bezier."""
    t = (1 - math.cos(math.pi * min(1.0, max(0.0, progress)))) / 2
    inverse = 1 - t
    x = (inverse * inverse * start[0]) + (2 * inverse * t * control[0]) + (t * t * target[0])
    y = (inverse * inverse * start[1]) + (2 * inverse * t * control[1]) + (t * t * target[1])
    return round(x), round(y)
