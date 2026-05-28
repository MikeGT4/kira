"""Tests fuer den SettingsDialog. Windows-only (PyQt6-Stack).

Der Dialog selbst ist ohne QApplication nicht instanziierbar; getestet
wird die reine Resolve-Logik des F9-Toggles, die als Staticmethod aus
der Widget-Verdrahtung herausgezogen ist.

Plus _PullWorker-Tests (qtbot) für den Modell-Pull-Pfad: Cancel-Flag,
qint64-Overflow-Schutz, Pydantic- vs Dict-Event-Parsing.
"""
from __future__ import annotations
import sys
import types
import pytest

if sys.platform != "win32":
    pytest.skip("windows-only tests (PyQt6)", allow_module_level=True)


def _install_fake_ollama(monkeypatch, events):
    """Plant ein Mini-Ollama-Modul in sys.modules. `events` ist Iterable;
    `_PullWorker.run()` macht `import ollama` und ruft `ollama.pull(...)`."""
    fake = types.ModuleType("ollama")
    fake.pull = lambda model, stream=False: iter(events)
    monkeypatch.setitem(sys.modules, "ollama", fake)


def test_resolve_edit_combo_disabled_returns_none():
    """Checkbox aus -> Feature aus, egal was im Hotkey-Feld steht."""
    from kira.ui.settings_dialog import SettingsDialog
    assert SettingsDialog._resolve_edit_combo(False, "f9") is None
    assert SettingsDialog._resolve_edit_combo(False, "") is None


def test_resolve_edit_combo_enabled_returns_field_value():
    """Checkbox an -> der Hotkey-Name aus dem Feld wird uebernommen."""
    from kira.ui.settings_dialog import SettingsDialog
    assert SettingsDialog._resolve_edit_combo(True, "f9") == "f9"


def test_resolve_edit_combo_enabled_with_blank_field_returns_none():
    """Checkbox an, aber Feld leer oder nur Whitespace -> kein Hotkey."""
    from kira.ui.settings_dialog import SettingsDialog
    assert SettingsDialog._resolve_edit_combo(True, "") is None
    assert SettingsDialog._resolve_edit_combo(True, "   ") is None


def test_resolve_edit_combo_strips_surrounding_whitespace():
    """Umgebenden Whitespace trimmen, damit ' f9 ' sauber als 'f9' landet."""
    from kira.ui.settings_dialog import SettingsDialog
    assert SettingsDialog._resolve_edit_combo(True, "  f9  ") == "f9"


# ----- unzensiertes Modell --------------------------------------------------


def test_uncensored_model_constant_is_verified_ollama_name():
    """Die Modul-Konstante zeigt auf das abliterierte Qwen3.6 27B."""
    from kira.ui.settings_dialog import _UNCENSORED_MODEL
    assert _UNCENSORED_MODEL == "huihui_ai/Qwen3.6-abliterated:27b"


def test_uncensored_gpu_blocks_warns_on_tight_and_insufficient():
    """Knapper / zu wenig VRAM -> vor dem 27B-Pull eine Warnung mit
    Abbruch-Option zeigen."""
    from kira.ui.settings_dialog import SettingsDialog
    assert SettingsDialog._uncensored_gpu_blocks("insufficient") is True
    assert SettingsDialog._uncensored_gpu_blocks("tight") is True


def test_uncensored_gpu_blocks_passes_on_ok_and_no_gpu():
    """Status 'ok' ist unkritisch; 'no_gpu' hat schon einen eigenen
    GPU-Check-Hinweis -> hier nicht doppelt warnen."""
    from kira.ui.settings_dialog import SettingsDialog
    assert SettingsDialog._uncensored_gpu_blocks("ok") is False
    assert SettingsDialog._uncensored_gpu_blocks("no_gpu") is False


