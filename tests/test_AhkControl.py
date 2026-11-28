import pytest

from yorha import Control
from yorha import Input as ahk_input

WINDOW = 0x100
EDIT = 0x200
WM_KEYDOWN = 0x0100
WM_KEYUP = 0x0101
WM_CHAR = 0x0102
WM_SYSKEYDOWN = 0x0104
WM_LBUTTONDOWN = 0x0201
WM_LBUTTONUP = 0x0202
WM_RBUTTONDOWN = 0x0204
WM_MOUSEWHEEL = 0x020A


@pytest.fixture
def posted(monkeypatch):
    messages = []
    monkeypatch.setattr(Control.api, "PostMessageW", lambda hwnd, message, wParam, lParam:
                        messages.append((hwnd, message, wParam, lParam)))
    monkeypatch.setattr(Control, "FindControl", lambda control, winTitle="": EDIT if control else WINDOW)
    monkeypatch.setattr(Control, "RequireWindow", lambda winTitle: WINDOW)
    monkeypatch.setattr(Control, "_ClientSize", lambda hwnd: (200, 100))
    monkeypatch.setattr(Control, "_ControlExists", lambda control, winTitle: False)
    monkeypatch.setattr(Control, "_ControlDelay", lambda: None)
    monkeypatch.setattr(Control.KeyCodes, "ScanCode", lambda key: 0x1E)
    monkeypatch.setattr(ahk_input, "Delay", lambda kind: None)
    return messages


def test_ControlSendPostsKeyDownAndUpWithTheirLParam(posted):
    Control.ControlSend("{Enter}", "Edit1", "ahk_exe app.exe")
    assert [(hwnd, message, wParam) for hwnd, message, wParam, _l in posted] == [
        (EDIT, WM_KEYDOWN, 0x0D), (EDIT, WM_KEYUP, 0x0D)]
    down, up = posted[0][3], posted[1][3]
    assert down == (1 | (0x1E << 16))
    assert up == (down | (1 << 30) | (1 << 31))


def test_ControlSendUsesSysKeysWhileAltIsDown(posted):
    Control.ControlSend("{Alt down}f{Alt up}")
    messages = [message for _h, message, _w, _l in posted]
    assert messages[:2] == [WM_SYSKEYDOWN, WM_SYSKEYDOWN]
    assert posted[1][3] & (1 << 29)


def test_ControlSendTextPostsCharacters(posted):
    Control.ControlSendText("ñ\n")
    assert [(message, wParam) for _h, message, wParam, _l in posted] == [
        (WM_CHAR, ord("ñ")), (WM_KEYDOWN, 0x0D), (WM_KEYUP, 0x0D)]


def test_ControlSendRefusesMouseButtons(posted):
    with pytest.raises(ValueError):
        Control.ControlSend("{LButton}")


def test_ControlClickClicksTheControlCentreByDefault(posted):
    Control.ControlClick("Button1")
    assert posted == [(EDIT, WM_LBUTTONDOWN, 0x1, 100 | (50 << 16)), (EDIT, WM_LBUTTONUP, 0, 100 | (50 << 16))]


def test_ControlClickOptions(posted):
    Control.ControlClick("Button1", "", "", "Right", 1, "D X5 Y7 NA")
    assert posted == [(EDIT, WM_RBUTTONDOWN, 0x2, 5 | (7 << 16))]


def test_ControlClickCoordinatesClickTheWindowWhenNoChildIsThere(posted, monkeypatch):
    monkeypatch.setattr(Control.api, "ChildWindowFromPointEx", lambda hwnd, point, flags: 0)
    Control.ControlClick("x10 y20", "ahk_exe app.exe", "", "left", 2)
    assert [(hwnd, message) for hwnd, message, _w, _l in posted] == [
        (WINDOW, WM_LBUTTONDOWN), (WINDOW, WM_LBUTTONUP)] * 2
    assert posted[0][3] == (10 | (20 << 16))


def test_ControlClickWheel(posted, monkeypatch):
    monkeypatch.setattr(Control.api, "ClientToScreen", lambda hwnd, point: None)
    Control.ControlClick("", "", "", "WheelDown", 2)
    assert [(message, wParam >> 16) for _h, message, wParam, _l in posted] == [(WM_MOUSEWHEEL, 0xFF88)] * 2


def test_ControlClickRefusesWinText(posted):
    with pytest.raises(ValueError):
        Control.ControlClick("", "", "some text")


def test_ClassNNCountsInstancesOfTheClass(monkeypatch):
    classes = {1: "Button", 2: "Edit", 3: "Edit"}
    monkeypatch.setattr(Control, "_ClassName", lambda hwnd: classes[hwnd])
    assert Control._ByClassNN([1, 2, 3], "Edit2") == 3
    assert Control._ByClassNN([1, 2, 3], "Edit3") == 0
    assert Control._ByClassNN([1, 2, 3], "Edit") == 0


def test_AnOmittedControlIsTheWindowItself(monkeypatch):
    monkeypatch.setattr(Control, "RequireWindow", lambda winTitle: WINDOW)
    assert Control.FindControl("", "ahk_exe app.exe") == WINDOW
