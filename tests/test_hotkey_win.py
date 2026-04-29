"""Tests for Windows F8 hotkey listener. Windows-only."""
from __future__ import annotations
import sys
import pytest

if sys.platform != "win32":
    pytest.skip("windows-only tests", allow_module_level=True)


def test_hotkey_rejects_unknown_combo():
    from kira.hotkey_win import HotkeyListener
    with pytest.raises(ValueError):
        HotkeyListener(combo="xyz", on_press=lambda: None, on_release=lambda: None)


def test_hotkey_accepts_f8():
    from kira.hotkey_win import HotkeyListener
    HotkeyListener(combo="f8", on_press=lambda: None, on_release=lambda: None)


def test_hotkey_press_callback_dispatched(monkeypatch):
    """keyboard.on_press_key + on_release_key registered with our F8 handler."""
    from kira import hotkey_win

    registered = {"press": None, "release": None, "suppress": None}

    def fake_on_press_key(key, cb, suppress=False):
        registered["press"] = (key, cb)
        registered["suppress"] = suppress

    def fake_on_release_key(key, cb, suppress=False):
        registered["release"] = (key, cb)

    monkeypatch.setattr(hotkey_win.keyboard, "on_press_key", fake_on_press_key)
    monkeypatch.setattr(hotkey_win.keyboard, "on_release_key", fake_on_release_key)
    monkeypatch.setattr(hotkey_win.keyboard, "unhook_all", lambda: None)

    pressed = {"n": 0}
    released = {"n": 0}

    listener = hotkey_win.HotkeyListener(
        combo="f8",
        on_press=lambda: pressed.update(n=pressed["n"] + 1),
        on_release=lambda: released.update(n=released["n"] + 1),
    )
    listener.start()

    assert registered["press"][0] == "f8"
    assert registered["release"][0] == "f8"
    assert registered["suppress"] is False  # pass-through

    registered["press"][1](None)   # simulate press
    assert pressed["n"] == 1

    registered["release"][1](None)  # simulate release
    assert released["n"] == 1


def test_hotkey_double_press_ignored_while_active(monkeypatch):
    """Auto-repeat second keydown while already active must not re-fire on_press."""
    from kira import hotkey_win

    registered = {}

    def capture(key, cb, suppress=False):
        registered[key] = cb

    monkeypatch.setattr(hotkey_win.keyboard, "on_press_key", capture)
    monkeypatch.setattr(hotkey_win.keyboard, "on_release_key", capture)
    monkeypatch.setattr(hotkey_win.keyboard, "unhook_all", lambda: None)

    pressed = {"n": 0}

    listener = hotkey_win.HotkeyListener(
        combo="f8",
        on_press=lambda: pressed.update(n=pressed["n"] + 1),
        on_release=lambda: None,
    )
    listener.start()

    registered["f8"](None)
    registered["f8"](None)  # auto-repeat keydown
    assert pressed["n"] == 1


def test_hotkey_stop_unhooks(monkeypatch):
    from kira import hotkey_win

    unhook_calls = {"n": 0}
    monkeypatch.setattr(hotkey_win.keyboard, "on_press_key", lambda *a, **k: object())
    monkeypatch.setattr(hotkey_win.keyboard, "on_release_key", lambda *a, **k: object())
    monkeypatch.setattr(
        hotkey_win.keyboard, "unhook",
        lambda h: unhook_calls.update(n=unhook_calls["n"] + 1),
    )

    listener = hotkey_win.HotkeyListener(
        combo="f8", on_press=lambda: None, on_release=lambda: None,
    )
    listener.start()
    listener.stop()
    assert unhook_calls["n"] == 2  # press + release


def test_start_idempotent(monkeypatch):
    """Calling start() twice must register hooks only once."""
    from kira import hotkey_win

    register_count = {"n": 0}

    def fake(*a, **kw):
        register_count["n"] += 1
        return object()  # fake handle

    monkeypatch.setattr(hotkey_win.keyboard, "on_press_key", fake)
    monkeypatch.setattr(hotkey_win.keyboard, "on_release_key", fake)
    monkeypatch.setattr(hotkey_win.keyboard, "unhook", lambda h: None)

    listener = hotkey_win.HotkeyListener(
        combo="f8", on_press=lambda: None, on_release=lambda: None,
    )
    listener.start()
    listener.start()  # idempotent
    # 2 (one press + one release from first start)
    assert register_count["n"] == 2


def test_stop_unhooks_selectively(monkeypatch):
    """stop() must call keyboard.unhook for each registered handle, not unhook_all."""
    from kira import hotkey_win

    handles_unhooked = []

    class FakeHandle:
        def __init__(self, kind): self.kind = kind
        def __repr__(self): return f"<handle {self.kind}>"

    press_h = FakeHandle("press")
    release_h = FakeHandle("release")

    monkeypatch.setattr(hotkey_win.keyboard, "on_press_key", lambda *a, **k: press_h)
    monkeypatch.setattr(hotkey_win.keyboard, "on_release_key", lambda *a, **k: release_h)
    monkeypatch.setattr(hotkey_win.keyboard, "unhook", lambda h: handles_unhooked.append(h))

    listener = hotkey_win.HotkeyListener(
        combo="f8", on_press=lambda: None, on_release=lambda: None,
    )
    listener.start()
    listener.stop()

    # Both handles must be unhooked; order is release-then-press because of
    # the start() registration order.
    assert set(handles_unhooked) == {press_h, release_h}
    assert len(handles_unhooked) == 2


def test_stop_when_not_started_is_noop(monkeypatch):
    """Calling stop() without start() must not raise."""
    from kira import hotkey_win

    unhook_calls = {"n": 0}
    monkeypatch.setattr(
        hotkey_win.keyboard, "unhook",
        lambda h: unhook_calls.update(n=unhook_calls["n"] + 1),
    )

    listener = hotkey_win.HotkeyListener(
        combo="f8", on_press=lambda: None, on_release=lambda: None,
    )
    listener.stop()  # must not raise
    assert unhook_calls["n"] == 0
