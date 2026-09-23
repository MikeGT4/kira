# © 2026 Mike Pollow, Digitalroots. Alle Rechte vorbehalten.
"""Gelernte Wortpaare: Ablage, Freigabe-Regeln und Sichten für die Anwendung.

Ein Eintrag ist ein Paar „falsch erkannt → richtig". Art ``replacement``
ersetzt fest, Art ``glossary`` geht nur als Hinweis an die Politur. Status
``pending`` wartet auf Freigabe, ``active`` wirkt, ``rejected`` ist dauerhaft
gesperrt. Auftreten in zwei verschiedenen Diktaten aktiviert ein Paar von
selbst, außer dieselbe falsche Seite hat mehrere richtige Seiten. Von Hand
bestätigte Einträge (``confirmed``) bleiben auch dann aktiv.
"""
from __future__ import annotations

import json
import logging
import os
import threading
from dataclasses import asdict, dataclass, replace
from datetime import datetime
from pathlib import Path
from typing import Callable, Iterable

log = logging.getLogger(__name__)

KIND_REPLACEMENT = "replacement"
KIND_GLOSSARY = "glossary"
STATUS_PENDING = "pending"
STATUS_ACTIVE = "active"
STATUS_REJECTED = "rejected"
AUTO_ACTIVATE_COUNT = 2
# kira.log und Verlauf stempeln dasselbe Diktat um bis zu eine Sekunde versetzt.
SAME_DICTATION_S = 2
EXAMPLE_MAX_CHARS = 120
PROMPT_TOKEN_BUDGET = 223
_SCHEMA_VERSION = 1

Key = tuple[str, str]


@dataclass(frozen=True)
class Entry:
    wrong: str
    right: str
    kind: str
    status: str
    count: int
    vocab: bool
    confirmed: bool
    first_seen: str
    last_seen: str
    example: str
    # Zeitstempel der Diktate, die den Eintrag gezählt haben: jedes zählt einmal,
    # auch wenn die Erstbefüllung wiederholt wird.
    seen: tuple[str, ...] = ()

    @property
    def key(self) -> Key:
        return (self.wrong.casefold(), self.right.casefold())


def _entry_from_json(raw) -> Entry:
    """Ein Eintrag aus learned.json, jeder Wert geprüft. ValueError, wenn einer nicht passt."""
    if not isinstance(raw, dict):
        raise ValueError("Eintrag ist kein Objekt")
    seen = raw.get("seen", [])
    if not isinstance(seen, list) or not all(isinstance(s, str) for s in seen):
        raise ValueError("ungültiges Feld: seen")
    entry = Entry(**{**raw, "seen": tuple(seen)})
    checks = {
        "wrong": isinstance(entry.wrong, str) and entry.wrong != "",
        "right": isinstance(entry.right, str) and entry.right != "",
        "kind": entry.kind in (KIND_REPLACEMENT, KIND_GLOSSARY),
        "status": entry.status in (STATUS_PENDING, STATUS_ACTIVE, STATUS_REJECTED),
        "count": isinstance(entry.count, int) and not isinstance(entry.count, bool)
        and entry.count >= 1,
        "vocab": isinstance(entry.vocab, bool),
        "confirmed": isinstance(entry.confirmed, bool),
        "first_seen": isinstance(entry.first_seen, str),
        "last_seen": isinstance(entry.last_seen, str),
        "example": isinstance(entry.example, str),
    }
    bad = [name for name, ok in checks.items() if not ok]
    if bad:
        raise ValueError("ungültiges Feld: " + ", ".join(bad))
    return entry


def _already_counted(seen: tuple[str, ...], when: datetime) -> bool:
    """Hat ein Diktat höchstens ``SAME_DICTATION_S`` Sekunden entfernt schon gezählt?"""
    for stamp in seen:
        try:
            if abs((when - datetime.fromisoformat(stamp)).total_seconds()) <= SAME_DICTATION_S:
                return True
        except (ValueError, TypeError):
            continue
    return False


def default_lexicon_path() -> Path:
    base = os.environ.get("APPDATA")
    root = Path(base) if base else Path.home() / "AppData" / "Roaming"
    return root / "Kira" / "learned.json"


