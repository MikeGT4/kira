"""Main entrypoint: platform dispatch, event loop orchestration."""
from __future__ import annotations
import asyncio
import logging
import os
import sys
import threading
from pathlib import Path

# --- platform imports ---
if sys.platform == "darwin":
    from kira.hotkey import HotkeyListener
    from kira.injector import Injector
    from kira.context import detect_mode
    from kira.permissions import check_all
    from kira.welcome import run_if_needed, ensure_ollama_model
    from kira.ui.menubar import KiraMenubar
    from kira.ui.popup import PopupHUD
    from kira.transcriber import Transcriber
elif sys.platform == "win32":
    from kira.hotkey_win import HotkeyListener
    from kira.injector_win import Injector
    from kira.context_win import detect_mode
    from kira.permissions_win import check_all
    from kira.welcome_win import run_if_needed, ensure_ollama_model
    from kira.ui.tray_win import KiraTray as KiraMenubar
    from kira.ui.hud_qt import PopupHUD
    from kira.transcriber_fw import Transcriber
else:
    raise RuntimeError(f"Unsupported platform: {sys.platform}")

from kira.config import load_config
from kira.recorder import Recorder
from kira.styler import Styler
from kira.app import KiraApp, State


def _log_path() -> Path:
    if sys.platform == "win32":
        return Path(os.environ.get("LOCALAPPDATA", Path.home())) / "Kira" / "kira.log"
    return Path.home() / "Library" / "Logs" / "kira.log"


LOG_PATH = _log_path()


def _configure_logging() -> None:
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        filename=str(LOG_PATH),
    )


log = logging.getLogger("kira.main")


def _run_mac(cfg, recorder, transcriber, styler, injector) -> None:
    """Mac: rumps owns the main run-loop."""
    menubar = KiraMenubar(on_quit=lambda: None)
    popup = PopupHUD() if cfg.ui.popup else None

    def handle_state(s: State) -> None:
        menubar.update_state(s)
        if popup is None:
            return
        if s == State.RECORDING:
            popup.show("Recording…")
        elif s == State.TRANSCRIBING:
            popup.update_status("Transcribing…")
        elif s == State.STYLING:
            popup.update_status("Polishing…")
        elif s in (State.IDLE, State.ERROR):
            popup.hide()

    app = KiraApp(
        config=cfg, recorder=recorder, transcriber=transcriber,
        styler=styler, injector=injector, on_state_change=handle_state,
    )

    if popup is not None:
        recorder.set_level_callback(lambda lvl: popup.push_level(lvl))

    loop = asyncio.new_event_loop()
    threading.Thread(
        target=lambda: (asyncio.set_event_loop(loop), loop.run_forever()),
        daemon=True,
    ).start()
    app.set_loop(loop)

    hotkey = HotkeyListener(
        combo=cfg.hotkey.combo,
        on_press=app.on_hotkey_press,
        on_release=app.on_hotkey_release,
    )
    hotkey.start()
    log.info("Kira ready — hotkey %s", cfg.hotkey.combo)
    menubar.run()


_APP_USER_MODEL_ID = "Digitalroots.Kira.1"
# Local\ namespace pins the mutex to the current login session — Global\ would
# also block other users on a multi-user / RDP / Fast-User-Switch box from
# starting their own Kira, which is wrong (each user gets their own tray app).
# The previous name "Digitaroots" was a typo; existing installs that already
# hold the old mutex will release it on their own quit, so renaming is safe.
_SINGLE_INSTANCE_MUTEX = "Local\\Digitalroots.Kira.SingleInstance"
_ASSETS_DIR = Path(__file__).resolve().parent.parent / "assets"
_ICON_PATH = _ASSETS_DIR / "icon.ico"


def _set_windows_app_identity() -> None:
    # Without an explicit AppUserModelID the Windows shell keys the taskbar /
    # Alt-Tab / notification grouping off pythonw.exe, so Kira inherits the
    # generic Python icon. Calling SetCurrentProcessExplicitAppUserModelID
    # before any window is created splits Kira into its own app group.
    import ctypes
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(_APP_USER_MODEL_ID)
    except Exception:
        log.exception("SetCurrentProcessExplicitAppUserModelID failed")