def test_uncensored_model_gpu_estimate_is_27b_class():
    """Sanity-Check der Integration mit gpu_check: der Modellname muss
    von estimate_polish_vram als ~16-GB-Klasse erkannt werden (sonst
    liefe der GPU-Check vor dem Pull ins Leere)."""
    from kira.gpu_check import estimate_polish_vram
    from kira.ui.settings_dialog import _UNCENSORED_MODEL
    assert estimate_polish_vram(_UNCENSORED_MODEL) >= 15.0


# ----- _PullWorker --------------------------------------------------------
#
# Regression-Tests gegen den 2026-05-28-Bug: User klickte „Unzensiertes
# Modell laden", sah Minusprozente + endloses Laden + Abbrechen ohne
# Wirkung. Root Causes:
#   1) pyqtSignal(int, int) marshalled C int (32-bit signed) → Werte
#      > 2 GiB wrappten in den negativen Bereich
#   2) _PullWorker hatte keine cancel()-Methode + Cancel-Signal war
#      nicht verdrahtet → der Knopf war wirkungslos
# Die Tests pinnen beide Verhalten fest.


def test_pull_worker_starts_with_cancelled_flag_false(qtbot):
    from kira.ui.settings_dialog import _PullWorker
    w = _PullWorker("any-model")
    assert w._cancelled is False


def test_pull_worker_cancel_sets_flag_true(qtbot):
    from kira.ui.settings_dialog import _PullWorker
    w = _PullWorker("any-model")
    w.cancel()
    assert w._cancelled is True


def test_pull_worker_loop_aborts_when_cancel_called_between_yields(
    qtbot, monkeypatch,
):
    """Cancel-Flag wird im Generator-Loop beim nächsten yield gecheckt
    und triggert finished(False, 'Abgebrochen.') — ohne die restlichen
    Events abzuarbeiten."""
    from kira.ui.settings_dialog import _PullWorker

    events = [
        {"status": "pulling manifest", "completed": 0, "total": 0},
        {"status": "downloading", "completed": 1_000_000, "total": 17_000_000_000},
        {"status": "downloading", "completed": 5_000_000, "total": 17_000_000_000},
    ]
    _install_fake_ollama(monkeypatch, events)

    w = _PullWorker("any")
    progress_calls: list = []
    finished_calls: list = []

    def on_progress(status, completed, total):
        progress_calls.append((status, completed, total))
        # nach dem ersten Event Cancel triggern
        if len(progress_calls) == 1:
            w.cancel()

    w.progress.connect(on_progress)
    w.finished.connect(lambda ok, msg: finished_calls.append((ok, msg)))
    w.run()

    assert len(progress_calls) == 1
    assert finished_calls == [(False, "Abgebrochen.")]


def test_pull_worker_emits_large_byte_counts_without_int32_overflow(
    qtbot, monkeypatch,
):
    """Layer eines 17 GB-Modells (das unzensierte Qwen3.6-27B hat einen
    17.4 GB-Blob) liefern completed/total > 2 GiB. Mit pyqtSignal(int)
    wuerden die Werte auf C int (32-bit) gemappt und zu negativen
    Zahlen wrappen — qint64 muss die echten Byte-Werte 1:1 durchreichen."""
    from kira.ui.settings_dialog import _PullWorker

    big_completed = 5 * 1024 ** 3           # 5 GiB
    big_total = 17 * 1024 ** 3 + 432        # 17.4 GiB
    assert big_completed > 2**31, "Test-Setup-Bug: Wert ist nicht overflow-gross"
    assert big_total > 2**31

    events = [{
        "status": "downloading",
        "completed": big_completed,
        "total": big_total,
    }]
    _install_fake_ollama(monkeypatch, events)

    seen: list = []
    w = _PullWorker("any")
    w.progress.connect(lambda s, c, t: seen.append((s, c, t)))
    w.finished.connect(lambda *a: None)
    w.run()

    assert len(seen) == 1
    status, completed, total = seen[0]
    assert status == "downloading"
    # NICHT negativ, NICHT gewrappt — exakte Byte-Werte
    assert completed == big_completed
    assert total == big_total
    assert completed > 0
    assert total > 0


