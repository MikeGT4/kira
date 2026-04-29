"""faster-whisper CUDA wrapper. Windows port of mlx-whisper.

Loads model lazily on first transcribe call. Returns same
TranscriptionResult dataclass as the Mac transcriber so app.py
doesn't care which backend is active.
"""
from __future__ import annotations
import logging
import os
import sys
import threading
from dataclasses import dataclass
from pathlib import Path

_DLL_HANDLES: list = []  # keep os.add_dll_directory() cookies alive for process lifetime

if sys.platform == "win32":
    # faster-whisper depends on cuBLAS + cuDNN; we ship them via pip wheels
    # (nvidia-cublas-cu12, nvidia-cudnn-cu12) but their DLLs live in
    # site-packages/nvidia/{cublas,cudnn}/bin, which is NOT on the default
    # DLL search path. CTranslate2 uses LoadLibrary at runtime for cuBLAS,
    # so os.add_dll_directory alone isn't enough — we also prepend PATH.
    import site
    _dll_dirs = []
    for _sp in site.getsitepackages():
        _nvidia_base = os.path.join(_sp, "nvidia")
        if os.path.isdir(_nvidia_base):
            for _subdir in ("cublas", "cudnn"):
                _dll_dir = os.path.join(_nvidia_base, _subdir, "bin")
                if os.path.isdir(_dll_dir):
                    _dll_dirs.append(_dll_dir)
                    _DLL_HANDLES.append(os.add_dll_directory(_dll_dir))
    if _dll_dirs:
        os.environ["PATH"] = os.pathsep.join(_dll_dirs) + os.pathsep + os.environ.get("PATH", "")

import numpy as np
from faster_whisper import WhisperModel
from kira.config import Config

log = logging.getLogger(__name__)


@dataclass
class TranscriptionResult:
    text: str
    language: str


_MLX_PREFIX = "mlx-community/whisper-"

# Common Whisper YouTube/subtitle boilerplate hallucinations.
# Whisper's training corpus is heavy on dubbed/subtitled video; when a
# segment falls below the speech-confidence threshold or hits the
# compression-ratio rejection, the high-temperature decoder fallback
# tends to land on these training-set means. We pin temperature=0.0
# below to suppress the sweep, but exact-match safety net stays —
# segments that still slip through (silence-burst, very repetitive
# utterances, codec artifacts) get filtered here.
# Match is exact, lowercased, trimmed; "Vielen Dank für deine Hilfe"
# is longer than every entry and passes through unchanged.
_KNOWN_HALLUCINATIONS = frozenset({
    "vielen dank.",
    "vielen dank",
    "vielen dank fürs zuschauen.",
    "vielen dank für die aufmerksamkeit.",
    "vielen dank für ihr interesse.",
    "vielen dank für eure aufmerksamkeit.",
    "tschüss.",
    "tschüss",
    "danke.",
    "danke",
    "thank you.",
    "thank you",
    "thanks for watching.",
    "thanks for watching",
    "untertitel im auftrag des zdf.",
    "untertitel im auftrag des zdf für funk, 2017",
    "untertitel der amara.org-community",
    "untertitelung aufgrund der amara.org-community",
    "untertitelung des zdf, 2020",
    "untertitel von stephanie geiges",
    "© zdf 2024",
    "subtitles by the amara.org community",
})


def _is_hallucination(text: str) -> bool:
    """True if the entire transcription is a known Whisper boilerplate.

    Exact match (case-insensitive, trimmed) against _KNOWN_HALLUCINATIONS.
    Substring matching would false-positive legitimate dictation that
    happens to contain "Vielen Dank" — exact match is conservative.
    """
    if not text:
        return False
    return text.strip().lower() in _KNOWN_HALLUCINATIONS


def _translate_model_name(name: str) -> str:
    """Translate a Mac MLX model name to its faster-whisper equivalent.

    faster-whisper loads CTranslate2 models, not MLX; the Mac default
    ``mlx-community/whisper-large-v3-turbo`` must become ``large-v3-turbo``.
    """
    if name.startswith(_MLX_PREFIX):
        return name[len(_MLX_PREFIX):]
    return name


