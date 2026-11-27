import threading
import time

import pytest

from yorha import ClearStop, MacroStopped, MarkMacroThread, RequestStop, SetPaused, SetTimer, SetTimerOnOwnThread, Sleep


def _Counter():
    calls = []

    def Tick():
        calls.append(time.monotonic())

    return Tick, calls


def test_NegativePeriodRunsOnce():
    tick, calls = _Counter()
    SetTimer(tick, -20)
    time.sleep(0.2)
    assert len(calls) == 1


def test_PositivePeriodRepeatsUntilDeleted():
    tick, calls = _Counter()
    SetTimer(tick, 20)
    time.sleep(0.25)
    SetTimer(tick, 0)
    count = len(calls)
    time.sleep(0.1)
    assert count >= 3
    assert len(calls) == count


def test_DeleteBeforeItFires():
    tick, calls = _Counter()
    SetTimer(tick, -50)
    SetTimer(tick, 0)
    time.sleep(0.12)
    assert calls == []


def test_RaisingCallbackKeepsItsTimer(caplog):
    calls = []

    def Boom():
        calls.append(1)
        raise RuntimeError("boom")

    SetTimer(Boom, 20)
    deadline = time.monotonic() + 2.0
    while (len(calls) < 2) and (time.monotonic() < deadline):
        time.sleep(0.01)
    SetTimer(Boom, 0)
    assert len(calls) >= 2
    assert "boom" in caplog.text


def _RunMacro(body) -> list[object]:
    outcome: list[object] = []

    def Target():
        MarkMacroThread()
        try:
            body()
            outcome.append("done")
        except MacroStopped:
            outcome.append("stopped")

    thread = threading.Thread(target=Target)
    thread.start()
    return outcome, thread


@pytest.fixture
def cleanStop():
    yield
    SetPaused(False)
    ClearStop()


def test_SleepRaisesMacroStoppedAfterAStop(cleanStop):
    outcome, thread = _RunMacro(lambda: Sleep(5000))
    time.sleep(0.1)
    RequestStop()
    thread.join(1)
    assert outcome == ["stopped"]


def test_SleepHoldsWhilePaused(cleanStop):
    SetPaused(True)
    outcome, thread = _RunMacro(lambda: Sleep(10))
    time.sleep(0.2)
    assert outcome == []
    SetPaused(False)
    thread.join(1)
    assert outcome == ["done"]


def test_ATimerTheMacroSetsRunsApartAndAStopInterruptsIt():
    started = threading.Event()
    seen = {}

    def rotation():
        seen["thread"] = threading.current_thread().name
        started.set()
        Sleep(5000)
        seen["finished"] = True

    def Macro():
        MarkMacroThread()
        SetTimer(rotation, -1)

    ClearStop()
    setter = threading.Thread(target=Macro)
    setter.start()
    setter.join()
    assert started.wait(2)
    RequestStop()
    time.sleep(0.3)
    ClearStop()
    assert seen["thread"] == "macro-timers"
    assert "finished" not in seen


def test_OwnThreadTimerKeepsTickingWhileTheSharedThreadIsBusy():
    tick, calls = _Counter()
    names = []
    release = threading.Event()

    def Slow():
        release.wait(1.0)

    def Own():
        names.append(threading.current_thread().name)
        tick()

    SetTimer(Slow, -1)
    SetTimerOnOwnThread(Own, 20, "test-own")
    time.sleep(0.25)
    SetTimer(Own, 0)
    count = len(calls)
    release.set()
    time.sleep(0.1)
    assert count >= 3
    assert len(calls) == count
    assert set(names) == {"test-own"}
