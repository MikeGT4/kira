"""Tests for kira.edit_command.read_selection."""
from __future__ import annotations
import pytest

# read_selection ist Windows-spezifisch (pywin32 indirekt via keyboard
# + pyperclip-Clipboard-Backend). Linux-CI hat weder den 'keyboard'-
# noch zuverlaessig 'pyperclip' — Tests skippen wenn die Module fehlen.
edit_command = pytest.importorskip("kira.edit_command")
read_selection = edit_command.read_selection


@pytest.fixture
def mock_clipboard(monkeypatch):
    """Vereinfachter Clipboard-Mock: state in einem dict, get/set
    routen alle pyperclip- und keyboard-Calls dort hin.

    keyboard.send('ctrl+c') wird via dict["selection_to_capture"] in
    den Clipboard kopiert — simuliert das echte Strg+C-Verhalten.
    """
    state = {
        "current": "vorher-clipboard-inhalt",
        "selection_to_capture": None,  # Was Strg+C einfangen wuerde
    }

    def fake_paste():
        return state["current"]

    def fake_copy(text):
        state["current"] = text

    def fake_send(combo):
        if combo == "ctrl+c" and state["selection_to_capture"] is not None:
            state["current"] = state["selection_to_capture"]

    monkeypatch.setattr(edit_command.pyperclip, "paste", fake_paste)
    monkeypatch.setattr(edit_command.pyperclip, "copy", fake_copy)
    monkeypatch.setattr(edit_command.keyboard, "send", fake_send)
    # Sleep-Zeit auf 0 fuer schnelle Tests
    monkeypatch.setattr(edit_command.time, "sleep", lambda _s: None)
    return state


def test_read_selection_returns_captured_text(mock_clipboard):
    mock_clipboard["selection_to_capture"] = "selected text from app"
    result = read_selection()
    assert result == "selected text from app"


def test_read_selection_restores_original_clipboard(mock_clipboard):
    """Original-Clipboard muss nach dem Read wieder im Clipboard sein —
    sonst zerstoert read_selection das Clipboard des Users."""
    mock_clipboard["current"] = "user-copied-vorher"
    mock_clipboard["selection_to_capture"] = "selected text"
    read_selection()
    assert mock_clipboard["current"] == "user-copied-vorher"


def test_read_selection_returns_none_when_no_selection(mock_clipboard):
    """Strg+C bei keiner Selection laesst das Clipboard auf dem Sentinel —
    Detection: result == _EMPTY_SENTINEL → None."""
    mock_clipboard["selection_to_capture"] = None  # Strg+C macht nix
    assert read_selection() is None


def test_read_selection_returns_none_when_clipboard_returns_empty(mock_clipboard):
    """Edge-Case: App reagiert auf Strg+C mit leerem String (manche
    Editor-Plugins). Wir wollen None zurueckgeben."""
    mock_clipboard["selection_to_capture"] = ""
    assert read_selection() is None


def test_read_selection_raises_on_pyperclip_initial_paste_failure(monkeypatch):
    """Wenn pyperclip.paste() VOR dem Strg+C fehlschlaegt, raisen wir
    ClipboardUnavailable — der Caller (KiraApp.on_edit_press) muss
    Clipboard-Failure von 'keine Selection' unterscheiden koennen.
    silent-failure-hunt 2026-05-09."""
    import pytest
    from kira.edit_command import ClipboardUnavailable

    def fail(*_a, **_kw):
        raise RuntimeError("clipboard not available")
    monkeypatch.setattr(edit_command.pyperclip, "paste", fail)
    with pytest.raises(ClipboardUnavailable, match="Clipboard-Lesen vor"):
        read_selection()


def test_read_selection_raises_on_keyboard_send_failure(monkeypatch):
    """keyboard.send-Fehler raised ClipboardUnavailable. Cleanup MUSS
    trotzdem laufen — Original-Clipboard restored."""
    import pytest
    from kira.edit_command import ClipboardUnavailable

    state = {"current": "user-original"}

    def fake_paste():
        return state["current"]

    def fake_copy(text):
        state["current"] = text

    def fail_send(_combo):
        raise RuntimeError("keyboard hook borked")

    monkeypatch.setattr(edit_command.pyperclip, "paste", fake_paste)
    monkeypatch.setattr(edit_command.pyperclip, "copy", fake_copy)
    monkeypatch.setattr(edit_command.keyboard, "send", fail_send)
    monkeypatch.setattr(edit_command.time, "sleep", lambda _s: None)

    with pytest.raises(ClipboardUnavailable, match="keyboard.send"):
        read_selection()
    # Cleanup-Restore muss VOR dem raise gegriffen haben:
    assert state["current"] == "user-original"
