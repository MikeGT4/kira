"""Tests für KiraTray.notify — Win32-Längen-Grenzen.

Shell_NotifyIcon (NOTIFYICONDATAW) deckelt szInfo auf 256 und
szInfoTitle auf 64 Zeichen (inkl. Nullterminator). pystray validiert
hart und wirft ValueError — passiert mit den ollama_diag-Hints
(369 Zeichen am 2026-07-03): Der Toast verpuffte komplett statt
gekürzt anzukommen. notify() kürzt jetzt selbst; der volle Text steht
weiterhin im Log des Aufrufers.
"""
from __future__ import annotations
import sys
from unittest.mock import MagicMock

import pytest

if sys.platform != "win32":
    pytest.skip("windows-only tests", allow_module_level=True)


@pytest.fixture
def tray():
    from kira.ui.tray_win import KiraTray
    t = KiraTray(on_quit=lambda: None)
    t._icon = MagicMock()
    return t


def test_notify_truncates_overlong_message(tray):
    long_msg = "x" * 369
    tray.notify("Kira — Polish auf CPU", long_msg)

    tray._icon.notify.assert_called_once()
    sent_msg, sent_title = tray._icon.notify.call_args.args
    assert len(sent_msg) <= 255
    assert sent_msg.endswith("…")
    assert len(sent_title) <= 63


def test_notify_passes_short_message_unchanged(tray):
    tray.notify("Kira", "kurz und gut")

    sent_msg, sent_title = tray._icon.notify.call_args.args
    assert sent_msg == "kurz und gut"
    assert sent_title == "Kira"


def test_notify_truncates_overlong_title(tray):
    tray.notify("T" * 100, "msg")

    _msg, sent_title = tray._icon.notify.call_args.args
    assert len(sent_title) <= 63
    assert sent_title.endswith("…")
