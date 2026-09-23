# © 2026 Mike Pollow, Digitalroots. Alle Rechte vorbehalten.
"""Tests für kira.learning_win.LearningService. Windows-only (transcriber_fw)."""
from __future__ import annotations
import json
import logging
import sys
from datetime import datetime, timedelta, timezone
import pytest

if sys.platform != "win32":
    pytest.skip("windows-only tests", allow_module_level=True)

from kira.learning_win import LearningService, prune_history
from kira.lexicon import Lexicon
from kira.transcriber_fw import TranscriptionResult

T0 = datetime(2026, 9, 22, 12, 0, tzinfo=timezone.utc)


class Clock:
    def __init__(self, now):
        self.now = now

    def __call__(self):
        return self.now


def _service(tmp_path, clock, sources=True, words=frozenset({"wir", "auf"})):
    src = tmp_path / "src"
    src.mkdir(exist_ok=True)
    return LearningService(
        sources=[src] if sources else [],
        lexicon=Lexicon(tmp_path / "learned.json"),
        history_dir=tmp_path / "history",
        state_path=tmp_path / "state.json",
        log_paths=[tmp_path / "kira.log"],
        words=words,
        active_app=lambda: "windowsterminal.exe",
        clock=clock,
    )


def _sent(tmp_path, when, text):
    stamp = when.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    with (tmp_path / "src" / "s.jsonl").open("a", encoding="utf-8") as fh:
        fh.write(json.dumps({"type": "user", "timestamp": stamp,
                             "message": {"content": text}}) + "\n")


def test_first_start_records_the_starting_point(tmp_path):
    _service(tmp_path, Clock(T0))
    state = json.loads((tmp_path / "state.json").read_text(encoding="utf-8"))
    assert state["started"] == T0.isoformat(timespec="seconds")


def test_after_inject_writes_history_line(tmp_path):
    svc = _service(tmp_path, Clock(T0))
    result = TranscriptionResult(text="Wir deployen", language="de", raw_text="wir deployen", avg_logprob=-0.3)
    svc.after_inject(mode="terminal", transcription=result, text="Wir deployen", duration_s=1.234)
    line = json.loads((tmp_path / "history" / "2026-09.jsonl").read_text(encoding="utf-8"))
    assert (line["app"], line["mode"], line["raw"], line["duration_s"]) == (
        "windowsterminal.exe", "terminal", "wir deployen", 1.23)


def test_learning_cycle_end_to_end(tmp_path):
    clock = Clock(T0)
    svc = _service(tmp_path, clock)
    result = TranscriptionResult(text="wir deployen auf kuh bernetes", language="de")
    clock.now = T0 + timedelta(minutes=1)
    svc.after_inject(mode="terminal", transcription=result, text=result.text, duration_s=2.0)
    _sent(tmp_path, T0 + timedelta(minutes=2), "Wir deployen auf Kubernetes")
    clock.now = T0 + timedelta(minutes=40)
    svc.run_once()
    assert svc.pending_count() == 1
    assert svc.metrics()["this_week"] == (1, 1)


def test_glossary_for_offers_active_glossary_terms(tmp_path):
    svc = _service(tmp_path, Clock(T0))
    for day in (1, 2):
        svc.lexicon.observe("nass", "NAS", kind="glossary", vocab=True, example="",
                            when=T0 + timedelta(days=day))
    assert svc.glossary_for("leg das auf das nass") == ["NAS"]


def test_run_without_sources_only_prunes(tmp_path):
    svc = _service(tmp_path, Clock(T0), sources=False)
    svc.run_once()
    assert svc.pending_count() == 0


def test_failing_run_is_logged_not_raised(tmp_path, monkeypatch, caplog):
    svc = _service(tmp_path, Clock(T0))

    def boom(**kwargs):
        raise RuntimeError("kaputt")

    monkeypatch.setattr("kira.learning_win.bootstrap", boom)
    with caplog.at_level(logging.ERROR):
        svc.run_once()
    assert "Lauf fehlgeschlagen" in caplog.text


def test_prune_history_deletes_old_months(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    history = tmp_path / "Kira" / "history"
    history.mkdir(parents=True)
    old = history / "2020-01.jsonl"
    current = history / f"{datetime.now():%Y-%m}.jsonl"
    for path in (old, current):
        path.write_text("{}\n", encoding="utf-8")
    prune_history()
    assert not old.exists()
    assert current.exists()


def test_prune_history_logs_errors_instead_of_raising(tmp_path, monkeypatch, caplog):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))

    def boom(directory, now):
        raise OSError("gesperrt")

    monkeypatch.setattr("kira.learning_win.prune", boom)
    with caplog.at_level(logging.ERROR):
        prune_history()
    assert "Verlauf" in caplog.text
