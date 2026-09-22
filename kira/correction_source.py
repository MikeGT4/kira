# © 2026 Mike Pollow, Digitalroots. Alle Rechte vorbehalten.
"""Abgeschickte Nachrichten aus JSONL-Chatverläufen lesen, schrittweise.

Jede Zeile einer Verlaufsdatei ist ein JSON-Objekt. Aufgenommen werden nur
Nachrichten, die ein Mensch abgeschickt hat: ``type == "user"``, nicht
``isSidechain``, nicht ``isMeta``, Inhalt als Zeichenkette oder Textblöcke,
keine Werkzeugergebnisse, Text beginnt nicht mit ``<``. Je Datei merkt sich
der Leser die Byte-Position; eine unvollständige letzte Zeile bleibt für den
nächsten Lauf liegen. Welche Ordner gelesen werden, steht in
``learning.sources`` der config.yaml.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

log = logging.getLogger(__name__)
_MAX_LINE_BYTES = 2_000_000


@dataclass(frozen=True)
class SentMessage:
    time: datetime
    text: str


def _message_text(obj: dict) -> str | None:
    if obj.get("type") != "user" or obj.get("isSidechain") or obj.get("isMeta"):
        return None
    content = (obj.get("message") or {}).get("content")
    if isinstance(content, str):
        text = content
    elif isinstance(content, list):
        if any(isinstance(c, dict) and c.get("type") == "tool_result" for c in content):
            return None
        text = "\n".join(
            c.get("text", "") for c in content
            if isinstance(c, dict) and c.get("type") == "text"
        )
    else:
        return None
    if not text.strip() or text.lstrip().startswith("<"):
        return None
    return text


def _parse_time(value) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        when = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return when if when.tzinfo else when.astimezone()


class SourceReader:
    def __init__(self, directories: list[Path], offsets: dict[str, int] | None = None) -> None:
        self._dirs = list(directories)
        self.offsets: dict[str, int] = dict(offsets or {})
        self.bytes_read = 0

    def read_new(self, modified_since: datetime | None = None) -> list[SentMessage]:
        self.bytes_read = 0
        out: list[SentMessage] = []
        for directory in self._dirs:
            try:
                files = sorted(directory.rglob("*.jsonl"))
            except OSError as exc:
                log.info("Lernquelle nicht erreichbar, übersprungen: %s (%s)", directory, exc)
                continue
            for path in files:
                out.extend(self._read_file(path, modified_since))
        out.sort(key=lambda m: m.time)
        return out

    def _read_file(self, path: Path, modified_since: datetime | None) -> list[SentMessage]:
        key = str(path)
        try:
            st = path.stat()
        except OSError:
            return []
        if modified_since is not None:
            if datetime.fromtimestamp(st.st_mtime).astimezone() < modified_since:
                return []
        start = self.offsets.get(key, 0)
        if st.st_size < start:
            start = 0
        if st.st_size == start:
            return []
        messages: list[SentMessage] = []
        pos = start
        try:
            with path.open("rb") as fh:
                fh.seek(start)
                for raw in fh:
                    if not raw.endswith(b"\n"):
                        break
                    pos += len(raw)
                    if len(raw) > _MAX_LINE_BYTES or b'"user"' not in raw:
                        continue
                    try:
                        obj = json.loads(raw)
                    except ValueError:
                        continue
                    if not isinstance(obj, dict):
                        continue
                    when = _parse_time(obj.get("timestamp"))
                    text = _message_text(obj)
                    if when is not None and text is not None:
                        messages.append(SentMessage(when, text))
        except OSError as exc:
            log.info("Lernquelle %s nicht lesbar (%s)", path, exc)
        self.bytes_read += pos - start
        self.offsets[key] = pos
        return messages
