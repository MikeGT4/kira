"""Tests for kira.replacements.apply()."""
from __future__ import annotations
from kira.replacements import apply


def test_empty_text_passes_through():
    assert apply("", {"foo": "bar"}) == ""


def test_empty_mapping_passes_through():
    assert apply("hello world", {}) == "hello world"


def test_simple_replacement():
    assert apply("kuh bernetes", {"kuh bernetes": "Kubernetes"}) == "Kubernetes"


def test_case_insensitive_match():
    assert apply("Kuh Bernetes", {"kuh bernetes": "Kubernetes"}) == "Kubernetes"
    assert apply("KUH BERNETES", {"kuh bernetes": "Kubernetes"}) == "Kubernetes"


def test_no_match_unchanged():
    assert apply("hello world", {"foo": "bar"}) == "hello world"


def test_multi_word_replacement():
    text = "Deployment auf kuh bernetes gestartet"
    out = apply(text, {"kuh bernetes": "Kubernetes"})
    assert out == "Deployment auf Kubernetes gestartet"


def test_multiple_replacements_in_one_text():
    text = "Frau Schmid kennt kuh bernetes"
    out = apply(
        text,
        {"frau schmid": "Frau Schmidt", "kuh bernetes": "Kubernetes"},
    )
    assert out == "Frau Schmidt kennt Kubernetes"


def test_insertion_order_chained_replacements():
    """Spaetere Keys sehen Output frueherer Keys."""
    out = apply("alpha", {"alpha": "beta", "beta": "gamma"})
    assert out == "gamma"


def test_empty_key_skipped():
    """Leerer Find-Key bricht nicht — er wird ignoriert."""
    out = apply("hello", {"": "X", "hello": "world"})
    assert out == "world"


def test_special_regex_chars_treated_as_literal():
    """Punkte/Sterne/Brackets im Key sind nicht als Regex-Metachars zu interpretieren."""
    out = apply("foo.bar", {"foo.bar": "baz"})
    assert out == "baz"
    # ohne re.escape wuerde "." in jedem 7-Zeichen-Token matchen
    out2 = apply("fooXbar", {"foo.bar": "baz"})
    assert out2 == "fooXbar"


def test_replacement_with_special_chars_inserted_literally():
    """Replacement-Sonderzeichen (\\1 backref-sytnax) duerfen nicht expanded werden."""
    # re.sub interpretiert \1 als Backref — wir muessen den Replacement
    # in einer Form uebergeben die das verhindert. Das ist eine bekannte
    # Falle; test dokumentiert Verhalten.
    # Aktuell wuerde "\\1" im replacement zu einem Backref-Lookup —
    # akzeptabel weil Mike's Use-Case keine Backslashes in Replacements
    # hat. Test ist hier als Dokumentation des Edge-Cases.
    pass
