# © 2026 Mike Pollow, Digitalroots. Alle Rechte vorbehalten.
"""Diktat-Verlauf: eine JSON-Zeile je Diktat, eine Datei je Monat.

Der Verlauf ist die Grundlage der Lernschleife. Er liegt nur lokal
(%LOCALAPPDATA%\\Kira\\history) und wird nach drei Monaten gelöscht.
"""
from __future__ import annotations

import json
import logging
import os
import threading
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterator

log = logging.getLogger(__name__)
KEEP_MONTHS = 3


@dataclass(frozen=True)
class HistoryRecord:
    ts: str
    app: str | None
    mode: str
    raw: str
    text: str
    avg_logprob: float | None = None
    duration_s: float | None = None

    @property
    def time(self) -> datetime:
        return datetime.fromisoformat(self.ts)


def default_history_dir() -> Path:
    base = os.environ.get("LOCALAPPDATA")
    root = Path(base) if base else Path.home() / "AppData" / "Local"
    return root / "Kira" / "history"


class HistoryWriter:
    def __init__(self, directory: Path) -> None:
        self._dir = directory
        self._lock = threading.Lock()

    def append(self, record: HistoryRecord) -> None:
        path = self._dir / f"{record.time.strftime('%Y-%m')}.jsonl"
        line = json.dumps(asdict(record), ensure_ascii=False)
        with self._lock:
            self._dir.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as fh:
                fh.write(line + "\n")


def read_records(
    directory: Path, since: datetime | None = None,
) -> Iterator[HistoryRecord]:
    """Alle Einträge nach ``since``, chronologisch (Monatsdateien sortiert)."""
    if not directory.is_dir():
        return
    if since is not None and since.tzinfo is None:
        since = since.astimezone()
    for path in sorted(directory.glob("*.jsonl")):
        with path.open(encoding="utf-8") as fh:
            for line in fh:
                try:
                    record = HistoryRecord(**json.loads(line))
                    when = record.time
                    if when.tzinfo is None:
                        when = when.astimezone()
                except (ValueError, TypeError):
                    continue
                if since is None or when > since:
                    yield record


def prune(directory: Path, now: datetime, keep_months: int = KEEP_MONTHS) -> list[Path]:
    """Löscht Monatsdateien, die mehr als ``keep_months`` Monate zurückliegen."""
    removed: list[Path] = []
    if not directory.is_dir():
        return removed
    cutoff = now.year * 12 + now.month - 1 - keep_months
    for path in sorted(directory.glob("*.jsonl")):
        try:
            year, month = (int(x) for x in path.stem.split("-"))
        except ValueError:
            continue
        if year * 12 + month - 1 < cutoff:
            path.unlink(missing_ok=True)
            removed.append(path)
    return removed
