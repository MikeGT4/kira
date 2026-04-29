"""Audio capture via sounddevice. Start/stop controlled by caller."""
from __future__ import annotations
import logging
import threading
from typing import Callable
import numpy as np
import sounddevice as sd

log = logging.getLogger(__name__)

SAMPLE_RATE = 16000
CHANNELS = 1
DTYPE = "float32"


class Recorder:
    """Non-blocking audio recorder writing to an in-memory buffer."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._buffer: list[np.ndarray] = []
        self._stream: sd.InputStream | None = None
        self._on_level: Callable[[float], None] | None = None

    def set_level_callback(self, cb: Callable[[float], None] | None) -> None:
        """Register a callback invoked with RMS level (float) for each audio block."""
        self._on_level = cb

    def _callback(self, indata: np.ndarray, frames: int, time_info, status) -> None:
        if status:
            log.debug("sounddevice status: %s", status)
        with self._lock:
            self._buffer.append(indata.copy())
        if self._on_level is not None:
            try:
                rms = float(np.sqrt((indata ** 2).mean()))
                self._on_level(rms)
            except Exception:
                log.exception("level callback raised")

    def start(self) -> None:
        if self._stream is not None:
            return
        with self._lock:
            self._buffer.clear()
        self._stream = sd.InputStream(
            samplerate=SAMPLE_RATE,
            channels=CHANNELS,
            dtype=DTYPE,
            callback=self._callback,
            blocksize=1600,  # 100 ms
        )
        self._stream.start()

    def stop(self) -> np.ndarray:
        """Stop recording and return mono float32 audio array."""
        if self._stream is None:
            return np.zeros(0, dtype=np.float32)
        self._stream.stop()
        self._stream.close()
        self._stream = None
        with self._lock:
            if not self._buffer:
                return np.zeros(0, dtype=np.float32)
            audio = np.concatenate(self._buffer, axis=0).reshape(-1)
        return audio.astype(np.float32)

    @property
    def is_recording(self) -> bool:
        return self._stream is not None
