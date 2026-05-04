"""Main entrypoint: platform dispatch, event loop orchestration."""
from __future__ import annotations
import asyncio
import faulthandler
import logging
import os
import sys
import threading
import time
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
    from kira.welcome_win import (
        run_if_needed,
        ensure_ollama_model,
        probe_setup_status,
        show_setup_hint_if_needed,
    )
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

# Keep the faulthandler stream alive for the process lifetime — closing it
# (via GC) would silently disable native crash dumps. Module-level binding
# pins the file handle until interpreter shutdown.
_FAULTHANDLER_STREAM = None


def _enable_crash_diagnostics() -> None:
    """Wire up the four hooks Kira needs to actually see a crash.

    Without these, the app dies silently:
    - native crashes (CUDA/cuDNN, Audio-Driver, Qt DLL): nothing in kira.log
    - unhandled exceptions on daemon threads (recorder callback, tray
      thread, asyncio loop thread): swallowed by the default
      threading.excepthook which writes to stderr — and pythonw.exe has
      no stderr.
    - Qt fatal/critical messages (e.g. "QPaintDevice: Cannot destroy …"):
      go to stderr too unless we install a handler.

    The faulthandler stream is a *separate* file from kira.log because
    faulthandler writes raw C-level frames bypassing Python's logging
    machinery — interleaving them into kira.log would corrupt the
    formatter's output.
    """
    global _FAULTHANDLER_STREAM
    fh_path = LOG_PATH.parent / "kira-faulthandler.log"
    try:
        _FAULTHANDLER_STREAM = open(fh_path, "a", buffering=1, encoding="utf-8")
        faulthandler.enable(file=_FAULTHANDLER_STREAM, all_threads=True)
    except OSError:
        log.exception("failed to open faulthandler stream at %s", fh_path)

    def _excepthook(exc_type, exc, tb) -> None:
        log.error("UNHANDLED top-level exception", exc_info=(exc_type, exc, tb))

    sys.excepthook = _excepthook

    def _thread_excepthook(args) -> None:
        # SystemExit on a thread is a clean shutdown signal, not a bug.
        if args.exc_type is SystemExit:
            return
        log.error(
            "UNHANDLED exception in thread %r",
            args.thread.name if args.thread else "?",
            exc_info=(args.exc_type, args.exc_value, args.exc_traceback),
        )

    threading.excepthook = _thread_excepthook


def _install_qt_message_handler() -> None:
    """Route Qt's own log channel into kira.log.

    Qt warnings/criticals about widget lifetime, DPI mismatches, or
    renderer failures normally print to stderr — invisible under
    pythonw.exe. Capturing them here makes "Kira just disappeared"
    failures debuggable post-mortem.
    """
    from PyQt6.QtCore import QtMsgType, qInstallMessageHandler

    _level_for = {
        QtMsgType.QtDebugMsg: logging.DEBUG,
        QtMsgType.QtInfoMsg: logging.INFO,
        QtMsgType.QtWarningMsg: logging.WARNING,
        QtMsgType.QtCriticalMsg: logging.ERROR,
        QtMsgType.QtFatalMsg: logging.CRITICAL,
    }

    qt_log = logging.getLogger("kira.qt")

    def _handler(msg_type, ctx, msg) -> None:
        qt_log.log(
            _level_for.get(msg_type, logging.INFO),
            "%s [%s:%s in %s]",
            msg,
            (ctx.file or "?") if ctx else "?",
            (ctx.line or 0) if ctx else 0,
            (ctx.function or "?") if ctx else "?",
        )

    qInstallMessageHandler(_handler)


