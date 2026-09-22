# © 2026 Mike Pollow, Digitalroots. Alle Rechte vorbehalten.
"""Klangähnlichkeit deutscher Wörter: Kölner Phonetik plus Dialektvarianten.

Kölner Phonetik nach Postel (1969), Tabelle wie in der deutschen Wikipedia:
Buchstaben auf Ziffern 0 bis 8, gleiche Nachbarn zusammenfassen, Nullen
außer am Anfang streichen. Umlaute zählen als Vokal, ß als s.

Zwei regionale Aussprachen deckt die Tabelle nicht ab, sie kommen als
Schreibvarianten dazu:
- ch und sch fallen zusammen (Koronalisierung, pfälzisch und rheinisch)
- g und j am Wortanfang (berlinerisch „jut", „jehen")
b/p, d/t, g/k (Konsonantenschwächung, am stärksten im Ostmitteldeutschen)
und gefärbte Vokale fängt die Kölner Phonetik ohnehin ab.
"""
from __future__ import annotations
import difflib
import re
from functools import lru_cache

_WORD_RE = re.compile(r"[^\W\d_]+")
_VOWELS = frozenset("aeijouy")
_C_HARD_AT_START = frozenset("ahkloqrux")
_C_HARD_INSIDE = frozenset("ahkoqux")
_FOLD = str.maketrans({"ä": "a", "ö": "o", "ü": "u", "ß": "s"})


def _normalize(word: str) -> str:
    return re.sub(r"[^a-z]", "", word.lower().translate(_FOLD))


def koelner(word: str) -> str:
    """Kölner-Phonetik-Code eines Worts; Bindestriche und Zeichen zählen nicht."""
    w = _normalize(word)
    digits: list[str] = []
    for i, c in enumerate(w):
        prev = w[i - 1] if i > 0 else ""
        nxt = w[i + 1] if i + 1 < len(w) else ""
        if c in _VOWELS:
            code = "0"
        elif c == "h":
            code = ""
        elif c == "b":
            code = "1"
        elif c == "p":
            code = "3" if nxt == "h" else "1"
        elif c in "dt":
            code = "8" if nxt and nxt in "csz" else "2"
        elif c in "fvw":
            code = "3"
        elif c in "gkq":
            code = "4"
        elif c == "c":
            if i == 0:
                code = "4" if nxt in _C_HARD_AT_START else "8"
            elif prev in "sz":
                code = "8"
            else:
                code = "4" if nxt in _C_HARD_INSIDE else "8"
        elif c == "x":
            code = "8" if prev and prev in "ckq" else "48"
        elif c == "l":
            code = "5"
        elif c in "mn":
            code = "6"
        elif c == "r":
            code = "7"
        elif c in "sz":
            code = "8"
        else:
            code = ""
        digits.append(code)
    collapsed: list[str] = []
    for d in "".join(digits):
        if not collapsed or collapsed[-1] != d:
            collapsed.append(d)
    joined = "".join(collapsed)
    return joined[:1] + joined[1:].replace("0", "")


def variants(text: str) -> set[str]:
    """Schreibvarianten für regionale Aussprache (ch/sch, g/j am Wortanfang)."""
    t = text.lower()
    return {
        t,
        re.sub(r"(?<!s)ch", "sch", t),
        t.replace("sch", "ch"),
        re.sub(r"\bg", "j", t),
        re.sub(r"\bj", "g", t),
    }


def phonetic_code(text: str) -> str:
    """Codes aller Wörter eines Texts, aneinandergereiht."""
    return "".join(koelner(w) for w in _WORD_RE.findall(text))


@lru_cache(maxsize=8192)
def _variant_codes(text: str) -> frozenset[str]:
    return frozenset(phonetic_code(v) for v in variants(text))


@lru_cache(maxsize=8192)
def _letters(text: str) -> str:
    return re.sub(r"[^a-zäöüß]", "", text.lower())


def _ratio(a: str, b: str) -> float:
    if not a and not b:
        return 1.0
    return difflib.SequenceMatcher(None, a, b, autojunk=False).ratio()


def _upper_bound(a: str, b: str) -> float:
    total = len(a) + len(b)
    return 1.0 if total == 0 else 2 * min(len(a), len(b)) / total


def sound_similarity(a: str, b: str) -> float:
    """Klangwert zweier Wörter oder Wortgruppen, 0 bis 1.

    Maximum aus der Ähnlichkeit der Kölner-Codes (über alle Varianten beider
    Seiten) und der reinen Buchstabenähnlichkeit.
    """
    phon = max(
        _ratio(x, y) for x in _variant_codes(a) for y in _variant_codes(b)
    )
    return max(phon, _ratio(_letters(a), _letters(b)))


def is_similar(a: str, b: str, threshold: float) -> bool:
    """``sound_similarity(a, b) >= threshold`` mit billiger Längen-Vorprüfung.

    Für die Glossar-Auswahl je Diktat, wo viele Paare zu prüfen sind.
    """
    la, lb = _letters(a), _letters(b)
    if _upper_bound(la, lb) >= threshold and _ratio(la, lb) >= threshold:
        return True
    for x in _variant_codes(a):
        for y in _variant_codes(b):
            if _upper_bound(x, y) >= threshold and _ratio(x, y) >= threshold:
                return True
    return False
