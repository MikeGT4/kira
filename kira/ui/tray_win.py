"""pystray-based tray icon for Windows. Mirrors Mac KiraMenubar API."""
from __future__ import annotations
import ctypes
import logging
import os
import subprocess
import threading
import time
from pathlib import Path
from typing import Callable
import pystray
from PIL import Image, ImageDraw
from pystray._util import win32 as _ps_win32
from pystray._win32 import Icon as _PystrayWin32Icon, _dispatcher
from kira.app import State

log = logging.getLogger(__name__)


# Stable identity for Win11's notification-area settings. Pystray's
# default class name interpolates id(self), which is randomised every
# launch — Win11 keys 'show always' on (window class, window title), so
# the user's choice gets dropped on every restart and the icon shows up
# as 'Python' (pythonw.exe FileDescription). With a stable class +
# explicit title Win11 sees the same Kira tray icon across launches.
_KIRA_TRAY_CLASS = "KiraDigitalrootsTrayIcon"
_KIRA_TRAY_TITLE = "Kira"


_WM_SETTEXT = 0x000C
_WM_GETTEXT = 0x000D
_WM_GETTEXTLENGTH = 0x000E


class _KiraPystrayIcon(_PystrayWin32Icon):
    """pystray.Icon subclass with a stable Win32 class name + working
    window-title persistence.

    pystray's _dispatcher returns 0 for any message not in
    self._message_handlers, which means WM_SETTEXT never reaches
    DefWindowProc — our SetWindowTextW(hwnd, 'Kira') call appeared to
    succeed but the title stayed empty. We wire WM_SETTEXT /
    WM_GETTEXT / WM_GETTEXTLENGTH straight through to DefWindowProc so
    the title is actually stored on the window.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        def _passthrough(msg):
            def _handler(wParam, lParam):
                # self._hwnd is set in _run() before any user message
                # arrives, so it's available by the time SetWindowText
                # bounces through here.
                return _ps_win32.DefWindowProc(self._hwnd, msg, wParam, lParam)
            return _handler

        for msg in (_WM_SETTEXT, _WM_GETTEXT, _WM_GETTEXTLENGTH):
            self._message_handlers[msg] = _passthrough(msg)

    def _register_class(self):
        wndclass = _ps_win32.WNDCLASSEX(
            cbSize=ctypes.sizeof(_ps_win32.WNDCLASSEX),
            style=0,
            lpfnWndProc=_dispatcher,
            cbClsExtra=0,
            cbWndExtra=0,
            hInstance=_ps_win32.GetModuleHandle(None),
            hIcon=None,
            hCursor=None,
            hbrBackground=_ps_win32.COLOR_WINDOW + 1,
            lpszMenuName=None,
            lpszClassName=_KIRA_TRAY_CLASS,
            hIconSm=None,
        )
        atom = _ps_win32.RegisterClassEx(wndclass)
        if atom == 0:
            # Class atom from a previous Kira process that died before
            # _unregister_class() could run (native CUDA crash, audio
            # callback abort, faulthandler exit). Without recovery, every
            # subsequent launch leaves the tray-daemon-thread silently
            # dead — Qt main loop runs, hotkey works, but the user sees
            # no tray icon and reads it as "Kira hängt beim Hochfahren".
            # Reboot used to be the only fix.
            try:
                ctypes.windll.user32.UnregisterClassW(
                    _KIRA_TRAY_CLASS, _ps_win32.GetModuleHandle(None),
                )
                atom = _ps_win32.RegisterClassEx(wndclass)
                if atom != 0:
                    log.info(
                        "Recovered stale tray window class %r from previous "
                        "Kira process — registration succeeded on retry",
                        _KIRA_TRAY_CLASS,
                    )
            except Exception:
                log.exception(
                    "tray window-class recovery failed (atom=%s)", atom,
                )
        return atom


def _set_tray_window_title(icon_holder: "KiraTray", timeout_s: float = 5.0) -> None:
    """Poll until the pystray window exists, then label it 'Kira'.

    pystray creates the hidden notification window on its own daemon
    thread inside _run(), so we can't simply call SetWindowText
    synchronously after Icon(...) construction. We loop briefly until
    `_hwnd` is set and patch it once. SetWindowText on a stable class
    is what makes Win11's notification-area panel show 'Kira' instead
    of falling back to the python.exe FileDescription.
    """
    SetWindowTextW = ctypes.windll.user32.SetWindowTextW
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        icon = icon_holder._icon
        if icon is not None:
            hwnd = getattr(icon, "_hwnd", None)
            if hwnd:
                SetWindowTextW(hwnd, _KIRA_TRAY_TITLE)
                log.info(
                    "Tray window labelled %r (class=%s, hwnd=0x%x)",
                    _KIRA_TRAY_TITLE, _KIRA_TRAY_CLASS, hwnd,
                )
                return
        time.sleep(0.05)
    log.warning(
        "Tray window did not appear within %.1fs — title not patched",
        timeout_s,
    )

from kira._resources import assets_dir as _assets_dir  # noqa: E402
ASSETS = _assets_dir()

# Branded tray icon: schwarzes Logo auf gelbem Rounded-Square. Der
# transparente Vorgänger war im Windows-11-Dark-Mode-Tray nahezu
# unsichtbar (schwarz auf schwarz). Gelb ist hell genug für Light- UND
# Dark-Mode und matcht den State.ERROR-Akzent farblich.
ICON_SIZE = 64
ICON_BG_COLOR = (255, 196, 0, 255)   # warmes Gelb (#FFC400)
ICON_BG_RADIUS = 12                  # Rounded-Corner-Radius in Pixel
# Innenabstand für das Logo. Windows skaliert das 64x64 Image im
# Notification Area weiter runter (16x16 / 22x22). Bei <10% Padding
# verschwindet der gelbe Rand bei dieser Skalierung praktisch komplett
# (1.6 -> 1px gerundet) und der User sieht nur noch das schwarze Logo.
# 10px (~16%) hinterlassen auch im 16x16-Tray noch einen 2-3px breiten
# gelben Rahmen, der das Icon vom dunklen Win11-Tray-Hintergrund trennt.
ICON_PADDING = 10


def _overlay_dot(img: Image.Image, rgba: tuple[int, int, int, int]) -> None:
    d = ImageDraw.Draw(img)
    w, h = img.size
    r = min(w, h) // 5
    d.ellipse((w - r*2, h - r*2, w, h), fill=rgba)


def _make_rounded_square(
    size: int,
    color: tuple[int, int, int, int],
    radius: int,
) -> Image.Image:
    """RGBA-Quadrat mit abgerundeten Ecken in der angegebenen Farbe."""
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    ImageDraw.Draw(img).rounded_rectangle(
        (0, 0, size - 1, size - 1), radius=radius, fill=color,
    )
    return img


# Module-level caches: assets/ lebt im WSL-Tree, der Process läuft auf
# Windows — jeder Image.open() landet als UNC-IO bei \\wsl.localhost\,
# das ist 3-15 ms pro Call (vs. <1 ms lokal NTFS). Über einen normalen
# F8-Zyklus laufen ~5 State-Changes; ohne Cache wäre das 15-75 ms reine
# Disk-IO. Wir laden das Logo einmal beim ersten Bedarf (lazy, damit
# Test-Imports ohne icon.ico nicht crashen) und memoizen die fertig
# komponierten Icons pro State.
_LOGO_CACHE: Image.Image | None = None
_LOGO_CACHE_FAILED = False
_ICON_CACHE: dict[State, Image.Image] = {}


def _get_logo() -> Image.Image | None:
    """Lazy-load + cache `assets/icon.ico` als RGBA. None falls Datei fehlt
    oder das Laden scheitert — Caller fällt dann auf Logo-Stand-In zurück."""
    global _LOGO_CACHE, _LOGO_CACHE_FAILED
    if _LOGO_CACHE is not None or _LOGO_CACHE_FAILED:
        return _LOGO_CACHE
    ico = ASSETS / "icon.ico"
    if not ico.exists():
        _LOGO_CACHE_FAILED = True
        return None
    try:
        _LOGO_CACHE = Image.open(ico).convert("RGBA")
    except Exception:
        log.exception("failed to load icon.ico, falling back to placeholder")
        _LOGO_CACHE_FAILED = True
    return _LOGO_CACHE


def _build_icon(state: State) -> Image.Image:
    """Render the branded icon for a given state from scratch.

    Use _load_or_generate_icon() instead when calling from production
    code — that one memoizes the result per state.
    """
    bg = _make_rounded_square(ICON_SIZE, ICON_BG_COLOR, ICON_BG_RADIUS)
    logo = _get_logo()
    if logo is not None:
        inner = ICON_SIZE - 2 * ICON_PADDING
        scaled_logo = logo.resize((inner, inner), Image.Resampling.LANCZOS)
        bg.alpha_composite(scaled_logo, (ICON_PADDING, ICON_PADDING))
    else:
        # Fallback wenn icon.ico fehlt / laden scheitert: schwarzer Kreis.
        ImageDraw.Draw(bg).ellipse(
            (ICON_PADDING + 2, ICON_PADDING + 2,
             ICON_SIZE - ICON_PADDING - 3, ICON_SIZE - ICON_PADDING - 3),
            fill=(0, 0, 0, 255),
        )

    if state == State.RECORDING:
        _overlay_dot(bg, (220, 30, 30, 255))      # kräftiges Rot
    elif state == State.ERROR:
        _overlay_dot(bg, (255, 80, 0, 255))       # Rotorange — Kontrast vs Gelb-BG
    return bg


def _load_or_generate_icon(state: State) -> Image.Image:
    """Schwarzes Kira-Logo auf gelbem Rounded-Square plus State-Overlay.

    Cached pro State — der erste Aufruf rendert, alle weiteren geben
    dasselbe Image-Objekt zurück. Sichtbar in beiden Windows-11-Tray-
    Themes (Light/Dark). Der Dot rechts unten markiert RECORDING (rot)
    und ERROR (rotorange) — beide auf dem gelben Hintergrund kontrastreich.
    """
    cached = _ICON_CACHE.get(state)
    if cached is not None:
        return cached
    icon = _build_icon(state)
    _ICON_CACHE[state] = icon
    return icon


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
        transcriber=None,
    ) -> None:
        self._on_quit = on_quit
        self._qt_marshal = qt_marshal
        # Optional Transcriber-Instanz für File-Transcription-Menue.
        # None = Menue-Eintrag „Datei transkribieren..." wird ausgeblendet
        # (z.B. im Test-Setup ohne Whisper-Modell). Wird in main.py nach
        # KiraApp-Konstruktion via tray.set_transcriber(...) gesetzt
        # damit dieselbe Whisper-Instanz im PTT-Pfad und File-Pfad
        # benutzt wird.
        self._transcriber = transcriber
        self._state = State.IDLE
        self._status_label = "Status: Idle"
        self._icon: pystray.Icon | None = None

    def set_transcriber(self, transcriber) -> None:
        """Wird im main.py nach Tray-Konstruktion gerufen — die Tray
        existiert bevor Transcriber gewarmupt ist, also late-binding."""
        self._transcriber = transcriber

    def _build_menu(self) -> pystray.Menu:
        # default=True wires the entry to Windows-tray double-click /
        # left-click ("default activate"); rechtsklick zeigt das ganze
        # Menu wie gehabt. Settings ist die Default-Action, weil das der
        # häufigste Konfig-Touchpoint ist (Mic, Polish-Modell, Hotkey).
        # Branded Header oben (Mike-Vorgabe 2026-05-09): pystray nutzt
        # Win32-Native-Popup-Menus (TrackPopupMenuEx) ohne Custom-Widget-
        # Support, daher kein zentriertes Logo mit BG. Was wir tun
        # koennen: ein disabled, default-aktiviertes Item mit Branding-
        # Text + Sparkles-Unicode + viel Padding fuer den Center-Effekt.
        # Win32-Menu rendert den Text mit System-Theme (Win11-Dark mit
        # weisser Schrift); das ist "schoener Hintergrund" so weit das
        # OS uns kommen laesst.
        header_text = "    ✨  Kira  ✨    "  # ✨ Kira ✨ + padding
        items = [
            pystray.MenuItem(header_text, None, enabled=False),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(self._status_label, None, enabled=False),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(
                "Einstellungen…", self._open_settings, default=True,
            ),
            pystray.MenuItem("Anleitung…", self._open_help),
            pystray.MenuItem("Open Log…", self._open_log),
        ]
        # File-Transcription-Eintrag nur sichtbar wenn ein Transcriber
        # gewired ist — im Test-/Headless-Modus hängt das Menue sonst
        # auf einer toten Aktion.
        if self._transcriber is not None:
            items.append(
                pystray.MenuItem(
                    "Datei transkribieren…", self._open_transcribe_file,
                ),
            )
        items.extend([
            pystray.MenuItem("Updates suchen…", self._check_for_updates),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("About Kira", self._about),
            pystray.MenuItem("Quit Kira", self._quit),
        ])
        return pystray.Menu(*items)

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
        try:
            subprocess.Popen(["notepad.exe", str(log_path)])
        except (OSError, FileNotFoundError) as exc:
            # Open Log ist Mike's Last-Resort-Debug-Pfad — wenn das
            # silent failt (Win11 N-Edition ohne notepad, Kiosk-Lock-
            # down) sieht der User nichts, klickt nochmal, gibt auf.
            # silent-failure-hunt 2026-05-09. Stattdessen Pfad anzeigen.
            log.exception("notepad launch failed for log %s", log_path)
            self._marshal_to_qt(
                lambda: self._show_notepad_fallback(str(log_path), str(exc)),
                "notepad fallback",
            )

    @staticmethod
    def _show_notepad_fallback(file_path: str, exc_msg: str) -> None:
        from kira.ui._dialog_style import light_warning
        light_warning(
            None, "Kira",
            f"Notepad konnte nicht gestartet werden: {exc_msg}\n\n"
            f"Datei manuell öffnen:\n{file_path}",
        )

    def _open_help(self, _icon, _item) -> None:
        """Wiederverwendet WelcomeDialog im as_help=True-Modus — selber
        Inhalt, ohne Marker-Schreiben + ohne 'nicht mehr zeigen'-Checkbox."""
        self._marshal_to_qt(self._show_help_dialog, "help dialog")

    @staticmethod
    def _show_help_dialog() -> None:
        from kira.ui.welcome_dialog import WelcomeDialog
        dlg = WelcomeDialog(as_help=True)
        getattr(dlg, "exec")()

    def _open_transcribe_file(self, _icon, _item) -> None:
        """File-Transcription via Tray: QFileDialog → faster-whisper →
        .txt-Datei daneben. Worker-Thread, sonst blockiert Whisper das
        Qt-Mainthread für Minuten bei langen Files."""
        if self._transcriber is None:
            log.warning("transcribe-file menu fired but no transcriber wired")
            return
        self._marshal_to_qt(
            lambda: self._show_transcribe_file_dialog(self._transcriber),
            "transcribe-file dialog",
        )

    @staticmethod
    def _show_transcribe_file_dialog(transcriber) -> None:
        # Imports lazy: das Tray-Modul wird auf jedem Boot importiert,
        # auch wenn der User nie File-Transcription nutzt — keine
        # PyQt-Worker-Allokationen on-load.
        from PyQt6.QtCore import QObject, QThread, Qt, pyqtSignal
        from PyQt6.QtWidgets import (
            QFileDialog, QProgressDialog,
        )
        from kira.ui._dialog_style import (
            apply_light_theme,
            light_critical,
            light_information,
        )

        path, _filter = QFileDialog.getOpenFileName(
            None,
            "Audio- oder Videodatei zum Transkribieren auswählen",
            "",
            "Medien (*.wav *.mp3 *.m4a *.flac *.ogg *.opus *.mp4 *.mov *.mkv *.webm);;Alle Dateien (*.*)",
        )
        if not path:
            return  # User hat Cancel geklickt
        log.info("File-Transcription requested: %s", path)

        progress = QProgressDialog(
            f"Transkribiere {Path(path).name}…",
            "Abbrechen", 0, 0, None,
        )
        progress.setWindowTitle("Kira — Datei transkribieren")
        progress.setWindowModality(Qt.WindowModality.ApplicationModal)
        progress.setMinimumDuration(0)
        apply_light_theme(progress)
        progress.show()

        class _Worker(QObject):
            done = pyqtSignal(str, str)   # output_path, language
            failed = pyqtSignal(str)      # error message

            def __init__(self, src_path: str):
                super().__init__()
                self._src = src_path

            def run(self) -> None:
                try:
                    result = transcriber.transcribe_file(self._src)
                    if not result.text:
                        self.failed.emit(
                            "Transkript ist leer — entweder Stille im File "
                            "oder Whisper konnte nichts erkennen."
                        )
                        return
                    out = Path(self._src).with_suffix(".txt")
                    out.write_text(result.text, encoding="utf-8")
                    self.done.emit(str(out), result.language)
                except Exception as exc:
                    log.exception("file-transcription worker crashed")
                    self.failed.emit(f"Fehler: {exc}")

        thread = QThread()
        worker = _Worker(path)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)

        def on_done(out_path: str, language: str) -> None:
            progress.close()
            thread.quit()
            thread.wait()
            light_information(
                None, "Kira",
                f"Fertig.\n\nTranskript gespeichert unter:\n{out_path}\n\n"
                f"Erkannte Sprache: {language}",
            )

        def on_failed(message: str) -> None:
            progress.close()
            thread.quit()
            thread.wait()
            light_critical(None, "Kira", message)

        worker.done.connect(on_done)
        worker.failed.connect(on_failed)
        thread.start()
        # Refs am Progress-Dialog festhalten, sonst frisst der GC sie
        # bevor der Worker fertig ist.
        progress._kira_thread = thread  # type: ignore[attr-defined]
        progress._kira_worker = worker  # type: ignore[attr-defined]

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
        """v0.2: echter Update-Check + Multi-Asset-Bundle-Pull.

        Bis v0.1 war das ein statischer Hint (Asset-Pull konnte nur den
        2 MB-Setup-Stub laden, die 7 .bin-Splits fehlten und Inno
        scheiterte). v0.2's updater holt das gesamte Bundle und verify
        SHA256SUMS falls vorhanden, bevor der Setup-Stub gestartet wird.

        Setup-Launch tut Kira selbst beenden (via self._on_quit), sodass
        das Programmverzeichnis für Inno schreibbar wird.
        """
        self._marshal_to_qt(
            lambda: self._run_update_flow_marshalled(self._on_quit),
            "update flow",
        )

    @staticmethod
    def _run_update_flow_marshalled(quit_callback) -> None:
        from kira.ui._update_runner import run_update_flow
        run_update_flow(parent=None, on_quit_request=quit_callback)

    def _quit(self, _icon, _item) -> None:
        try:
            self._on_quit()
        except Exception:
            log.exception("on_quit raised")
        if self._icon is not None:
            self._icon.stop()

    def run(self) -> None:
        """Blocks. Must be started in a non-main thread (Qt owns the main loop)."""
        self._icon = _KiraPystrayIcon(
            "kira",
            icon=_load_or_generate_icon(State.IDLE),
            title="Kira",
            menu=self._build_menu(),
        )
        self._icon.run()

    def run_detached(self) -> threading.Thread:
        """Convenience: start run() in a background daemon thread.

        Spawns a tiny helper that polls for the pystray window and
        patches its title to 'Kira' so Win11's notification-area
        settings show the right name (see _set_tray_window_title).
        """
        t = threading.Thread(target=self.run, daemon=True, name="kira-tray")
        t.start()
        threading.Thread(
            target=lambda: _set_tray_window_title(self),
            daemon=True, name="kira-tray-title",
        ).start()
        return t
