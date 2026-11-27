"""AHK error classes with no direct Python equivalent."""


class TargetError(RuntimeError):
    """AHK TargetError: the window or control a function needs was not found."""
