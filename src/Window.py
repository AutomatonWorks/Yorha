"""WinTitle matching (SetTitleMatchMode 2, case-sensitive) and the Win* functions, plus monitors and DPI."""

from __future__ import annotations

import ctypes
import re
from ctypes import wintypes
from dataclasses import dataclass

from yorha import Win32Api as api
from yorha.Errors import TargetError
from yorha.Timing import Sleep, TickCount

PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
GWL_STYLE = -16
SW_MINIMIZE = 6
SW_RESTORE = 9
VK_MENU = 0x12
KEYEVENTF_KEYUP = 0x0002
SM_CXSCREEN = 0
SM_CYSCREEN = 1
MONITORINFOF_PRIMARY = 1
DPI_AWARENESS_PER_MONITOR_AWARE = 2
DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2 = -4
WIN_WAIT_POLL_MS = 50
ACTIVATE_ATTEMPTS = 2

_CRITERIA = re.compile(r"\s*\bahk_(exe|pid|id|class)\s+", re.IGNORECASE)
_settings = {"detect_hidden": False, "win_delay": 100}
_lastFound = [0]


@dataclass(frozen=True)
class WinCriteria:
    title: str = ""
    exe: str = ""
    pid: int = 0
    hwnd: int = 0
    windowClass: str = ""
    active: bool = False
    pureHwnd: bool = False


def ParseWinTitle(title: str | int) -> WinCriteria:
    """The criteria of an AHK WinTitle: "A", a title substring, ahk_exe/ahk_pid/ahk_id/ahk_class or an HWND."""
    if isinstance(title, int):
        return WinCriteria(hwnd=title, pureHwnd=True)
    if title == "A":
        return WinCriteria(active=True)
    parts = _CRITERIA.split(title)
    values: dict[str, str] = {}
    for index in range(1, len(parts) - 1, 2):
        values[parts[index].lower()] = parts[index + 1].strip()
    return WinCriteria(
        title=parts[0].strip() if values else parts[0],
        exe=values.get("exe", ""),
        pid=_AhkInt(values.get("pid", "0")),
        hwnd=_AhkInt(values.get("id", "0")),
        windowClass=values.get("class", ""),
    )


def _AhkInt(text: str) -> int:
    return int(text, 16) if text.lower().startswith("0x") else int(text)


def DetectHiddenWindows(state: bool) -> None:
    _settings["detect_hidden"] = state


def SetWinDelay(ms: int) -> None:
    _settings["win_delay"] = ms


def _WinDelay() -> None:
    if _settings["win_delay"] >= 0:
        Sleep(_settings["win_delay"])


# ---- window properties ----


def WinGetTitle(title: str | int) -> str:
    return _WindowText(_Require(title))


def _WindowText(hwnd: int) -> str:
    length = api.GetWindowTextLengthW(hwnd)
    buffer = ctypes.create_unicode_buffer(length + 1)
    api.GetWindowTextW(hwnd, buffer, length + 1)
    return buffer.value


def _ClassName(hwnd: int) -> str:
    buffer = ctypes.create_unicode_buffer(256)
    api.GetClassNameW(hwnd, buffer, 256)
    return buffer.value


def _WindowPid(hwnd: int) -> int:
    pid = wintypes.DWORD()
    api.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return pid.value


def ProcessImagePath(pid: int) -> str:
    handle = api.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return ""
    try:
        size = wintypes.DWORD(1024)
        buffer = ctypes.create_unicode_buffer(size.value)
        if not api.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size)):
            return ""
        return buffer.value
    finally:
        api.CloseHandle(handle)


# ---- matching ----


def WindowMatches(criteria: WinCriteria, hwnd: int, title: str, windowClass: str, pid: int, exePath: str) -> bool:
    """Whether a window with these properties meets `criteria` (title contains, case-sensitive)."""
    if criteria.hwnd and (hwnd != criteria.hwnd):
        return False
    if criteria.title and (criteria.title not in title):
        return False
    if criteria.windowClass and (criteria.windowClass != windowClass):
        return False
    if criteria.pid and (pid != criteria.pid):
        return False
    if criteria.exe:
        wanted = criteria.exe.lower()
        exe = exePath.lower() if ("\\" in wanted) else exePath.rsplit("\\", 1)[-1].lower()
        if exe != wanted:
            return False
    return True


