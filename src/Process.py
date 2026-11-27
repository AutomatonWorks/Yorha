"""ProcessExist, ProcessClose, Run, RunWait and the admin checks."""

from __future__ import annotations

import ctypes
import os
import subprocess
import sys
import time
from ctypes import wintypes
from pathlib import Path

from yorha import Win32Api as api
from yorha.Timing import Sleep

if sys.platform == "win32":
    import pywintypes
    import win32process
    from win32com.shell import shell

    import win32api

TH32CS_SNAPPROCESS = 0x00000002
INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value
PROCESS_TERMINATE = 0x0001
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
SYNCHRONIZE = 0x00100000
STILL_ACTIVE = 259
SEE_MASK_NOCLOSEPROCESS = 0x00000040
STARTF_USESHOWWINDOW = 0x00000001
SHOW_COMMANDS = {"": 1, "hide": 0, "min": 6, "max": 3}
FILETIME_UNIX_EPOCH = 116444736000000000
FILETIME_TICKS_PER_MS = 10000
RUN_WAIT_POLL_MS = 50

_children: list[subprocess.Popen] = []


# ---- process lookup ----


def _ProcessEntries() -> list[tuple[int, str]]:
    snapshot = api.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if snapshot == INVALID_HANDLE_VALUE:
        raise OSError(ctypes.get_last_error(), "CreateToolhelp32Snapshot failed")
    entries = []
    try:
        entry = api.PROCESSENTRY32W()
        entry.dwSize = ctypes.sizeof(api.PROCESSENTRY32W)
        more = api.Process32FirstW(snapshot, ctypes.byref(entry))
        while more:
            entries.append((entry.th32ProcessID, entry.szExeFile))
            more = api.Process32NextW(snapshot, ctypes.byref(entry))
    finally:
        api.CloseHandle(snapshot)
    return entries


def ProcessExist(nameOrPid: str | int | None = None) -> int:
    """The PID of the first process with that name or PID, 0 when none; no argument = this process."""
    if (nameOrPid is None) or (nameOrPid == ""):
        return api.GetCurrentProcessId()
    text = str(nameOrPid)
    if text.isdigit():
        pid = int(text)
        return pid if any(entryPid == pid for entryPid, _ in _ProcessEntries()) else 0
    wanted = text.lower()
    for pid, exe in _ProcessEntries():
        if exe.lower() == wanted:
            return pid
    return 0


def ProcessClose(nameOrPid: str | int) -> int:
    """Terminates the process and returns its PID, or 0 when it was not found or could not be closed."""
    pid = ProcessExist(nameOrPid)
    if not pid:
        return 0
    handle = api.OpenProcess(PROCESS_TERMINATE, False, pid)
    if not handle:
        return 0
    try:
        return pid if api.TerminateProcess(handle, 0) else 0
    finally:
        api.CloseHandle(handle)


def ProcessStartTimeMs(pid: int) -> int:
    """When the process started, in Unix epoch milliseconds."""
    handle = api.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        raise OSError(ctypes.get_last_error(), f"Cannot open process {pid}")
    try:
        times = [wintypes.FILETIME() for _ in range(4)]
        if not api.GetProcessTimes(handle, *(ctypes.byref(time) for time in times)):
            raise OSError(ctypes.get_last_error(), f"GetProcessTimes failed for {pid}")
        created = (times[0].dwHighDateTime << 32) | times[0].dwLowDateTime
        return (created - FILETIME_UNIX_EPOCH) // FILETIME_TICKS_PER_MS
    finally:
        api.CloseHandle(handle)


# ---- launching ----


def _ShowCommand(options: str) -> int:
    for word in options.lower().split():
        if word in SHOW_COMMANDS:
            return SHOW_COMMANDS[word]
    return SHOW_COMMANDS[""]


def _SplitTarget(target: str) -> tuple[str, str, str]:
    """(verb, file, parameters) of a Run target, honouring a leading *Verb and a quoted file."""
    verb = ""
    if target.startswith("*"):
        verb, _, target = target[1:].partition(" ")
        target = target.strip()
    if target.startswith('"'):
        file, _, params = target[1:].partition('"')
        return verb, file, params.strip()
    if Path(target).exists():
        return verb, target, ""
    file, _, params = target.partition(" ")
    return verb, file, params.strip()


