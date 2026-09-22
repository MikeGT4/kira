# © 2026 Mike Pollow, Digitalroots. Alle Rechte vorbehalten.
"""Tests für das Fenster „Gelernte Wörter". Windows-only (PyQt6)."""
from __future__ import annotations
import sys
from datetime import datetime, timedelta, timezone
import pytest

if sys.platform != "win32":
    pytest.skip("windows-only tests (PyQt6)", allow_module_level=True)

from kira.lexicon import STATUS_REJECTED, Lexicon

T0 = datetime(2026, 9, 22, 12, 0, tzinfo=timezone.utc)


class FakeService:
    def __init__(self, lexicon):
        self.lexicon = lexicon

    def metrics(self):
        return {"this_week": (3, 176), "last_week": None, "baseline": (17, 976),
                "coverage": (176, 214)}


def _lexicon(tmp_path):
    lex = Lexicon(tmp_path / "learned.json")
    lex.observe("kuh bernetes", "Kubernetes", kind="replacement", vocab=True,
                example="auf kuh bernetes", when=T0)
    for day in (1, 2):
        lex.observe("doku", "Docker", kind="replacement", vocab=True,
                    example="mit doku", when=T0 + timedelta(days=day))
    return lex


def test_format_rate():
    from kira.ui.learned_words_dialog import format_rate
    assert format_rate((3, 176)) == "1,7 % (3 von 176)"
    assert format_rate(None) == "noch keine Daten"


def test_tables_show_pending_and_active(qtbot, tmp_path):
    from kira.ui.learned_words_dialog import LearnedWordsDialog
    dlg = LearnedWordsDialog(FakeService(_lexicon(tmp_path)))
    qtbot.addWidget(dlg)
    assert dlg.pending_table.rowCount() == 1
    assert dlg.active_table.rowCount() == 1
    assert dlg.pending_table.item(0, 1).text() == "Kubernetes"
    assert "1,7 %" in dlg.metrics_label.text()
    assert "Zuordnung diese Woche: 82,2 % (176 von 214)" in dlg.metrics_label.text()


def test_accept_moves_entry_to_active_and_saves(qtbot, tmp_path):
    from kira.ui.learned_words_dialog import LearnedWordsDialog
    dlg = LearnedWordsDialog(FakeService(_lexicon(tmp_path)))
    qtbot.addWidget(dlg)
    dlg.pending_table.selectRow(0)
    dlg.accept_button.click()
    assert dlg.pending_table.rowCount() == 0
    assert dlg.active_table.rowCount() == 2
    assert (tmp_path / "learned.json").exists()


def test_delete_rejects_active_entry(qtbot, tmp_path):
    from kira.ui.learned_words_dialog import LearnedWordsDialog
    lex = _lexicon(tmp_path)
    dlg = LearnedWordsDialog(FakeService(lex))
    qtbot.addWidget(dlg)
    dlg.active_table.selectRow(0)
    dlg.delete_button.click()
    assert dlg.active_table.rowCount() == 0
    assert [e.status for e in lex.entries() if e.right == "Docker"] == [STATUS_REJECTED]