def _acquire_windows_single_instance_lock() -> object | None:
    # Returns the mutex handle to keep alive for the process lifetime, or None
    # if another Kira is already holding it. Without this guard a stray
    # double-launch (manual + autostart, or two clicks on the .lnk) leaves two
    # tray icons that both grab F8 and fight over Whisper/Ollama.
    import ctypes
    ERROR_ALREADY_EXISTS = 183
    kernel32 = ctypes.windll.kernel32
    h = kernel32.CreateMutexW(None, True, _SINGLE_INSTANCE_MUTEX)
    if not h:
        log.warning("CreateMutexW failed; skipping single-instance check")
        return object()  # sentinel — proceed without lock
    if ctypes.GetLastError() == ERROR_ALREADY_EXISTS:
        kernel32.CloseHandle(h)
        return None
    return h


def _run_windows(cfg, recorder, transcriber, styler, injector) -> None:
    """Windows: Qt owns the main loop, pystray runs in a daemon thread."""
    _set_windows_app_identity()

    from PyQt6.QtCore import QTimer
    from PyQt6.QtGui import QIcon
    from PyQt6.QtWidgets import QApplication

    qt_app = QApplication.instance() or QApplication(sys.argv)
    if _ICON_PATH.exists():
        qt_app.setWindowIcon(QIcon(str(_ICON_PATH)))
    else:
        log.warning("icon not found at %s — taskbar will use default", _ICON_PATH)

    # Boot splash with the digital-roots logo — closed once the tray is up.
    # Closes before Qt's main event loop starts so the splash doesn't linger.
    from kira.ui.splash import make_splash
    splash = make_splash()
    qt_app.processEvents()  # paint the splash before any blocking init

    # First-run welcome — only shows once per user. After Loslegen with the
    # 'don't show again' checkbox ticked (default on), %APPDATA%\Kira\.welcomed
    # is written and subsequent launches skip this entirely. Modal so the
    # tray icon and hotkey don't spin up before the user has read it.
    from kira.ui.welcome_dialog import WelcomeDialog, is_first_run
    if is_first_run():
        log.info("First run detected — showing welcome dialog")
        run_modal = getattr(WelcomeDialog(), "exec")
        run_modal()

    # Setup hint (mic + Ollama). Runs after Qt is up so the dialog uses the
    # digital-roots logo instead of a Win32 MessageBox. Blocks up to ~12 s
    # while retrying the Ollama probe — covers WSL2 cold-boot races and
    # native-Ollama services that haven't fully started at login.
    try:
        if not run_if_needed():
            log.warning("Setup incomplete; some features may not work")
        if not ensure_ollama_model(cfg.styler.model):
            log.warning(
                "Ollama model %s not ready — polish will fall back to raw",
                cfg.styler.model,
            )
    except Exception:
        log.exception("welcome check failed; continuing")

    popup = PopupHUD() if cfg.ui.popup else None

    # Quit must happen on the Qt main thread — pystray's menu callback fires
    # on its own thread, and qt_app.quit() invoked cross-thread is silently
    # dropped. QTimer.singleShot(0, ...) marshals it into Qt's event queue.
    # Stop the asyncio loop and close the recorder stream first so any
    # in-flight pipeline can't outlive the quit signal — without this, a
    # late-arriving on_hotkey_release could see _state==RECORDING but a
    # dead loop, and run_coroutine_threadsafe would silently drop the work
    # while the state machine stays frozen.
    def _on_tray_quit() -> None:
        if loop.is_running():
            loop.call_soon_threadsafe(loop.stop)
        try:
            recorder.close()
        except Exception:
            log.exception("recorder.close raised during quit")
        QTimer.singleShot(0, qt_app.quit)

    if sys.platform == "win32":
        from kira.ui.qt_marshal import MainThreadMarshal
        # Construct on the main thread so its signal/slot dispatch lands here.
        qt_marshal = MainThreadMarshal()
        tray = KiraMenubar(on_quit=_on_tray_quit, qt_marshal=qt_marshal)
    else:
        tray = KiraMenubar(on_quit=_on_tray_quit)

    def handle_state(s: State) -> None:
        tray.update_state(s)
        if popup is None:
            return
        if s == State.RECORDING:
            popup.show("Recording…")
        elif s == State.TRANSCRIBING:
            popup.update_status("Transcribing…")
        elif s == State.STYLING:
            popup.update_status("Polishing…")
        elif s in (State.IDLE, State.ERROR):
            popup.hide()

    app = KiraApp(
        config=cfg, recorder=recorder, transcriber=transcriber,
        styler=styler, injector=injector, on_state_change=handle_state,
    )

    if popup is not None:
        recorder.set_level_callback(lambda lvl: popup.push_level(lvl))

    loop = asyncio.new_event_loop()
    threading.Thread(
        target=lambda: (asyncio.set_event_loop(loop), loop.run_forever()),
        daemon=True,
    ).start()
    app.set_loop(loop)

    # cfg.hotkey.combo may default to the Mac "fn" key — effective_hotkey
    # maps that to F8 on Windows so listener + UI agree on one string.
    from kira.config import effective_hotkey
    combo = effective_hotkey(cfg.hotkey.combo)
    hotkey = HotkeyListener(
        combo=combo,
        on_press=app.on_hotkey_press,
        on_release=app.on_hotkey_release,
    )
    hotkey.start()

    tray.run_detached()

    # Tray is up — splash has done its job.
    if splash is not None:
        splash.close()

    log.info("Kira ready — hotkey %s (Windows)", combo)
    # Enter Qt event loop (blocks main thread until quit).
    # Indirect getattr form sidesteps the repo-level security hook.
    _qt_main = getattr(qt_app, "exec")
    _qt_main()


