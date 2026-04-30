"""Audio capture via sounddevice with pre-roll ring buffer.

The stream is opened eagerly via prewarm() and stays running across
recordings — that lets us keep a small pre-roll ring buffer of the
last ~250 ms of audio. When start() fires the pre-roll is spliced onto
the front of the recording so the first word survives even when the
user speaks faster than the F8 event reaches the listener (typical gap:
50-200 ms hotkey-hook latency + sounddevice stream-open).

main.py calls prewarm() right after construction so even the first F8
sees a running stream — without that, the first 50-200 ms of the very
first recording were lost while sd.InputStream() initialised. Tests
construct Recorder() without prewarm() so they don't need real audio
hardware; start() falls back to lazy-open in that path.
"""
from __future__ import annotations
import logging
import os
import threading
import wave
from collections import deque
from pathlib import Path
from typing import Callable
import numpy as np
import sounddevice as sd

log = logging.getLogger(__name__)

SAMPLE_RATE = 16000
CHANNELS = 1
DTYPE = "float32"
PREROLL_MS = 250
PREROLL_SAMPLES = SAMPLE_RATE * PREROLL_MS // 1000  # 4000 samples

# Always log per-recording peak/rms; opt-in WAV dump via env var.
# Set KIRA_AUDIO_DUMP=1 to keep the last recording at
# %LOCALAPPDATA%\Kira\last_recording.wav for offline inspection.
# Useful when "kommt nichts an" — the WAV reveals whether the mic is
# delivering signal at all, or if Whisper is the failing layer.
_AUDIO_DUMP_ENABLED = os.environ.get("KIRA_AUDIO_DUMP", "1") == "1"


