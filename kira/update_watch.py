# © 2026 Mike Pollow, Digitalroots. Alle Rechte vorbehalten.
"""Wiederholte Update-Prüfung, solange Kira läuft (seit v0.4.1).

Die Startprüfung in ``kira/main.py`` fragt einmal nach dem Start per Dialog.
Kira läuft aber oft tagelang; ``UpdateWatch`` prüft deshalb alle
``updates.check_interval_hours`` Stunden erneut. Gibt es eine neuere Version,
zeigt das Tray-Menü einen Eintrag zum Installieren, und einmal je Version
kommt eine Windows-Meldung, kein Dialog mitten in der Arbeit. Abgelehnte
Versionen (Marker ``.update-declined``) melden sich nicht, der Menüeintrag
bleibt trotzdem sichtbar.
"""
from __future__ import annotations

import logging
import threading
from typing import Callable

log = logging.getLogger(__name__)


class UpdateWatch:
    """Eine Prüfung: Ergebnis auswerten, Menü setzen, höchstens einmal je Version melden."""

    def __init__(
        self,
        check: Callable[[], object],
        is_declined: Callable[[str], bool],
        set_available: Callable[[str], None],
        notify: Callable[[str], None],
    ) -> None:
        self._check = check
        self._is_declined = is_declined
        self._set_available = set_available
        self._notify = notify
        self._notified: str | None = None

    def mark_notified(self, version: str) -> None:
        """Die Startprüfung hat für diese Version schon gefragt; keine zweite Meldung."""
        self._notified = version

    def run_once(self) -> str | None:
        """Einmal prüfen; gibt die neuere Version zurück oder None."""
        result = self._check()
        status = getattr(result, "status", None)
        if status != "newer":
            log.info("Update-Prüfung: keine Aktion (status=%s)", status)
            return None
        remote = getattr(result, "remote_version", None) or "?"
        self._set_available(remote)
        if remote != self._notified and not self._is_declined(remote):
            self._notified = remote
            log.info("Update-Prüfung: v%s verfügbar, Meldung im Tray", remote)
            self._notify(remote)
        return remote


def run_periodically(watch: UpdateWatch, interval_s: float, stop: threading.Event) -> None:
    """Alle ``interval_s`` Sekunden prüfen, bis ``stop`` gesetzt ist; Fehler nur ins Log."""
    while not stop.wait(interval_s):
        try:
            watch.run_once()
        except Exception:
            log.exception("Update-Prüfung fehlgeschlagen; nächster Versuch im nächsten Takt")
