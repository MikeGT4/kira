import asyncio
import pytest
from kira.app import KiraApp, State
from kira.config import Config
from kira.recorder import Recorder


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


def test_release_with_stopped_loop_resets_to_idle():
    """If the asyncio loop is set but not running (e.g. shutdown race),
    run_coroutine_threadsafe would silently drop the work. The pipeline
    must reset to IDLE instead of leaving the state machine stuck in
    RECORDING — otherwise the next F8 is ignored forever."""
    app = KiraApp.for_test()
    loop = asyncio.new_event_loop()  # created but never started
    app.set_loop(loop)
    assert not loop.is_running()
    app.on_hotkey_press()
    app.on_hotkey_release(duration_ms=500)
    assert app.state == State.IDLE
    loop.close()


class _EmptyStyler:
    """Returns the empty string regardless of input — simulates the
    'fallback_to_raw=False + model returned empty content' path."""
    def __init__(self, cfg): self.cfg = cfg
    async def polish(self, text, mode): return ""


class _RecordingInjector:
    def __init__(self): self.last = "<unset>"
    def inject(self, text): self.last = text


def test_empty_polish_does_not_inject():
    """Empty polish output must skip inject() rather than passing "" through.
    Earlier code logged a warning but still called injector.inject(""),
    which is a silent no-op the user never sees."""
    cfg = Config()
    injector = _RecordingInjector()
    app = KiraApp(
        config=cfg,
        recorder=Recorder(),
        transcriber=KiraApp.for_test()._transcriber,  # stub returns "stub"
        styler=_EmptyStyler(cfg),
        injector=injector,
    )
    app.on_hotkey_press()
    app.on_hotkey_release(duration_ms=500)
    assert app.state == State.IDLE
    # injector must NOT have been called with empty string
    assert injector.last == "<unset>"
