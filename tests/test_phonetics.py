# © 2026 Mike Pollow, Digitalroots. Alle Rechte vorbehalten.
"""Tests für kira.phonetics. Sollwerte der Kölner Phonetik aus der deutschen Wikipedia."""
from __future__ import annotations
import pytest
from kira.phonetics import is_similar, koelner, sound_similarity, variants


@pytest.mark.parametrize("word, code", [
    ("Müller-Lüdenscheidt", "65752682"),
    ("Breschnew", "17863"),
    ("Wikipedia", "3412"),
    ("Heinz", "068"),
    ("Classen", "4586"),
])
def test_koelner_matches_reference_examples(word, code):
    assert koelner(word) == code


def test_word_final_consonants_are_coded_correctly():
    assert koelner("Rat") == "72"
    assert koelner("Rad") == "72"
    assert koelner("Ac") == "08"


def test_voiced_and_voiceless_consonants_share_a_code():
    assert koelner("Kaffee") == koelner("Gaffee")
    assert koelner("Tag") == koelner("Dag")
    assert koelner("Post") == koelner("Bost")


def test_variants_cover_ch_sch_and_g_j():
    assert "isch" in variants("ich")
    assert "gut" in variants("jut")


@pytest.mark.parametrize("a, b", [
    ("isch", "ich"), ("jut", "gut"), ("feschd", "fest"),
    ("kuh bernetes", "Kubernetes"), ("Zettel Kasten", "Zettelkasten"),
])
def test_dialect_and_split_words_reach_full_similarity(a, b):
    assert sound_similarity(a, b) == pytest.approx(1.0)


@pytest.mark.parametrize("a, b", [
    ("Hintergrund", "Kriminalpolizei"), ("Tisch", "Stuhl"), ("Sonne", "Sonnenschirm"),
])
def test_unrelated_words_stay_below_pair_threshold(a, b):
    assert sound_similarity(a, b) < 0.65


@pytest.mark.parametrize("a, b, threshold", [
    ("Kubernetes", "kuh bernetes", 0.8), ("Haus", "Maus", 0.8),
    ("Tisch", "Stuhl", 0.65), ("isch", "ich", 0.8),
])
def test_is_similar_agrees_with_sound_similarity(a, b, threshold):
    assert is_similar(a, b, threshold) == (sound_similarity(a, b) >= threshold)