def _Candidate(criteria: WinCriteria, hwnd: int) -> bool:
    if (not _settings["detect_hidden"]) and (not api.IsWindowVisible(hwnd)):
        return False
    pid = _WindowPid(hwnd) if (criteria.pid or criteria.exe) else 0
    exePath = ProcessImagePath(pid) if criteria.exe else ""
    title = _WindowText(hwnd) if criteria.title else ""
    windowClass = _ClassName(hwnd) if criteria.windowClass else ""
    return WindowMatches(criteria, hwnd, title, windowClass, pid, exePath)


def _TopLevelWindows() -> list[int]:
    found: list[int] = []

    def Collect(hwnd, _param):
        found.append(hwnd)
        return True

    api.EnumWindows(api.WNDENUMPROC(Collect), 0)
    return found


def _Find(title: str | int) -> int:
    if (title == "") or (title is None):
        last = _lastFound[0]
        return last if (last and api.IsWindow(last)) else 0
    criteria = ParseWinTitle(title)
    if criteria.active:
        return api.GetForegroundWindow() or 0
    if criteria.pureHwnd:
        return criteria.hwnd if api.IsWindow(criteria.hwnd) else 0
    if criteria.hwnd:
        return criteria.hwnd if (api.IsWindow(criteria.hwnd) and _Candidate(criteria, criteria.hwnd)) else 0
    for hwnd in _TopLevelWindows():
        if _Candidate(criteria, hwnd):
            return hwnd
    return 0


def _Require(title: str | int) -> int:
    hwnd = _Find(title)
    if not hwnd:
        raise TargetError(f"Target window not found: {title}")
    return hwnd


def WinExist(title: str | int = "") -> int:
    hwnd = _Find(title)
    if hwnd:
        _lastFound[0] = hwnd
    return hwnd


def WinActive(title: str | int = "") -> int:
    hwnd = _Find(title)
    if hwnd and (hwnd == api.GetForegroundWindow()):
        _lastFound[0] = hwnd
        return hwnd
    return 0


# ---- activation ----


def WinActivate(title: str | int = "") -> None:
    hwnd = _Require(title)
    _lastFound[0] = hwnd
    if api.IsIconic(hwnd):
        api.ShowWindow(hwnd, SW_RESTORE)
    if api.GetForegroundWindow() != hwnd:
        _ForceForeground(hwnd)
    _WinDelay()


def _ForceForeground(hwnd: int) -> None:
    """SetForegroundWindow with AHK's fallbacks: attach to the foreground thread's input, then Alt taps."""
    if api.SetForegroundWindow(hwnd) and (api.GetForegroundWindow() == hwnd):
        return
    if _AttachedActivate(hwnd):
        return
    for _ in range(ACTIVATE_ATTEMPTS):
        api.keybdEvent(VK_MENU, 0, 0, 0)
        api.keybdEvent(VK_MENU, 0, KEYEVENTF_KEYUP, 0)
    api.SetForegroundWindow(hwnd)
    api.BringWindowToTop(hwnd)


def _AttachedActivate(hwnd: int) -> bool:
    mine = api.GetCurrentThreadId()
    foregroundThread = api.GetWindowThreadProcessId(api.GetForegroundWindow(), None)
    targetThread = api.GetWindowThreadProcessId(hwnd, None)
    attached = [thread for thread in {foregroundThread, targetThread} if thread and (thread != mine)]
    for thread in attached:
        api.AttachThreadInput(mine, thread, True)
    try:
        api.SetForegroundWindow(hwnd)
        api.BringWindowToTop(hwnd)
    finally:
        for thread in attached:
            api.AttachThreadInput(mine, thread, False)
    return api.GetForegroundWindow() == hwnd


def WinWaitActive(title: str | int = "", timeoutS: float | None = None) -> int:
    """The active matching window's HWND, or 0 when `timeoutS` runs out first."""
    deadline = None if (timeoutS is None) else (TickCount() + (timeoutS * 1000))
    while True:
        hwnd = WinActive(title)
        if hwnd:
            _WinDelay()
            return hwnd
        if (deadline is not None) and (TickCount() >= deadline):
            return 0
        Sleep(WIN_WAIT_POLL_MS)


# ---- geometry and state ----


def ClientToScreen(hwnd: int, x: int, y: int) -> tuple[int, int]:
    point = wintypes.POINT(x, y)
    api.ClientToScreen(hwnd, ctypes.byref(point))
    return point.x, point.y


