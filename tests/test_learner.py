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
