"""First-run detection via marker file in %APPDATA%\\Kira\\."""
from __future__ import annotations

import os
from pathlib import Path

FIRST_RUN_MARKER_NAME = ".first-run-complete"


def _kira_appdata_dir() -> Path:
    appdata = os.environ.get("APPDATA")
    if not appdata:
        raise RuntimeError("APPDATA env var not set — Kira requires Windows.")
    return Path(appdata) / "Kira"


def is_first_run() -> bool:
    return not (_kira_appdata_dir() / FIRST_RUN_MARKER_NAME).exists()


def mark_first_run_complete() -> None:
    kira_dir = _kira_appdata_dir()
    kira_dir.mkdir(parents=True, exist_ok=True)
    (kira_dir / FIRST_RUN_MARKER_NAME).write_text("done\n", encoding="utf-8")
