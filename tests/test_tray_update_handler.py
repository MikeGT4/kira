"""Tests for KiraTray._check_for_updates handler.

The in-app updater is intentionally disabled in v0.1.x because the installer
ships as a multi-file Inno bundle (1 stub + 7 .bin splits) and kira.updater
only knows single-asset pulls — wiring it up would download a useless 2 MB
stub and produce a broken install. The handler now shows an informational
hint until v0.2 lands manifest-based multi-asset updates with signature
verification. Tests here only assert the no-op + hint behaviour; the
update-check logic itself is covered by test_updater.py.
"""
from __future__ import annotations
import sys
from unittest.mock import patch

import pytest

if sys.platform != "win32":
    pytest.skip("windows-only tests", allow_module_level=True)


@pytest.fixture
def tray():
    from kira.ui.tray_win import KiraTray
    quit_calls = []
    t = KiraTray(on_quit=lambda: quit_calls.append(1))
    t._quit_calls = quit_calls
    return t


def test_handler_shows_v02_hint_messagebox(tray):
    with patch("kira.ui.tray_win.ctypes") as mock_ctypes:
        tray._check_for_updates(None, None)
    mock_ctypes.windll.user32.MessageBoxW.assert_called_once()
    args = mock_ctypes.windll.user32.MessageBoxW.call_args.args
    body = args[1]
    # Must mention v0.2 so the user understands this is a known-disabled feature.
    assert "v0.2" in body
    # MB_ICONINFORMATION (0x40), not warning — it's an expected state, not an error.
    assert args[3] == 0x40


def test_handler_does_not_quit_kira(tray):
    """The disabled handler must not trigger on_quit — earlier code did
    quit Kira after launching the installer; the no-op variant must not."""
    with patch("kira.ui.tray_win.ctypes"):
        tray._check_for_updates(None, None)
    assert tray._quit_calls == []


def test_handler_does_not_touch_subprocess(tray):
    """No installer should be spawned — the multi-file path is broken and
    silent privilege-escalating Popen is exactly what we removed."""
    with patch("kira.ui.tray_win.ctypes"), \
         patch("kira.ui.tray_win.subprocess.Popen") as mock_popen:
        tray._check_for_updates(None, None)
    mock_popen.assert_not_called()


def test_menu_includes_check_for_updates_item(tray):
    """Menu entry stays visible so users see the feature is planned —
    only the handler behaviour is disabled."""
    menu = tray._build_menu()
    labels = [getattr(item, "text", None) for item in menu.items]
    assert "Updates suchen…" in labels
