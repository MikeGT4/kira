# © 2026 Mike Pollow, Digitalroots. Alle Rechte vorbehalten.
"""Lernschleife unter Windows: Verlauf, Lexikon, Lernlauf und KiraApp-Haken.

``LearningService.create(cfg)`` baut alles aus der Konfiguration. main.py
reicht den Dienst an KiraApp (Haken), Transcriber (Lexikon) und Tray
(Fenster „Gelernte Wörter") weiter und startet den Lernlauf-Thread.
``prune_history()`` läuft bei jedem Start, auch bei ausgeschaltetem Lernen.
"""
from __future__ import annotations

import logging
import os
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Callable

from kira.config import Config
from kira.correction_source import SourceReader
from kira.glossary import select_glossary
from kira.history import HistoryRecord, HistoryWriter, default_history_dir, prune
from kira.learner import LearningState, bootstrap, metrics_summary, run_once
from kira.lexicon import Lexicon, default_lexicon_path
from kira.wordlist import default_wordlist

log = logging.getLogger(__name__)
FIRST_RUN_DELAY_S = 120
RUN_INTERVAL_S = 30 * 60
GLOSSARY_SLOW_MS = 20.0


def _local_kira_dir() -> Path:
    base = os.environ.get("LOCALAPPDATA")
    return (Path(base) if base else Path.home() / "AppData" / "Local") / "Kira"


def _now() -> datetime:
    return datetime.now().astimezone()


def prune_history() -> None:
    """Löschfrist des Verlaufs (drei Monate), unabhängig vom Lernen."""
    try:
        removed = prune(default_history_dir(), _now())
    except Exception:
        log.exception("Verlauf: alte Monatsdateien ließen sich nicht löschen")
        return
    if removed:
        log.info("Verlauf: %d alte Monatsdateien gelöscht", len(removed))


class LearningService:
    def __init__(
        self, *, sources: list[Path], lexicon: Lexicon, history_dir: Path,
        state_path: Path, log_paths: list[Path], words: frozenset[str],
        active_app: Callable[[], str | None] = lambda: None,
        clock: Callable[[], datetime] = _now,
    ) -> None:
        self.lexicon = lexicon
        self._sources = list(sources)
        self._history_dir = history_dir
        self._writer = HistoryWriter(history_dir)
        self._state_path = state_path
        self._state = LearningState.load(state_path)
        self._log_paths = list(log_paths)
        self._words = words
        self._active_app = active_app
        self._clock = clock
        self._run_lock = threading.Lock()
        if self._state.started is None:
            stamp = clock().isoformat(timespec="seconds")
            self._state.started = stamp
            self._state.processed_until = stamp
            self._state.save(state_path)
        self._metrics = metrics_summary(self._state, clock())
        if not words:
            log.warning("Lernen: Wortliste fehlt, Paare werden nur als Glossar verbucht")
        if not self._sources:
            log.info("Lernen: learning.sources ist leer, es wird nur der Verlauf geschrieben")

    @classmethod
    def create(cls, cfg: Config) -> "LearningService":
        from kira.context_win import active_exe
        local = _local_kira_dir()
        return cls(
            sources=[Path(p) for p in cfg.learning.sources],
            lexicon=Lexicon.load(default_lexicon_path()),
            history_dir=default_history_dir(),
            state_path=local / "learning-state.json",
            log_paths=[local / "kira.log.1", local / "kira.log"],
            words=default_wordlist(),
            active_app=active_exe,
        )

    def glossary_for(self, text: str) -> list[str]:
        start = time.perf_counter()
        terms = select_glossary(text, self.lexicon.glossary_entries())
        elapsed_ms = (time.perf_counter() - start) * 1000
        if elapsed_ms > GLOSSARY_SLOW_MS:
            log.warning("Lernen: Glossar-Auswahl dauerte %.1f ms", elapsed_ms)
        if terms:
            log.info("Glossar angeboten: %s", ", ".join(terms))
        return terms

    def after_inject(self, *, mode: str, transcription, text: str, duration_s: float) -> None:
        self._writer.append(HistoryRecord(
            ts=self._clock().isoformat(timespec="seconds"),
            app=self._active_app(),
            mode=mode,
            raw=getattr(transcription, "raw_text", "") or transcription.text,
            text=text,
            avg_logprob=getattr(transcription, "avg_logprob", None),
            duration_s=round(duration_s, 2),
        ))

    def run_once(self) -> None:
        if not self._run_lock.acquire(blocking=False):
            return
        try:
            now = self._clock()
            if self._sources and not self._state.bootstrapped:
                # Die Erstbefüllung läuft nur einmal und braucht alle Quellen.
                unreachable = [d for d in self._sources if not d.is_dir()]
                if unreachable:
                    log.warning(
                        "Lernen: Erstbefüllung verschoben, Lernquelle nicht erreichbar: %s",
                        ", ".join(str(d) for d in unreachable),
                    )
                else:
                    log.info("Lernen: Erstbefüllung aus kira.log beginnt")
                    r = bootstrap(
                        log_paths=self._log_paths, source_dirs=self._sources,
                        lexicon=self.lexicon, words=self._words, state=self._state,
                    )
                    self._state.save(self._state_path)
                    log.info(
                        "Lernen: Erstbefüllung fertig: %d Diktate, %d zugeordnet, "
                        "%d korrigiert, %d Paare", r.processed, r.matched, r.corrected, r.pairs,
                    )
            if self._sources:
                reader = SourceReader(self._sources, self._state.offsets)
                r = run_once(
                    now=now, history_dir=self._history_dir, reader=reader,
                    lexicon=self.lexicon, words=self._words, state=self._state,
                )
                summary = metrics_summary(self._state, now)
                log.info(
                    "Lernen: Lauf fertig: %d Diktate, %d zugeordnet, %d korrigiert, "
                    "%d Paare, %d wartend, %.1f MB gelesen, Korrekturquote %s, "
                    "Zuordnung %s", r.processed, r.matched, r.corrected, r.pairs,
                    len(self.lexicon.pending()), reader.bytes_read / 1e6,
                    summary["this_week"], summary["coverage"],
                )
            else:
                prune(self._history_dir, now)
            self._state.save(self._state_path)
            self._metrics = metrics_summary(self._state, now)
        except Exception:
            log.exception("Lernen: Lauf fehlgeschlagen, nächster Versuch planmäßig")
        finally:
            self._run_lock.release()

    def start(self) -> threading.Thread:
        def loop() -> None:
            time.sleep(FIRST_RUN_DELAY_S)
            while True:
                self.run_once()
                time.sleep(RUN_INTERVAL_S)

        thread = threading.Thread(target=loop, daemon=True, name="kira-learner")
        thread.start()
        return thread

    def pending_count(self) -> int:
        return len(self.lexicon.pending())

    def metrics(self) -> dict[str, tuple[int, int] | None]:
        return dict(self._metrics)
