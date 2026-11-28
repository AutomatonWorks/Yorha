"""ctypes declarations of the user32/kernel32 calls the yorha package makes.

Explicit argtypes and restypes keep 64-bit handles and pointer-sized values intact.
"""

from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes as w

IS_WINDOWS = sys.platform == "win32"


class _MissingFunction:
    """Stands in for a Win32 call off Windows, so importing the package works (CI collects on Linux)."""

    def __init__(self, name: str) -> None:
        self.name = name
        self.restype = None
        self.argtypes = ()

    def __call__(self, *args):
        raise OSError(f"{self.name} needs Windows")


class _MissingDll:
    def __getattr__(self, name: str) -> _MissingFunction:
        return _MissingFunction(name)


if IS_WINDOWS:
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _FUNCTYPE = ctypes.WINFUNCTYPE
else:
    user32 = _MissingDll()
    kernel32 = _MissingDll()
    _FUNCTYPE = ctypes.CFUNCTYPE

ULONG_PTR = ctypes.c_size_t
LONG_PTR = ctypes.c_ssize_t
LRESULT = ctypes.c_ssize_t

INPUT_MOUSE = 0
INPUT_KEYBOARD = 1


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", w.WORD), ("wScan", w.WORD), ("dwFlags", w.DWORD), ("time", w.DWORD),
                ("dwExtraInfo", ULONG_PTR)]


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", w.LONG), ("dy", w.LONG), ("mouseData", w.DWORD), ("dwFlags", w.DWORD),
                ("time", w.DWORD), ("dwExtraInfo", ULONG_PTR)]


class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [("uMsg", w.DWORD), ("wParamL", w.WORD), ("wParamH", w.WORD)]


class _INPUTUNION(ctypes.Union):
    _fields_ = [("ki", KEYBDINPUT), ("mi", MOUSEINPUT), ("hi", HARDWAREINPUT)]


class INPUT(ctypes.Structure):
    _fields_ = [("type", w.DWORD), ("u", _INPUTUNION)]


class KBDLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [("vkCode", w.DWORD), ("scanCode", w.DWORD), ("flags", w.DWORD), ("time", w.DWORD),
                ("dwExtraInfo", ULONG_PTR)]


class MSLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [("pt", w.POINT), ("mouseData", w.DWORD), ("flags", w.DWORD), ("time", w.DWORD),
                ("dwExtraInfo", ULONG_PTR)]


class MONITORINFOEXW(ctypes.Structure):
    _fields_ = [("cbSize", w.DWORD), ("rcMonitor", w.RECT), ("rcWork", w.RECT), ("dwFlags", w.DWORD),
                ("szDevice", w.WCHAR * 32)]


class PROCESSENTRY32W(ctypes.Structure):
    _fields_ = [("dwSize", w.DWORD), ("cntUsage", w.DWORD), ("th32ProcessID", w.DWORD),
                ("th32DefaultHeapID", ULONG_PTR), ("th32ModuleID", w.DWORD), ("cntThreads", w.DWORD),
                ("th32ParentProcessID", w.DWORD), ("pcPriClassBase", w.LONG), ("dwFlags", w.DWORD),
                ("szExeFile", w.WCHAR * 260)]


HOOKPROC = _FUNCTYPE(LRESULT, ctypes.c_int, w.WPARAM, w.LPARAM)
WNDENUMPROC = _FUNCTYPE(w.BOOL, w.HWND, w.LPARAM)
MONITORENUMPROC = _FUNCTYPE(w.BOOL, w.HMONITOR, w.HDC, ctypes.POINTER(w.RECT), w.LPARAM)


def _Proto(dll: ctypes.WinDLL, name: str, restype, *argtypes):
    function = getattr(dll, name)
    function.restype = restype
    function.argtypes = argtypes
    return function


