# © 2026 Mike Pollow, Digitalroots. Alle Rechte vorbehalten.
"""Tests für kira.learner."""
from __future__ import annotations
from datetime import datetime, timedelta, timezone
from kira.correction_source import SentMessage
from kira.learner import (
    Pair, best_window, classify, extract_pairs, match_message, week_key,
)
from kira.lexicon import KIND_GLOSSARY, KIND_REPLACEMENT

T0 = datetime(2026, 9, 22, 12, 0, tzinfo=timezone.utc)


def test_best_window_finds_dictation_inside_longer_message():
    ratio, window = best_window(
        "wir deployen heute auf kuh bernetes und prüfen danach die logs",
        "Kurze Vorrede. Wir deployen heute auf Kubernetes und prüfen danach die Logs. Danke!",
    )
    assert ratio >= 0.75
    assert window == "Wir deployen heute auf Kubernetes und prüfen danach die Logs"


def test_best_window_rejects_unrelated_message():
    ratio, _ = best_window("wir deployen heute auf kuh bernetes", "Etwas ganz anderes steht hier")
    assert ratio < 0.75


def test_match_message_uses_time_window():
    text = "wir deployen heute auf kuh bernetes"
    sent = "Wir deployen heute auf Kubernetes"
    msgs = [
        SentMessage(T0 - timedelta(minutes=1), sent),
        SentMessage(T0 + timedelta(minutes=3), "Etwas ganz anderes steht hier"),
        SentMessage(T0 + timedelta(minutes=30), sent),
    ]
    assert match_message(text, T0, msgs, [m.time for m in msgs]) is None
    inside = [SentMessage(T0 + timedelta(minutes=2), sent)]
    assert match_message(text, T0, inside, [m.time for m in inside]) == sent


def test_extract_pairs_finds_split_word():
    pairs = extract_pairs("Wir deployen heute auf kuh bernetes.", "Wir deployen heute auf Kubernetes.")
    assert pairs == [Pair("kuh bernetes", "Kubernetes")]


def test_content_edits_are_not_pairs():
    assert extract_pairs("Stell den Tisch in die Ecke", "Stell den Stuhl in die Ecke") == []


def test_case_punctuation_and_additions_are_not_pairs():
    assert extract_pairs("Das ist gut so.", "das ist Gut so") == []
    assert extract_pairs("Das ist gut", "Das ist gut und schön") == []


def test_short_wrong_side_is_ignored():
    assert extract_pairs("un dann weiter", "Und dann weiter") == []


def test_same_pair_counts_once_per_dictation():
    pairs = extract_pairs(
        "wir nehmen den zettel kasten mit und den zettel kasten",
        "wir nehmen den Zettelkasten mit und den Zettelkasten",
    )
    assert pairs == [Pair("zettel kasten", "Zettelkasten")]


def test_long_rewrites_are_not_pairs():
    assert extract_pairs(
        "das sind vier falsche worte hier",
        "das sind ganz andere begriffe jetzt hier",
    ) == []


def test_classify_uses_the_word_list():
    words = frozenset({"nass", "haus"})
    assert classify(Pair("nass", "NAS"), words) == (KIND_GLOSSARY, True)
    assert classify(Pair("Kuhbernetes", "Kubernetes"), words) == (KIND_REPLACEMENT, True)
    assert classify(Pair("hauß", "Haus"), words) == (KIND_REPLACEMENT, False)


def test_classify_without_word_list_is_glossary_only():
    assert classify(Pair("Kuhbernetes", "Kubernetes"), frozenset()) == (KIND_GLOSSARY, False)


def test_week_key_is_iso_week():
    assert week_key(T0) == "2026-W39"


import json
from kira.correction_source import SourceReader
from kira.history import HistoryRecord, HistoryWriter
from kira.learner import (
    LearningState, bootstrap, metrics_summary, parse_log_dictations, run_once,
)
from kira.lexicon import STATUS_ACTIVE, Lexicon

WORDS = frozenset({"wir", "deployen", "heute", "auf", "und", "morgen", "wieder"})


def _history(directory, when, text, mode="terminal"):
    HistoryWriter(directory).append(HistoryRecord(
        ts=when.isoformat(timespec="seconds"), app=None, mode=mode, raw=text, text=text,
    ))


def _sent(directory, when, text):
    stamp = when.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    with (directory / "s.jsonl").open("a", encoding="utf-8") as fh:
        fh.write(json.dumps({"type": "user", "timestamp": stamp,
                             "message": {"content": text}}, ensure_ascii=False) + "\n")


