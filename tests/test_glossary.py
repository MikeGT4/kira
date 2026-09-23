# © 2026 Mike Pollow, Digitalroots. Alle Rechte vorbehalten.
"""Tests für kira.glossary."""
from __future__ import annotations
import time
from kira.glossary import select_glossary
from kira.lexicon import KIND_GLOSSARY, STATUS_ACTIVE, Entry


def _entry(wrong, right, count=2):
    return Entry(wrong=wrong, right=right, kind=KIND_GLOSSARY, status=STATUS_ACTIVE,
                 count=count, vocab=True, confirmed=False, first_seen="2026-09-01T10:00:00+00:00",
                 last_seen="2026-09-02T10:00:00+00:00", example="")


def test_wrong_side_in_dictation_offers_the_term():
    assert select_glossary("leg das auf das nass", [_entry("nass", "NAS")]) == ["NAS"]


def test_similar_sounding_word_offers_the_term():
    assert select_glossary("leg das auf das näs", [_entry("nass", "NAS")]) == ["NAS"]


def test_term_already_written_correctly_is_not_offered():
    assert select_glossary("leg das auf das NAS", [_entry("nass", "NAS")]) == []


def test_unrelated_text_offers_nothing():
    assert select_glossary("heute scheint die Sonne", [_entry("nass", "NAS")]) == []


def test_at_most_five_terms():
    entries = [_entry(f"wort{i}", f"Begriff{i}") for i in range(7)]
    text = " ".join(f"wort{i}" for i in range(7))
    assert len(select_glossary(text, entries)) == 5


def test_selection_stays_fast_with_many_entries():
    entries = [_entry(f"eintrag{i}", f"Fachbegriff{i}") for i in range(100)]
    text = " ".join(["das ist ein ganz normaler Satz ohne besondere Wörter"] * 6)
    start = time.perf_counter()
    select_glossary(text, entries)
    assert time.perf_counter() - start < 0.2


def test_repeated_sentence_gives_same_selection_as_single_sentence():
    """Die Entdopplung der Wortgruppen darf nur Tempo, nicht das Ergebnis ändern:
    ein wiederholter Satz muss dieselbe Auswahl liefern wie der einzelne Satz,
    auch wenn der Treffer über die Klangähnlichkeit kommt (Kubernetes/kuh bernetes)."""
    entries = [_entry("kubernetes", "Kubernetes")]
    sentence = "heute starten wir kuh bernetes auf dem testserver neu"
    single = select_glossary(sentence, entries)
    repeated = select_glossary(" ".join([sentence] * 4), entries)
    assert repeated == single == ["Kubernetes"]
