"""Main entrypoint: wires everything up and starts the menubar."""
from __future__ import annotations
import asyncio
import logging
import signal
import threading
from pathlib import Path
from kira.config import load_config
from kira.recorder import Recorder
from kira.transcriber import Transcriber
from kira.styler import Styler
from kira.injector import Injector
from kira.hotkey import HotkeyListener
from kira.app import KiraApp, State
from kira.ui.menubar import KiraMenubar
from kira.ui.popup import PopupHUD


LOG_PATH = Path.home() / "Library" / "Logs" / "kira.log"


def _configure_logging() -> None:
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        filename=str(LOG_PATH),
        force=True,
    )


log = logging.getLogger("kira.main")


def run() -> None:
    _configure_logging()
    from kira.welcome import run_if_needed, ensure_ollama_model
    cfg = load_config()
    log.info("Starting Kira")

    try:
        if not run_if_needed():
            log.warning("Some permissions or Ollama missing; app may not function fully")
        if not ensure_ollama_model(cfg.styler.model):
            log.warning("Ollama model %s not present. Run: ollama pull %s", cfg.styler.model, cfg.styler.model)
    except Exception:
        log.exception("welcome check failed; continuing")

    recorder = Recorder()
    transcriber = Transcriber(cfg)
    styler = Styler(cfg)
    injector = Injector(restore_after_ms=cfg.injector.restore_clipboard_after_ms)

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
        config=cfg,
        recorder=recorder,
        transcriber=transcriber,
        styler=styler,
        injector=injector,
        on_state_change=handle_state,
    )

    if popup is not None:
        recorder.set_level_callback(lambda lvl: popup.push_level(lvl))

    loop = asyncio.new_event_loop()

    def _loop_runner():
        asyncio.set_event_loop(loop)
        loop.run_forever()

    threading.Thread(target=_loop_runner, daemon=True).start()
    app.set_loop(loop)

    if cfg.styler.warmup_on_start:
        asyncio.run_coroutine_threadsafe(styler.warmup(), loop)

    hotkey = HotkeyListener(
        combo=cfg.hotkey.combo,
        on_press=app.on_hotkey_press,
        on_release=app.on_hotkey_release,
    )
    hotkey.start()

    _shutdown_done = threading.Event()

    def _graceful_shutdown():
        if _shutdown_done.is_set():
            return
        _shutdown_done.set()
        try:
            hotkey.stop()
        except Exception:
            log.exception("hotkey.stop raised")
        try:
            recorder._shutdown()
        except Exception:
            log.exception("recorder shutdown raised")
        try:
            loop.call_soon_threadsafe(loop.stop)
        except Exception:
            pass

    def _signal_handler(signum, _frame):
        log.info("received signal %s — shutting down", signum)
        _graceful_shutdown()
        try:
            import os
            os._exit(0)
        except Exception:
            raise SystemExit(0)

    try:
        signal.signal(signal.SIGINT, _signal_handler)
        signal.signal(signal.SIGTERM, _signal_handler)
    except ValueError:
        log.warning("could not install signal handlers (not on main thread)")

    import atexit
    atexit.register(_graceful_shutdown)

    log.info("Kira ready — hotkey %s", cfg.hotkey.combo)
    menubar.run()


if __name__ == "__main__":
    run()
