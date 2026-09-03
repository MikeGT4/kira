"""rumps-based menubar app with state-reactive icon."""
from __future__ import annotations
import logging
import subprocess
import threading
from pathlib import Path
from typing import Callable
import rumps
from PyObjCTools import AppHelper
from kira import __version__
from kira.app import State
from kira.config import default_config_path
from kira.ui.settings_window import SettingsWindow

log = logging.getLogger(__name__)

def _assets_dir() -> Path:
    """Locate the bundled assets directory in both dev and py2app contexts."""
    import os
    rp = os.environ.get("RESOURCEPATH")
    if rp:
        bundled = Path(rp) / "assets"
        if bundled.exists():
            return bundled
    return Path(__file__).parent.parent.parent / "assets"


ASSETS = _assets_dir()
ICON_DEFAULT = str(ASSETS / "icon-template.png")


class KiraMenubar(rumps.App):
    def __init__(self, on_quit: Callable[[], None], config_path: Path | None = None) -> None:
        super().__init__(
            name="Kira",
            title=None,
            icon=ICON_DEFAULT,
            template=True,
            quit_button=None,
        )
        self._on_quit = on_quit
        self._config_path = config_path or default_config_path()
        self._settings = None
        self._status_item = rumps.MenuItem("Status: Bereit")
        self.menu = [
            self._status_item,
            None,
            rumps.MenuItem("Einstellungen…", callback=self._open_settings),
            rumps.MenuItem("Konfigurationsdatei…", callback=self._open_config),
            rumps.MenuItem("Protokoll…", callback=self._open_log),
            None,
            rumps.MenuItem("Über Kira", callback=self._about),
            rumps.MenuItem("Kira beenden", callback=self._quit),
        ]

    def _open_settings(self, _):
        if self._settings is None:
            self._settings = SettingsWindow(self._config_path)
        self._settings.show()

    def update_state(self, state: State) -> None:
        """Thread-safe entrypoint. Dispatches onto the AppKit main thread."""
        if threading.current_thread() is threading.main_thread():
            self._apply_state(state)
        else:
            AppHelper.callAfter(self._apply_state, state)

    def _apply_state(self, state: State) -> None:
        label = {
            State.IDLE: "Bereit",
            State.RECORDING: "Aufnahme…",
            State.EDITING: "Bearbeiten…",
            State.TRANSCRIBING: "Transkription…",
            State.STYLING: "Polieren…",
            State.INJECTING: "Einfügen…",
            State.ERROR: "Fehler (siehe Protokoll)",
        }.get(state, "Unknown")
        try:
            self._status_item.title = f"Status: {label}"
        except Exception:
            log.exception("failed to update menubar status")
        try:
            self.title = "●" if state in (State.RECORDING, State.EDITING) else None
        except Exception:
            pass

    def _open_config(self, _):
        cfg_path = default_config_path()
        cfg_path.parent.mkdir(parents=True, exist_ok=True)
        if not cfg_path.exists():
            cfg_path.write_text("# Kira config\n")
        subprocess.Popen(["open", "-e", str(cfg_path)])

    def _open_log(self, _):
        log_path = Path.home() / "Library" / "Logs" / "kira.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        if not log_path.exists():
            log_path.write_text("")
        subprocess.Popen(["open", str(log_path)])

    def _about(self, _):
        rumps.alert(
            title="Kira",
            message=f"Voice-to-text menubar app.\nv{__version__}\n© 2026 Digitalroots",
        )

    def _quit(self, _):
        try:
            self._on_quit()
        except Exception:
            log.exception("on_quit handler raised")
        rumps.quit_application()