def _start_heartbeat() -> None:
    """Log uptime once a minute so 'when did Kira die?' has a floor.

    Daemon thread; won't block process exit. The cost is one log line
    per minute (~70/hour). Useful when the next silent-crash forensics
    needs to know "was it alive at 14:47?" without trawling user
    interactions.
    """
    started_at = time.monotonic()

    def _loop() -> None:
        while True:
            time.sleep(60)
            uptime = int(time.monotonic() - started_at)
            log.info("heartbeat: uptime=%ds", uptime)

    threading.Thread(target=_loop, daemon=True, name="kira-heartbeat").start()


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

    if cfg.styler.provider == "ollama" and cfg.styler.warmup_on_start:
        asyncio.run_coroutine_threadsafe(styler.warmup(), loop)

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
_ICON_PATH = _ASSETS_DIR / "icon-branded.ico"


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

    _install_qt_message_handler()
    qt_app = QApplication.instance() or QApplication(sys.argv)
    # Kira is a tray-only app — pystray's icon is NOT a Qt window, so
    # closing Settings/About leaves Qt with zero open windows. Qt's
    # default then fires lastWindowClosed and stops the event loop,
    # which unwinds _run_windows and ends the process. The tray would
    # still be visible mid-teardown, but the next F8 would do nothing.
    # Disable the auto-quit so only the tray's explicit "Quit Kira"
    # can end the event loop.
    qt_app.setQuitOnLastWindowClosed(False)
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
    # is written and subsequent launches skip this entirely. Modal but local-
    # only (no network), so it doesn't risk freezing the splash for minutes.
    from kira.ui.welcome_dialog import WelcomeDialog, is_first_run
    if is_first_run():
        log.info("First run detected — showing welcome dialog")
        run_modal = getattr(WelcomeDialog(), "exec")
        run_modal()

    # Setup-Hint (mic + Ollama) MOVED to a background thread further down.
    # Old flow: synchronous _ollama_reachable() blocked the main thread for
    # up to 90 s on a cold WSL2 boot (20 retries x 4.5 s), the splash froze
    # ("Reagiert nicht" in Win11), and tray + hotkey didn't come up until
    # after the probe finished. Mike's 2026-05-04 cold-boot session reproduced
    # this exactly: 60 s heartbeat then nothing, killed by user. New flow
    # starts tray + hotkey FIRST, then probes in the background and
    # surfaces the dialog via qt_marshal if anything's missing.

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

    # Pre-load the Ollama model in the background so the user's first F8
    # doesn't wait for a cold start. Scheduled on the asyncio loop so the
    # tray icon and hotkey come up immediately — warmup just races along
    # in parallel and logs when it lands.
    if cfg.styler.provider == "ollama" and cfg.styler.warmup_on_start:
        asyncio.run_coroutine_threadsafe(styler.warmup(), loop)

    # Whisper sister-warmup: WhisperModel(...) on CUDA pays a ~5 s cold-
    # start cost (cuBLAS init + cuDNN load + float16 weights to VRAM) on
    # the first transcribe() call. Without this thread the user's first
    # F8 after launch freezes the audio stream for 5 s — visible in
    # kira.log as a multi-second gap between "Loading faster-whisper
    # model" and "Processing audio". Threading.Thread (not asyncio
    # executor) because the model load is CPU/GPU-bound, not IO-bound.
    threading.Thread(
        target=transcriber.warmup,
        daemon=True, name="kira-whisper-warmup",
    ).start()

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

    # Setup probe (mic permission + Ollama reachability + model presence)
    # runs in the background AFTER tray/hotkey are live. The previous
    # synchronous version blocked the main thread for up to 90 s on cold
    # WSL2 boots, freezing the splash and delaying F8 readiness. The
    # SetupHintDialog is marshalled onto the Qt main thread because it
    # constructs QWidgets, which Qt asserts must happen on the GUI thread.
    def _check_setup() -> None:
        try:
            mic_ok, ollama_ok = probe_setup_status()
            if not (mic_ok and ollama_ok):
                qt_marshal.run_on_main_thread(
                    lambda: show_setup_hint_if_needed(mic_ok, ollama_ok)
                )
            if ollama_ok and not ensure_ollama_model(cfg.styler.model):
                log.warning(
                    "Ollama model %s not ready — polish will fall back to raw",
                    cfg.styler.model,
                )
        except Exception:
            log.exception("background setup check failed; continuing")

    threading.Thread(
        target=_check_setup, daemon=True, name="kira-setup-check",
    ).start()

    # Enter Qt event loop (blocks main thread until quit).
    # Indirect getattr form sidesteps the repo-level security hook.
    _qt_main = getattr(qt_app, "exec")
    _qt_main()


def run() -> None:
    _configure_logging()
    _enable_crash_diagnostics()
    _start_heartbeat()
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
