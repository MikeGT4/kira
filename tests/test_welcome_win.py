"""Tests for kira.welcome_win — reachability retry + neutrality check.

The Qt SetupHintDialog itself is not exercised here (headless Qt is brittle
under pytest; covered by the manual install smoke test).
"""
from __future__ import annotations
import sys
import urllib.error
from unittest.mock import MagicMock, patch

import pytest

if sys.platform != "win32":
    pytest.skip("windows-only tests", allow_module_level=True)

from kira import welcome_win


def _ok_response():
    resp = MagicMock()
    resp.status = 200
    resp.__enter__ = lambda self: self
    resp.__exit__ = lambda *a: None
    return resp


def test_ollama_reachable_returns_true_on_first_success():
    with patch("kira.welcome_win.urllib.request.urlopen", return_value=_ok_response()):
        assert welcome_win._ollama_reachable(attempts=4, delay=0.0) is True


def test_ollama_reachable_succeeds_after_retries():
    calls = {"n": 0}

    def fake_urlopen(*_a, **_kw):
        calls["n"] += 1
        if calls["n"] < 3:
            raise urllib.error.URLError("connection refused")
        return _ok_response()

    with patch("kira.welcome_win.urllib.request.urlopen", side_effect=fake_urlopen):
        assert welcome_win._ollama_reachable(attempts=4, delay=0.0) is True
    assert calls["n"] == 3


def test_ollama_reachable_returns_false_after_all_retries_fail():
    calls = {"n": 0}

    def fake_urlopen(*_a, **_kw):
        calls["n"] += 1
        raise urllib.error.URLError("connection refused")

    with patch("kira.welcome_win.urllib.request.urlopen", side_effect=fake_urlopen):
        assert welcome_win._ollama_reachable(attempts=4, delay=0.0) is False
    assert calls["n"] == 4


def test_ollama_reachable_handles_timeout_error():
    with patch("kira.welcome_win.urllib.request.urlopen", side_effect=TimeoutError):
        assert welcome_win._ollama_reachable(attempts=2, delay=0.0) is False


def test_probe_setup_status_returns_pure_tuple(monkeypatch):
    """probe_setup_status must return (mic_ok, ollama_ok) without touching UI.

    This separation is what lets the Windows boot path run the slow Ollama
    probe in a daemon thread instead of blocking the Qt event loop. If
    anything in this function spawned a QDialog or other Qt object, the
    background-thread call from main.py would crash with a 'QObject must
    be created on the GUI thread' assertion.
    """
    fake_status = MagicMock()
    fake_status.microphone = True
    with patch.object(welcome_win, "check_all", return_value=fake_status), \
            patch.object(welcome_win, "_ollama_reachable", return_value=True):
        result = welcome_win.probe_setup_status()
    assert result == (True, True)


def test_probe_setup_status_propagates_failures(monkeypatch):
    fake_status = MagicMock()
    fake_status.microphone = False
    with patch.object(welcome_win, "check_all", return_value=fake_status), \
            patch.object(welcome_win, "_ollama_reachable", return_value=False):
        result = welcome_win.probe_setup_status()
    assert result == (False, False)


def test_show_setup_hint_skips_when_all_ok():
    """When mic + Ollama are healthy (the warm-boot path), no dialog at all."""
    with patch("kira.ui.setup_hint_dialog.SetupHintDialog") as Dlg:
        welcome_win.show_setup_hint_if_needed(mic_ok=True, ollama_ok=True)
    Dlg.assert_not_called()


def test_show_setup_hint_suppresses_ollama_only_failure():
    """When only Ollama is missing (mic OK), no dialog.

    The polish backend's cold-start race (autostart hits before the
    backend service is ready) was tripping the dialog at every reboot
    even though Ollama was about to come up on its own. Polish falls
    back to raw Whisper text on errors, so the dialog would only nag
    without fixing anything; main.py keeps probing in the background
    so the model still gets pre-loaded once Ollama is reachable.
    """
    with patch("kira.ui.setup_hint_dialog.SetupHintDialog") as Dlg:
        welcome_win.show_setup_hint_if_needed(mic_ok=True, ollama_ok=False)
    Dlg.assert_not_called()


def test_show_setup_hint_dialogs_when_mic_missing():
    """Mic-permission failures need user action — dialog must surface."""
    with patch("kira.ui.setup_hint_dialog.SetupHintDialog") as Dlg, \
            patch.object(welcome_win, "open_microphone_settings"):
        Dlg.return_value.user_clicked_open_mic_settings = False
        welcome_win.show_setup_hint_if_needed(mic_ok=False, ollama_ok=True)
    Dlg.assert_called_once_with(mic_ok=False, ollama_ok=True)


def test_show_setup_hint_dialogs_when_both_missing():
    """If mic AND Ollama are missing, the user has to fix mic anyway —
    surface the dialog so they see both items at once."""
    with patch("kira.ui.setup_hint_dialog.SetupHintDialog") as Dlg, \
            patch.object(welcome_win, "open_microphone_settings"):
        Dlg.return_value.user_clicked_open_mic_settings = False
        welcome_win.show_setup_hint_if_needed(mic_ok=False, ollama_ok=False)
    Dlg.assert_called_once_with(mic_ok=False, ollama_ok=False)


def test_module_source_is_neutral_about_install_source():
    """Kira works with both native-Windows Ollama and WSL-hosted Ollama.

    Why: the Setup-bundle installs Ollama natively via OllamaSetup.exe
    (no WSL on the friend's PC). The Dev-Setup uses WSL-Ollama. The
    user-facing text must not assume one or the other.
    """
    import inspect
    source = inspect.getsource(welcome_win)
    forbidden = ["wsl -d Ubuntu", "in WSL", "Ollama-in-WSL", "WSL-Ollama"]
    for marker in forbidden:
        assert marker not in source, f"Found forbidden WSL hardcoding: {marker!r}"
