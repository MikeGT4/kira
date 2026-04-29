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
