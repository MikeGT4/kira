"""Marker-File fuer den automatischen Update-Check beim App-Start.

Der Start-Update-Check (siehe ``kira/main.py::_check_for_app_update``)
fragt GitHub-Releases ab und fragt den Nutzer proaktiv, wenn eine neuere
Version vorliegt. Sagt der Nutzer "nein", darf Kira ihn beim naechsten
Start NICHT erneut mit derselben Version nerven.

Dieses Modul kapselt das: ein winziges Text-File unter
``%APPDATA%\\Kira\\.update-declined`` haelt die zuletzt abgelehnte
Versions-Nummer fest. ``is_update_declined("0.3.0")`` ist True genau
dann, wenn der Nutzer fuer 0.3.0 schon "nein" gesagt hat.

Gleiches ``%APPDATA%\\Kira``-Resolve-Muster + USERPROFILE-Defense wie
``kira/firstrun.py`` — siehe dort fuer die Begruendung der Env-Var-
Whitelist. Anders als der First-Run-Marker ist hier aber jeder Fehler
unkritisch: der Update-Check ist ein Komfort-Feature, kein Pflicht-
Schritt. ``is_update_declined`` faengt OSError daher selbst ab und
gibt im Zweifel ``False`` zurueck (= "nicht abgelehnt" → der Nutzer
wird gefragt; lieber einmal zu viel fragen als einen Marker-Fehler
in die Boot-Sequenz durchschlagen lassen).
"""
from __future__ import annotations

import logging
import os
from pathlib import Path

log = logging.getLogger(__name__)

UPDATE_DECLINED_MARKER_NAME = ".update-declined"


def _kira_appdata_dir() -> Path:
    """Resolve ``%APPDATA%\\Kira`` mit Defense-in-Depth gegen manipulierte Env.

    Wirft EnvironmentError (OSError-Subclass) wenn APPDATA fehlt oder
    NICHT unter USERPROFILE liegt — identische Semantik wie
    ``kira.firstrun._kira_appdata_dir``. Caller in diesem Modul fangen
    den Fehler ab; der Update-Check soll daran nicht scheitern.
    """
    appdata_str = os.environ.get("APPDATA")
    if not appdata_str:
        raise EnvironmentError("APPDATA env var not set — Kira requires Windows.")
    appdata = Path(appdata_str).resolve()

    user_profile_str = os.environ.get("USERPROFILE")
    if user_profile_str:
        user_profile = Path(user_profile_str).resolve()
        try:
            appdata.relative_to(user_profile)
        except ValueError:
            raise EnvironmentError(
                f"APPDATA ({appdata}) liegt nicht unter USERPROFILE "
                f"({user_profile}) — moeglich manipulierte Env. Kira "
                "refusing to write outside user scope."
            )

    return appdata / "Kira"


def is_update_declined(version: str) -> bool:
    """True wenn der Nutzer fuer genau ``version`` schon "nein" gesagt hat.

    Vergleich ist exakter String-Match auf den Marker-Inhalt. Eine andere
    (neuere) Version raeumt den Anker faktisch ab: der Marker enthaelt nur
    die EINE zuletzt abgelehnte Version, also liefert ``is_update_declined``
    fuer jede andere Version ``False`` und der Nutzer wird wieder gefragt.

    Jeder Lese-/Env-Fehler → ``False`` (im Zweifel fragen). Der Update-
    Check ist Komfort, kein Pflicht-Pfad — ein Marker-Fehler darf die
    Boot-Sequenz nicht beeinflussen.
    """
    try:
        marker = _kira_appdata_dir() / UPDATE_DECLINED_MARKER_NAME
        if not marker.exists():
            return False
        return marker.read_text(encoding="utf-8").strip() == version.strip()
    except OSError as exc:
        log.warning("update-declined marker konnte nicht gelesen werden: %s", exc)
        return False


def mark_update_declined(version: str) -> None:
    """Merke ``version`` als vom Nutzer abgelehnt.

    Ueberschreibt den Marker-Inhalt — es wird immer nur die zuletzt
    abgelehnte Version gehalten. Fehler werden geloggt und geschluckt:
    schlaegt das Schreiben fehl, wird der Nutzer beim naechsten Start halt
    noch einmal gefragt; das ist nervig, aber nicht kaputt.
    """
    try:
        kira_dir = _kira_appdata_dir()
        kira_dir.mkdir(parents=True, exist_ok=True)
        (kira_dir / UPDATE_DECLINED_MARKER_NAME).write_text(
            version.strip() + "\n", encoding="utf-8",
        )
        log.info("Update v%s vom Nutzer abgelehnt — Marker gesetzt", version)
    except OSError as exc:
        log.warning("update-declined marker konnte nicht geschrieben werden: %s", exc)
