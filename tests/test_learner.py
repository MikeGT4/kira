# © 2026 Mike Pollow, Digitalroots. Alle Rechte vorbehalten.
"""Tests für kira.learner."""
from __future__ import annotations
import logging
from datetime import datetime, timedelta, timezone
import pytest
from kira.correction_source import SentMessage
from kira.learner import (
    PAIR_MIN_SOUND, Pair, best_window, classify, extract_pairs, match_message, week_key,
)
from kira.lexicon import KIND_GLOSSARY, KIND_REPLACEMENT
from kira.phonetics import sound_similarity

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


@pytest.mark.parametrize("dictated, sent", [
    ("Wir gehen die Liste einmal durch", "Wir gehen die Liste einmal durch.Und"),
    ("Bei der Abfrage fehlt ein Feld", "wegBei der Abfrage fehlt ein Feld"),
    ("Bitte prüf die Markdowns", "Bitte prüf die MarkdownsUnd"),
], ids=["durch.Und", "wegBei", "MarkdownsUnd"])
def test_glued_neighbour_word_is_not_a_pair(dictated, sent):
    # Diktate kommen ohne Leerzeichen an; das Nachbarwort klebt an der richtigen Seite.
    assert extract_pairs(dictated, sent) == []


@pytest.mark.parametrize("dictated, sent, pair", [
    ("leg die Datei auf das nass", "leg die Datei auf das NAS", Pair("nass", "NAS")),
    ("Wir deployen heute auf kuh bernetes.", "Wir deployen heute auf Kubernetes.",
     Pair("kuh bernetes", "Kubernetes")),
    ("das Projekt liegt auf Git Hub", "das Projekt liegt auf GitHub", Pair("Git Hub", "GitHub")),
], ids=["nass-NAS", "kuh bernetes-Kubernetes", "Git Hub-GitHub"])
def test_shorter_or_equal_right_side_stays_a_pair(dictated, sent, pair):
    assert extract_pairs(dictated, sent) == [pair]


@pytest.mark.parametrize("dictated, sent", [
    ("Das passt so", "0Das passt so"),
    ("Wir machen weiter", "8.Wir machen weiter"),
    ("Einfach neu starten", "127.0.0.1Einfach neu starten"),
    ("Wir gehen das durch", "Wir gehen das durch.2"),
    ("Also dann los", "VoIPAlso dann los"),
    ("Figma ist offen", "3DFigma ist offen"),
], ids=["0Das", "8.Wir", "IP-Einfach", "durch.2", "VoIPAlso", "3DFigma"])
def test_glued_digits_or_punctuation_are_not_a_pair(dictated, sent):
    assert extract_pairs(dictated, sent) == []


@pytest.mark.parametrize("dictated, sent, pair", [
    ("starte den Lama Server", "starte den Ollama Server", Pair("Lama", "Ollama")),
    ("das läuft auf Buntu", "das läuft auf Ubuntu", Pair("Buntu", "Ubuntu")),
    ("frag mal Ermes", "frag mal Hermes", Pair("Ermes", "Hermes")),
], ids=["Lama-Ollama", "Buntu-Ubuntu", "Ermes-Hermes"])
def test_lost_word_start_stays_a_pair(dictated, sent, pair):
    # Ohne Naht (Ziffer, Satzzeichen, klein-groß) ist das kein angeklebtes Wort.
    assert extract_pairs(dictated, sent) == [pair]


def test_umlaut_spelling_change_is_not_a_pair():
    assert extract_pairs("Das ändert alles", "Das aendert alles") == []


def test_pair_min_sound_boundary():
    above = sound_similarity("Wagen", "Regen")
    below = sound_similarity("Mappe", "Marke")
    assert (above, below) == (pytest.approx(2 / 3), pytest.approx(3 / 5))
    assert below < PAIR_MIN_SOUND <= above
    assert extract_pairs("wir warten auf den Wagen", "wir warten auf den Regen") == [
        Pair("Wagen", "Regen")]
    assert extract_pairs("gib mir die Mappe dort", "gib mir die Marke dort") == []


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


