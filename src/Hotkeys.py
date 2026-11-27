"""Global hotkeys with AHK syntax: a hook thread that only decides and queues, and a dispatcher thread
that runs the callbacks."""

from __future__ import annotations

import ctypes
import logging
import queue
import sys
import threading
from collections.abc import Callable
from ctypes import wintypes

from yorha import Input as ahk_input
from yorha import Win32Api as api
from yorha.HotkeyMatcher import MENU_MASK_KEY, Decision, HotkeyMatcher, IsMouseHotkey, ParseHotkey
from yorha.KeyCodes import KeyCode

WH_KEYBOARD_LL = 13
WH_MOUSE_LL = 14
HC_ACTION = 0
WM_QUIT = 0x0012
WM_APP_INSTALL_MOUSE = 0x8001
WM_APP_REINSTALL = 0x8002
# input the system saw this long after the hooks' last event means Windows dropped them
HOOK_SILENCE_MS = 1500
LLKHF_EXTENDED = 0x01
LLKHF_INJECTED = 0x10
LLMHF_INJECTED = 0x01
KEY_UP_MESSAGES = (0x0101, 0x0105)
# mouse message -> (vk, up); X buttons read the button from mouseData
MOUSE_BUTTON_MESSAGES = {
    0x0201: (0x01, False), 0x0202: (0x01, True), 0x0204: (0x02, False), 0x0205: (0x02, True),
    0x0207: (0x04, False), 0x0208: (0x04, True), 0x020B: (0x05, False), 0x020C: (0x05, True),
}
WM_MOUSEWHEEL = 0x020A
WM_MOUSEHWHEEL = 0x020E
XBUTTON2 = 2
STOP_TIMEOUT_S = 2.0

log = logging.getLogger(__name__)

if sys.platform == "win32":
    _kernel32 = ctypes.windll.kernel32
    _user32 = ctypes.windll.user32
# GetTickCount of the last event either hook saw
_lastEvent = [0]

_matcher = HotkeyMatcher()
_callbacks: dict[str, Callable[[str], object]] = {}
_lock = threading.Lock()
_queue: queue.Queue[tuple[Callable[[str], object], str] | None] = queue.Queue()
_hook = {"thread": None, "thread_id": 0, "keyboard": None, "mouse": None, "dispatcher": None}
_ready = threading.Event()


# ---- registration ----


def _Key(name: str) -> str:
    return name.strip().lower()


def Hotkey(name: str, callback: Callable[[str], object] | None = None, options: str = "") -> None:
    """Hotkey(name, callback, options): registers or updates a hotkey; options "On"/"Off", "S" (keeps working
    while suspended) and "S0" (P<n>/T<n> ignored). Without a callback it only switches an existing hotkey."""
    words = {word.lower() for word in options.split()}
    key = _Key(name)
    with _lock:
        if callback is None:
            if key not in _matcher.hotkeys:
                raise ValueError(f"Nonexistent hotkey: {name}")
        else:
            _matcher.hotkeys[key] = ParseHotkey(name)
            _callbacks[key] = callback
            _matcher.enabled.add(key)
        if "off" in words:
            _matcher.enabled.discard(key)
        elif "on" in words:
            _matcher.enabled.add(key)
        if "s" in words:
            _matcher.exempt.add(key)
        elif "s0" in words:
            _matcher.exempt.discard(key)
        needsMouse = IsMouseHotkey(_matcher.hotkeys[key])
    if needsMouse and _hook["thread_id"] and (_hook["mouse"] is None):
        api.PostThreadMessageW(_hook["thread_id"], WM_APP_INSTALL_MOUSE, 0, 0)


def ClearHotkeys() -> None:
    """Drops every hotkey, so the settings can register them again. Keys held right now still release
    cleanly: the hook keeps what it swallowed."""
    with _lock:
        _matcher.hotkeys.clear()
        _matcher.enabled.clear()
        _matcher.exempt.clear()
        _matcher.ClearPending()
        _callbacks.clear()


def Suspend(state: bool | None = None) -> bool:
    """Suspend: True disables every hotkey but the exempt ones, None toggles. Returns the new state."""
    with _lock:
        _matcher.suspended = (not _matcher.suspended) if (state is None) else state
        return _matcher.suspended


def Suspended() -> bool:
    return _matcher.suspended


def SetSuspendExempt(name: str, exempt: bool = True) -> None:
    with _lock:
        if exempt:
            _matcher.exempt.add(_Key(name))
        else:
            _matcher.exempt.discard(_Key(name))


def PhysicalKeyDown(key: KeyCode) -> bool | None:
    """The physical state the hook tracked, or None when the hook is not running."""
    if _hook["keyboard"] is None:
        return None
    with _lock:
        return _matcher.PhysicalDown(key)


# ---- hook thread ----


def _Decide(vk: int, extended: bool, up: bool) -> bool:
    """Runs on the hook thread: must stay fast. Returns whether to hide the event."""
    with _lock:
        decision: Decision = _matcher.event(vk, extended, up)
        # decision.fire holds the hotkey names as registered (A_ThisHotkey); the tables are keyed by _key(name)
        callbacks = [(_callbacks[_Key(name)], name) for name in decision.fire]
    for callback, name in callbacks:
        _queue.put((callback, name))
    if decision.mask:
        ahk_input.TapKey(MENU_MASK_KEY)
    if decision.replay is not None:
        ahk_input.TapKey(decision.replay)
    return decision.suppress


def _KeyboardProc(code: int, wParam: int, lParam: int) -> int:
    if code == HC_ACTION:
        _lastEvent[0] = _kernel32.GetTickCount()
        info = api.KBDLLHOOKSTRUCT.from_address(lParam)
        injected = (info.flags & LLKHF_INJECTED) != 0
        if (not injected) and _Decide(info.vkCode, bool(info.flags & LLKHF_EXTENDED), wParam in KEY_UP_MESSAGES):
            return 1
    return api.CallNextHookEx(None, code, wParam, lParam)


