"""Orchestrator: state machine, wiring modules together."""
from __future__ import annotations
import asyncio
import logging
import time
from enum import Enum, auto
from typing import Callable
import numpy as np
from kira.config import Config
from kira.recorder import Recorder
from kira.transcriber import TranscriptionResult
from kira.context import detect_mode
from kira.edit_command import ClipboardUnavailable, read_selection

log = logging.getLogger(__name__)


class State(Enum):
    IDLE = auto()
    RECORDING = auto()
    EDITING = auto()
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
        self._edit_mode = False
        self._captured_selection: str | None = None

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
        self._recorder.start()
        self._set_state(State.RECORDING)

    def on_edit_detected(self) -> None:
        if self._state != State.RECORDING or self._edit_mode:
            return
        try:
            selection = read_selection()
        except ClipboardUnavailable as exc:
            log.warning("edit hotkey: pasteboard unavailable (%s), staying in dictation mode", exc)
            return
        if not selection:
            log.info("edit hotkey: nothing selected, staying in dictation mode")
            return
        self._edit_mode = True
        self._captured_selection = selection
        self._set_state(State.EDITING)

    def on_hotkey_release(self, duration_ms: int | None = None) -> None:
        if self._state not in (State.RECORDING, State.EDITING):
            return
        if duration_ms is None and self._press_time is not None:
            duration_ms = int((time.monotonic() - self._press_time) * 1000)
        self._press_time = None
        audio = self._recorder.stop()
        if (duration_ms or 0) < self._config.hotkey.min_duration_ms:
            self._edit_mode = False
            self._captured_selection = None
            self._set_state(State.IDLE)
            return
        if self._loop is None:
            log.warning("no event loop set — running pipeline synchronously via new loop")
            asyncio.run(self._run_pipeline(audio))
            return
        asyncio.run_coroutine_threadsafe(self._run_pipeline(audio), self._loop)

    async def _run_pipeline(self, audio: np.ndarray) -> None:
        edit_mode = self._edit_mode
        selection = self._captured_selection
        try:
            self._set_state(State.TRANSCRIBING)
            transcription = self._transcriber.transcribe(audio)
            if not transcription.text:
                self._set_state(State.IDLE)
                return
            self._set_state(State.STYLING)
            if edit_mode and selection:
                polished = await self._styler.edit_command(selection, transcription.text)
                log.info("Edit out (sel=%d chars, cmd=%r, out=%d chars)", len(selection), transcription.text[:60], len(polished))
            else:
                mode = detect_mode(self._config)
                polished = await self._styler.polish(transcription.text, mode=mode)
            if not polished:
                log.warning("polish returned empty, nothing injected")
                return
            self._set_state(State.INJECTING)
            self._injector.inject(polished)
        except Exception:
            log.exception("pipeline failed")
            self._set_state(State.ERROR)
        finally:
            self._edit_mode = False
            self._captured_selection = None
            self._set_state(State.IDLE)


class _StubTranscriber:
    def transcribe(self, audio):
        return TranscriptionResult(text="stub", language="de")


class _StubStyler:
    def __init__(self, cfg): self.cfg = cfg
    async def polish(self, text, mode): return text
    async def edit_command(self, selection, command): return f"{selection}+{command}"


class _StubInjector:
    def __init__(self): self.last = None
    def inject(self, text): self.last = text
