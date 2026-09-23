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
from kira.recorder import Recorder, DeviceUnavailable, SAMPLE_RATE

if sys.platform == "win32":
    from kira.transcriber_fw import TranscriptionResult
    from kira.context_win import detect_mode
    from kira.edit_command import ClipboardUnavailable, read_selection
else:
    from kira.transcriber import TranscriptionResult
    from kira.context import detect_mode

    class ClipboardUnavailable(RuntimeError):  # type: ignore[no-redef]
        pass

    def read_selection() -> str | None:  # type: ignore[misc]
        """Mac stub — Edit-Command-Hotkey wird auf Mac aktuell nicht
        wired (Mac-Branch nutzt Fn-Key für Standard-Polish, F9-Doppel-
        binding wäre ungewollt). Kein-op damit der Import nicht
        kracht."""
        return None

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
        learning=None,
    ) -> None:
        self._config = config
        self._recorder = recorder
        self._transcriber = transcriber
        self._styler = styler
        self._injector = injector
        self._on_state_change = on_state_change
        # Lernschleife (v0.4.0, nur Windows verdrahtet): Glossar je Diktat und
        # Verlaufseintrag nach dem Einfügen. None = aus.
        self._learning = learning
        self._state = State.IDLE
        self._press_time: float | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        # Edit-Command-Pfad (F9): wird bei on_edit_press gesetzt und
        # in _run_pipeline ausgewertet. Reset im Pipeline finally-Block
        # plus im Short-Press-Pfad in on_hotkey_release.
        self._edit_mode: bool = False
        self._captured_selection: str | None = None
        # Für die Aufnahme-Anzeige (v0.4.1): letzter Whisper-Text, letzter
        # polierter Text und Grund des letzten Fehlers („Zeile 1|Zeile 2“).
        # Jeweils gesetzt, BEVOR der passende Zustand gemeldet wird, damit der
        # Zustands-Handler sie im selben Aufruf lesen kann.
        self.last_transcript: str = ""
        self.last_polished: str = ""
        self.last_error: str = ""

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
        self.last_transcript = ""
        self.last_polished = ""
        self.last_error = ""
        try:
            self._recorder.start()
        except DeviceUnavailable as e:
            log.warning("Hotkey press but input device unavailable: %s", e)
            self._press_time = None
            self.last_error = "Mikrofon nicht gefunden.|Gerät prüfen, dann erneut drücken."
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

    def on_edit_press(self) -> None:
        """F9 hold: Selection erfassen, dann recordet Voice-Command.

        State-Check VOR read_selection (silent-failure-hunt 2026-05-09):
        sonst macht ein zweites F9 während STYLING/INJECTING noch den
        teuren 100-ms-Strg+C-Roundtrip + setzt _edit_mode/_captured_
        selection auf neue Werte, die das finally der laufenden Pipeline
        zwar wegräumt aber Race-anfällig macht.
        """
        if self._state != State.IDLE:
            return
        try:
            selection = read_selection()
        except ClipboardUnavailable as exc:
            # Clipboard-Fehler ist NICHT "keine Selection" — User soll
            # ein sichtbares Fehler-Signal kriegen, sonst weiss er nicht
            # dass F9 was gemacht hat.
            log.warning("Edit hotkey aborted (clipboard unavailable): %s", exc)
            self._flash_error_briefly("Zwischenablage nicht erreichbar.|Gleich noch einmal versuchen.")
            return
        if selection is None:
            # Echte "keine Selection" - User-Feedback via kurzer ERROR-
            # Flash, sonst sieht der User keinen Unterschied zwischen
            # "F9 nicht gebunden" und "ich hatte nichts markiert".
            log.info("Edit hotkey pressed without selection — flashing ERROR")
            self._flash_error_briefly("Nichts markiert.|Erst Text markieren, dann erneut.")
            return
        self._captured_selection = selection
        self._edit_mode = True
        self.on_hotkey_press()
        # Falls on_hotkey_press aus DeviceUnavailable o.ä. nicht in
        # RECORDING gewechselt ist, Flags zurücknehmen damit der nächste
        # F8 nicht versehentlich als Edit interpretiert wird.
        if self._state != State.RECORDING:
            self._edit_mode = False
            self._captured_selection = None

    def _flash_error_briefly(self, reason: str = "") -> None:
        """1.5 s ERROR-State (gelbes Tray-Icon) → IDLE. Dient als
        sichtbares 'Hotkey kam an, aber konnte nicht ausgefuehrt werden'-
        Signal für F9-no-selection und Clipboard-Fehler."""
        if self._state != State.IDLE:
            return
        self.last_error = reason
        self._set_state(State.ERROR)
        threading.Timer(
            1.5, lambda: self._set_state(State.IDLE)
            if self._state == State.ERROR else None
        ).start()

    def on_hotkey_release(self, duration_ms: int | None = None) -> None:
        if self._state != State.RECORDING:
            return
        if duration_ms is None and self._press_time is not None:
            duration_ms = int((time.monotonic() - self._press_time) * 1000)
        self._press_time = None
        audio = self._recorder.stop()
        if (duration_ms or 0) < self._config.hotkey.min_duration_ms:
            # Short-press path: pipeline laeuft nicht → finally-Reset
            # greift nicht → wir muessen die Edit-Flags hier explizit
            # zuruecksetzen, sonst pollutieren sie den naechsten Cycle.
            self._edit_mode = False
            self._captured_selection = None
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
        # Snapshot des Edit-States BEFORE finally clears them — sodass
        # ein paralleles on_edit_press während Pipeline-Laufzeit nicht
        # das Verhalten der laufenden Pipeline ändert.
        edit_mode = self._edit_mode
        captured_selection = self._captured_selection
        mode: str | None = None
        try:
            self._set_state(State.TRANSCRIBING)
            # asyncio.to_thread: Whisper-transcribe ist CPU/GPU-bound +
            # 5-10 s Modell-Cold-Start auf erstem Call. Synchron im
            # async-Loop wuerde die Tray-State-Updates + Hotkey-Polling
            # für die ganze Zeit einfrieren. to_thread laesst den Loop
            # weiterlaufen, der Worker-Thread bekommt die Last.
            transcription = await asyncio.to_thread(
                self._transcriber.transcribe, audio
            )
            log.info(
                "Whisper out (%d chars, lang=%s): %r",
                len(transcription.text), transcription.language,
                transcription.text[:80],
            )
            if not transcription.text:
                log.warning("Whisper returned empty text — pipeline aborted before polish")
                self._set_state(State.IDLE)
                return
            self.last_transcript = transcription.text
            self._set_state(State.STYLING)
            if edit_mode and captured_selection:
                # F9-Pfad: Voice-Command + erfasste Selektion → LLM rewriteset
                # die Selektion. Output landet im Inject, wo Strg+V die noch
                # aktive Selektion in der Ziel-App ersetzt.
                polished = await self._styler.edit_command(
                    selection=captured_selection,
                    command=transcription.text,
                )
                log.info(
                    "Edit-command out (sel=%d chars, cmd=%r, out=%d chars): %r",
                    len(captured_selection), transcription.text[:60],
                    len(polished), polished[:80],
                )
            else:
                mode = detect_mode(self._config)
                glossary = self._glossary_for(transcription.text)
                # Nur mit Begriffen übergeben: Styler-Attrappen und der
                # Mac-Zweig kennen den Parameter nicht (tests/test_state_machine.py).
                extra = {"glossary": glossary} if glossary else {}
                polished = await self._styler.polish(
                    transcription.text, mode=mode, **extra,
                )
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
            self.last_polished = polished
            self._set_state(State.INJECTING)
            self._injector.inject(polished)
            if mode is not None:
                self._record_dictation(mode, transcription, polished, audio)
        except Exception:
            log.exception("pipeline failed")
            self.last_error = "Verarbeitung fehlgeschlagen.|Details im Log."
            self._set_state(State.ERROR)
        finally:
            # Edit-Mode-Flags IMMER resetten — das hier ist der einzige
            # garantierte Endpunkt fuer einen langen Press-Cycle.
            self._edit_mode = False
            self._captured_selection = None
            # Hold ERROR briefly so the tray icon actually shows yellow long
            # enough to notice; otherwise IDLE overwrote it within a frame.
            # Guard im Timer verhindert dass ein parallel-laufender
            # Hotkey-Pfad (oder zukünftiger State-Setter) der State
            # zwischenzeitlich änderte, vom Auto-Reset überschrieben
            # wird — gleiche Logik wie in on_hotkey_press's Auto-Reset.
            if self._state == State.ERROR:
                threading.Timer(
                    3.0, lambda: self._set_state(State.IDLE)
                    if self._state == State.ERROR else None
                ).start()
            else:
                self._set_state(State.IDLE)

    def _glossary_for(self, text: str) -> list[str] | None:
        if self._learning is None:
            return None
        try:
            return self._learning.glossary_for(text) or None
        except Exception:
            log.exception("Lernen: Glossar-Auswahl fehlgeschlagen, Diktat läuft ohne")
            return None

    def _record_dictation(self, mode: str, transcription, text: str, audio: np.ndarray) -> None:
        if self._learning is None:
            return
        try:
            self._learning.after_inject(
                mode=mode, transcription=transcription, text=text,
                duration_s=audio.size / SAMPLE_RATE,
            )
        except Exception:
            log.exception("Lernen: Verlaufseintrag fehlgeschlagen")


class _StubTranscriber:
    def transcribe(self, audio):
        return TranscriptionResult(text="stub", language="de")


class _StubStyler:
    def __init__(self, cfg): self.cfg = cfg
    async def polish(self, text, mode, glossary=None): return text


class _StubInjector:
    def __init__(self): self.last = None
    def inject(self, text): self.last = text