def _MouseVk(wParam: int, info: api.MSLLHOOKSTRUCT) -> tuple[int, bool] | None:
    if wParam in MOUSE_BUTTON_MESSAGES:
        vk, up = MOUSE_BUTTON_MESSAGES[wParam]
        if (vk == 0x05) and ((info.mouseData >> 16) == XBUTTON2):
            vk = 0x06
        return vk, up
    if wParam in (WM_MOUSEWHEEL, WM_MOUSEHWHEEL):
        delta = ctypes.c_short(info.mouseData >> 16).value
        if wParam == WM_MOUSEWHEEL:
            return (0x9F if (delta > 0) else 0x9E), False
        return (0x9D if (delta > 0) else 0x9C), False
    return None


def _MouseProc(code: int, wParam: int, lParam: int) -> int:
    if code == HC_ACTION:
        _lastEvent[0] = _kernel32.GetTickCount()
        info = api.MSLLHOOKSTRUCT.from_address(lParam)
        event = None if (info.flags & LLMHF_INJECTED) else _MouseVk(wParam, info)
        if (event is not None) and _Decide(event[0], False, event[1]):
            return 1
    return api.CallNextHookEx(None, code, wParam, lParam)


# Kept referenced for the life of the module: Windows calls them after SetWindowsHookEx returns.
_KEYBOARD_PROC = api.HOOKPROC(_KeyboardProc)
_MOUSE_PROC = api.HOOKPROC(_MouseProc)


def _Install(kind: int) -> int:
    proc = _KEYBOARD_PROC if (kind == WH_KEYBOARD_LL) else _MOUSE_PROC
    handle = api.SetWindowsHookExW(kind, proc, api.GetModuleHandleW(None), 0)
    if not handle:
        raise OSError(ctypes.get_last_error(), "SetWindowsHookEx failed")
    return handle


def _AnyMouseHotkey() -> bool:
    with _lock:
        return any(IsMouseHotkey(spec) for spec in _matcher.hotkeys.values())


def _HookLoop() -> None:
    _hook["thread_id"] = api.GetCurrentThreadId()
    _hook["keyboard"] = _Install(WH_KEYBOARD_LL)
    if _AnyMouseHotkey():
        _hook["mouse"] = _Install(WH_MOUSE_LL)
    _lastEvent[0] = _kernel32.GetTickCount()
    _ready.set()
    message = wintypes.MSG()
    try:
        while api.GetMessageW(ctypes.byref(message), None, 0, 0) > 0:
            if (message.message == WM_APP_INSTALL_MOUSE) and (_hook["mouse"] is None):
                _hook["mouse"] = _Install(WH_MOUSE_LL)
            elif message.message == WM_APP_REINSTALL:
                _Reinstall()
    finally:
        for kind in ("keyboard", "mouse"):
            if _hook[kind] is not None:
                api.UnhookWindowsHookEx(_hook[kind])
                _hook[kind] = None
        _hook["thread_id"] = 0


def _Reinstall() -> None:
    for kind, hookType in (("keyboard", WH_KEYBOARD_LL), ("mouse", WH_MOUSE_LL)):
        if _hook[kind] is not None:
            api.UnhookWindowsHookEx(_hook[kind])
            _hook[kind] = _Install(hookType)
    _lastEvent[0] = _kernel32.GetTickCount()


# ---- watchdog ----


class _LastInputInfo(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.UINT), ("dwTime", wintypes.DWORD)]


def HookDropped() -> bool:
    """Windows silently removes a low-level hook whose callback is too slow. With the mouse hook in, every
    input reaches the hooks, so input the system saw well after the hooks' last event means they are
    gone: this reinstalls them and returns True."""
    if (_hook["mouse"] is None) or (_hook["thread_id"] == 0):
        return False
    info = _LastInputInfo(ctypes.sizeof(_LastInputInfo), 0)
    if not _user32.GetLastInputInfo(ctypes.byref(info)):
        return False
    unseenMs = (info.dwTime - _lastEvent[0]) & 0xFFFFFFFF
    if (unseenMs > 0x7FFFFFFF) or (unseenMs < HOOK_SILENCE_MS):
        return False
    api.PostThreadMessageW(_hook["thread_id"], WM_APP_REINSTALL, 0, 0)
    return True


# ---- dispatcher ----


def _DispatchLoop() -> None:
    while True:
        item = _queue.get()
        if item is None:
            return
        callback, name = item
        try:
            callback(name)
        except Exception:
            log.exception("Hotkey %s callback raised", name)


def Start() -> None:
    """Installs the hooks and starts the dispatcher; does nothing when they already run."""
    if (_hook["thread"] is not None) and _hook["thread"].is_alive():
        return
    _ready.clear()
    _hook["dispatcher"] = threading.Thread(target=_DispatchLoop, name="ahk-hotkey-dispatch", daemon=True)
    _hook["dispatcher"].start()
    _hook["thread"] = threading.Thread(target=_HookLoop, name="ahk-hotkey-hook", daemon=True)
    _hook["thread"].start()
    _ready.wait(STOP_TIMEOUT_S)


def Stop() -> None:
    thread = _hook["thread"]
    if (thread is None) or not thread.is_alive():
        return
    api.PostThreadMessageW(_hook["thread_id"], WM_QUIT, 0, 0)
    thread.join(STOP_TIMEOUT_S)
    _queue.put(None)
    _hook["dispatcher"].join(STOP_TIMEOUT_S)
    _hook["thread"] = None