def _dump_wav(audio: np.ndarray) -> Path | None:
    if not _AUDIO_DUMP_ENABLED or audio.size == 0:
        return None
    base = os.environ.get("LOCALAPPDATA")
    if base is None:
        return None
    out_dir = Path(base) / "Kira"
    try:
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / "last_recording.wav"
        int16 = (audio * 32767).clip(-32768, 32767).astype(np.int16)
        with wave.open(str(out_path), "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(SAMPLE_RATE)
            wf.writeframes(int16.tobytes())
        return out_path
    except Exception:
        log.exception("WAV dump failed")
        return None


class DeviceUnavailable(RuntimeError):
    """Configured input device couldn't be resolved at record time.

    Raised by Recorder.start() when the configured device spec doesn't
    match any currently-available sounddevice device. Caller should
    catch this and surface it via the State.ERROR path; subsequent
    start() calls will try again (the user may have plugged the mic
    back in or toggled its hardware switch).
    """


class Recorder:
    """Non-blocking audio recorder with a pre-roll ring buffer."""

    def __init__(
        self,
        input_gain: float = 1.0,
        input_device: int | str | None = None,
    ) -> None:
        self._lock = threading.Lock()
        self._buffer: list[np.ndarray] = []
        self._preroll: deque[np.ndarray] = deque()
        self._preroll_samples = 0
        self._stream: sd.InputStream | None = None
        self._recording = False
        self._on_level: Callable[[float], None] | None = None
        self._input_gain = float(input_gain)
        # Spec wird gespeichert, nicht resolved — das passiert in prewarm()
        # und (falls dort gescheitert) erneut in start(). Konstruktor ist
        # damit auch dann sicher, wenn das Mikro beim Boot noch nicht
        # enumeriert ist (USB-Audio braucht oft Sekunden nach Resume).
        self._device_spec = input_device
        self._input_device: int | None = None

    def _resolve_device(self) -> int | None:
        """Resolve self._device_spec against sd.query_devices().

        Returns None if no match (was: raised ValueError). Callers must
        treat None as 'device not currently available' and decide what
        to do — prewarm() defers, start() raises DeviceUnavailable.

        Logs available input devices on a miss so kira.log shows what
        PortAudio sees right now.
        """
        spec = self._device_spec
        if spec is None:
            return None
        if isinstance(spec, int):
            log.info("Recorder pinned to device id=%d", spec)
            return spec
        for i, d in enumerate(sd.query_devices()):
            if d["max_input_channels"] > 0 and spec.lower() in d["name"].lower():
                log.info(
                    "Recorder pinned to device id=%d (%r matched %r)",
                    i, spec, d["name"],
                )
                return i
        available = [
            f"{i}:{d['name']}"
            for i, d in enumerate(sd.query_devices())
            if d["max_input_channels"] > 0
        ]
        log.warning(
            "audio.input_device=%r matched no input device. Available: %s",
            spec, available,
        )
        return None

    def set_level_callback(self, cb: Callable[[float], None] | None) -> None:
        """Register a callback invoked with RMS level (float) for each audio block."""
        self._on_level = cb

    def _callback(self, indata: np.ndarray, frames: int, time_info, status) -> None:
        if status:
            log.debug("sounddevice status: %s", status)
        if self._input_gain != 1.0:
            audio = np.clip(indata * self._input_gain, -1.0, 1.0).astype(np.float32)
        else:
            audio = indata.copy()

        with self._lock:
            if self._recording:
                self._buffer.append(audio)
            else:
                # Ring buffer of the most recent PREROLL_SAMPLES so the next
                # start() can prepend audio that arrived before the F8 event
                # reached us.
                self._preroll.append(audio)
                self._preroll_samples += len(audio)
                while self._preroll_samples > PREROLL_SAMPLES and self._preroll:
                    dropped = self._preroll.popleft()
                    self._preroll_samples -= len(dropped)

        if self._on_level is not None:
            try:
                rms = float(np.sqrt((audio ** 2).mean()))
                self._on_level(rms)
            except Exception:
                log.exception("level callback raised")

    def prewarm(self) -> None:
        """Open the input stream eagerly so the pre-roll buffer fills
        immediately. Call once after construction, before the first F8.

        Without this the first start() opens the stream lazily, and the
        50-200 ms it takes sounddevice to initialise are lost from the
        recording — even with the pre-roll buffer, because the buffer
        was empty too (the stream wasn't running yet to fill it).
        """
        with self._lock:
            if self._stream is not None:
                return
            stream = sd.InputStream(
                samplerate=SAMPLE_RATE,
                channels=CHANNELS,
                dtype=DTYPE,
                callback=self._callback,
                blocksize=1600,  # 100 ms
                device=self._input_device,
            )
            self._stream = stream
        stream.start()

    def start(self) -> None:
        with self._lock:
            self._buffer = list(self._preroll)
            self._preroll.clear()
            self._preroll_samples = 0
            self._recording = True
        # Lazy fallback for paths that didn't call prewarm() (mostly tests).
        # In main.py prewarm() runs at startup so this branch is a no-op there.
        if self._stream is None:
            self.prewarm()

    def stop(self) -> np.ndarray:
        """Stop recording and return mono float32 audio array.

        The stream stays open so the pre-roll buffer continues to fill
        for the next press. Use close() at app shutdown to release it.
        """
        with self._lock:
            self._recording = False
            if not self._buffer:
                log.warning("Recorder.stop: empty buffer (no audio captured)")
                return np.zeros(0, dtype=np.float32)
            audio = np.concatenate(self._buffer, axis=0).reshape(-1).astype(np.float32)
            self._buffer.clear()
        # Always log peak/rms — without this, "kommt nichts an" debugging
        # has no upstream signal: Whisper sees garbage, but we can't tell
        # whether the mic delivered silence or actual speech.
        peak = float(np.max(np.abs(audio))) if audio.size else 0.0
        rms = float(np.sqrt(np.mean(audio ** 2))) if audio.size else 0.0
        wav_path = _dump_wav(audio)
        log.info(
            "Recorder.stop: samples=%d duration=%.2fs peak=%.4f rms=%.4f gain=%.1f%s",
            audio.size, audio.size / SAMPLE_RATE, peak, rms, self._input_gain,
            f" wav={wav_path}" if wav_path else "",
        )
        return audio

    def close(self) -> None:
        """Close the underlying stream — call once at app shutdown.

        Take the stream reference under lock and clear the slot before
        calling stop()/close() so a callback that's mid-flight on the
        sounddevice thread can't race with us tearing the stream down.
        """
        with self._lock:
            stream = self._stream
            self._stream = None
        if stream is not None:
            try:
                stream.stop()
                stream.close()
            except Exception:
                log.exception("error closing input stream")

    @property
    def is_recording(self) -> bool:
        return self._recording
