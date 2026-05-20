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
