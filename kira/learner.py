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

import ast
import bisect
import difflib
import json
import logging
import os
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

from kira.correction_source import SentMessage, SourceReader
from kira.history import HistoryRecord, prune, read_records
from kira.lexicon import KIND_GLOSSARY, KIND_REPLACEMENT, Lexicon
from kira.phonetics import sound_similarity
from kira.wordlist import is_common

log = logging.getLogger(__name__)

MATCH_MIN_RATIO = 0.75
PAIR_MIN_SOUND = 0.65
MAX_SPAN_WORDS = 3
MIN_WRONG_LETTERS = 3
WINDOW_BEFORE = timedelta(seconds=5)
WINDOW_AFTER = timedelta(minutes=20)
BOOTSTRAP_PROGRESS_EVERY = 500

_TOKEN_RE = re.compile(r"\S+")
_EDGE_RE = re.compile(r"^[^\w]+|[^\w]+$")
_NOT_LETTER_RE = re.compile(r"[^a-zäöüß]")


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


def _glued(wrong: str, right: str) -> bool:
    """Die richtige Seite ist die falsche plus ein angeklebtes Nachbarwort.

    Diktate werden ohne Leerzeichen eingefügt; zwei Diktate hintereinander
    oder Tippen plus Diktat kommen verklebt an („durchUnd“, „wegBei“).
    Verglichen werden nur die Buchstaben, klein. Die Gegenrichtung bleibt
    ein Paar, so sehen echte Fehlerkennungen aus („nass“ → „NAS“).
    """
    w = _NOT_LETTER_RE.sub("", wrong.casefold())
    r = _NOT_LETTER_RE.sub("", right.casefold())
    return len(r) > len(w) and (r.startswith(w) or r.endswith(w))


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
        if _glued(wrong, right):
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


_LOG_LINE_RE = re.compile(
    r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}),\d+ INFO kira\.app: "
    r"Polish out \(mode=(\w+), (\d+) chars\): (.*)$"
)


def _new_counter() -> dict[str, int]:
    return {"dictations": 0, "terminal": 0, "matched": 0, "terminal_matched": 0, "corrected": 0}


