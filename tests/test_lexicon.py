# © 2026 Mike Pollow, Digitalroots. Alle Rechte vorbehalten.
"""Tests für kira.lexicon."""
from __future__ import annotations
import json
import logging
from datetime import datetime, timedelta, timezone
import pytest
from kira.lexicon import (
    KIND_GLOSSARY, KIND_REPLACEMENT, STATUS_ACTIVE, STATUS_PENDING,
    STATUS_REJECTED, Lexicon, build_initial_prompt,
)

T1 = datetime(2026, 9, 1, 10, 0, tzinfo=timezone.utc)
T2 = datetime(2026, 9, 2, 10, 0, tzinfo=timezone.utc)
T3 = datetime(2026, 9, 3, 10, 0, tzinfo=timezone.utc)


def _observe(lex, wrong, right, when, kind=KIND_REPLACEMENT, vocab=True):
    return lex.observe(wrong, right, kind=kind, vocab=vocab, example=f"… {wrong} …", when=when)


def test_first_occurrence_is_pending(tmp_path):
    lex = Lexicon(tmp_path / "learned.json")
    e = _observe(lex, "kuh bernetes", "Kubernetes", T1)
    assert (e.status, e.count) == (STATUS_PENDING, 1)


def test_second_dictation_activates(tmp_path):
    lex = Lexicon(tmp_path / "learned.json")
    _observe(lex, "kuh bernetes", "Kubernetes", T1)
    e = _observe(lex, "Kuh Bernetes", "kubernetes", T2)
    assert (e.status, e.count) == (STATUS_ACTIVE, 2)
    assert lex.active_replacements() == {"kuh bernetes": "Kubernetes"}


def test_rejected_pair_is_never_counted_again(tmp_path):
    lex = Lexicon(tmp_path / "learned.json")
    e = _observe(lex, "kuh bernetes", "Kubernetes", T1)
    lex.reject(e.key)
    assert _observe(lex, "kuh bernetes", "Kubernetes", T2) is None
    assert lex.entries()[0].status == STATUS_REJECTED
    assert lex.entries()[0].count == 1


def test_conflict_keeps_all_unconfirmed_variants_pending(tmp_path):
    lex = Lexicon(tmp_path / "learned.json")
    _observe(lex, "zettel", "Zettelkasten", T1)
    _observe(lex, "zettel", "Zettelkasten", T2)
    _observe(lex, "zettel", "Zettelwirtschaft", T3)
    assert {e.status for e in lex.entries()} == {STATUS_PENDING}


def test_confirmed_entry_survives_conflict(tmp_path):
    lex = Lexicon(tmp_path / "learned.json")
    e = _observe(lex, "zettel", "Zettelkasten", T1)
    lex.accept(e.key)
    _observe(lex, "zettel", "Zettelwirtschaft", T2)
    states = {x.right: x.status for x in lex.entries()}
    assert states == {"Zettelkasten": STATUS_ACTIVE, "Zettelwirtschaft": STATUS_PENDING}


def test_rejecting_one_variant_resolves_conflict(tmp_path):
    lex = Lexicon(tmp_path / "learned.json")
    _observe(lex, "zettel", "Zettelkasten", T1)
    _observe(lex, "zettel", "Zettelkasten", T2)
    other = _observe(lex, "zettel", "Zettelwirtschaft", T3)
    lex.reject(other.key)
    states = {x.right: x.status for x in lex.entries()}
    assert states == {"Zettelkasten": STATUS_ACTIVE, "Zettelwirtschaft": STATUS_REJECTED}


def test_views_split_by_kind_and_vocab(tmp_path):
    lex = Lexicon(tmp_path / "learned.json")
    for when in (T1, T2):
        _observe(lex, "kuh bernetes", "Kubernetes", when)
        _observe(lex, "nass", "NAS", when, kind=KIND_GLOSSARY)
        _observe(lex, "haus", "Maus", when, kind=KIND_GLOSSARY, vocab=False)
    assert lex.active_replacements() == {"kuh bernetes": "Kubernetes"}
    assert [e.right for e in lex.glossary_entries()] == ["Maus", "NAS"]
    assert sorted(lex.vocabulary_terms()) == ["Kubernetes", "NAS"]


