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
    """When mic + Ollama are healthy (the warm-boot path), no dialog at all.

    Mike's ~9 out of 10 boots now hit this path silently — the dialog used
    to fire when the synchronous probe gave up after 12 s while WSL2 was
    still spinning up Ollama (~27 s on his box).
    """
    welcome_win.show_setup_hint_if_needed(mic_ok=True, ollama_ok=True)


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
