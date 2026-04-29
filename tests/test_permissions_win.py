"""Tests for Windows permission checks."""
from __future__ import annotations
import sys
import pytest

if sys.platform != "win32":
    pytest.skip("windows-only tests", allow_module_level=True)


def test_check_microphone_true_when_stream_opens(monkeypatch):
    from kira import permissions_win

    class FakeStream:
        def __enter__(self): return self
        def __exit__(self, *a): return False

    class FakeSd:
        def InputStream(self, **kw): return FakeStream()

    monkeypatch.setattr(permissions_win, "sd", FakeSd())
    assert permissions_win.check_microphone() is True


def test_check_microphone_false_on_error(monkeypatch):
    from kira import permissions_win

    class FakeSd:
        def InputStream(self, **kw):
            raise RuntimeError("mic denied")

    monkeypatch.setattr(permissions_win, "sd", FakeSd())
    assert permissions_win.check_microphone() is False


def test_check_all_returns_permission_status(monkeypatch):
    from kira import permissions_win
    monkeypatch.setattr(permissions_win, "check_microphone", lambda: True)
    s = permissions_win.check_all()
    assert s.microphone is True
    assert s.all_granted is True


def test_all_granted_false_when_mic_missing(monkeypatch):
    from kira import permissions_win
    monkeypatch.setattr(permissions_win, "check_microphone", lambda: False)
    s = permissions_win.check_all()
    assert s.all_granted is False


def test_open_microphone_settings_invokes_start(monkeypatch):
    from kira import permissions_win

    calls = []
    class FakePopen:
        def __init__(self, args, **kw): calls.append((args, kw.get("shell")))

    monkeypatch.setattr(permissions_win.subprocess, "Popen", FakePopen)
    permissions_win.open_microphone_settings()
    assert calls[0][0] == ["start", "ms-settings:privacy-microphone"]
    assert calls[0][1] is True
