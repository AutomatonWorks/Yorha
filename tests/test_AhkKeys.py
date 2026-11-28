import sys

import pytest

from yorha import GetKeyName, GetKeySC, GetKeyVK, KeyState

windowsOnly = pytest.mark.skipif(sys.platform != "win32", reason="needs the Windows keyboard layout")


def test_GetKeyNameReturnsTheCanonicalSpelling():
    assert GetKeyName("Esc") == "Escape"
    assert GetKeyName("vk1B") == "Escape"
    assert GetKeyName("Return") == "Enter"
    assert GetKeyName("Del") == "Delete"
    assert GetKeyName("NumpadEnter") == "NumpadEnter"
    assert GetKeyName("Ctrl") == "Control"
    assert GetKeyName("LCtrl") == "LControl"
    assert GetKeyName("A") == "a"
    assert GetKeyName("lbutton") == "LButton"


def test_UnknownKeysGiveBlankAndZero():
    assert GetKeyName("NotAKey") == ""
    assert GetKeyVK("NotAKey") == 0
    assert GetKeySC("NotAKey") == 0


def test_GetKeyVK():
    assert GetKeyVK("Enter") == 0x0D
    assert GetKeyVK("LButton") == 0x01
    assert GetKeyVK("F1") == 0x70


@windowsOnly
def test_GetKeySCAddsTheExtendedFlagAndGivesMouseButtonsZero():
    assert GetKeySC("Enter") == 0x1C
    assert GetKeySC("NumpadEnter") == 0x11C
    assert GetKeySC("Up") == 0x148
    assert GetKeySC("RCtrl") == 0x11D
    assert GetKeySC("PrintScreen") == 0x137
    assert GetKeySC("sc01E") == 0x1E
    assert GetKeySC("LButton") == 0


@windowsOnly
def test_GetKeyNameOfAScanCodeIsTheKeyItTypes():
    assert GetKeyName("sc01E") == "a"


# ---- KeyWait ----


@pytest.fixture
def keyboard(monkeypatch):
    """A key that is down for the first `downPolls` checks, on a clock Sleep moves forward."""
    state = {"downPolls": 0, "checks": 0, "now": 0, "physical": []}

    def IsDown(key, physical):
        state["checks"] += 1
        state["physical"].append(physical)
        return state["checks"] <= state["downPolls"]

    def FakeSleep(ms):
        state["now"] += ms

    monkeypatch.setattr(KeyState, "_IsDown", IsDown)
    monkeypatch.setattr(KeyState, "Sleep", FakeSleep)
    monkeypatch.setattr(KeyState, "TickCount", lambda: state["now"])
    return state


def test_KeyWaitReturnsOnceTheKeyIsReleased(keyboard):
    keyboard["downPolls"] = 3
    assert KeyState.KeyWait("RButton") == 1
    assert keyboard["checks"] == 4
    assert all(keyboard["physical"])


def test_KeyWaitTimesOutWithZero(keyboard):
    keyboard["downPolls"] = 10_000
    assert KeyState.KeyWait("f", "T0.5") == 0
    assert 500 <= keyboard["now"] <= 520


def test_KeyWaitDWaitsForThePressAndLChecksTheLogicalState(keyboard):
    assert KeyState.KeyWait("f", "D L T1") == 0
    assert not any(keyboard["physical"])
    keyboard.update(downPolls=1, checks=0)
    assert KeyState.KeyWait("f", "DT2") == 1


def test_KeyWaitRejectsUnknownKeys():
    with pytest.raises(ValueError):
        KeyState.KeyWait("NotAKey")


def test_MouseButtonsHaveNoHookStateWithoutTheMouseHook(monkeypatch):
    from yorha import Hotkeys
    from yorha.KeyCodes import GetKeyCode
    monkeypatch.setitem(Hotkeys._hook, "keyboard", 1)
    monkeypatch.setitem(Hotkeys._hook, "mouse", None)
    assert Hotkeys.PhysicalKeyDown(GetKeyCode("LButton")) is None
    assert Hotkeys.PhysicalKeyDown(GetKeyCode("a")) is False
