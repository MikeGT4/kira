# © 2026 Mike Pollow, Digitalroots. Alle Rechte vorbehalten.
"""Tests für den Tray-Eintrag „Gelernte Wörter". Windows-only."""
from __future__ import annotations
import sys
from unittest.mock import MagicMock
import pytest

if sys.platform != "win32":
    pytest.skip("windows-only tests", allow_module_level=True)


class FakeLearning:
    def __init__(self, pending):
        self.pending = pending

    def pending_count(self):
        return self.pending


class FakeLearningPendingCountRaises:
    """Simuliert ein kaputtes Lexikon: pending_count() wirft."""

    def pending_count(self):
        raise RuntimeError("boom")


def _tray(learning=None):
    from kira.ui.tray_win import KiraTray
    return KiraTray(on_quit=lambda: None, learning=learning)


def _texts(menu):
    return [str(item.text) for item in menu.items]


def test_menu_shows_count_of_pending_words():
    assert "Gelernte Wörter (3 neu)…" in _texts(_tray(FakeLearning(3))._build_menu())


def test_menu_label_without_pending_words():
    assert "Gelernte Wörter…" in _texts(_tray(FakeLearning(0))._build_menu())


def test_menu_hides_entry_without_learning():
    assert not any("Gelernte Wörter" in t for t in _texts(_tray()._build_menu()))


def test_menu_label_survives_pending_count_error():
    """pending_count() kann werfen (kaputtes Lexikon, IO-Fehler): das Menü
    zeigt dann trotzdem den Grundtext, statt den Aufbau abzubrechen."""
    texts = _texts(_tray(FakeLearningPendingCountRaises())._build_menu())
    assert "Gelernte Wörter…" in texts


def test_menu_entry_directly_after_settings():
    texts = _texts(_tray(FakeLearning(3))._build_menu())
    idx = texts.index("Einstellungen…")
    assert texts[idx + 1] == "Gelernte Wörter (3 neu)…"


def test_open_when_already_open_raises_existing():
    tray = _tray(FakeLearning(0))
    existing = MagicMock()
    tray._learned_dlg = existing
    tray._show_learned_words_dialog()
    existing.raise_.assert_called_once()
    existing.activateWindow.assert_called_once()