# Input
SendInput = _Proto(user32, "SendInput", w.UINT, w.UINT, ctypes.POINTER(INPUT), ctypes.c_int)
mouseEvent = _Proto(user32, "mouse_event", None, w.DWORD, w.LONG, w.LONG, w.DWORD, ULONG_PTR)
keybdEvent = _Proto(user32, "keybd_event", None, w.BYTE, w.BYTE, w.DWORD, ULONG_PTR)
GetAsyncKeyState = _Proto(user32, "GetAsyncKeyState", w.SHORT, ctypes.c_int)
GetKeyState = _Proto(user32, "GetKeyState", w.SHORT, ctypes.c_int)
MapVirtualKeyW = _Proto(user32, "MapVirtualKeyW", w.UINT, w.UINT, w.UINT)
VkKeyScanW = _Proto(user32, "VkKeyScanW", w.SHORT, w.WCHAR)
GetCursorPos = _Proto(user32, "GetCursorPos", w.BOOL, ctypes.POINTER(w.POINT))
GetSystemMetrics = _Proto(user32, "GetSystemMetrics", ctypes.c_int, ctypes.c_int)
GetLastInputInfo = _Proto(user32, "GetLastInputInfo", w.BOOL, ctypes.c_void_p)
GetKeyboardLayout = _Proto(user32, "GetKeyboardLayout", w.HKL, w.DWORD)
ToUnicodeEx = _Proto(user32, "ToUnicodeEx", ctypes.c_int, w.UINT, w.UINT, ctypes.POINTER(ctypes.c_ubyte), w.LPWSTR,
                     ctypes.c_int, w.UINT, w.HKL)
GetTickCount = _Proto(kernel32, "GetTickCount", w.DWORD)

# Messages to windows that are not in front
PostMessageW = _Proto(user32, "PostMessageW", w.BOOL, w.HWND, w.UINT, w.WPARAM, w.LPARAM)
EnumChildWindows = _Proto(user32, "EnumChildWindows", w.BOOL, w.HWND, WNDENUMPROC, w.LPARAM)
ChildWindowFromPointEx = _Proto(user32, "ChildWindowFromPointEx", w.HWND, w.HWND, w.POINT, w.UINT)

# Windows
GetForegroundWindow = _Proto(user32, "GetForegroundWindow", w.HWND)
SetForegroundWindow = _Proto(user32, "SetForegroundWindow", w.BOOL, w.HWND)
BringWindowToTop = _Proto(user32, "BringWindowToTop", w.BOOL, w.HWND)
AttachThreadInput = _Proto(user32, "AttachThreadInput", w.BOOL, w.DWORD, w.DWORD, w.BOOL)
EnumWindows = _Proto(user32, "EnumWindows", w.BOOL, WNDENUMPROC, w.LPARAM)
IsWindow = _Proto(user32, "IsWindow", w.BOOL, w.HWND)
IsWindowVisible = _Proto(user32, "IsWindowVisible", w.BOOL, w.HWND)
IsIconic = _Proto(user32, "IsIconic", w.BOOL, w.HWND)
IsZoomed = _Proto(user32, "IsZoomed", w.BOOL, w.HWND)
GetWindowTextLengthW = _Proto(user32, "GetWindowTextLengthW", ctypes.c_int, w.HWND)
GetWindowTextW = _Proto(user32, "GetWindowTextW", ctypes.c_int, w.HWND, w.LPWSTR, ctypes.c_int)
GetClassNameW = _Proto(user32, "GetClassNameW", ctypes.c_int, w.HWND, w.LPWSTR, ctypes.c_int)
GetWindowThreadProcessId = _Proto(user32, "GetWindowThreadProcessId", w.DWORD, w.HWND, ctypes.POINTER(w.DWORD))
GetClientRect = _Proto(user32, "GetClientRect", w.BOOL, w.HWND, ctypes.POINTER(w.RECT))
GetWindowRect = _Proto(user32, "GetWindowRect", w.BOOL, w.HWND, ctypes.POINTER(w.RECT))
ClientToScreen = _Proto(user32, "ClientToScreen", w.BOOL, w.HWND, ctypes.POINTER(w.POINT))
ScreenToClient = _Proto(user32, "ScreenToClient", w.BOOL, w.HWND, ctypes.POINTER(w.POINT))
MoveWindow = _Proto(user32, "MoveWindow", w.BOOL, w.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                    ctypes.c_int, w.BOOL)
ShowWindow = _Proto(user32, "ShowWindow", w.BOOL, w.HWND, ctypes.c_int)
GetWindowLongPtrW = _Proto(user32, "GetWindowLongPtrW", LONG_PTR, w.HWND, ctypes.c_int)

