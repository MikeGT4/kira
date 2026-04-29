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
