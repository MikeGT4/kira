# © 2026 Mike Pollow, Digitalroots. Alle Rechte vorbehalten.
"""Tests für kira.wordlist."""
from __future__ import annotations
import logging
from kira.wordlist import is_common, load_wordlist


def _write(tmp_path, lines):
    path = tmp_path / "wordlist-de.txt"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def test_header_lines_are_skipped_and_words_casefolded(tmp_path):
    words = load_wordlist(_write(tmp_path, ["# Kopf", "Haus", "nass", "Straße"]))
    assert words == frozenset({"haus", "nass", "strasse"})


def test_is_common_needs_every_word_of_the_phrase(tmp_path):
    words = load_wordlist(_write(tmp_path, ["das", "haus", "ist", "nass"]))
    assert is_common("Nass", words)
    assert is_common("das Haus", words)
    assert not is_common("das Kuhbernetes", words)
    assert not is_common("", words)


def test_missing_file_gives_empty_set_and_warning(tmp_path, caplog):
    with caplog.at_level(logging.WARNING):
        assert load_wordlist(tmp_path / "fehlt.txt") == frozenset()
    assert "Wortliste" in caplog.text


def test_undecodable_file_gives_empty_set_and_warning(tmp_path, caplog):
    path = tmp_path / "wordlist-de.txt"
    path.write_bytes("Haus\nStraße\n".encode("cp1252"))
    with caplog.at_level(logging.WARNING):
        assert load_wordlist(path) == frozenset()
    assert "Wortliste" in caplog.text