# Monitors and DPI
EnumDisplayMonitors = _Proto(user32, "EnumDisplayMonitors", w.BOOL, w.HDC, ctypes.POINTER(w.RECT),
                             MONITORENUMPROC, w.LPARAM)
GetMonitorInfoW = _Proto(user32, "GetMonitorInfoW", w.BOOL, w.HMONITOR, ctypes.POINTER(MONITORINFOEXW))
GetThreadDpiAwarenessContext = _Proto(user32, "GetThreadDpiAwarenessContext", ctypes.c_void_p)
GetAwarenessFromDpiAwarenessContext = _Proto(user32, "GetAwarenessFromDpiAwarenessContext", ctypes.c_int,
                                             ctypes.c_void_p)
SetProcessDpiAwarenessContext = _Proto(user32, "SetProcessDpiAwarenessContext", w.BOOL, ctypes.c_void_p)

# Hooks and message loop
SetWindowsHookExW = _Proto(user32, "SetWindowsHookExW", w.HHOOK, ctypes.c_int, HOOKPROC, w.HINSTANCE, w.DWORD)
UnhookWindowsHookEx = _Proto(user32, "UnhookWindowsHookEx", w.BOOL, w.HHOOK)
CallNextHookEx = _Proto(user32, "CallNextHookEx", LRESULT, w.HHOOK, ctypes.c_int, w.WPARAM, w.LPARAM)
GetMessageW = _Proto(user32, "GetMessageW", w.BOOL, ctypes.POINTER(w.MSG), w.HWND, w.UINT, w.UINT)
PostThreadMessageW = _Proto(user32, "PostThreadMessageW", w.BOOL, w.DWORD, w.UINT, w.WPARAM, w.LPARAM)

# Processes
GetCurrentThreadId = _Proto(kernel32, "GetCurrentThreadId", w.DWORD)
GetCurrentProcessId = _Proto(kernel32, "GetCurrentProcessId", w.DWORD)
GetModuleHandleW = _Proto(kernel32, "GetModuleHandleW", w.HMODULE, w.LPCWSTR)
OpenProcess = _Proto(kernel32, "OpenProcess", w.HANDLE, w.DWORD, w.BOOL, w.DWORD)
CloseHandle = _Proto(kernel32, "CloseHandle", w.BOOL, w.HANDLE)
QueryFullProcessImageNameW = _Proto(kernel32, "QueryFullProcessImageNameW", w.BOOL, w.HANDLE, w.DWORD, w.LPWSTR,
                                    ctypes.POINTER(w.DWORD))
TerminateProcess = _Proto(kernel32, "TerminateProcess", w.BOOL, w.HANDLE, w.UINT)
GetProcessTimes = _Proto(kernel32, "GetProcessTimes", w.BOOL, w.HANDLE, ctypes.POINTER(w.FILETIME),
                         ctypes.POINTER(w.FILETIME), ctypes.POINTER(w.FILETIME), ctypes.POINTER(w.FILETIME))
GetExitCodeProcess = _Proto(kernel32, "GetExitCodeProcess", w.BOOL, w.HANDLE, ctypes.POINTER(w.DWORD))
CreateToolhelp32Snapshot = _Proto(kernel32, "CreateToolhelp32Snapshot", w.HANDLE, w.DWORD, w.DWORD)
Process32FirstW = _Proto(kernel32, "Process32FirstW", w.BOOL, w.HANDLE, ctypes.POINTER(PROCESSENTRY32W))
Process32NextW = _Proto(kernel32, "Process32NextW", w.BOOL, w.HANDLE, ctypes.POINTER(PROCESSENTRY32W))
