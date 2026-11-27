"""ToolTip(text): AHK's ToolTip, a small always-on-top label near the mouse cursor; ToolTip() hides it.
Callable from any thread: the label lives on the Qt thread and the call is posted there."""

from __future__ import annotations

import threading
from typing import Callable

from PySide6.QtCore import QCoreApplication, QObject, Qt, QThread, Signal
from PySide6.QtGui import QCursor
from PySide6.QtWidgets import QFrame, QLabel, QToolTip

# AHK places the tooltip just below and right of the cursor
CURSOR_OFFSET = 16


class _Invoker(QObject):
    call = Signal(object)

    def __init__(self) -> None:
        super().__init__()
        self.call.connect(self._Run, Qt.ConnectionType.QueuedConnection)

    @staticmethod
    def _Run(fn: Callable[[], None]) -> None:
        fn()


_label: list[QLabel | None] = [None]
_invoker: list[_Invoker | None] = [None]
_lock = threading.Lock()


def ToolTip(text: str = "") -> None:
    app = QCoreApplication.instance()
    if app is None:
        return
    if QThread.currentThread() is app.thread():
        _Apply(text)
        return
    with _lock:
        if _invoker[0] is None:
            invoker = _Invoker()
            invoker.moveToThread(app.thread())
            _invoker[0] = invoker
    _invoker[0].call.emit(lambda: _Apply(text))


def _Apply(text: str) -> None:
    if text == "":
        if _label[0] is not None:
            _label[0].hide()
        return
    label = _label[0] if (_label[0] is not None) else _Build()
    label.setText(text)
    label.adjustSize()
    cursor = QCursor.pos()
    label.move((cursor.x() + CURSOR_OFFSET), (cursor.y() + CURSOR_OFFSET))
    label.show()


def _Build() -> QLabel:
    label = QLabel()
    label.setWindowFlags(Qt.WindowType.ToolTip | Qt.WindowType.WindowStaysOnTopHint
                         | Qt.WindowType.WindowTransparentForInput | Qt.WindowType.WindowDoesNotAcceptFocus)
    label.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
    label.setPalette(QToolTip.palette())
    label.setAutoFillBackground(True)
    label.setFrameStyle(QFrame.Shape.Box | QFrame.Shadow.Plain)
    label.setFont(QToolTip.font())
    label.setMargin(4)
    _label[0] = label
    return label
