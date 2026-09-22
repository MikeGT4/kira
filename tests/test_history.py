# © 2026 Mike Pollow, Digitalroots. Alle Rechte vorbehalten.
"""Tests für kira.history."""
from __future__ import annotations
import json
from datetime import datetime, timezone
from kira.history import HistoryRecord, HistoryWriter, prune, read_records


def _rec(ts, text="Hallo Welt"):
    return HistoryRecord(ts=ts, app="notepad.exe", mode="plain", raw=text.lower(),
                         text=text, avg_logprob=-0.2, duration_s=1.5)


def test_append_writes_one_json_line_into_the_month_file(tmp_path):
    HistoryWriter(tmp_path).append(_rec("2026-09-22T20:15:33+02:00"))
    lines = (tmp_path / "2026-09.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0])["text"] == "Hallo Welt"


def test_umlauts_are_stored_as_text(tmp_path):
    HistoryWriter(tmp_path).append(_rec("2026-09-22T20:15:33+02:00", "Grüße"))
    assert "Grüße" in (tmp_path / "2026-09.jsonl").read_text(encoding="utf-8")


def test_read_records_filters_by_time_and_skips_broken_lines(tmp_path):
    w = HistoryWriter(tmp_path)
    w.append(_rec("2026-08-31T10:00:00+02:00", "alt"))
    w.append(_rec("2026-09-01T10:00:00+02:00", "neu"))
    with (tmp_path / "2026-09.jsonl").open("a", encoding="utf-8") as fh:
        fh.write("{kaputt\n")
    since = datetime(2026, 9, 1, 0, 0, tzinfo=timezone.utc)
    assert [r.text for r in read_records(tmp_path, since)] == ["neu"]
    assert [r.text for r in read_records(tmp_path)] == ["alt", "neu"]


def test_read_records_on_missing_directory_yields_nothing(tmp_path):
    assert list(read_records(tmp_path / "fehlt")) == []


def test_prune_keeps_three_months(tmp_path):
    for month in ("2026-05", "2026-06", "2026-09"):
        (tmp_path / f"{month}.jsonl").write_text("", encoding="utf-8")
    removed = prune(tmp_path, datetime(2026, 9, 22, tzinfo=timezone.utc))
    assert [p.name for p in removed] == ["2026-05.jsonl"]
    assert sorted(p.name for p in tmp_path.glob("*.jsonl")) == ["2026-06.jsonl", "2026-09.jsonl"]
