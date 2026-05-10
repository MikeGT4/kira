"""First-run detection via marker file in %APPDATA%\\Kira\\."""
from __future__ import annotations

import os
from pathlib import Path

FIRST_RUN_MARKER_NAME = ".first-run-complete"


def _kira_appdata_dir() -> Path:
    """Resolve %APPDATA%\\Kira mit Defense-in-Depth gegen manipulierte Env.

    Wirft EnvironmentError (OSError-Subclass, wird vom SetupWizard.accept()
    gefangen) wenn:
    - APPDATA gar nicht gesetzt ist (=> wir laufen nicht auf Windows)
    - APPDATA NICHT unter USERPROFILE liegt (=> Env wurde manipuliert,
      potentiell Path-Traversal-Attack via gesetztem APPDATA="C:/Windows
      /System32" oder einer Network-Share). Wir refusen dann den Schreib-
      vorgang anstatt blind dort hinzuschreiben.

    EnvironmentError ist die Standard-Subclass von OSError seit Python 3.3
    und wird vom existierenden `except OSError` im Wizard gefangen.
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


def is_first_run() -> bool:
    return not (_kira_appdata_dir() / FIRST_RUN_MARKER_NAME).exists()


def mark_first_run_complete() -> None:
    kira_dir = _kira_appdata_dir()
    kira_dir.mkdir(parents=True, exist_ok=True)
    (kira_dir / FIRST_RUN_MARKER_NAME).write_text("done\n", encoding="utf-8")
