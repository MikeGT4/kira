"""Polish raw transcribed text via local Ollama with mode-specific prompts."""
from __future__ import annotations
import asyncio
import logging
from pathlib import Path
import ollama
from kira.config import Config

log = logging.getLogger(__name__)

PROMPT_DIR = Path(__file__).parent.parent / "prompts"
VALID_MODES = ("email", "chat", "terminal", "code", "plain")


def load_prompt(mode: str) -> str:
    """Load prompt template for given mode; fall back to 'plain' if missing."""
    candidate = PROMPT_DIR / f"{mode}.md"
    if not candidate.exists():
        candidate = PROMPT_DIR / "plain.md"
    return candidate.read_text(encoding="utf-8")


class Styler:
    """Async Ollama-based text polisher."""

    def __init__(self, config: Config):
        self._config = config
        self._client = ollama.AsyncClient()

    async def warmup(self) -> None:
        """Issue a tiny chat request to force Ollama to load the model now.

        Without this, the very first F8 dictation after app start pays the
        full cold-start cost (cuBLAS init + weight load — typically 1-2 s
        for gemma2:2b, much more for 27B-class models). Combined with
        ``keep_alive`` on the polish path, this keeps the model resident
        from boot to quit.
        """
        model = self._config.styler.model
        keep_alive = self._config.styler.keep_alive
        try:
            await asyncio.wait_for(
                self._client.chat(
                    model=model,
                    messages=[{"role": "user", "content": "ok"}],
                    options={"temperature": 0.0, "num_predict": 1},
                    keep_alive=keep_alive,
                ),
                timeout=60.0,
            )
            log.info(
                "Styler warmup complete (model=%s, keep_alive=%s)",
                model, keep_alive,
            )
        except asyncio.TimeoutError:
            log.warning(
                "Styler warmup timed out after 60 s (model=%s). "
                "Model load takes longer than expected — first dictation "
                "may still be slow. Check `ollama list` for the model.",
                model,
            )
        except Exception as exc:
            log.warning(
                "Styler warmup failed (%s). First dictation will pay the "
                "cold-start cost. Polish still falls back to raw on real "
                "errors, so this is non-fatal.",
                exc,
            )

    async def polish(self, text: str, mode: str) -> str:
        if not text.strip():
            return text
        prompt = load_prompt(mode).format(text=text)
        timeout = self._config.styler.timeout_seconds
        try:
            response = await asyncio.wait_for(
                self._client.chat(
                    model=self._config.styler.model,
                    messages=[{"role": "user", "content": prompt}],
                    options={"temperature": 0.2},
                    keep_alive=self._config.styler.keep_alive,
                ),
                timeout=timeout,
            )
            polished = response["message"]["content"].strip()
            if not polished:
                # gemma3 occasionally returns an empty string (or pure
                # whitespace) when the prompt ends with "Output:" — Ollama
                # treats that as the model's "I'm done" signal. Without this
                # branch the empty string falls all the way through to
                # injector.inject() which silently no-ops, leaving the user
                # with no visible feedback. Treat it like a timeout instead.
                log.warning(
                    "Styler returned empty response (model=%s, raw_chars=%d). "
                    "Falling back to raw transcription.",
                    self._config.styler.model, len(text),
                )
                if self._config.styler.fallback_to_raw:
                    return text
            return polished
        except asyncio.TimeoutError:
            # asyncio.TimeoutError has str(exc) == "" — the original generic
            # except branch logged "Styler failed ()." with empty parens,
            # which during the 2026-04-25 debug session masked exactly this
            # condition for hours. Treat timeout as its own case so the log
            # line names the timeout value and the model.
            log.warning(
                "Styler timed out after %.1fs (model=%s). "
                "First-call cold-start can be ~14s for 27B-class models; "
                "raise styler.timeout_seconds in config.yaml if this keeps "
                "firing. Falling back to raw transcription.",
                timeout, self._config.styler.model,
            )
            if self._config.styler.fallback_to_raw:
                return text
            raise
        except Exception as exc:
            log.warning("Styler failed (%s). Fallback to raw.", exc)
            if self._config.styler.fallback_to_raw:
                return text
            raise
