"""mlx-whisper wrapper — loads model once, transcribes numpy audio."""
from __future__ import annotations
import logging
from dataclasses import dataclass
import numpy as np
import mlx_whisper
from kira.config import Config

log = logging.getLogger(__name__)


@dataclass
class TranscriptionResult:
    text: str
    language: str


class Transcriber:
    """Wraps mlx_whisper.transcribe. Model is lazily loaded on first call."""

    def __init__(self, config: Config):
        self._config = config
        self._model = config.whisper.model

    def transcribe(self, audio: np.ndarray) -> TranscriptionResult:
        if audio.size == 0:
            return TranscriptionResult(text="", language="")
        if audio.dtype != np.float32:
            audio = audio.astype(np.float32)
        kwargs: dict = {"path_or_hf_repo": self._model}
        lang = self._config.whisper.language
        if lang != "auto":
            kwargs["language"] = lang
        try:
            result = mlx_whisper.transcribe(audio, **kwargs)
            return TranscriptionResult(
                text=str(result.get("text", "")).strip(),
                language=str(result.get("language", "")),
            )
        except Exception as exc:
            log.exception("Whisper transcription failed: %s", exc)
            raise
