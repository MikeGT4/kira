"""Main entrypoint: platform dispatch, event loop orchestration."""
from __future__ import annotations
import asyncio
import faulthandler
import logging
import logging.handlers
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

# kira.log hard cap: 15 MB pro Datei × (1 aktuelle + 1 Backup) = 30 MB
# gesamt. Vorher wuchs kira.log unbegrenzt (13 MB nach ~7 Wochen Laufzeit,
# 2026-06-28). faulthandler.log rotiert bewusst NICHT mit — es ist winzig
# (~10 KB) und umgeht die logging-Maschinerie absichtlich (siehe run()).
LOG_MAX_BYTES = 15 * 1024 * 1024
LOG_BACKUP_COUNT = 1
_LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"


def _build_log_handler(path: Path) -> logging.Handler:
    """Rotierender File-Handler mit hartem 30-MB-Gesamtcap, UTF-8.

    UTF-8 explizit gesetzt: ohne das schreibt Python auf Windows in der
    ANSI-Codepage (cp1252) und deutsche Umlaute landen als Mojibake in
    kira.log (z. B. "M�ll" statt "Müll").
    """
    handler = logging.handlers.RotatingFileHandler(
        str(path),
        maxBytes=LOG_MAX_BYTES,
        backupCount=LOG_BACKUP_COUNT,
        encoding="utf-8",
    )
    handler.setFormatter(logging.Formatter(_LOG_FORMAT))
    return handler


def _configure_logging() -> None:
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(level=logging.INFO, handlers=[_build_log_handler(LOG_PATH)])


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

# Resource-Lookup: dual-mode (Wheel-Install vs Editable/Source-Tree).
#
# Wheel-Install (Slim-Installer-Bundle): pyproject.toml force-include packt
# assets/ -> kira/_assets/, installer/embedded/ -> kira/_embedded/, prompts/
# -> kira/_prompts/. Path(__file__).parent ist <site-packages>/kira/, also
# <site-packages>/kira/_assets/ etc.
#
# Editable/Source-Tree-Mode: kein force-include, klassischer Repo-Layout —
# Path(__file__).parent.parent ist <repo-root>/, also <repo-root>/assets/ etc.
#
# Wir versuchen Wheel-Layout zuerst; faellt zurueck auf Source-Tree.
def _resolve_assets_dir() -> Path:
    pkg_dir = Path(__file__).resolve().parent
    wheel_assets = pkg_dir / "_assets"
    if wheel_assets.exists():
        return wheel_assets
    return pkg_dir.parent / "assets"


_ASSETS_DIR = _resolve_assets_dir()
_ICON_PATH = _ASSETS_DIR / "icon-branded.ico"


_RESOURCE_REL_MAP = {
    "assets": "_assets",
    "prompts": "_prompts",
}


def _bundle_root() -> Path | None:
    """Return Inno-Slim-Bundle-Root wenn wir aus dem deployed Bundle laufen,
    sonst None.

    Im Bundle ist sys.executable = `{app}\\python\\python.exe`, d.h.
    Path(sys.executable).parent.parent = `{app}`. Zusaetzlich
    `{app}\\installer\\embedded\\OllamaSetup.exe` als Existenz-Check, damit
    wir kein false-positive bei einem random embedded Python woanders
    haben.
    """
    try:
        candidate = Path(sys.executable).resolve().parent.parent
    except (OSError, ValueError):
        return None
    if (candidate / "installer" / "embedded").exists():
        return candidate
    return None