def test_repeated_bootstrap_counts_each_dictation_once(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    local = datetime(2026, 9, 20, 10, 0).astimezone()
    log_path = tmp_path / "kira.log"
    log_path.write_text(
        f"{local:%Y-%m-%d %H:%M:%S},000 INFO kira.app: Polish out (mode=terminal, 35 chars): "
        "'wir deployen heute auf kuh bernetes'\n",
        encoding="utf-8",
    )
    _sent(src, local + timedelta(minutes=1), "Wir deployen heute auf Kubernetes")
    started = (local + timedelta(days=1)).isoformat(timespec="seconds")

    def counts(runs):
        lex = Lexicon(tmp_path / f"learned-{runs}.json")
        for _ in range(runs):
            state = LearningState(started=started)
            bootstrap(log_paths=[log_path], source_dirs=[src], lexicon=lex,
                      words=WORDS, state=state)
        return [(e.wrong, e.right, e.count, e.status) for e in lex.entries()], state.baseline

    once = counts(1)
    assert once[0] == [("kuh bernetes", "Kubernetes", 1, "pending")]
    assert counts(2) == once


def test_parse_log_dictations_skips_impossible_timestamps(tmp_path):
    log_path = tmp_path / "kira.log"
    log_path.write_text(
        "2026-13-40 10:00:00,000 INFO kira.app: Polish out (mode=plain, 5 chars): 'hallo'\n"
        "2026-09-20 10:00:00,000 INFO kira.app: Polish out (mode=plain, 5 chars): 'hallo'\n",
        encoding="utf-8",
    )
    items = parse_log_dictations([log_path])
    assert len(items) == 1
    assert items[0][0].text == "hallo"


def test_bootstrap_without_pairs_does_not_write_lexicon(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    lex = Lexicon(tmp_path / "learned.json")
    log_path = tmp_path / "kira.log"
    log_path.write_text(
        f"{T0:%Y-%m-%d %H:%M:%S},000 INFO kira.app: Polish out (mode=plain, 35 chars): "
        "'wir deployen heute auf kuh bernetes'\n",
        encoding="utf-8",
    )
    state = LearningState(started=(T0 - timedelta(hours=1)).isoformat(timespec="seconds"))
    r = bootstrap(log_paths=[log_path], source_dirs=[src], lexicon=lex, words=WORDS, state=state)
    assert r.processed == 1
    assert r.pairs == 0
    assert state.bootstrapped is True
    assert not (tmp_path / "learned.json").exists()


def test_run_once_skips_a_failing_dictation(tmp_path, monkeypatch):
    hist, src, lex, state = _setup(tmp_path)
    _history(hist, T0, "wir deployen heute auf kuh bernetes")
    _history(hist, T0 + timedelta(minutes=1), "und morgen wieder auf kuh bernetes deployen")
    _sent(src, T0 + timedelta(minutes=2), "Wir deployen heute auf Kubernetes")
    _sent(src, T0 + timedelta(minutes=3), "Und morgen wieder auf Kubernetes deployen")
    original_extract_pairs = __import__("kira.learner", fromlist=["extract_pairs"]).extract_pairs
    def extract_pairs_with_error(dictated, sent):
        if dictated.startswith("wir"):
            raise RuntimeError("Simulated error")
        return original_extract_pairs(dictated, sent)
    monkeypatch.setattr("kira.learner.extract_pairs", extract_pairs_with_error)
    r = _run(T0 + timedelta(minutes=40), hist, src, lex, state)
    assert r.processed == 2
    assert r.pairs == 1


def test_history_entry_without_timezone_does_not_end_the_run(tmp_path):
    hist, src, lex, state = _setup(tmp_path)
    HistoryWriter(hist).append(HistoryRecord(
        ts="2026-09-23T12:00:00", app=None, mode="terminal",
        raw="ohne Zeitzone", text="ohne Zeitzone",
    ))
    _history(hist, T0, "wir deployen heute auf kuh bernetes")
    _sent(src, T0 + timedelta(minutes=2), "Wir deployen heute auf Kubernetes")
    r = _run(T0 + timedelta(minutes=40), hist, src, lex, state)
    assert (r.processed, r.pairs) == (1, 1)


def test_lexicon_is_saved_before_pruning(tmp_path, monkeypatch):
    hist, src, lex, state = _setup(tmp_path)
    _history(hist, T0, "wir deployen heute auf kuh bernetes")
    _sent(src, T0 + timedelta(minutes=2), "Wir deployen heute auf Kubernetes")

    def boom(directory, now):
        raise OSError("gesperrt")

    monkeypatch.setattr("kira.learner.prune", boom)
    with pytest.raises(OSError):
        _run(T0 + timedelta(minutes=30), hist, src, lex, state)
    assert (tmp_path / "learned.json").exists()


def test_bootstrap_logs_progress_every_500_dictations(tmp_path, caplog):
    src = tmp_path / "src"
    src.mkdir()
    log_path = tmp_path / "kira.log"
    line = f"{T0:%Y-%m-%d %H:%M:%S},000 INFO kira.app: Polish out (mode=plain, 5 chars): 'hallo'\n"
    log_path.write_text(line * 1000, encoding="utf-8")
    state = LearningState(started=(T0 + timedelta(days=1)).isoformat(timespec="seconds"))
    with caplog.at_level(logging.INFO, logger="kira.learner"):
        bootstrap(log_paths=[log_path], source_dirs=[src], lexicon=Lexicon(tmp_path / "learned.json"),
                  words=WORDS, state=state)
    progress = [r.getMessage() for r in caplog.records if "Erstbefüllung, " in r.getMessage()]
    assert progress == [
        "Lernen: Erstbefüllung, 500 von 1000 Diktaten",
        "Lernen: Erstbefüllung, 1000 von 1000 Diktaten",
    ]


def test_parse_log_dictations_skips_lines_with_replacement_character(tmp_path):
    log_path = tmp_path / "kira.log"
    line = "2026-09-20 {}:00:00,000 INFO kira.app: Polish out (mode=plain, 4 chars): 'Müll'\n"
    log_path.write_bytes(line.format("10").encode("cp1252") + line.format("11").encode("utf-8"))
    items = parse_log_dictations([log_path])
    assert [r.text for r, _ in items] == ["Müll"]