def _setup(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    start = (T0 - timedelta(hours=1)).isoformat(timespec="seconds")
    state = LearningState(started=start, processed_until=start)
    return tmp_path / "history", src, Lexicon(tmp_path / "learned.json"), state


def _run(now, hist, src, lex, state):
    return run_once(now=now, history_dir=hist, reader=SourceReader([src], state.offsets),
                    lexicon=lex, words=WORDS, state=state)


def test_run_once_learns_and_activates_on_second_dictation(tmp_path):
    hist, src, lex, state = _setup(tmp_path)
    _history(hist, T0, "wir deployen heute auf kuh bernetes")
    _sent(src, T0 + timedelta(minutes=2), "Wir deployen heute auf Kubernetes")
    r = _run(T0 + timedelta(minutes=30), hist, src, lex, state)
    assert (r.processed, r.matched, r.corrected, r.pairs) == (1, 1, 1, 1)
    assert lex.pending()[0].right == "Kubernetes"
    t1 = T0 + timedelta(days=1)
    _history(hist, t1, "und morgen wieder auf kuh bernetes deployen")
    _sent(src, t1 + timedelta(minutes=1), "Und morgen wieder auf Kubernetes deployen")
    _run(t1 + timedelta(minutes=30), hist, src, lex, state)
    assert [e.status for e in lex.entries()] == [STATUS_ACTIVE]
    assert lex.active_replacements() == {"kuh bernetes": "Kubernetes"}
    assert (tmp_path / "learned.json").exists()


def test_dictation_waits_until_its_window_is_closed(tmp_path):
    hist, src, lex, state = _setup(tmp_path)
    _history(hist, T0, "wir deployen heute auf kuh bernetes")
    assert _run(T0 + timedelta(minutes=5), hist, src, lex, state).processed == 0
    _sent(src, T0 + timedelta(minutes=10), "Wir deployen heute auf Kubernetes")
    assert _run(T0 + timedelta(minutes=12), hist, src, lex, state).processed == 0
    r = _run(T0 + timedelta(minutes=40), hist, src, lex, state)
    assert (r.processed, r.matched, r.pairs) == (1, 1, 1)


def test_metrics_report_corrected_of_matched(tmp_path):
    hist, src, lex, state = _setup(tmp_path)
    _history(hist, T0, "wir deployen heute auf kuh bernetes")
    _sent(src, T0 + timedelta(minutes=2), "Wir deployen heute auf Kubernetes")
    _run(T0 + timedelta(minutes=30), hist, src, lex, state)
    summary = metrics_summary(state, T0 + timedelta(minutes=30))
    assert summary == {"this_week": (1, 1), "last_week": None, "baseline": None,
                       "coverage": (1, 1)}


def test_state_survives_save_and_load(tmp_path):
    state = LearningState(started="2026-09-22T10:00:00+00:00", bootstrapped=True)
    state.save(tmp_path / "state.json")
    assert LearningState.load(tmp_path / "state.json") == state
    assert LearningState.load(tmp_path / "fehlt.json") == LearningState()


def test_parse_log_dictations_reads_polish_lines(tmp_path):
    log_path = tmp_path / "kira.log"
    log_path.write_text(
        "2026-09-20 10:00:00,123 INFO kira.app: Polish out (mode=terminal, 35 chars): "
        "'wir deployen heute auf kuh bernetes'\n"
        "2026-09-20 10:00:01,000 INFO kira.injector_win: Injecting 35 chars\n"
        "2026-09-20 11:00:00,000 INFO kira.app: Polish out (mode=plain, 120 chars): "
        "'ein langer text der abgeschnitten wurde und mitt'\n",
        encoding="utf-8",
    )
    items = parse_log_dictations([log_path])
    assert [(r.mode, truncated) for r, truncated in items] == [("terminal", False), ("plain", True)]


def test_bootstrap_learns_from_log_and_sets_baseline(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    lex = Lexicon(tmp_path / "learned.json")
    local = datetime(2026, 9, 20, 10, 0).astimezone()
    later = local + timedelta(days=3)
    log_path = tmp_path / "kira.log"
    log_path.write_text(
        f"{local:%Y-%m-%d %H:%M:%S},000 INFO kira.app: Polish out (mode=terminal, 35 chars): "
        "'wir deployen heute auf kuh bernetes'\n"
        f"{later:%Y-%m-%d %H:%M:%S},000 INFO kira.app: Polish out (mode=terminal, 35 chars): "
        "'wir deployen heute auf kuh bernetes'\n",
        encoding="utf-8",
    )
    _sent(src, local + timedelta(minutes=1), "Wir deployen heute auf Kubernetes")
    state = LearningState(started=(local + timedelta(days=2)).isoformat(timespec="seconds"))
    r = bootstrap(log_paths=[log_path], source_dirs=[src], lexicon=lex, words=WORDS, state=state)
    assert (r.processed, r.matched, r.pairs) == (1, 1, 1)
    assert state.bootstrapped is True
    assert metrics_summary(state, local)["baseline"] == (1, 1)
