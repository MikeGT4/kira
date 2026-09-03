import asyncio
import pytest
from kira.app import KiraApp, State


def test_initial_state_is_idle():
    app = KiraApp.for_test()
    assert app.state == State.IDLE


def test_press_moves_to_recording():
    app = KiraApp.for_test()
    app.on_hotkey_press()
    assert app.state == State.RECORDING


def test_short_release_aborts_to_idle():
    app = KiraApp.for_test()
    app.on_hotkey_press()
    app.on_hotkey_release(duration_ms=100)  # below 300ms
    assert app.state == State.IDLE


def test_long_release_runs_pipeline_and_ends_idle():
    app = KiraApp.for_test()
    app.on_hotkey_press()
    # No event loop set -> pipeline runs synchronously via asyncio.run
    app.on_hotkey_release(duration_ms=500)
    # After pipeline completes, state should be IDLE again
    assert app.state == State.IDLE
    # The stub injector should have received text
    assert app._injector.last == "stub"


def test_double_press_while_active_is_ignored():
    app = KiraApp.for_test()
    app.on_hotkey_press()
    assert app.state == State.RECORDING
    app.on_hotkey_press()
    # Should still be RECORDING (not reset press_time or change state)
    assert app.state == State.RECORDING


def test_release_without_press_is_ignored():
    app = KiraApp.for_test()
    # Not in RECORDING -> ignored
    app.on_hotkey_release(duration_ms=500)
    assert app.state == State.IDLE


def test_edit_hotkey_uses_selection_and_edit_command(monkeypatch):
    import kira.app as app_module
    monkeypatch.setattr(app_module, "read_selection", lambda: "Hallo Welt")
    app = KiraApp.for_test()
    app.on_hotkey_press()
    app.on_edit_detected()
    assert app.state == State.EDITING
    app.on_hotkey_release(duration_ms=500)
    assert app.state == State.IDLE
    assert app._injector.last == "Hallo Welt+stub"
    assert app._edit_mode is False and app._captured_selection is None


def test_edit_hotkey_without_selection_stays_in_dictation(monkeypatch):
    import kira.app as app_module
    monkeypatch.setattr(app_module, "read_selection", lambda: None)
    app = KiraApp.for_test()
    app.on_hotkey_press()
    app.on_edit_detected()
    assert app.state == State.RECORDING
    app.on_hotkey_release(duration_ms=500)
    assert app._injector.last == "stub"


def test_edit_hotkey_when_pasteboard_unavailable_stays_in_dictation(monkeypatch):
    import kira.app as app_module
    from kira.edit_command import ClipboardUnavailable

    def boom():
        raise ClipboardUnavailable("locked")

    monkeypatch.setattr(app_module, "read_selection", boom)
    app = KiraApp.for_test()
    app.on_hotkey_press()
    app.on_edit_detected()
    assert app.state == State.RECORDING