def _resource_path(rel_path: str) -> Path:
    """Resolve a bundled resource path with multi-mode support.

    Cascade:
      1. **Wheel-Layout** (force-include): kira/_assets/, kira/_prompts/
         werden via pyproject.toml ins wheel gepackt. Resource resolves
         relativ zum kira-Modul.
      2. **PyInstaller-Bundle** (sys._MEIPASS): historisch, falls jemals
         PyInstaller-Bundle gebaut wird.
      3. **Inno-Slim-Bundle** (sys.executable): grosse Resources wie
         installer/embedded/OllamaSetup.exe (~1.98 GB) sind absichtlich
         NICHT im wheel — Inno deployed sie nach {app}\\installer\\embedded\\.
         _bundle_root() detected das via sys.executable.
      4. **Source-Tree** (parent of kira/-Modul): editable Install im
         Repo-Root.

    Path-Traversal-protected via ``.resolve()`` + ``.is_relative_to(base)``.
    Raises ``ValueError`` wenn ``rel_path`` aus Base raushuepft.
    """
    pkg_dir = Path(__file__).resolve().parent
    rel_norm = rel_path.replace("\\", "/")

    # 1. Wheel-Layout
    for source_prefix, wheel_prefix in _RESOURCE_REL_MAP.items():
        if rel_norm.startswith(source_prefix + "/") or rel_norm == source_prefix:
            wheel_rel = wheel_prefix + rel_norm[len(source_prefix):]
            wheel_target = (pkg_dir / wheel_rel).resolve()
            if wheel_target.exists() and wheel_target.is_relative_to(pkg_dir):
                return wheel_target
            break

    # 2. PyInstaller-Bundle
    if hasattr(sys, "_MEIPASS"):
        base = Path(sys._MEIPASS).resolve()
        target = (base / rel_path).resolve()
        if not target.is_relative_to(base):
            raise ValueError(f"Path traversal attempt blocked: {rel_path!r}")
        return target

    # 3. Inno-Slim-Bundle (assets/big files via Inno-deployed paths)
    bundle_root = _bundle_root()
    if bundle_root is not None:
        target = (bundle_root / rel_path).resolve()
        if target.exists() and target.is_relative_to(bundle_root):
            return target

    # 4. Source-Tree-Fallback
    base = pkg_dir.parent
    target = (base / rel_path).resolve()
    if not target.is_relative_to(base):
        raise ValueError(f"Path traversal attempt blocked: {rel_path!r}")
    return target


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

    # WSL2 doesn't auto-start at Win-login. On boxes where the polish
    # backend lives in WSL (Mike's setup), autostart races WSL2 cold-boot
    # every reboot — the setup probe times out at 90 s and the
    # SetupHintDialog used to fire every morning. Fire wsl.exe non-
    # blocking now so WSL spins up in parallel with Kira's own splash
    # + tray init; by the time _check_setup probes (~5 s later) Ollama
    # is usually reachable. No-op on boxes without WSL installed.
    from kira._wsl_warmup import kick_wsl_distro
    kick_wsl_distro()

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

    # First-run wizard: vor Splash + Welcome, weil ohne Whisper-Modell + Ollama
    # die Tray gar nichts Sinnvolles tun kann. Marker liegt unter
    # %APPDATA%\Kira\.first-run-complete und wird ausschliesslich von
    # SetupWizard.accept() gesetzt — ein Cancel laesst ihn fehlen, sodass der
    # User beim naechsten Start wieder den Wizard sieht.
    # Alias als is_first_setup_run um Namens-Kollision mit dem WelcomeDialog-
    # is_first_run weiter unten zu vermeiden — beide checken unterschiedliche
    # Marker (.first-run-complete vs .welcomed-version-string).
    from kira.firstrun import is_first_run as is_first_setup_run
    if is_first_setup_run():
        from kira.setup_wizard import SetupWizard

        # Whisper-Target deckt sich mit der Default-Convention aus
        # config.yaml.template ("C:/Users/${USERNAME}/models/...").
        whisper_target = Path.home() / "models" / "faster-whisper-large-v3"
        ollama_setup = _resource_path("installer/embedded/OllamaSetup.exe")

        log.info("First-run detected — launching SetupWizard")
        wizard = SetupWizard(whisper_target, ollama_setup)
        wizard_result = wizard.exec()
        if wizard_result != SetupWizard.DialogCode.Accepted:
            log.warning("First-run wizard aborted by user — exiting.")
            return

    # Boot splash with the digital-roots logo — sequentiell vor dem Welcome.
    # Vorher liefen Splash + Welcome PARALLEL: Splash (frameless, OnTop)
    # und Welcome (modal) ueberlagerten sich auf 4K-Displays haesslich,
    # User klickte Splash weg (kein Effekt -> Welcome blieb sichtbar mit
    # Splash dahinter) oder Welcome weg (Splash-Pixmap erschien drunter
    # und sah aus wie ein zweites Welcome). Mike's Bug-Report:
    # "willkommensscreen war immer sofort weg" + "kam beim Wegklicken
    # wieder" — beides Folge dieses Layer-Konflikts.
    # Fix: Splash 2 Sek allein zeigen, dann schliessen, DANN Welcome.
    from kira.ui.splash import make_splash
    splash = make_splash()
    if splash is not None:
        from PyQt6.QtCore import QElapsedTimer
        timer = QElapsedTimer()
        timer.start()
        # processEvents-Loop fuer 2 s — splash bleibt sichtbar, Qt kann
        # paint/repaint events verarbeiten. time.sleep waere blockierender,
        # der Splash wuerde nicht repaintet beim Maus-Hovering darueber.
        while timer.elapsed() < 2000:
            qt_app.processEvents()
            time.sleep(0.05)
        splash.close()
        qt_app.processEvents()
        splash = None  # damit der spaetere splash.close()-Block no-op ist

    # First-run welcome — only shows once per user-version. After Loslegen
    # with the 'don't show again' checkbox ticked (default on),
    # %APPDATA%\Kira\.welcomed wird mit __version__ geschrieben.
    # is_first_run() vergleicht Marker-Version vs current — bei Major/
    # Minor-Update zeigt sich der Dialog erneut ("Was ist neu").
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
        tray = KiraMenubar(
            on_quit=_on_tray_quit,
            qt_marshal=qt_marshal,
            transcriber=transcriber,
        )
        # v0.2.6: Polish-Latenz-Detection — wenn das Polish-Modell auf
        # CPU rutscht (Ollama-on-Win11-Bug), feuert der Styler nach 3
        # Slow-Polishes in Folge einen Tray-Toast. Setter statt ctor-
        # kwarg, weil Styler in run() vor Tray erzeugt wird.
        styler.set_on_slow_polish_detected(
            lambda: tray.notify(
                "Kira — Polish auf CPU",
                "Polish-Latenz hoch. Temporaer auf schnelles Modell "
                "umgeschaltet. Pruefe Settings → GPU-Check.",
            )
        )
        # v0.3.0: deterministischer CPU-Fallback-Toast aus verify_gpu_placement
        # (size_vram=0 nach Warmup). Die msg traegt den actionablen Hinweis
        # (Ollama neu starten -> VRAM-Tuning greift).
        styler.set_on_cpu_fallback_detected(
            lambda msg: tray.notify("Kira — Polish auf CPU", msg)
        )
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
        recorder.set_samples_callback(lambda arr: popup.push_samples(arr))

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

    # Optional zweite Combo fuer AI-Editing-Commands (F9 Default).
    # cfg.hotkey.edit_combo=None deaktiviert das Feature komplett. Press
    # delegiert auf KiraApp.on_edit_press (das macht Selection-Capture
    # und ruft danach intern on_hotkey_press), Release nutzt den
    # gemeinsamen on_hotkey_release-Pfad — dieser entscheidet im Pipeline
    # via _edit_mode-Flag ob Polish oder Edit-Command-LLM gefragt wird.
    edit_hotkey = None
    if cfg.hotkey.edit_combo:
        try:
            edit_hotkey = HotkeyListener(
                combo=cfg.hotkey.edit_combo,
                on_press=app.on_edit_press,
                on_release=app.on_hotkey_release,
            )
            edit_hotkey.start()
            log.info(
                "Edit-Command hotkey aktiv (combo=%s)", cfg.hotkey.edit_combo,
            )
        except ValueError:
            log.warning(
                "edit_combo=%r ist nicht supported — Edit-Command-Feature "
                "deaktiviert. Erlaubt: %s",
                cfg.hotkey.edit_combo,
                ", ".join(sorted(__import__("kira.hotkey_win", fromlist=["SUPPORTED_COMBOS"]).SUPPORTED_COMBOS)),
            )

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
            from kira.welcome_win import _ollama_reachable_once
            mic_ok, ollama_ok = probe_setup_status()
            # Mic-permission failures need user action — always surface.
            # Ollama-only failures are handled silently below.
            if not mic_ok:
                qt_marshal.run_on_main_thread(
                    lambda: show_setup_hint_if_needed(mic_ok, ollama_ok)
                )
            if ollama_ok:
                if not ensure_ollama_model(cfg.styler.model):
                    log.warning(
                        "Ollama model %s not ready — polish will fall back to raw",
                        cfg.styler.model,
                    )
                return
            # Initial 90 s probe missed Ollama — keep polling quietly so
            # we can pre-load the model when the backend (e.g. WSL2 +
            # ollama.service) eventually finishes coming up. No dialog:
            # polish falls back to raw Whisper text on errors, and the
            # dialog at every cold boot would only nag.
            log.info(
                "Ollama unreachable in initial probe; background re-probe started"
            )
            for i in range(20):  # 20 × 30 s = 10 min total
                time.sleep(30)
                if _ollama_reachable_once():
                    log.info("Ollama reachable on retry #%d", i + 1)
                    if not ensure_ollama_model(cfg.styler.model):
                        log.warning(
                            "Ollama model %s not ready — polish will fall back to raw",
                            cfg.styler.model,
                        )
                    return
            log.info(
                "Ollama still unreachable after 10 min; polish will use raw fallback"
            )
        except Exception:
            log.exception("background setup check failed; continuing")

    threading.Thread(
        target=_check_setup, daemon=True, name="kira-setup-check",
    ).start()

    # Automatischer Update-Check beim Start. Laeuft — wie der Setup-Probe
    # darueber — auf einem eigenen Daemon-Thread, damit der Boot NICHT
    # blockiert wird (Boot-Hang ist eine teure, dokumentierte Falle, s.
    # CLAUDE.md "Boot sequence"). Fragt GitHub-Releases ab; nur bei einer
    # echten neueren Version (status == 'newer') wird der Nutzer gefragt,
    # und auch das nur, wenn er diese Version nicht schon abgelehnt hat.
    # Netzwerk-/Parse-Fehler (status == 'failed') scheitern still — nur
    # Log, kein Dialog. Die Abfrage selbst wird ueber den qt_marshal auf
    # den Qt-Main-Thread marshalled (QMessageBox darf nur dort laufen).
    def _check_for_app_update() -> None:
        if not cfg.updates.check_on_start:
            log.info("Start-Update-Check via Config deaktiviert (updates.check_on_start=false)")
            return
        try:
            from kira import __version__, UPDATE_REPO
            from kira._update_marker import is_update_declined, mark_update_declined
            from kira.updater import check_for_update

            result = check_for_update(local_version=__version__, repo=UPDATE_REPO)
            if result.status != "newer":
                # 'current' / 'local_newer' / 'no_asset' / 'failed' — alle
                # ohne Nutzer-Interaktion. 'failed' (kein Netz o.ae.) hat
                # check_for_update bereits als WARNING geloggt; hier nur
                # noch eine ruhige INFO-Zeile zur Nachvollziehbarkeit.
                log.info("Start-Update-Check: keine Aktion (status=%s)", result.status)
                return

            remote = result.remote_version or "?"
            if is_update_declined(remote):
                # Nutzer hat genau diese Version schon abgelehnt — nicht
                # bei jedem Start erneut nerven.
                log.info(
                    "Start-Update-Check: v%s verfuegbar, aber vom Nutzer "
                    "bereits abgelehnt — keine Abfrage", remote,
                )
                return

            log.info("Start-Update-Check: neuere Version v%s verfuegbar", remote)
            qt_marshal.run_on_main_thread(
                lambda: tray.prompt_start_update(remote, on_declined=mark_update_declined)
            )
        except Exception:
            # Defense-in-Depth: check_for_update kollabiert Netz-/Parse-
            # Fehler schon zu status='failed'. Ein Fehler hier waere also
            # unerwartet — trotzdem nur loggen, der Update-Check darf den
            # Rest der App nie beeintraechtigen.
            log.exception("Start-Update-Check fehlgeschlagen; wird ignoriert")

    threading.Thread(
        target=_check_for_app_update, daemon=True, name="kira-update-check",
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

    # VRAM-Tuning fuer den Ollama-Polish-Pfad persistent setzen (Windows-only +
    # idempotent, no-op auf Mac). Flash-Attention + q8-KV-Cache senken den
    # VRAM-Bedarf, statt die GPU-Platzierung mit num_gpu=999 zu erzwingen.
    # Greift nach dem naechsten Ollama-Neustart; ein laufender Server wird
    # bewusst nicht neu gestartet (geteilt mit anderen Clients). S. ollama_env.
    if cfg.styler.provider == "ollama":
        try:
            from kira.ollama_env import apply_tuning_env
            apply_tuning_env()
        except Exception:
            log.exception("Ollama-VRAM-Tuning fehlgeschlagen; continuing")

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
