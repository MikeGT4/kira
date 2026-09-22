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


def test_no_chaining_single_pass():
    """Das Ergebnis einer Ersetzung wird nicht erneut ersetzt."""
    out = apply("alpha", {"alpha": "beta", "beta": "gamma"})
    assert out == "beta"


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


def test_replacement_with_backslash_inserted_literally():
    assert apply("foo", {"foo": r"\1bar"}) == r"\1bar"


def test_only_whole_words_are_replaced():
    assert apply("das Feld ist nass", {"nass": "NAS"}) == "das Feld ist NAS"
    assert apply("in Nassau", {"nass": "NAS"}) == "in Nassau"


def test_umlaut_and_sharp_s_count_as_word_characters():
    assert apply("Maße und Grüße", {"maß": "X", "grü": "Y"}) == "Maße und Grüße"
    assert apply("Das Maß ist voll", {"maß": "Glas"}) == "Das Glas ist voll"


def test_longer_keys_win_over_shorter_ones():
    out = apply("öffne vieh es code", {"code": "Code", "vieh es code": "VS Code"})
    assert out == "öffne VS Code"


def test_punctuation_next_to_word_still_matches():
    assert apply("Start auf kuh bernetes.", {"kuh bernetes": "Kubernetes"}) == "Start auf Kubernetes."


def test_callback_reports_each_replacement():
    seen = []
    apply("auf kuh bernetes und Kuh Bernetes", {"kuh bernetes": "Kubernetes"},
          on_replace=lambda found, new: seen.append((found, new)))
    assert seen == [("kuh bernetes", "Kubernetes"), ("Kuh Bernetes", "Kubernetes")]


def test_sharp_s_and_ss_keys_stay_distinct():
    """ß und ss sollten nicht unter casefold() zusammenfallen."""
    mapping = {
        "straße": "Straße (Adresse)",
        "strasse": "Strasse (CH-Schreibweise)",
    }
    text = "Die Straße ist gesperrt, die strasse auch."
    out = apply(text, mapping)
    assert out == "Die Straße (Adresse) ist gesperrt, die Strasse (CH-Schreibweise) auch."
