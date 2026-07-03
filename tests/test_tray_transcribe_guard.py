"""Tests für KiraTray._show_transcribe_file_dialog — Anker + Doppel-Start-Guard.

Review-Findings 2026-07-03: (a) QThread/Worker/Progress hingen als
Attribute am Progress-Dialog, der selbst nur Teil des Referenz-Zyklus
war — Pythons Zyklus-GC konnte den laufenden QThread einsammeln.
(b) Ein zweiter Klick auf „Datei transkribieren…" während eines
laufenden Jobs hätte die Anker überschrieben (und Whisper doppelt
belegt). Anker liegen jetzt auf der langlebigen Tray-Instanz, ein
Guard blockt den Doppel-Start mit Hinweis-Dialog.

Gleiche Konstruktions-Muster wie test_tray_settings_guard.py.
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


def test_transcribe_anchors_start_none(tray):
    """Frische Tray hält keine Transcribe-Referenzen."""
    assert tray._transcribe_thread is None
    assert tray._transcribe_worker is None
    assert tray._transcribe_progress is None


def test_second_transcription_while_running_shows_hint(tray, monkeypatch):
    """Läuft schon ein Transcribe-QThread, zeigt ein erneuter Aufruf nur
    den Hinweis und öffnet KEINEN File-Dialog (Anker bleiben unberührt)."""
    running = MagicMock()
    running.isRunning.return_value = True
    tray._transcribe_thread = running

    infos = []
    monkeypatch.setattr(
        "kira.ui._dialog_style.light_information",
        lambda *a, **k: infos.append(a),
    )
    from PyQt6.QtWidgets import QFileDialog
    opened = []
    monkeypatch.setattr(
        QFileDialog, "getOpenFileName",
        staticmethod(lambda *a, **k: (opened.append(1), ("", ""))[1]),
    )

    tray._show_transcribe_file_dialog(transcriber=MagicMock())

    assert infos, "Hinweis-Dialog muss erscheinen"
    assert not opened, "kein File-Dialog waehrend laufendem Job"
    assert tray._transcribe_thread is running  # Anker unberührt


def test_finished_thread_does_not_block_new_transcription(tray, monkeypatch):
    """Ein ausgelaufener (nicht mehr running) Thread-Rest blockt nicht —
    der User kommt bis zum File-Dialog (der hier Cancel liefert)."""
    finished = MagicMock()
    finished.isRunning.return_value = False
    tray._transcribe_thread = finished

    infos = []
    monkeypatch.setattr(
        "kira.ui._dialog_style.light_information",
        lambda *a, **k: infos.append(a),
    )
    from PyQt6.QtWidgets import QFileDialog
    opened = []
    monkeypatch.setattr(
        QFileDialog, "getOpenFileName",
        staticmethod(lambda *a, **k: (opened.append(1), ("", ""))[1]),
    )

    tray._show_transcribe_file_dialog(transcriber=MagicMock())

    assert opened, "File-Dialog muss aufgehen"
    assert not infos, "kein Blockier-Hinweis"