@dataclass
class LearningState:
    """Was der Lernlauf zwischen zwei Läufen und über Neustarts behält."""
    offsets: dict[str, int] = field(default_factory=dict)
    started: str | None = None
    processed_until: str | None = None
    buffer: list[dict] = field(default_factory=list)
    weeks: dict[str, dict[str, int]] = field(default_factory=dict)
    baseline: dict[str, int] | None = None
    bootstrapped: bool = False

    @classmethod
    def load(cls, path: Path) -> "LearningState":
        try:
            return cls(**json.loads(path.read_text(encoding="utf-8")))
        except FileNotFoundError:
            return cls()
        except (OSError, ValueError, TypeError) as exc:
            log.warning("Lernen: Zustand %s unlesbar (%s), beginne neu", path, exc)
            return cls()

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(json.dumps(asdict(self), ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, path)


@dataclass
class RunResult:
    processed: int = 0
    matched: int = 0
    corrected: int = 0
    pairs: int = 0


def _learn_from(
    record: HistoryRecord, *, truncated: bool, messages: list[SentMessage],
    times: list[datetime], lexicon: Lexicon, words: frozenset[str],
    counter: dict[str, int], result: RunResult,
) -> None:
    counter["dictations"] += 1
    if record.mode == "terminal":
        counter["terminal"] += 1
    window = match_message(record.text, record.time, messages, times)
    if window is None:
        return
    counter["matched"] += 1
    if record.mode == "terminal":
        counter["terminal_matched"] += 1
    result.matched += 1
    # Aus kira.log kommen nur 80 Zeichen; das letzte Wort kann angeschnitten sein.
    dictated = record.text.rsplit(" ", 1)[0] if truncated else record.text
    pairs = extract_pairs(dictated, window)
    if not pairs:
        return
    counter["corrected"] += 1
    result.corrected += 1
    for pair in pairs:
        kind, vocab = classify(pair, words)
        entry = lexicon.observe(
            pair.wrong, pair.right, kind=kind, vocab=vocab,
            example=record.text, when=record.time,
        )
        if entry is not None:
            result.pairs += 1
            log.info(
                "Lernen: %s %r -> %r (%s, %dx)",
                entry.status, entry.wrong, entry.right, entry.kind, entry.count,
            )


def run_once(
    *, now: datetime, history_dir: Path, reader: SourceReader, lexicon: Lexicon,
    words: frozenset[str], state: LearningState,
) -> RunResult:
    """Ein Lernlauf. Ein Diktat wird erst verarbeitet, wenn sein Zeitfenster
    geschlossen ist; bis dahin gelesene Nachrichten warten im Puffer."""
    result = RunResult()
    started = datetime.fromisoformat(state.started) if state.started else now
    for message in reader.read_new(modified_since=started - timedelta(days=1)):
        state.buffer.append({"time": message.time.isoformat(), "text": message.text})
    state.offsets = dict(reader.offsets)
    messages = sorted(
        (SentMessage(datetime.fromisoformat(b["time"]), b["text"]) for b in state.buffer),
        key=lambda m: m.time,
    )
    times = [m.time for m in messages]
    until = now - WINDOW_AFTER - timedelta(minutes=1)
    since = datetime.fromisoformat(state.processed_until) if state.processed_until else started
    if until > since:
        for record in read_records(history_dir, since=since):
            # Auch Zeitvergleich und Wochenschlüssel je Diktat: ein Eintrag
            # ohne Zeitzone überspringt nur sich selbst.
            try:
                if record.time > until:
                    continue
                result.processed += 1
                counter = state.weeks.setdefault(week_key(record.time), _new_counter())
                _learn_from(
                    record, truncated=False, messages=messages, times=times,
                    lexicon=lexicon, words=words, counter=counter, result=result,
                )
            except Exception:
                log.exception("Lernen: Diktat vom %s übersprungen", record.ts)
        state.processed_until = until.isoformat(timespec="seconds")
    keep_from = datetime.fromisoformat(state.processed_until or until.isoformat()) - WINDOW_BEFORE
    state.buffer = [
        b for b in state.buffer if datetime.fromisoformat(b["time"]) >= keep_from
    ]
    if result.pairs:
        lexicon.save()
    prune(history_dir, now)
    return result


def parse_log_dictations(paths: list[Path]) -> list[tuple[HistoryRecord, bool]]:
    """``Polish out``-Zeilen aus kira.log als Kurz-Verlauf: (Eintrag, gekürzt?)."""
    items: list[tuple[HistoryRecord, bool]] = []
    for path in paths:
        try:
            fh = path.open(encoding="utf-8", errors="replace")
        except OSError:
            continue
        with fh:
            for line in fh:
                if "Polish out" not in line:
                    continue
                # Alte Zeilen in Windows-1252: der Text trägt Ersatzzeichen statt Umlauten.
                if "\ufffd" in line:
                    continue
                match = _LOG_LINE_RE.match(line.rstrip("\n"))
                if not match:
                    continue
                try:
                    text = ast.literal_eval(match.group(4))
                except (ValueError, SyntaxError):
                    continue
                if not isinstance(text, str) or not text.strip():
                    continue
                try:
                    when = datetime.strptime(match.group(1), "%Y-%m-%d %H:%M:%S").astimezone()
                except ValueError:
                    continue
                record = HistoryRecord(
                    ts=when.isoformat(timespec="seconds"), app=None,
                    mode=match.group(2), raw=text, text=text,
                )
                items.append((record, int(match.group(3)) > len(text)))
    items.sort(key=lambda item: item[0].time)
    return items


def bootstrap(
    *, log_paths: list[Path], source_dirs: list[Path], lexicon: Lexicon,
    words: frozenset[str], state: LearningState,
) -> RunResult:
    """Einmalig: Diktate aus kira.log vor Verlaufsbeginn gegen alle Verläufe
    abgleichen. Misst dabei den Ausgangswert der Korrekturquote."""
    result = RunResult()
    started = datetime.fromisoformat(state.started) if state.started else None
    items = [
        (record, truncated) for record, truncated in parse_log_dictations(log_paths)
        if started is None or record.time <= started
    ]
    baseline = _new_counter()
    if items:
        reader = SourceReader(source_dirs)
        messages = reader.read_new(modified_since=items[0][0].time)
        times = [m.time for m in messages]
        for number, (record, truncated) in enumerate(items, start=1):
            result.processed += 1
            try:
                _learn_from(
                    record, truncated=truncated, messages=messages, times=times,
                    lexicon=lexicon, words=words, counter=baseline, result=result,
                )
            except Exception:
                log.exception("Lernen: Diktat vom %s übersprungen", record.ts)
            if number % BOOTSTRAP_PROGRESS_EVERY == 0:
                log.info("Lernen: Erstbefüllung, %d von %d Diktaten", number, len(items))
        if result.pairs:
            lexicon.save()
    state.baseline = baseline
    state.bootstrapped = True
    return result


def correction_rate(counter: dict[str, int] | None) -> tuple[int, int] | None:
    """(korrigiert, zugeordnet) oder None ohne zugeordnete Diktate."""
    if not counter or not counter.get("matched"):
        return None
    return counter["corrected"], counter["matched"]


def coverage_rate(counter: dict[str, int] | None) -> tuple[int, int] | None:
    """(zugeordnete, alle) Terminal-Diktate: wie viel die Quellen abdecken."""
    if not counter or not counter.get("terminal"):
        return None
    return counter.get("terminal_matched", 0), counter["terminal"]


def metrics_summary(state: LearningState, now: datetime) -> dict[str, tuple[int, int] | None]:
    return {
        "this_week": correction_rate(state.weeks.get(week_key(now))),
        "last_week": correction_rate(state.weeks.get(week_key(now - timedelta(days=7)))),
        "baseline": correction_rate(state.baseline),
        "coverage": coverage_rate(state.weeks.get(week_key(now))),
    }
