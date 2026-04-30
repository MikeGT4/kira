"""Orchestrator: state machine, wiring modules together.

Platform-aware imports: TranscriptionResult and detect_mode come
from the Mac or Windows peer modules depending on sys.platform.
The rest of the orchestration is platform-agnostic.
"""
from __future__ import annotations
import asyncio
import logging
import sys
import threading
import time
from enum import Enum, auto
from typing import Callable
import numpy as np
from kira.config import Config
from kira.recorder import Recorder, DeviceUnavailable

if sys.platform == "win32":
    from kira.transcriber_fw import TranscriptionResult
    from kira.context_win import detect_mode
else:
    from kira.transcriber import TranscriptionResult
    from kira.context import detect_mode

log = logging.getLogger(__name__)


class State(Enum):
    IDLE = auto()
    RECORDING = auto()
    TRANSCRIBING = auto()
    STYLING = auto()
    INJECTING = auto()
    ERROR = auto()


class KiraApp:
    """Wires hotkey -> recorder -> transcriber -> styler -> injector."""

    def __init__(
        self,
        config: Config,
        recorder: Recorder,
        transcriber,
        styler,
        injector,
        on_state_change: Callable[[State], None] = lambda s: None,
    ) -> None:
        self._config = config
        self._recorder = recorder
        self._transcriber = transcriber
        self._styler = styler
        self._injector = injector
        self._on_state_change = on_state_change
        self._state = State.IDLE
        self._press_time: float | None = None
        self._loop: asyncio.AbstractEventLoop | None = None

    @classmethod
    def for_test(cls) -> "KiraApp":
        """Construct with stub components for unit tests."""
        cfg = Config()
        return cls(
            config=cfg,
            recorder=Recorder(),
            transcriber=_StubTranscriber(),
            styler=_StubStyler(cfg),
            injector=_StubInjector(),
        )

    def set_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    @property
    def state(self) -> State:
        return self._state

    def _set_state(self, s: State) -> None:
        self._state = s
        try:
            self._on_state_change(s)
        except Exception:
            log.exception("state change handler raised")

    def on_hotkey_press(self) -> None:
        if self._state != State.IDLE:
            return
        self._press_time = time.monotonic()
        try:
            self._recorder.start()
        except DeviceUnavailable as e:
            log.warning("Hotkey press but input device unavailable: %s", e)
            self._press_time = None
            self._set_state(State.ERROR)
            # Auto-Reset nach 3 s analog zum Pipeline-Error-Pfad
            # (_run_pipeline finally-Block) — ohne Reset bliebe state
            # auf ERROR und das nächste F8 würde durch
            # `if self._state != State.IDLE: return` ignoriert werden.
            threading.Timer(
                3.0, lambda: self._set_state(State.IDLE)
                if self._state == State.ERROR else None
            ).start()
            return
        self._set_state(State.RECORDING)

    def on_hotkey_release(self, duration_ms: int | None = None) -> None:
        if self._state != State.RECORDING:
            return
        if duration_ms is None and self._press_time is not None:
            duration_ms = int((time.monotonic() - self._press_time) * 1000)
        self._press_time = None
        audio = self._recorder.stop()
        if (duration_ms or 0) < self._config.hotkey.min_duration_ms:
            self._set_state(State.IDLE)
            return
        if self._loop is None:
            log.warning("no event loop set — running pipeline synchronously via new loop")
            asyncio.run(self._run_pipeline(audio))
            return
        if not self._loop.is_running():
            # Loop was stopped (typically during Qt-quit). run_coroutine_threadsafe
            # would silently return a Future that never resolves, leaving the
            # state machine stuck in RECORDING and ignoring the next F8.
            log.warning("event loop not running — pipeline dropped, resetting to IDLE")
            self._set_state(State.IDLE)
            return
        asyncio.run_coroutine_threadsafe(self._run_pipeline(audio), self._loop)

    async def _run_pipeline(self, audio: np.ndarray) -> None:
        try:
            self._set_state(State.TRANSCRIBING)
            transcription = self._transcriber.transcribe(audio)
            log.info(
                "Whisper out (%d chars, lang=%s): %r",
                len(transcription.text), transcription.language,
                transcription.text[:80],
            )
            if not transcription.text:
                log.warning("Whisper returned empty text — pipeline aborted before polish")
                self._set_state(State.IDLE)
                return
            self._set_state(State.STYLING)
            mode = detect_mode(self._config)
            polished = await self._styler.polish(transcription.text, mode=mode)
            log.info(
                "Polish out (mode=%s, %d chars): %r",
                mode, len(polished), polished[:80],
            )
            if not polished:
                # Empty polish (e.g. fallback_to_raw=False with empty model
                # response) used to fall through to inject(""), which is a
                # silent no-op — user gets no feedback. Treat as IDLE recovery.
                log.warning("Polish returned empty — skipping inject")
                return
            self._set_state(State.INJECTING)
            self._injector.inject(polished)
        except Exception:
            log.exception("pipeline failed")
            self._set_state(State.ERROR)
        finally:
            # Hold ERROR briefly so the tray icon actually shows yellow long
            # enough to notice; otherwise IDLE overwrote it within a frame.
            if self._state == State.ERROR:
                threading.Timer(3.0, lambda: self._set_state(State.IDLE)).start()
            else:
                self._set_state(State.IDLE)


class _StubTranscriber:
    def transcribe(self, audio):
        return TranscriptionResult(text="stub", language="de")


class _StubStyler:
    def __init__(self, cfg): self.cfg = cfg
    async def polish(self, text, mode): return text


class _StubInjector:
    def __init__(self): self.last = None
    def inject(self, text): self.last = text