class Lexicon:
    """Thread-sicher: Lernlauf, Oberfläche und Diktat greifen parallel zu."""

    def __init__(self, path: Path, entries: Iterable[Entry] = ()) -> None:
        self._path = path
        self._lock = threading.RLock()
        self._entries: dict[Key, Entry] = {e.key: e for e in entries}
        self._version = 0

    @classmethod
    def load(cls, path: Path) -> "Lexicon":
        """Eine defekte Datei wird als .bak beiseitegelegt, das Lexikon beginnt
        leer. Lesefehler und ein gescheitertes Beiseitelegen werden
        weitergeworfen: Ein leeres Lexikon würde die Datei später überschreiben.
        """
        if not path.exists():
            return cls(path)
        raw = path.read_bytes()
        try:
            data = json.loads(raw.decode("utf-8"))
            entries = [_entry_from_json(item) for item in data["entries"]]
        except (ValueError, KeyError, TypeError, RecursionError) as exc:
            backup = path.with_name(path.name + ".bak")
            try:
                os.replace(path, backup)
            except OSError:
                log.error("Lernen: %s unlesbar (%s) und nicht beiseitezulegen", path, exc)
                raise
            log.warning(
                "Lernen: %s unlesbar (%s), als %s gesichert, Lexikon beginnt leer",
                path, exc, backup.name,
            )
            return cls(path)
        return cls(path, entries)

    def save(self) -> None:
        with self._lock:
            payload = {
                "version": _SCHEMA_VERSION,
                "entries": [asdict(e) for e in self._entries.values()],
            }
            self._path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._path.with_name(self._path.name + ".tmp")
            tmp.write_text(
                json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8",
            )
            os.replace(tmp, self._path)

    @property
    def version(self) -> int:
        with self._lock:
            return self._version

    def observe(
        self, wrong: str, right: str, *, kind: str, vocab: bool,
        example: str, when: datetime,
    ) -> Entry | None:
        """Ein Auftreten aus einem Diktat verbuchen. None bei gesperrtem Paar
        und wenn dieses Diktat das Paar schon gezählt hat (Zeitstempel höchstens
        ``SAME_DICTATION_S`` Sekunden entfernt)."""
        stamp = when.isoformat(timespec="seconds")
        key = (wrong.casefold(), right.casefold())
        with self._lock:
            current = self._entries.get(key)
            if current is not None and (
                current.status == STATUS_REJECTED or _already_counted(current.seen, when)
            ):
                return None
            if current is None:
                entry = Entry(
                    wrong=wrong, right=right, kind=kind, status=STATUS_PENDING,
                    count=1, vocab=vocab, confirmed=False, first_seen=stamp,
                    last_seen=stamp, example=example[:EXAMPLE_MAX_CHARS],
                    seen=(stamp,),
                )
            else:
                entry = replace(
                    current, count=current.count + 1, last_seen=stamp,
                    example=example[:EXAMPLE_MAX_CHARS], seen=current.seen + (stamp,),
                )
            self._entries[key] = entry
            self._apply_rules(key[0])
            self._version += 1
            return self._entries[key]

    def _apply_rules(self, wrong_folded: str) -> None:
        siblings = [
            e for e in self._entries.values()
            if e.key[0] == wrong_folded and e.status != STATUS_REJECTED
        ]
        conflict = len({e.key[1] for e in siblings}) > 1
        for e in siblings:
            if e.confirmed:
                continue
            if not conflict and e.count >= AUTO_ACTIVATE_COUNT:
                status = STATUS_ACTIVE
            else:
                status = STATUS_PENDING
            if status != e.status:
                self._entries[e.key] = replace(e, status=status)

    def accept(self, key: Key) -> None:
        with self._lock:
            e = self._entries[key]
            self._entries[key] = replace(e, status=STATUS_ACTIVE, confirmed=True)
            self._version += 1

    def reject(self, key: Key) -> None:
        with self._lock:
            e = self._entries[key]
            self._entries[key] = replace(e, status=STATUS_REJECTED, confirmed=False)
            self._apply_rules(key[0])
            self._version += 1

    def entries(self) -> list[Entry]:
        with self._lock:
            return sorted(
                self._entries.values(),
                key=lambda e: (-e.count, e.wrong.casefold(), e.right.casefold()),
            )

    def pending(self) -> list[Entry]:
        return [e for e in self.entries() if e.status == STATUS_PENDING]

    def active(self) -> list[Entry]:
        return [e for e in self.entries() if e.status == STATUS_ACTIVE]

    def active_replacements(self) -> dict[str, str]:
        return {e.wrong: e.right for e in self.active() if e.kind == KIND_REPLACEMENT}

    def glossary_entries(self) -> list[Entry]:
        return [e for e in self.active() if e.kind == KIND_GLOSSARY]

    def vocabulary_terms(self) -> list[str]:
        """Richtige Schreibweisen für Whispers Wortliste, wichtigste zuerst."""
        terms: list[str] = []
        seen: set[str] = set()
        ranked = sorted(self.active(), key=lambda e: (e.count, e.last_seen), reverse=True)
        for e in ranked:
            folded = e.right.casefold()
            if e.vocab and folded not in seen:
                seen.add(folded)
                terms.append(e.right)
        return terms


def build_initial_prompt(
    base: str | None,
    terms: Iterable[str],
    count_tokens: Callable[[str], int],
    budget: int = PROMPT_TOKEN_BUDGET,
) -> str | None:
    """Whisper-Prompt: Begriffe aus config.yaml vorn, gelernte dahinter.

    Hängt Begriffe an, solange ``count_tokens`` im Budget bleibt. Ein zu
    langer Begriff wird übersprungen, kürzere dahinter dürfen noch.
    """
    prompt = (base or "").strip()
    for raw in terms:
        term = raw.strip()
        if not term or term.casefold() in prompt.casefold():
            continue
        candidate = f"{prompt.rstrip('.')}, {term}." if prompt else f"{term}."
        if count_tokens(candidate) <= budget:
            prompt = candidate
    return prompt or None