def test_pull_worker_finished_true_on_clean_stream(qtbot, monkeypatch):
    """Stream-Ende ohne Cancel → finished.emit(True, <message mit Modellname>)."""
    from kira.ui.settings_dialog import _PullWorker

    events = [
        {"status": "pulling manifest"},
        {"status": "downloading", "completed": 100, "total": 1000},
        {"status": "verifying sha256 digest"},
        {"status": "writing manifest"},
        {"status": "success"},
    ]
    _install_fake_ollama(monkeypatch, events)

    finished_calls: list = []
    w = _PullWorker("my-model")
    w.progress.connect(lambda *a: None)
    w.finished.connect(lambda ok, msg: finished_calls.append((ok, msg)))
    w.run()

    assert len(finished_calls) == 1
    ok, msg = finished_calls[0]
    assert ok is True
    assert "my-model" in msg


def test_pull_worker_finished_false_when_ollama_raises(qtbot, monkeypatch):
    """Ein Stream-Fehler (Netz weg, Modellname falsch) → finished.emit(
    False, <fehler-msg>)."""
    from kira.ui.settings_dialog import _PullWorker

    fake = types.ModuleType("ollama")

    def boom(*args, **kwargs):
        raise ConnectionError("Ollama-Server nicht erreichbar")

    fake.pull = boom  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "ollama", fake)

    finished_calls: list = []
    w = _PullWorker("foo")
    w.progress.connect(lambda *a: None)
    w.finished.connect(lambda ok, msg: finished_calls.append((ok, msg)))
    w.run()

    assert len(finished_calls) == 1
    ok, msg = finished_calls[0]
    assert ok is False
    assert "Modell-Update fehlgeschlagen" in msg


def test_pull_worker_parses_pydantic_style_events(qtbot, monkeypatch):
    """ollama-lib v0.4+ liefert PullResponse-Objekte (Attribut-Access),
    nicht dict. _PullWorker muss beide Wege handhaben (getattr-Pfad).
    Regression: vor 2026-05-28 war der Fallback-Operator-Chain mit
    `or 0` da, aber das Pydantic-Pfad-Branching ist seitdem unverändert."""
    from kira.ui.settings_dialog import _PullWorker

    class FakeEvent:
        def __init__(self, **kw):
            for k, v in kw.items():
                setattr(self, k, v)

    events = [FakeEvent(
        status="downloading",
        completed=2_000_000_000,
        total=5_000_000_000,
    )]
    _install_fake_ollama(monkeypatch, events)

    seen: list = []
    w = _PullWorker("any")
    w.progress.connect(lambda s, c, t: seen.append((s, c, t)))
    w.finished.connect(lambda *a: None)
    w.run()

    assert seen == [("downloading", 2_000_000_000, 5_000_000_000)]


def test_pull_worker_does_not_emit_progress_after_cancel(qtbot, monkeypatch):
    """Wenn die Loop wegen Cancel aussteigt, darf KEIN weiteres
    progress-Signal mehr feuern — sonst landet ein verspätetes Update
    in einem schon geschlossenen QProgressDialog."""
    from kira.ui.settings_dialog import _PullWorker

    events = [
        {"status": "a", "completed": 100, "total": 1000},
        {"status": "b", "completed": 200, "total": 1000},
        {"status": "c", "completed": 300, "total": 1000},
        {"status": "d", "completed": 400, "total": 1000},
    ]
    _install_fake_ollama(monkeypatch, events)

    w = _PullWorker("any")
    progress_calls: list = []

    def on_progress(*a):
        progress_calls.append(a)
        w.cancel()  # nach jedem Event canceln → genau 1 Event durch

    w.progress.connect(on_progress)
    w.finished.connect(lambda *a: None)
    w.run()

    assert len(progress_calls) == 1, progress_calls
