import asyncio
import numpy as np
import pytest
from kira.app import KiraApp, State
from kira.config import Config
from kira.recorder import Recorder, DeviceUnavailable


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


class _BrokenRecorder(Recorder):
    """Recorder-Stub, der bei start() DeviceUnavailable wirft —
    simuliert das Crash-Loop-Szenario vom 2026-04-30 morgens, als
    das ROG-Theta-USB-Headset beim Boot noch nicht im Audio-Stack
    enumeriert war.

    Erbt von Recorder damit KiraApp.__init__'s strikter
    `recorder: Recorder`-Type-Hint zufrieden ist; der Konstruktor
    macht kein Audio-Setup (nur Attribut-Initialisierung), das
    überschriebene start() umgeht den echten sd.InputStream-Pfad."""

    def __init__(self):
        super().__init__()
        self.start_calls = 0

    def start(self):
        self.start_calls += 1
        raise DeviceUnavailable(
            "audio.input_device='ROG Theta' not available right now"
        )


def test_hotkey_press_with_unavailable_device_sets_error_state():
    """F8 mit absentem Mikro → State.ERROR, Pipeline nicht angelaufen.
    Trigger: Crash-Loop am 2026-04-30 morgens, weil ROG Theta beim
    Boot noch nicht enumeriert war."""
    cfg = Config()
    injector = _RecordingInjector()
    broken = _BrokenRecorder()
    app = KiraApp(
        config=cfg,
        recorder=broken,
        transcriber=KiraApp.for_test()._transcriber,
        styler=KiraApp.for_test()._styler,
        injector=injector,
    )
    app.on_hotkey_press()
    assert app.state == State.ERROR
    assert broken.start_calls == 1
    # Pipeline darf nicht gelaufen sein:
    assert injector.last == "<unset>"


def test_hotkey_release_after_device_error_is_ignored():
    """Nach DeviceUnavailable bei press: state ist ERROR, ein folgendes
    release darf den State nicht durcheinanderbringen — release() prüft
    state == RECORDING, ERROR ist das nicht, also no-op."""
    cfg = Config()
    injector = _RecordingInjector()
    app = KiraApp(
        config=cfg,
        recorder=_BrokenRecorder(),
        transcriber=KiraApp.for_test()._transcriber,
        styler=KiraApp.for_test()._styler,
        injector=injector,
    )
    app.on_hotkey_press()
    assert app.state == State.ERROR
    app.on_hotkey_release(duration_ms=500)
    # State darf nicht zu RECORDING/IDLE wechseln durch den Release.
    assert app.state == State.ERROR
    assert injector.last == "<unset>"


def test_hotkey_press_ignored_while_in_error_state():
    """Während des 3-s-ERROR-Holds darf ein zweites F8 nicht erneut
    Recorder.start() aufrufen — wir warten auf den Auto-Reset zu IDLE.
    Verhindert eine Endlos-Schleife wenn der User F8 panisch drückt."""
    cfg = Config()
    broken = _BrokenRecorder()
    app = KiraApp(
        config=cfg,
        recorder=broken,
        transcriber=KiraApp.for_test()._transcriber,
        styler=KiraApp.for_test()._styler,
        injector=_RecordingInjector(),
    )
    app.on_hotkey_press()
    assert broken.start_calls == 1
    assert app.state == State.ERROR
    # Zweiter Press während ERROR: ignoriert (state != IDLE)
    app.on_hotkey_press()
    assert broken.start_calls == 1  # KEIN zweiter start()-Call


# ===== Edit-Command-Pfad (F9) =========================================


class _EditAwareStyler:
    """Stub-Styler mit polish()+edit_command()-Methoden, der
    Aufrufe protokolliert. Erlaubt Pipeline-Branch-Tests ohne Ollama."""

    def __init__(self, cfg):
        self.cfg = cfg
        self.polish_calls = []
        self.edit_calls = []

    async def polish(self, text, mode):
        self.polish_calls.append((text, mode))
        return text

    async def edit_command(self, selection, command):
        self.edit_calls.append((selection, command))
        return f"[edited]:{selection}"


def test_edit_press_no_selection_stays_idle(monkeypatch):
    """on_edit_press ohne Selection: bleibt IDLE, kein Recording, kein
    Edit-Mode-Flag haengen. Fix-Prevention: Edit-Mode-Pollution beim
    naechsten F8."""
    monkeypatch.setattr("kira.app.read_selection", lambda: None)
    app = KiraApp.for_test()
    app.on_edit_press()
    assert app.state == State.IDLE
    assert app._edit_mode is False
    assert app._captured_selection is None


def test_edit_press_with_selection_enters_recording_with_flags(monkeypatch):
    monkeypatch.setattr("kira.app.read_selection", lambda: "selected text")
    app = KiraApp.for_test()
    app.on_edit_press()
    assert app.state == State.RECORDING
    assert app._edit_mode is True
    assert app._captured_selection == "selected text"


def test_edit_pipeline_calls_edit_command_not_polish(monkeypatch):
    """Voller F9-Cycle: press (mit Selection) → release → Pipeline
    nimmt edit_command-Pfad, nicht polish."""
    monkeypatch.setattr("kira.app.read_selection", lambda: "hi leute")
    cfg = Config()
    styler = _EditAwareStyler(cfg)
    injector = _RecordingInjector()
    app = KiraApp(
        config=cfg,
        recorder=Recorder(),
        transcriber=KiraApp.for_test()._transcriber,  # returns "stub"
        styler=styler,
        injector=injector,
    )
    app.on_edit_press()
    assert app.state == State.RECORDING
    app.on_hotkey_release(duration_ms=500)
    assert app.state == State.IDLE
    # Edit-Pfad genommen, NICHT polish
    assert len(styler.edit_calls) == 1
    assert styler.edit_calls[0] == ("hi leute", "stub")
    assert len(styler.polish_calls) == 0
    # Injection mit Edit-Output
    assert injector.last == "[edited]:hi leute"


def test_normal_f8_pipeline_still_calls_polish(monkeypatch):
    """Sicherstellen dass F8 (ohne edit_press) weiterhin polish() ruft,
    nicht versehentlich edit_command. Regression-Guard fuer den Branch."""
    cfg = Config()
    styler = _EditAwareStyler(cfg)
    injector = _RecordingInjector()
    app = KiraApp(
        config=cfg,
        recorder=Recorder(),
        transcriber=KiraApp.for_test()._transcriber,
        styler=styler,
        injector=injector,
    )
    app.on_hotkey_press()
    app.on_hotkey_release(duration_ms=500)
    assert len(styler.polish_calls) == 1
    assert len(styler.edit_calls) == 0


def test_edit_flags_reset_after_pipeline(monkeypatch):
    """Nach erfolgreicher Edit-Pipeline muessen _edit_mode und
    _captured_selection wieder None sein, damit der naechste F8
    nicht versehentlich als Edit interpretiert wird."""
    monkeypatch.setattr("kira.app.read_selection", lambda: "selection")
    app = KiraApp.for_test()
    app.on_edit_press()
    app.on_hotkey_release(duration_ms=500)
    assert app._edit_mode is False
    assert app._captured_selection is None


def test_edit_flags_reset_after_short_press(monkeypatch):
    """Short-Press (unter min_duration_ms) skippt die Pipeline — Flags
    muessen trotzdem zuruecksetzen."""
    monkeypatch.setattr("kira.app.read_selection", lambda: "selection")
    app = KiraApp.for_test()
    app.on_edit_press()
    app.on_hotkey_release(duration_ms=50)  # below 300ms
    assert app.state == State.IDLE
    assert app._edit_mode is False
    assert app._captured_selection is None