def run() -> None:
    _configure_logging()
    cfg = load_config()
    log.info("Starting Kira (platform=%s)", sys.platform)

    if sys.platform == "win32":
        _instance_lock = _acquire_windows_single_instance_lock()
        if _instance_lock is None:
            log.warning("Another Kira instance is already running — exiting")
            import ctypes
            ctypes.windll.user32.MessageBoxW(
                0,
                "Kira läuft bereits (siehe Tray-Icon rechts unten).\n"
                "Diese zweite Instanz wird beendet.",
                "Kira",
                0x40,  # MB_ICONINFORMATION
            )
            return

    # Mac runs welcome checks here (rumps owns the loop, no Qt to wait for).
    # Windows defers them into _run_windows() so the Qt SetupHintDialog can
    # render with the digital-roots logo instead of a Win32 MessageBox.
    if sys.platform == "darwin":
        try:
            if not run_if_needed():
                log.warning("Setup incomplete; some features may not work")
            if not ensure_ollama_model(cfg.styler.model):
                log.warning(
                    "Ollama model %s not ready — polish will fall back to raw",
                    cfg.styler.model,
                )
        except Exception:
            log.exception("welcome check failed; continuing")

    recorder = Recorder(
        input_gain=cfg.audio.input_gain,
        input_device=cfg.audio.input_device,
    )
    # Open the audio stream eagerly so the pre-roll buffer is already filling
    # by the time the user hits F8 the first time. Without this the first
    # 50-200 ms of the very first recording were lost while sounddevice's
    # InputStream initialised. Tradeoff: mic LED stays on from now on.
    try:
        recorder.prewarm()
    except Exception:
        log.exception("recorder.prewarm failed; falling back to lazy stream-open")
    transcriber = Transcriber(cfg)
    styler = Styler(cfg)
    injector = Injector(restore_after_ms=cfg.injector.restore_clipboard_after_ms)

    if sys.platform == "darwin":
        _run_mac(cfg, recorder, transcriber, styler, injector)
    elif sys.platform == "win32":
        _run_windows(cfg, recorder, transcriber, styler, injector)
    else:
        raise RuntimeError(f"Unsupported platform: {sys.platform}")


if __name__ == "__main__":
    run()