def test_vocabulary_orders_by_count_then_recency(tmp_path):
    lex = Lexicon(tmp_path / "learned.json")
    for when in (T1, T2, T3):
        _observe(lex, "kuh bernetes", "Kubernetes", when)
    for when in (T1, T2):
        _observe(lex, "doku", "Docker", when)
    assert lex.vocabulary_terms() == ["Kubernetes", "Docker"]


def test_save_and_load_round_trip_with_umlauts(tmp_path):
    path = tmp_path / "learned.json"
    lex = Lexicon(path)
    _observe(lex, "grüne", "Grüner", T1)
    lex.save()
    again = Lexicon.load(path)
    assert [(e.wrong, e.right) for e in again.entries()] == [("grüne", "Grüner")]
    assert "grüne" in path.read_text(encoding="utf-8")


def test_corrupt_file_is_set_aside_and_lexicon_starts_empty(tmp_path, caplog):
    path = tmp_path / "learned.json"
    path.write_text("{kaputt", encoding="utf-8")
    with caplog.at_level(logging.WARNING):
        lex = Lexicon.load(path)
    assert lex.entries() == []
    assert (tmp_path / "learned.json.bak").read_text(encoding="utf-8") == "{kaputt"
    assert "unlesbar" in caplog.text


def _raw_entry(**changes):
    raw = {
        "wrong": "kuh bernetes", "right": "Kubernetes", "kind": KIND_REPLACEMENT,
        "status": STATUS_PENDING, "count": 1, "vocab": True, "confirmed": False,
        "first_seen": "2026-09-01T10:00:00+00:00", "last_seen": "2026-09-01T10:00:00+00:00",
        "example": "auf kuh bernetes",
    }
    raw.update(changes)
    return raw


def _write_lexicon(path, *entries):
    path.write_text(json.dumps({"version": 1, "entries": list(entries)}), encoding="utf-8")


def test_same_dictation_counts_once(tmp_path):
    lex = Lexicon(tmp_path / "learned.json")
    v0 = lex.version
    _observe(lex, "kuh bernetes", "Kubernetes", T1)
    assert _observe(lex, "kuh bernetes", "Kubernetes", T1) is None
    assert [e.count for e in lex.entries()] == [1]
    assert lex.version == v0 + 1
    assert _observe(lex, "doku", "Docker", T1) is not None


def test_seen_is_saved_as_list_and_still_counts_after_reload(tmp_path):
    path = tmp_path / "learned.json"
    lex = Lexicon(path)
    _observe(lex, "kuh bernetes", "Kubernetes", T1)
    lex.save()
    stored = json.loads(path.read_text(encoding="utf-8"))["entries"][0]
    assert stored["seen"] == [T1.isoformat(timespec="seconds")]
    again = Lexicon.load(path)
    assert _observe(again, "kuh bernetes", "Kubernetes", T1) is None
    assert _observe(again, "kuh bernetes", "Kubernetes", T2).count == 2


def test_old_file_without_seen_loads(tmp_path):
    path = tmp_path / "learned.json"
    _write_lexicon(path, _raw_entry())
    lex = Lexicon.load(path)
    assert [(e.wrong, e.count, e.seen) for e in lex.entries()] == [("kuh bernetes", 1, ())]
    assert not (tmp_path / "learned.json.bak").exists()


@pytest.mark.parametrize("field, value", [
    ("count", "2"), ("wrong", None), ("right", ""), ("kind", "ersetzung"),
    ("status", "aktiv"), ("count", True), ("count", 0), ("vocab", "ja"),
    ("confirmed", 1), ("first_seen", None), ("last_seen", 5), ("example", ["x"]),
    ("seen", "2026-09-01"), ("seen", [1]),
])
def test_wrong_value_sets_file_aside(tmp_path, caplog, field, value):
    path = tmp_path / "learned.json"
    _write_lexicon(path, _raw_entry(**{field: value}))
    original = path.read_text(encoding="utf-8")
    with caplog.at_level(logging.WARNING):
        lex = Lexicon.load(path)
    assert lex.entries() == []
    assert (tmp_path / "learned.json.bak").read_text(encoding="utf-8") == original
    assert "unlesbar" in caplog.text


