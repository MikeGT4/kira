# © 2026 Mike Pollow, Digitalroots. Alle Rechte vorbehalten.
"""Aus Korrekturen lernen: Diktate mit abgeschickten Nachrichten abgleichen.

Ein Diktat gilt als zugeordnet, wenn eine Nachricht aus dem Zeitfenster
(5 s davor bis 20 min danach) einen Ausschnitt enthält, der dem Diktat zu
mindestens 0,75 ähnelt. Aus dem Wortvergleich werden nur ausgetauschte
Wörter (1 bis 3 je Seite) zu Paaren, und nur, wenn beide Seiten ähnlich
klingen. Einfügungen, Löschungen, Groß/klein und Satzzeichen sind
Bearbeitung, kein Hörfehler.
"""
from __future__ import annotations

import bisect
import difflib
import re
from dataclasses import dataclass
from datetime import datetime, timedelta

from kira.correction_source import SentMessage
from kira.lexicon import KIND_GLOSSARY, KIND_REPLACEMENT
from kira.phonetics import sound_similarity
from kira.wordlist import is_common

MATCH_MIN_RATIO = 0.75
PAIR_MIN_SOUND = 0.65
MAX_SPAN_WORDS = 3
MIN_WRONG_LETTERS = 3
WINDOW_BEFORE = timedelta(seconds=5)
WINDOW_AFTER = timedelta(minutes=20)

_TOKEN_RE = re.compile(r"\S+")
_EDGE_RE = re.compile(r"^[^\w]+|[^\w]+$")


@dataclass(frozen=True)
class Pair:
    wrong: str
    right: str


def _tokens(text: str) -> tuple[list[str], list[str]]:
    """Wörter wie geschrieben und klein; Satzzeichen am Wortrand zählen nicht."""
    orig = [t for t in (_EDGE_RE.sub("", tok) for tok in _TOKEN_RE.findall(text)) if t]
    return orig, [t.casefold() for t in orig]


def best_window(dictated: str, message: str) -> tuple[float, str]:
    """Ähnlichster Ausschnitt der Nachricht zum Diktat: (Ähnlichkeit, Text).

    Anker ist der längste gemeinsame Zeichenblock; um ihn herum werden
    Wortfenster verschiedener Länge auf Zeichenebene verglichen.
    """
    d_orig, d_norm = _tokens(dictated)
    m_orig, m_norm = _tokens(message)
    if not d_norm or not m_norm:
        return 0.0, ""
    probe = " ".join(d_norm)
    hay = " ".join(m_norm)
    blocks = difflib.SequenceMatcher(None, probe, hay, autojunk=False).get_matching_blocks()
    anchor = max(blocks, key=lambda b: b.size)
    if anchor.size == 0:
        return 0.0, ""
    base = hay[:max(0, anchor.b - anchor.a)].count(" ")
    n = len(d_norm)
    best_ratio, best_text = 0.0, ""
    for start in range(max(0, base - 2), base + 3):
        for size in range(max(1, n - 2), n + 3):
            end = min(len(m_norm), start + size)
            if end <= start:
                continue
            ratio = difflib.SequenceMatcher(
                None, " ".join(m_norm[start:end]), probe, autojunk=False,
            ).ratio()
            if ratio > best_ratio:
                best_ratio, best_text = ratio, " ".join(m_orig[start:end])
    return best_ratio, best_text


def match_message(
    text: str, when: datetime, messages: list[SentMessage], times: list[datetime],
) -> str | None:
    """Passender Nachrichtenausschnitt zum Diktat oder None.

    ``messages`` zeitlich sortiert, ``times`` die zugehörigen Zeitpunkte.
    """
    lo = bisect.bisect_left(times, when - WINDOW_BEFORE)
    hi = bisect.bisect_right(times, when + WINDOW_AFTER)
    best_ratio, best_text = 0.0, None
    for message in messages[lo:hi]:
        ratio, window = best_window(text, message.text)
        if ratio > best_ratio:
            best_ratio, best_text = ratio, window
    return best_text if best_ratio >= MATCH_MIN_RATIO else None


def extract_pairs(dictated: str, sent: str) -> list[Pair]:
    """Klangähnliche Austausche zwischen Diktat und abgeschicktem Text."""
    d_orig, d_norm = _tokens(dictated)
    s_orig, s_norm = _tokens(sent)
    pairs: list[Pair] = []
    seen: set[tuple[str, str]] = set()
    matcher = difflib.SequenceMatcher(None, d_norm, s_norm, autojunk=False)
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag != "replace":
            continue
        if not (1 <= i2 - i1 <= MAX_SPAN_WORDS and 1 <= j2 - j1 <= MAX_SPAN_WORDS):
            continue
        wrong = " ".join(d_orig[i1:i2])
        right = " ".join(s_orig[j1:j2])
        key = (wrong.casefold(), right.casefold())
        if key[0] == key[1] or key in seen:
            continue
        if sum(ch.isalpha() for ch in wrong) < MIN_WRONG_LETTERS:
            continue
        if sound_similarity(wrong, right) < PAIR_MIN_SOUND:
            continue
        seen.add(key)
        pairs.append(Pair(wrong, right))
    return pairs


def classify(pair: Pair, words: frozenset[str]) -> tuple[str, bool]:
    """(Art, Wortliste?) für ein Paar. Ohne Wortliste nur Glossar."""
    if not words:
        return KIND_GLOSSARY, False
    kind = KIND_GLOSSARY if is_common(pair.wrong, words) else KIND_REPLACEMENT
    return kind, not is_common(pair.right, words)


def week_key(when: datetime) -> str:
    iso = when.isocalendar()
    return f"{iso.year}-W{iso.week:02d}"
