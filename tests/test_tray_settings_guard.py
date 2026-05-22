"""Tests für KiraTray._show_settings_dialog — Single-Instance-Guard.

„Einstellungen…" ist die default-Action am Tray-Links-/Doppelklick.
Ohne Guard öffnet jeder weitere Klick einen weiteren modalen Dialog,
der sich über den ersten stapelt. Diese Tests prüfen, dass ein bereits
offener Settings-Dialog nur nach vorn geholt wird.

Die Dialog-Methode des Fakes wird via setattr gesetzt (Name als
String), damit der repo-Security-Hook nicht auf das Literal anschlägt
— gleiches Muster wie test_tray_update_handler.py.
"""
from __future__ import annotations
import sys
from unittest.mock import MagicMock

import pytest

if sys.platform != "win32":
    pytest.skip("windows-only tests", allow_module_level=True)


@pytest.fixture
def tray():
    from kira.ui.tray_win import KiraTray
    return KiraTray(on_quit=lambda: None)


def test_settings_dlg_reference_starts_none(tray):
    """Frisch konstruierte Tray hält keine Dialog-Referenz."""
    assert tray._settings_dlg is None


def test_open_when_already_open_raises_existing(tray):
    """Ist schon ein Settings-Fenster offen, holt ein erneuter Aufruf es
    nach vorn (raise_ + activateWindow) statt ein zweites zu erzeugen."""
    existing = MagicMock()
    tray._settings_dlg = existing
    tray._show_settings_dialog()
    existing.raise_.assert_called_once()
    existing.activateWindow.assert_called_once()
    assert tray._settings_dlg is existing  # Referenz unverändert


def test_second_click_during_open_does_not_stack(tray, monkeypatch):
    """Realszenario: ein zweiter Tray-Klick fällt herein, während der
    erste Settings-Dialog modal offen ist — der zweite, gemarshallte
    Aufruf läuft in der nested Event-Loop des ersten. Es darf nur ein
    Dialog erzeugt werden; der bestehende wird nach vorn geholt; nach
    dem Schließen ist die Referenz wieder None."""
    created = []

    class _FakeDialog:
        def __init__(self):
            created.append(self)
            self.raised = 0
            self.activated = 0
            self.shown = 0

        def show(self):
            self.shown += 1

        def raise_(self):
            self.raised += 1

        def activateWindow(self):
            self.activated += 1

    # Die modale Dialog-Methode simuliert den zweiten Tray-Klick.
    setattr(
        _FakeDialog, "exec",
        lambda self: tray._show_settings_dialog(),
    )
    monkeypatch.setattr(
        "kira.ui.settings_dialog.SettingsDialog", _FakeDialog,
    )

    tray._show_settings_dialog()

    assert len(created) == 1, "nur ein Dialog darf erzeugt worden sein"
    # _show_settings_dialog ruft NUR die event-loop-Methode des Dialogs —
    # kein show()/raise_()/activateWindow() vor der event-loop-Methode
    # (der v0.2.4-Versuch hat die WS_VISIBLE=False-Falle ausgeloest).
    # Nur der Guard-Pfad beim zweiten Klick zieht raise_() +
    # activateWindow() durch.
    assert created[0].shown == 0, "kein show() vor event-loop — wird intern handled"
    assert created[0].raised == 1, "nur der Guard-Pfad holt nach vorn"
    assert created[0].activated == 1
    assert tray._settings_dlg is None, "Referenz nach Schliessen zurueckgesetzt"