def ScreenToClient(hwnd: int, x: int, y: int) -> tuple[int, int]:
    point = wintypes.POINT(x, y)
    api.ScreenToClient(hwnd, ctypes.byref(point))
    return point.x, point.y


def WinGetClientPos(title: str | int = "") -> tuple[int, int, int, int]:
    """(x, y, width, height) of the client area, x and y in screen coordinates."""
    hwnd = _Require(title)
    rect = wintypes.RECT()
    api.GetClientRect(hwnd, ctypes.byref(rect))
    x, y = ClientToScreen(hwnd, 0, 0)
    return x, y, (rect.right - rect.left), (rect.bottom - rect.top)


def WinGetPos(title: str | int = "") -> tuple[int, int, int, int]:
    hwnd = _Require(title)
    rect = wintypes.RECT()
    api.GetWindowRect(hwnd, ctypes.byref(rect))
    return rect.left, rect.top, (rect.right - rect.left), (rect.bottom - rect.top)


def WinMove(x: int | None = None, y: int | None = None, width: int | None = None, height: int | None = None,
             title: str | int = "") -> None:
    """WinMove: a None argument keeps that part of the current position or size."""
    hwnd = _Require(title)
    current = WinGetPos(hwnd)
    wanted = [current[index] if (value is None) else value for index, value in enumerate((x, y, width, height))]
    api.MoveWindow(hwnd, wanted[0], wanted[1], wanted[2], wanted[3], True)
    _WinDelay()


def WinMinimize(title: str | int = "") -> None:
    api.ShowWindow(_Require(title), SW_MINIMIZE)
    _WinDelay()


def WinGetStyle(title: str | int = "") -> int:
    return api.GetWindowLongPtrW(_Require(title), GWL_STYLE) & 0xFFFFFFFF


def WinGetMinMax(title: str | int = "") -> int:
    """-1 minimized, 1 maximized, 0 neither."""
    hwnd = _Require(title)
    if api.IsIconic(hwnd):
        return -1
    return 1 if api.IsZoomed(hwnd) else 0


def WinGetPid(title: str | int = "") -> int:
    return _WindowPid(_Require(title))


# ---- monitors ----


def _Monitors() -> list[api.MONITORINFOEXW]:
    """Every monitor in EnumDisplayMonitors order, the numbering MonitorGet uses."""
    found: list[api.MONITORINFOEXW] = []

    def Collect(handle, _hdc, _rect, _param):
        info = api.MONITORINFOEXW()
        info.cbSize = ctypes.sizeof(api.MONITORINFOEXW)
        api.GetMonitorInfoW(handle, ctypes.byref(info))
        found.append(info)
        return True

    api.EnumDisplayMonitors(None, None, api.MONITORENUMPROC(Collect), 0)
    return found


def MonitorGetCount() -> int:
    return len(_Monitors())


def MonitorGetPrimary() -> int:
    for number, info in enumerate(_Monitors(), start=1):
        if info.dwFlags & MONITORINFOF_PRIMARY:
            return number
    return 1


def _Monitor(n: int | None) -> api.MONITORINFOEXW:
    monitors = _Monitors()
    index = MonitorGetPrimary() if (n is None) else n
    if not (1 <= index <= len(monitors)):
        raise ValueError(f"Monitor {n} does not exist")
    return monitors[index - 1]


def MonitorGet(n: int | None = None) -> tuple[int, int, int, int]:
    rect = _Monitor(n).rcMonitor
    return rect.left, rect.top, rect.right, rect.bottom


def MonitorGetWorkArea(n: int | None = None) -> tuple[int, int, int, int]:
    rect = _Monitor(n).rcWork
    return rect.left, rect.top, rect.right, rect.bottom


def ScreenWidth() -> int:
    return api.GetSystemMetrics(SM_CXSCREEN)


def ScreenHeight() -> int:
    return api.GetSystemMetrics(SM_CYSCREEN)


def EnsureDpiAwareness() -> None:
    """Per-monitor-v2 DPI awareness unless the process already has it (Qt sets it at startup)."""
    context = api.GetThreadDpiAwarenessContext()
    if api.GetAwarenessFromDpiAwarenessContext(context) != DPI_AWARENESS_PER_MONITOR_AWARE:
        api.SetProcessDpiAwarenessContext(DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2)
