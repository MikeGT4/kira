"""Tests fuer den SettingsDialog. Windows-only (PyQt6-Stack).

Der Dialog selbst ist ohne QApplication nicht instanziierbar; getestet
wird die reine Resolve-Logik des F9-Toggles, die als Staticmethod aus
der Widget-Verdrahtung herausgezogen ist.
"""
from __future__ import annotations
import sys
import pytest

if sys.platform != "win32":
    pytest.skip("windows-only tests (PyQt6)", allow_module_level=True)


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
