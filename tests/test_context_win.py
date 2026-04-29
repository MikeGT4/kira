"""Tests for active-exe context detection on Windows."""
from __future__ import annotations
import sys
import pytest

if sys.platform != "win32":
    pytest.skip("windows-only tests", allow_module_level=True)


def test_active_exe_returns_lower_name(monkeypatch):
    from kira import context_win

    class FakeProc:
        def name(self): return "Outlook.EXE"

    monkeypatch.setattr(context_win.win32gui, "GetForegroundWindow", lambda: 42)
    monkeypatch.setattr(
        context_win.win32process, "GetWindowThreadProcessId",
        lambda hwnd: (1, 9999),
    )
    monkeypatch.setattr(context_win.psutil, "Process", lambda pid: FakeProc())

    assert context_win.active_exe() == "outlook.exe"


def test_active_exe_returns_none_on_error(monkeypatch):
    from kira import context_win

    def boom(*a, **kw): raise RuntimeError("no foreground")

    monkeypatch.setattr(context_win.win32gui, "GetForegroundWindow", boom)
    assert context_win.active_exe() is None


def test_active_exe_returns_none_on_pid_zero(monkeypatch):
    """pid=0 (desktop / lock screen) must yield None, not 'system idle process'."""
    from kira import context_win

    called = {"psutil_process": 0}

    def fake_psutil_process(pid):
        called["psutil_process"] += 1
        raise AssertionError("psutil.Process should not be called for pid=0")

    monkeypatch.setattr(context_win.win32gui, "GetForegroundWindow", lambda: 0)
    monkeypatch.setattr(
        context_win.win32process, "GetWindowThreadProcessId",
        lambda hwnd: (0, 0),
    )
    monkeypatch.setattr(context_win.psutil, "Process", fake_psutil_process)

    assert context_win.active_exe() is None
    assert called["psutil_process"] == 0


def test_detect_mode_maps_outlook_to_email(monkeypatch):
    from kira import context_win
    from kira.config import Config

    monkeypatch.setattr(context_win, "active_exe", lambda: "outlook.exe")
    cfg = Config()
    cfg.context_modes = context_win.DEFAULT_CONTEXT_MODES_WIN.copy()
    assert context_win.detect_mode(cfg) == "email"


def test_detect_mode_maps_terminal(monkeypatch):
    from kira import context_win
    from kira.config import Config

    monkeypatch.setattr(context_win, "active_exe", lambda: "windowsterminal.exe")
    cfg = Config()
    cfg.context_modes = context_win.DEFAULT_CONTEXT_MODES_WIN.copy()
    assert context_win.detect_mode(cfg) == "terminal"


def test_detect_mode_unknown_exe_falls_back_to_plain(monkeypatch):
    from kira import context_win
    from kira.config import Config

    monkeypatch.setattr(context_win, "active_exe", lambda: "some-random.exe")
    cfg = Config()
    cfg.context_modes = context_win.DEFAULT_CONTEXT_MODES_WIN.copy()
    assert context_win.detect_mode(cfg) == "plain"


def test_detect_mode_no_foreground_is_plain(monkeypatch):
    from kira import context_win
    from kira.config import Config

    monkeypatch.setattr(context_win, "active_exe", lambda: None)
    cfg = Config()
    cfg.context_modes = context_win.DEFAULT_CONTEXT_MODES_WIN.copy()
    assert context_win.detect_mode(cfg) == "plain"


def test_user_config_overrides_default(monkeypatch):
    from kira import context_win
    from kira.config import Config

    monkeypatch.setattr(context_win, "active_exe", lambda: "myapp.exe")
    cfg = Config()
    cfg.context_modes = {"myapp.exe": "code"}
    assert context_win.detect_mode(cfg) == "code"
