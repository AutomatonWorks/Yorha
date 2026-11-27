import sys

import pytest

from yorha import MonitorGet, MonitorGetCount, MonitorGetPrimary, MouseGetPos, TargetError, WinExist, WinGetPos
from yorha import Win32Api as api
from yorha.Window import ParseWinTitle, WinCriteria, WindowMatches

windowsOnly = pytest.mark.skipif(sys.platform != "win32", reason="needs real Windows windows")


def test_ParseActiveAndHwnd():
    assert ParseWinTitle("A") == WinCriteria(active=True)
    assert ParseWinTitle(0x1234) == WinCriteria(hwnd=0x1234, pureHwnd=True)


def test_ParseTitleWithCriteria():
    criteria = ParseWinTitle("Zenless Zone Zero ahk_exe ZenlessZoneZero.exe")
    assert (criteria.title, criteria.exe) == ("Zenless Zone Zero", "ZenlessZoneZero.exe")
    assert ParseWinTitle("ahk_pid 42").pid == 42
    assert ParseWinTitle("ahk_id 0x10").hwnd == 0x10
    assert ParseWinTitle("ahk_class Notepad").windowClass == "Notepad"


def test_PlainTitleKeepsItsSpaces():
    assert ParseWinTitle(" Title ").title == " Title "


def test_MatchIsContainsAndCaseSensitive():
    criteria = ParseWinTitle("Zone")
    assert WindowMatches(criteria, 1, "Zenless Zone Zero", "", 0, "")
    assert not WindowMatches(criteria, 1, "zenless zone zero", "", 0, "")


def test_ExeMatchesNameCaseInsensitivelyOrFullPath():
    path = "path\\to\\ZenlessZoneZero.exe"
    assert WindowMatches(ParseWinTitle("ahk_exe zenlesszonezero.exe"), 1, "", "", 7, path)
    assert WindowMatches(ParseWinTitle("ahk_exe " + path), 1, "", "", 7, path)
    assert not WindowMatches(ParseWinTitle("ahk_exe other.exe"), 1, "", "", 7, path)
    assert not WindowMatches(ParseWinTitle("ahk_pid 8"), 1, "", "", 7, path)


@windowsOnly
def test_ActiveWindowAndMonitorOnThisMachine():
    assert WinExist("A") != 0
    left, top, right, bottom = MonitorGet(1)
    assert (right > left) and (bottom > top)
    assert MonitorGetCount() >= 1
    x, y = MouseGetPos()
    assert isinstance(x, int) and isinstance(y, int)


@windowsOnly
def test_MonitorsFollowEnumDisplayMonitorsOrder():
    rects = []

    def Collect(_handle, _hdc, rect, _param):
        bounds = rect.contents
        rects.append((bounds.left, bounds.top, bounds.right, bounds.bottom))
        return True

    api.EnumDisplayMonitors(None, None, api.MONITORENUMPROC(Collect), 0)
    assert [MonitorGet(n) for n in range(1, MonitorGetCount() + 1)] == rects
    primary = MonitorGet(MonitorGetPrimary())
    assert (primary[0], primary[1]) == (0, 0)
    assert MonitorGet() == primary


@windowsOnly
def test_MissingWindowRaisesTargetError():
    with pytest.raises(TargetError):
        WinGetPos("no window has this title 9f3c1e ahk_exe nothing-9f3c1e.exe")
    with pytest.raises(ValueError):
        MonitorGet(99)