def test_read_error_raises_and_sets_nothing_aside(tmp_path):
    path = tmp_path / "learned.json"
    path.mkdir()
    with pytest.raises(OSError):
        Lexicon.load(path)
    assert path.is_dir()
    assert not (tmp_path / "learned.json.bak").exists()


def test_failed_set_aside_raises_and_keeps_file(tmp_path):
    path = tmp_path / "learned.json"
    path.write_text("{kaputt", encoding="utf-8")
    blocker = tmp_path / "learned.json.bak"
    blocker.mkdir()
    (blocker / "belegt.txt").write_text("x", encoding="utf-8")
    with pytest.raises(OSError):
        Lexicon.load(path)
    assert path.read_text(encoding="utf-8") == "{kaputt"


def test_version_changes_on_every_mutation(tmp_path):
    lex = Lexicon(tmp_path / "learned.json")
    v0 = lex.version
    e = _observe(lex, "kuh bernetes", "Kubernetes", T1)
    v1 = lex.version
    lex.accept(e.key)
    assert v0 < v1 < lex.version


def test_entries_returns_snapshot(tmp_path):
    lex = Lexicon(tmp_path / "learned.json")
    _observe(lex, "kuh bernetes", "Kubernetes", T1)
    snapshot = lex.entries()
    _observe(lex, "doku", "Docker", T1)
    assert len(snapshot) == 1


def _words(text: str) -> int:
    return len(text.split())


def test_prompt_without_terms_keeps_base_unchanged():
    assert build_initial_prompt("Linux Kira Ollama", [], _words) == "Linux Kira Ollama"
    assert build_initial_prompt(None, [], _words) is None


def test_prompt_appends_terms_within_budget():
    out = build_initial_prompt("Kira, Linux.", ["Kubernetes", "Docker"], _words, budget=4)
    assert out == "Kira, Linux, Kubernetes, Docker."


def test_prompt_skips_too_long_term_but_keeps_shorter_ones():
    out = build_initial_prompt("Kira.", ["sehr langer Begriff mit vielen Wörtern", "Docker"], _words, budget=3)
    assert out == "Kira, Docker."


def test_prompt_skips_terms_already_in_base():
    assert build_initial_prompt("Kira, Docker.", ["docker"], _words) == "Kira, Docker."


def test_same_dictation_stamped_one_second_apart_counts_once(tmp_path):
    # kira.log und Verlauf stempeln dasselbe Diktat um bis zu eine Sekunde versetzt.
    lex = Lexicon(tmp_path / "learned.json")
    lex.observe("doku", "Docker", kind=KIND_REPLACEMENT, vocab=True, example="", when=T1)
    again = lex.observe("doku", "Docker", kind=KIND_REPLACEMENT, vocab=True, example="",
                        when=T1 + timedelta(seconds=1))
    assert again is None
    assert [e.count for e in lex.entries()] == [1]


def test_separate_dictations_a_few_seconds_apart_count_twice(tmp_path):
    lex = Lexicon(tmp_path / "learned.json")
    lex.observe("doku", "Docker", kind=KIND_REPLACEMENT, vocab=True, example="", when=T1)
    lex.observe("doku", "Docker", kind=KIND_REPLACEMENT, vocab=True, example="",
                when=T1 + timedelta(seconds=5))
    assert [e.count for e in lex.entries()] == [2]


def test_deeply_nested_file_is_set_aside(tmp_path):
    path = tmp_path / "learned.json"
    path.write_text("[" * 200000 + "]" * 200000, encoding="utf-8")
    assert Lexicon.load(path).entries() == []
    assert (tmp_path / "learned.json.bak").exists()
