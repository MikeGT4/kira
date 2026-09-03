"""Audio capture via sounddevice. Start/stop controlled by caller."""
from __future__ import annotations
import atexit
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

    def __init__(self, input_device: str | None = None) -> None:
        self._input_device = input_device
        self._lock = threading.Lock()
        self._buffer: list[np.ndarray] = []
        self._stream: sd.InputStream | None = None
        self._on_level: Callable[[float], None] | None = None
        self._on_samples: Callable[[np.ndarray], None] | None = None
        self._closed = False
        atexit.register(self._shutdown)

    def set_level_callback(self, cb: Callable[[float], None] | None) -> None:
        """Register a callback invoked with RMS level (float) for each audio block."""
        self._on_level = cb

    def set_samples_callback(self, cb: Callable[[np.ndarray], None] | None) -> None:
        """Register a callback invoked with the raw mono audio block for each frame."""
        self._on_samples = cb

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
        if self._on_samples is not None:
            try:
                mono = indata[:, 0] if indata.ndim > 1 else indata
                self._on_samples(mono.copy())
            except Exception:
                log.exception("samples callback raised")

    def _resolve_device(self) -> int | None:
        spec = (self._input_device or "").strip().lower()
        if not spec:
            return None
        try:
            devices = sd.query_devices()
        except Exception as exc:
            log.warning("query_devices failed (%s), using the default input", exc)
            return None
        for index, dev in enumerate(devices):
            if dev.get("max_input_channels", 0) > 0 and spec in str(dev.get("name", "")).lower():
                log.info("Recorder pinned to input %d (%s)", index, dev.get("name"))
                return index
        log.warning("input device %r not found, using the default input", self._input_device)
        return None

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
            blocksize=1600,
            device=self._resolve_device(),
        )
        self._stream.start()

    def stop(self) -> np.ndarray:
        """Stop recording and return mono float32 audio array."""
        if self._stream is None:
            return np.zeros(0, dtype=np.float32)
        stream, self._stream = self._stream, None
        try:
            stream.stop()
        except Exception:
            log.exception("stream.stop() raised")
        try:
            stream.close()
        except Exception:
            log.exception("stream.close() raised")
        with self._lock:
            if not self._buffer:
                return np.zeros(0, dtype=np.float32)
            audio = np.concatenate(self._buffer, axis=0).reshape(-1)
        return audio.astype(np.float32)

    def _shutdown(self) -> None:
        """atexit/signal handler: abort PortAudio before Python teardown."""
        if self._closed:
            return
        self._closed = True
        stream, self._stream = self._stream, None
        if stream is None:
            return
        try:
            stream.abort()
        except Exception:
            pass
        try:
            stream.close()
        except Exception:
            pass

    @property
    def is_recording(self) -> bool:
        return self._stream is not None
