"""Marshal a 0-arg callable from a non-Qt thread onto the Qt main thread.

Why this exists: pystray menu callbacks run on a daemon thread that has
no Qt event loop. The bare ``QTimer.singleShot(0, fn)`` form posts the
slot to the *calling* thread's queue — which on a daemon thread means
nowhere — so dialog clicks 'go nowhere'. PyQt6 also doesn't expose the
``QTimer.singleShot(msec, context, slot)`` overload that would force the
slot onto a specific QObject's thread (only the C++ Qt API does), so we
use a queued-signal connection on a long-lived main-thread QObject.

Usage:

    # On the main thread, after QApplication is created:
    marshal = MainThreadMarshal()

    # From any thread:
    marshal.run_on_main_thread(lambda: open_my_dialog())
"""
from __future__ import annotations
import logging
from typing import Callable

from PyQt6.QtCore import QObject, Qt, pyqtSignal

log = logging.getLogger(__name__)


class MainThreadMarshal(QObject):
    """Hands a callable from any thread to the thread this QObject lives on.

    Construct on the main thread (where the QApplication event loop runs).
    Call ``run_on_main_thread(fn)`` from anywhere — the signal/slot
    connection is queued so emission from a worker thread defers slot
    invocation onto the owning thread's event queue.

    The dispatcher catches and logs exceptions because Kira's GUI runs as
    ``pythonw.exe`` (no console); an unhandled exception in the slot
    would otherwise vanish silently.
    """

    _request = pyqtSignal(object)

    def __init__(self) -> None:
        super().__init__()
        self._request.connect(self._dispatch, Qt.ConnectionType.QueuedConnection)

    def _dispatch(self, fn: Callable[[], None]) -> None:
        try:
            fn()
        except Exception:
            log.exception("marshalled call failed")

    def run_on_main_thread(self, fn: Callable[[], None]) -> None:
        """Queue ``fn()`` for execution on the thread this object lives on."""
        self._request.emit(fn)