def _ShellExecute(verb: str, file: str, params: str, workingDir: str, show: int) -> int:
    """ShellExecuteEx; returns the process handle (0 when the shell reused a running process)."""
    # pywin32 rejects None for its string fields: leave out the empty ones.
    optional = {"lpVerb": verb, "lpParameters": params, "lpDirectory": workingDir}
    given = {key: value for key, value in optional.items() if value}
    try:
        info = shell.ShellExecuteEx(fMask=SEE_MASK_NOCLOSEPROCESS, lpFile=file, nShow=show, **given)
    except pywintypes.error as error:
        raise OSError(error.winerror, f"Failed attempt to launch program or document: {file}") from error
    handle = info.get("hProcess")
    # Detached, or the PyHANDLE would close it when collected.
    return handle.Detach() if handle else 0


def _Launch(target: str, workingDir: str, options: str) -> subprocess.Popen | int:
    """A Popen for what CreateProcess can start, else the handle ShellExecuteEx returns."""
    show = _ShowCommand(options)
    verb, file, params = _SplitTarget(target)
    if not verb:
        startup = subprocess.STARTUPINFO(dwFlags=STARTF_USESHOWWINDOW, wShowWindow=show)
        try:
            return subprocess.Popen(target, cwd=workingDir or None, startupinfo=startup)
        except OSError:
            pass
    return _ShellExecute(verb, file, params, workingDir, show)


def Run(target: str, workingDir: str = "", options: str = "") -> int:
    """Run: starts `target` without waiting and returns its PID (0 when the shell started none)."""
    launched = _Launch(target, workingDir, options)
    if isinstance(launched, subprocess.Popen):
        _children[:] = [child for child in _children if child.poll() is None]
        _children.append(launched)
        return launched.pid
    if not launched:
        return 0
    pid = win32process.GetProcessId(launched)
    win32api.CloseHandle(launched)
    return pid


def RunWait(target: str, workingDir: str = "", options: str = "") -> int:
    """RunWait: starts `target` and waits (through sleep, so a stop applies) for its exit code."""
    launched = _Launch(target, workingDir, options)
    if isinstance(launched, subprocess.Popen):
        while launched.poll() is None:
            Sleep(RUN_WAIT_POLL_MS)
        return launched.returncode
    if not launched:
        return 0
    try:
        while win32process.GetExitCodeProcess(launched) == STILL_ACTIVE:
            Sleep(RUN_WAIT_POLL_MS)
        return win32process.GetExitCodeProcess(launched)
    finally:
        win32api.CloseHandle(launched)


# ---- elevation ----


def IsAdmin() -> bool:
    return bool(ctypes.windll.shell32.IsUserAnAdmin())


def RelaunchAsAdmin(argv: list[str]) -> bool:
    """Starts this program again elevated (UAC "runas") with `argv` (sys.argv); the caller exits after.
    False when the user declined the prompt."""
    frozen = getattr(sys, "frozen", False)
    arguments = argv[1:] if frozen else argv
    executable = sys.executable
    if not frozen:
        # like AutoHotkey.exe: no console of its own, so the Dev console is the one SetupConsole allocates and places
        executable = str(Path(sys.executable).with_name("pythonw.exe"))
    try:
        handle = _ShellExecute("runas", executable, subprocess.list2cmdline(arguments), "",
                                SHOW_COMMANDS[""])
    except OSError:
        return False
    if handle:
        win32api.CloseHandle(handle)
    return True


# The new copy is told which process it replaces: it loads while that one exits and waits for it in
# WaitForReplacedProcess before doing anything the two would share (single instance, hooks).
WAIT_FOR_PID_ENV = "AUTOMATON_WAIT_FOR_PID"
SYNCHRONIZE = 0x00100000
REPLACED_PROCESS_TIMEOUT_MS = 30000


def RelaunchOverlapped(argv: list[str]) -> None:
    """Starts `argv` (interpreter first) right away; the caller exits right after."""
    env = dict(os.environ)
    env[WAIT_FOR_PID_ENV] = str(os.getpid())
    # a onefile exe would otherwise reuse this process's unpack folder, which is deleted when this one exits
    env["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
    subprocess.Popen(argv, env=env)


def WaitForReplacedProcess() -> float:
    """Waits for the process this one replaces (RelaunchOverlapped) to end; returns the ms waited, 0 without one."""
    pid = os.environ.pop(WAIT_FOR_PID_ENV, "")
    if not pid:
        return 0.0
    started = time.perf_counter()
    kernel32 = ctypes.windll.kernel32
    handle = kernel32.OpenProcess(SYNCHRONIZE, False, int(pid))
    if handle:
        kernel32.WaitForSingleObject(handle, REPLACED_PROCESS_TIMEOUT_MS)
        kernel32.CloseHandle(handle)
    return round((time.perf_counter() - started) * 1000, 1)
