"""pystray-based tray icon for Windows. Mirrors Mac KiraMenubar API."""
from __future__ import annotations
import ctypes
import logging
import os
import subprocess
import threading
from pathlib import Path
from typing import Callable
import pystray
from PIL import Image, ImageDraw
from kira.app import State

log = logging.getLogger(__name__)

ASSETS = Path(__file__).parent.parent.parent / "assets"


def _overlay_dot(img: Image.Image, rgba: tuple[int, int, int, int]) -> None:
    d = ImageDraw.Draw(img)
    w, h = img.size
    r = min(w, h) // 5
    d.ellipse((w - r*2, h - r*2, w, h), fill=rgba)


def _load_or_generate_icon(state: State) -> Image.Image:
    """Prefer the ICO in assets/; fall back to a colored circle."""
    ico = ASSETS / "icon.ico"
    if ico.exists():
        try:
            img = Image.open(ico).convert("RGBA")
            if state == State.RECORDING:
                _overlay_dot(img, (255, 64, 64, 255))
            elif state == State.ERROR:
                _overlay_dot(img, (255, 200, 0, 255))
            return img
        except Exception:
            log.exception("failed to load icon.ico, falling back")

    color = {
        State.IDLE: (120, 120, 120, 255),
        State.RECORDING: (240, 80, 80, 255),
        State.TRANSCRIBING: (80, 160, 240, 255),
        State.STYLING: (80, 160, 240, 255),
        State.INJECTING: (80, 160, 240, 255),
        State.ERROR: (240, 200, 0, 255),
    }.get(state, (120, 120, 120, 255))
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    ImageDraw.Draw(img).ellipse((4, 4, 60, 60), fill=color)
    return img


class KiraTray:
    """Windows tray icon with the same public API as KiraMenubar (Mac).

    ``qt_marshal`` is a MainThreadMarshal living on the Qt main thread.
    When pystray fires a menu callback from its daemon thread, we route
    any Qt-touching work through the marshal so dialogs construct and
    show on the right thread. Without it (None), the about/settings
    handlers log a warning and skip — keeps the tray usable even in
    test/headless environments where no Qt loop is up.
    """

    def __init__(
        self,
        on_quit: Callable[[], None],
        qt_marshal=None,
    ) -> None:
        self._on_quit = on_quit
        self._qt_marshal = qt_marshal
        self._state = State.IDLE
        self._status_label = "Status: Idle"
        self._icon: pystray.Icon | None = None

    def _build_menu(self) -> pystray.Menu:
        return pystray.Menu(
            pystray.MenuItem(self._status_label, None, enabled=False),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Einstellungen…", self._open_settings),
            pystray.MenuItem("Open Log…", self._open_log),
            pystray.MenuItem("Updates suchen…", self._check_for_updates),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("About Kira", self._about),
            pystray.MenuItem("Quit Kira", self._quit),
        )

    def update_state(self, state: State) -> None:
        """Thread-safe state + icon update."""
        self._state = state
        self._status_label = {
            State.IDLE: "Status: Idle",
            State.RECORDING: "Status: Recording…",
            State.TRANSCRIBING: "Status: Transcribing…",
            State.STYLING: "Status: Polishing…",
            State.INJECTING: "Status: Injecting…",
            State.ERROR: "Status: Error (see log)",
        }.get(state, "Status: Unknown")
        if self._icon is not None:
            self._icon.icon = _load_or_generate_icon(state)
            self._icon.menu = self._build_menu()

    def _open_settings(self, _icon, _item) -> None:
        """Open the form-based settings dialog. The Notepad fallback for
        complex fields lives inside the dialog as 'Rohconfig öffnen…'."""
        self._marshal_to_qt(self._show_settings_dialog, "settings dialog")

    @staticmethod
    def _show_settings_dialog() -> None:
        from kira.ui.settings_dialog import SettingsDialog
        dlg = SettingsDialog()
        getattr(dlg, "exec")()

    def _open_log(self, _icon, _item) -> None:
        log_path = Path(os.environ["LOCALAPPDATA"]) / "Kira" / "kira.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        if not log_path.exists():
            log_path.write_text("", encoding="utf-8")
        subprocess.Popen(["notepad.exe", str(log_path)])

    def _about(self, _icon, _item) -> None:
        self._marshal_to_qt(self._show_about_dialog, "about dialog")

    @staticmethod
    def _show_about_dialog() -> None:
        from kira.ui.about_dialog import AboutDialog
        dlg = AboutDialog()
        getattr(dlg, "exec")()

    def _marshal_to_qt(self, func, label: str) -> None:
        """Hand ``func()`` over to the Qt main thread for execution.

        pystray fires menu callbacks on its own daemon thread which has
        no Qt event loop. ``QTimer.singleShot(0, callable)`` from there
        queues the slot on the daemon thread (which never runs it), and
        PyQt6 doesn't expose the ``QTimer.singleShot(msec, context, slot)``
        overload that would force a specific thread. We route through a
        long-lived MainThreadMarshal QObject instead — its queued-signal
        connection is the supported PyQt6 idiom.
        """
        if self._qt_marshal is None:
            log.warning(
                "%s: no qt_marshal wired up, skipping (Qt loop unavailable)",
                label,
            )
            return
        self._qt_marshal.run_on_main_thread(func)

    def _check_for_updates(self, _icon, _item) -> None:
        # In-app update is intentionally disabled in v0.1.x:
        # the installer is a multi-file Inno bundle (1 stub + 7 .bin splits, ~13 GB),
        # but kira.updater only knows how to pull a single Setup.exe asset.
        # Wiring the previous handler up would silently download just the 2 MB
        # stub and produce a broken install when the user clicks. Worse, the
        # download had no Authenticode/SHA256 verification — a GitHub-account
        # compromise (Shai-Hulud profile) would mean a single tray click =
        # silent privileged code-exec on the friend's machine.
        # Keep the menu entry so users see the feature is planned; show a
        # plain hint until v0.2 ships manifest-based multi-asset pulls with
        # signature verification.
        ctypes.windll.user32.MessageBoxW(
            0,
            "Updates werden ab v0.2 direkt aus Kira geladen.\n\n"
            "Bis dahin: neues Setup-Bundle vom Verteilungspfad herunterladen "
            "und Setup.exe ausführen — der bestehende Installer erkennt "
            "vorhandene Installationen automatisch und aktualisiert sie.",
            "Kira",
            0x40,  # MB_ICONINFORMATION
        )

    def _quit(self, _icon, _item) -> None:
        try:
            self._on_quit()
        except Exception:
            log.exception("on_quit raised")
        if self._icon is not None:
            self._icon.stop()

    def run(self) -> None:
        """Blocks. Must be started in a non-main thread (Qt owns the main loop)."""
        self._icon = pystray.Icon(
            "kira",
            icon=_load_or_generate_icon(State.IDLE),
            title="Kira",
            menu=self._build_menu(),
        )
        self._icon.run()

    def run_detached(self) -> threading.Thread:
        """Convenience: start run() in a background daemon thread."""
        t = threading.Thread(target=self.run, daemon=True, name="kira-tray")
        t.start()
        return t