class Transcriber:
    """Wraps faster-whisper. Model is lazily loaded on first call."""

    def __init__(self, config: Config):
        self._config = config
        original = config.whisper.model
        self._model_name = _translate_model_name(original)
        if self._model_name != original:
            log.info("Translated MLX model %s -> %s for faster-whisper", original, self._model_name)
        self._model: WhisperModel | None = None
        self._model_lock = threading.Lock()

    def _ensure_model(self) -> WhisperModel:
        with self._model_lock:
            if self._model is None:
                log.info("Loading faster-whisper model %s on CUDA", self._model_name)
                self._model = WhisperModel(
                    self._model_name,
                    device="cuda",
                    compute_type="float16",
                    download_root=str(Path.home() / ".cache" / "faster-whisper"),
                )
            return self._model

    def transcribe(self, audio: np.ndarray) -> TranscriptionResult:
        if audio.size == 0:
            return TranscriptionResult(text="", language="")
        if audio.dtype != np.float32:
            audio = audio.astype(np.float32)
        model = self._ensure_model()
        wcfg = self._config.whisper
        lang = wcfg.language
        try:
            # beam_size=1: PTT snippets are short — beam past 1 buys ≤0.5 %
            # WER for ~5× GPU time.
            # vad_filter=False: Silero VAD removed the entire audio buffer
            # on Mike's setup even at threshold=0.15 (see log 2026-04-27
            # 14:53, "removed 00:02.700 of 00:02.700"), starving Whisper.
            # F8-hold IS the speech window — manual start/stop makes Silero
            # redundant in the PTT path.
            # no_speech_threshold 0.6 → 0.9 + compression_ratio_threshold
            # 2.4 → 1.8: replace VAD as the hallucination defense. The
            # first drops segments where Whisper estimates no speech is
            # present instead of letting it guess "Vielen Dank." style
            # boilerplate; the second rejects repetitive outputs like
            # "Untertitel im Auftrag des ZDF". Both default conservatively
            # for batch transcription, we want them aggressive for short
            # PTT clips.
            segments, info = model.transcribe(
                audio,
                language=None if lang == "auto" else lang,
                beam_size=1,
                vad_filter=False,
                condition_on_previous_text=wcfg.condition_on_previous_text,
                initial_prompt=wcfg.initial_prompt,
                no_speech_threshold=0.9,
                # 1.8 was rejecting legitimately repetitive PTT speech
                # ("ja ja ja ja", "test test test test", etc.) on Mike's
                # 2026-04-28 evening test, which then triggered Whisper's
                # temperature-fallback sweep into hallucinated boilerplate
                # ("Vielen Dank."). 2.0 is loose enough for natural repeats
                # while still rejecting genuine repetition-collapse output.
                compression_ratio_threshold=2.0,
                # Single-value temperature (NOT the default
                # [0.0, 0.2, 0.4, 0.6, 0.8, 1.0] sweep). When a segment
                # hits compression_ratio or no_speech rejection, the sweep
                # would re-decode at higher temperatures and consistently
                # land on the most common training-set boilerplate
                # ("Vielen Dank.", "Untertitel im Auftrag des ZDF").
                # Pinning to 0.0 keeps decoding deterministic and removes
                # the hallucination retry path entirely.
                temperature=0.0,
            )
            # Materialise the segment generator once so we can both log
            # per-segment confidence AND join the text. faster-whisper's
            # generator is single-pass.
            seg_list = list(segments)
            if seg_list:
                # getattr defaults so test stubs without these fields don't
                # crash the pipeline — only real faster-whisper Segment
                # objects carry no_speech_prob / avg_logprob.
                stats = " ".join(
                    f"[no_speech={getattr(s, 'no_speech_prob', 0.0):.2f} "
                    f"avg_logp={getattr(s, 'avg_logprob', 0.0):.2f}]"
                    for s in seg_list
                )
                log.info(
                    "Whisper %d segment(s): %s",
                    len(seg_list), stats,
                )
            else:
                log.info("Whisper produced 0 segments (silence?)")
            text = " ".join(s.text.strip() for s in seg_list).strip()
            if _is_hallucination(text):
                # Safety net for hallucinations that slip through despite
                # temperature=0.0 (cold-start codec artifacts, very brief
                # silence-bursts during PTT). Returning empty makes app.py
                # abort the pipeline before polish/inject — the user gets
                # no output rather than a YouTube-outro injected at the cursor.
                log.warning(
                    "Whisper hallucination filter caught %r — pipeline "
                    "will abort before polish",
                    text,
                )
                return TranscriptionResult(text="", language=info.language)
            return TranscriptionResult(text=text, language=info.language)
        except Exception as exc:
            log.exception("faster-whisper transcription failed: %s", exc)
            raise
