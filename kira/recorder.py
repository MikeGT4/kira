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
        # Set by _callback when PortAudio reports input_underflow/overflow.
        # USB-Mic-Hot-Unplug shows up as input_underflow on the next callback —
        # we cycle the stream on the next start() so a dead PortAudio handle
        # can't crash the C audio thread on the recording after.
        self._stream_dirty = False

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
        # Single enumeration: query_devices() can block 50-200 ms on
        # Windows when ASIO/WASAPI/MME endpoints are scanned under load.
        # Calling it twice (match-loop + available-list) doubles the worst
        # case; cache the snapshot to keep the Recorder lock short.
        #
        # Defensive try/except: query_devices() itself can throw
        # (PortAudioError, OSError) when the Windows audio service is
        # mid-disconnect — USB hot-plug races with MMNotificationClient,
        # service restart, etc. Treat that as 'not currently available'
        # so the exception doesn't propagate out of prewarm()/start()
        # past on_hotkey_press's DeviceUnavailable-only catch and kill
        # the hotkey thread.
        try:
            devices = list(sd.query_devices())
        except Exception:
            log.exception(
                "sd.query_devices() failed during resolve "
                "(audio service mid-disconnect?); treating as unavailable",
            )
            return None
        for i, d in enumerate(devices):
            if d["max_input_channels"] > 0 and spec.lower() in d["name"].lower():
                log.info(
                    "Recorder pinned to device id=%d (%r matched %r)",
                    i, spec, d["name"],
                )
                return i
        available = [
            f"{i}:{d['name']}"
            for i, d in enumerate(devices)
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
            # USB hot-unplug surfaces as input_underflow on the very next
            # callback. Was DEBUG (silenced at default INFO level) — upgraded
            # to WARNING so post-mortem can correlate "kein Audio mehr" with
            # an actual PortAudio signal.
            log.warning("sounddevice callback status: %s", status)
            # Nur input_underflow flagt den Stream dirty — overflow ist
            # häufig ein transient Spike direkt nach Stream-Start (PortAudio
            # kalibriert Buffer-Größen) und würde sonst beim nächsten F8
            # den Pre-Roll-Buffer wegblasen. Underflow heißt das Device
            # liefert nichts mehr — typisch für Hot-Unplug.
            if status.input_underflow:
                self._stream_dirty = True
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

        Tolerates absent device: if the configured device spec can't be
        resolved against sd.query_devices() right now (e.g. USB headset
        not enumerated yet, hardware mute), prewarm becomes a no-op.
        The next start() will retry the resolution; if it still fails
        there, start() raises DeviceUnavailable for KiraApp to surface
        as State.ERROR.

        Without this the first start() opens the stream lazily, and the
        50-200 ms it takes sounddevice to initialise are lost from the
        recording — even with the pre-roll buffer, because the buffer
        was empty too (the stream wasn't running yet to fill it).
        """
        with self._lock:
            if self._stream is not None:
                return
            if self._input_device is None:
                self._input_device = self._resolve_device()
            # Spec gegeben aber nicht auflösbar → keinen Stream öffnen.
            # Wir fallen bewusst NICHT auf System-Default zurück: der
            # explizite Pin existiert genau um schlechte Whisper-Quality
            # vom Laptop-Mikro stillschweigend zu vermeiden.
            if self._input_device is None and self._device_spec is not None:
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

    def _is_device_still_present(self) -> bool:
        """True wenn das ge-pinnte Device noch in sd.query_devices() steht.

        Wir prüfen den heute gespeicherten _input_device-Index gegen die
        aktuelle PortAudio-Enumeration. Bei USB-Mic-Hot-Unplug schrumpft
        die Liste oder das vorherige Device hat 0 Input-Channels (ASIO
        re-enumeriert manchmal in-place statt Slot freizugeben).

        Wenn kein konkretes Device gepinnt ist (_device_spec=None →
        System-Default), gibt es nichts zu re-prüfen — der Stream wird
        gegen den OS-Default gefahren und PortAudio routet automatisch
        um. In dem Fall ist "device present" trivially True.
        """
        if self._device_spec is None:
            return True
        if self._input_device is None:
            return False
        try:
            devices = list(sd.query_devices())
        except Exception:
            log.warning(
                "sd.query_devices() failed during health-check; "
                "treating pinned device as gone",
            )
            return False
        if self._input_device >= len(devices):
            return False
        return devices[self._input_device].get("max_input_channels", 0) > 0

    def _cycle_stream_if_unhealthy(self) -> bool:
        """Schließe alten Stream wenn dirty/inaktiv/Device weg. Return True wenn cycelt.

        Der Hot-Unplug-Pfad: Mike zieht den ROG Theta ab → der nächste
        sounddevice-Callback kommt mit status.input_underflow → wir setzen
        _stream_dirty. Beim nächsten F8 (start()) cycelt diese Methode
        den toten Stream UND setzt _input_device zurück, sodass prewarm()
        neu resolven kann. Ohne den Cycle hätten wir den native Crash:
        PortAudio's C-Thread feuert weiter Callbacks gegen ein totes
        Device-Handle, irgendwann abort()'d die DLL und pythonw.exe
        verschwindet ohne Python-Trace und ohne faulthandler-Eintrag.
        """
        with self._lock:
            stream = self._stream
            dirty = self._stream_dirty
        if stream is None:
            return False
        try:
            active = bool(stream.active)
        except Exception:
            active = False
        device_present = self._is_device_still_present()
        if not dirty and active and device_present:
            return False
        log.warning(
            "Cycling input stream (dirty=%s active=%s device_present=%s) "
            "— likely mic hot-unplug. Will re-resolve device on next start().",
            dirty, active, device_present,
        )
        self.close()
        self._input_device = None
        self._stream_dirty = False
        return True

    def start(self) -> None:
        """Begin recording. Re-resolves device if not already streaming.

        Raises DeviceUnavailable if the configured device spec still
        doesn't match anything in sd.query_devices(). The exception is
        the App's signal to surface State.ERROR without entering the
        transcription pipeline. Subsequent start() calls retry — useful
        when the user toggled the mic's hardware switch or plugged the
        USB cable back in between F8 presses.

        Pre-Roll-Setup wird ERST NACH erfolgreichem Stream-Check
        committed — sonst wäre _recording=True während des 50-200 ms
        blockierenden query_devices()-Re-Resolve sichtbar, und eine
        Exception aus sd.InputStream(...) (z.B. TOCTOU wenn Device
        zwischen query_devices und InputStream weggeht) würde den
        Recording-Flag dauerhaft auf True kleben lassen.
        """
        # Hot-unplug-Recovery: wenn der existing stream tot/dirty ist
        # (USB-Mic abgesteckt während prewarm()-Stream lief), recyceln
        # bevor wir ein Recording-Flag setzen — sonst ginge der Buffer
        # leer in die Pipeline, oder schlimmer, der nächste C-Callback
        # crasht den Process nativ.
        self._cycle_stream_if_unhealthy()
        if self._stream is None:
            # Re-resolve: vorheriger prewarm()-Versuch hat None geliefert
            # und das in self._input_device festgehalten. Resetten, damit
            # prewarm() die Suche frisch macht (Mikro könnte zwischen
            # zwei F8-Presses eingeschaltet worden sein).
            #
            # prewarm() acquired den Lock selbst — wir rufen es deshalb
            # AUSSERHALB jedes eigenen Lock-Blocks; threading.Lock ist
            # non-reentrant, ein Nested-Acquire würde deadlocken.
            self._input_device = None
            self.prewarm()
            if self._stream is None:
                raise DeviceUnavailable(
                    f"audio.input_device={self._device_spec!r} "
                    f"not available right now"
                )
        with self._lock:
            self._buffer = list(self._preroll)
            self._preroll.clear()
            self._preroll_samples = 0
            self._recording = True

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
