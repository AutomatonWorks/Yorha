import threading

import pytest

from yorha import HotkeyContext, InputLevel
from yorha.HotkeyMatcher import HotkeyMatcher, ParseHotkey

F5 = 0x74


@pytest.fixture
def clock(monkeypatch):
    now = {"tick": 1000}
    monkeypatch.setattr(HotkeyContext, "_Tick", lambda: now["tick"])
    monkeypatch.setattr(HotkeyContext, "_global", {"this": None, "prior": None})
    monkeypatch.setattr(HotkeyContext, "_history", type(HotkeyContext._history)(maxlen=HotkeyContext.KEY_HISTORY_SIZE))
    HotkeyContext.HotkeyFinished()
    return now


def test_NothingFiredYet(clock):
    assert (HotkeyContext.ThisHotkey(), HotkeyContext.PriorHotkey()) == ("", "")
    assert HotkeyContext.TimeSinceThisHotkey() == HotkeyContext.NO_HOTKEY_TIME
    assert HotkeyContext.TimeSincePriorHotkey() == HotkeyContext.NO_HOTKEY_TIME


def test_ThisAndPriorHotkeyWithTheTimeSinceEachWasPressed(clock):
    HotkeyContext.HotkeyStarted("~F1", 900)
    HotkeyContext.HotkeyFinished()
    HotkeyContext.HotkeyStarted("^F2", 990)
    assert (HotkeyContext.ThisHotkey(), HotkeyContext.PriorHotkey()) == ("^F2", "~F1")
    assert (HotkeyContext.TimeSinceThisHotkey(), HotkeyContext.TimeSincePriorHotkey()) == (10, 100)
    HotkeyContext.HotkeyFinished()


def test_ACallbackKeepsItsOwnHotkeyWhileAnotherFiresElsewhere(clock):
    HotkeyContext.HotkeyStarted("F1", 1000)
    seenElsewhere = []
    other = threading.Thread(target=lambda: (HotkeyContext.HotkeyStarted("F2", 1000),
                                             seenElsewhere.append(HotkeyContext.ThisHotkey()),
                                             HotkeyContext.HotkeyFinished()))
    other.start()
    other.join()
    assert seenElsewhere == ["F2"]
    assert HotkeyContext.ThisHotkey() == "F1"
    HotkeyContext.HotkeyFinished()
    assert HotkeyContext.ThisHotkey() == "F2"


def test_PriorKeyIsTheLastPressBeforeTheLatestEvent(clock):
    HotkeyContext.RecordKey("a", False)
    HotkeyContext.RecordKey("a", True)
    HotkeyContext.RecordKey("LButton", False)
    assert HotkeyContext.PriorKey() == "a"
    HotkeyContext.RecordKey("LButton", True)
    assert HotkeyContext.PriorKey() == "LButton"


def test_PhysicalIdleTimesCountFromTheLastPhysicalEventWhileTheHookRuns(clock, monkeypatch):
    monkeypatch.setattr(HotkeyContext, "TimeIdle", lambda: 5)
    monkeypatch.setattr(HotkeyContext, "_physicalTicks", {"keyboard": 0, "mouse": 0})
    assert HotkeyContext.TimeIdlePhysical() == 5
    HotkeyContext.HookInstalled("keyboard", True)
    HotkeyContext.RecordPhysical("keyboard")
    clock["tick"] += 300
    assert HotkeyContext.TimeIdleKeyboard() == 300
    assert HotkeyContext.TimeIdleMouse() == 5
    assert HotkeyContext.TimeIdlePhysical() == 5


# ---- SendLevel against hotkey input levels ----


def _Matcher(name: str, level: int = 0) -> HotkeyMatcher:
    matcher = HotkeyMatcher()
    matcher.hotkeys[name.lower()] = ParseHotkey(name)
    matcher.enabled.add(name.lower())
    if level:
        matcher.levels[name.lower()] = level
    return matcher


def test_GeneratedInputFiresOnlyHotkeysOfALowerInputLevel():
    assert _Matcher("F5").event(F5, False, False, level=1).fire == ["F5"]
    assert _Matcher("F5", level=1).event(F5, False, False, level=1).fire == []
    assert _Matcher("F5", level=1).event(F5, False, False, level=2).fire == ["F5"]
    assert _Matcher("F5", level=5).event(F5, False, False).fire == ["F5"]


def test_GeneratedKeysDoNotCountAsPhysicallyHeld():
    matcher = _Matcher("F5")
    matcher.event(F5, False, False, level=1)
    assert not matcher.PhysicalDown(ParseHotkey("F5").key)
    matcher.event(F5, False, False)
    assert matcher.PhysicalDown(ParseHotkey("F5").key)


def test_TheHookSeesPhysicalInputAndAhkInputAboveLevelZeroOnly():
    from yorha import Hotkeys
    assert Hotkeys._HotkeysSee(False, None)
    assert not Hotkeys._HotkeysSee(True, None)
    assert not Hotkeys._HotkeysSee(True, InputLevel.LevelOf(InputLevel.ExtraInfo(0)))
    assert Hotkeys._HotkeysSee(True, InputLevel.LevelOf(InputLevel.ExtraInfo(1)))


def test_HotkeyOptionISetsTheInputLevel():
    from yorha import Hotkeys
    try:
        Hotkeys.Hotkey("F5", lambda name: None, "I2")
        assert Hotkeys._matcher.levels["f5"] == 2
    finally:
        Hotkeys.ClearHotkeys()
    assert Hotkeys._matcher.levels == {}


def test_TheKeyboardHookRecordsHistoryAndFeedsInputHooksButSkipsItsOwnLevelZeroInput(clock, monkeypatch):
    from yorha import Hotkeys, InputCapture
    from yorha import Win32Api as api
    fed = []
    decided = []
    monkeypatch.setattr(InputCapture, "Feed", lambda vk, sc, extended, up, level, held: fed.append((vk, level)) or False)
    monkeypatch.setattr(Hotkeys, "_Decide", lambda vk, extended, up, level: decided.append(vk) or False)
    physical = api.KBDLLHOOKSTRUCT(0x41, 0x1E, 0, 0, 0)
    generated = api.KBDLLHOOKSTRUCT(0x42, 0x30, Hotkeys.LLKHF_INJECTED, 0, InputLevel.ExtraInfo(0))
    raised = api.KBDLLHOOKSTRUCT(0x43, 0x2E, Hotkeys.LLKHF_INJECTED, 0, InputLevel.ExtraInfo(2))
    for info in (physical, generated, raised):
        Hotkeys._OnKeyEvent(info, False)
    assert decided == [0x41, 0x43]
    assert fed == [(0x41, None), (0x42, 0), (0x43, 2)]
    assert list(HotkeyContext._history) == [("a", False)]
