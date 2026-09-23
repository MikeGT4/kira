# © 2026 Mike Pollow, Digitalroots. Alle Rechte vorbehalten.
"""Wiederholte Update-Prüfung, solange Kira läuft (seit v0.4.1).

Die Startprüfung in ``kira/main.py`` fragt einmal nach dem Start per Dialog.
Kira läuft aber oft tagelang; ``UpdateWatch`` prüft deshalb alle
``updates.check_interval_hours`` Stunden erneut. Gibt es eine neuere Version,
zeigt das Tray-Menü einen Eintrag zum Installieren, und einmal je Version
kommt eine Windows-Meldung, kein Dialog mitten in der Arbeit. Abgelehnte
Versionen (Marker ``.update-declined``) melden sich nicht, der Menüeintrag
bleibt trotzdem sichtbar. Ist das Release wieder weg oder ohne Setup-Dateien,
verschwindet der Eintrag; ein Netzfehler lässt ihn stehen.
"""
from __future__ import annotations

import logging
import threading
from typing import Callable

log = logging.getLogger(__name__)

# Ergebnisse, nach denen es nichts (mehr) zu installieren gibt. "failed"
# (kein Netz) zählt nicht dazu: dann bleibt der bekannte Stand stehen.
_NOTHING_TO_INSTALL = ("current", "local_newer", "no_asset")


class UpdateWatch:
    """Eine Prüfung: Ergebnis auswerten, Menü setzen, höchstens einmal je Version melden."""

    def __init__(
        self,
        check: Callable[[], object],
        is_declined: Callable[[str], bool],
        set_available: Callable[[str | None], None],
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

    def start_result(self, result: object) -> str | None:
        """Ergebnis der Startprüfung übernehmen: Menü setzen, Version als gemeldet merken.

        Gibt die Version zurück, nach der der Startdialog fragen soll, sonst None
        (nichts Neueres, oder diese Version wurde schon abgelehnt)."""
        status = getattr(result, "status", None)
        if status != "newer":
            log.info("Start-Update-Check: keine Aktion (status=%s)", status)
            return None
        remote = getattr(result, "remote_version", None) or "?"
        self._set_available(remote)
        self.mark_notified(remote)
        if self._is_declined(remote):
            log.info(
                "Start-Update-Check: v%s verfügbar, vom Nutzer bereits abgelehnt, keine Abfrage",
                remote,
            )
            return None
        log.info("Start-Update-Check: neuere Version v%s verfügbar", remote)
        return remote

    def run_once(self) -> str | None:
        """Einmal prüfen; gibt die neuere Version zurück oder None."""
        result = self._check()
        status = getattr(result, "status", None)
        if status != "newer":
            log.info("Update-Prüfung: keine Aktion (status=%s)", status)
            if status in _NOTHING_TO_INSTALL:
                self._set_available(None)
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


def start_watch(
    watch: UpdateWatch,
    *,
    enabled: bool,
    interval_h: float,
    stop: threading.Event | None = None,
) -> threading.Thread | None:
    """Wiederholte Prüfung als Daemon-Thread starten, wenn eingeschaltet.

    ``enabled`` ist ``updates.check_on_start``; ``interval_h`` 0 heißt nur beim Start."""
    if not enabled or interval_h <= 0:
        log.info("Wiederholte Update-Prüfung aus (check_on_start=%s, Intervall %.1f h)",
                 enabled, interval_h)
        return None
    thread = threading.Thread(
        target=run_periodically,
        args=(watch, interval_h * 3600.0, stop or threading.Event()),
        daemon=True,
        name="kira-update-watch",
    )
    thread.start()
    log.info("Update-Prüfung alle %.1f h aktiv", interval_h)
    return thread
