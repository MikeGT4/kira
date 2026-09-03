"""Polish raw transcribed text via local Ollama with mode-specific prompts."""
from __future__ import annotations
import asyncio
import logging
import os
import re
from pathlib import Path
import ollama
from kira.config import Config

log = logging.getLogger(__name__)

_THINKING_MODEL_RE = re.compile(r"qwen3|gemma[-_ ]?[4-9]", re.IGNORECASE)


def _thinking_kwargs(model: str) -> dict:
    """Extra ``ollama.chat`` kwargs suppressing hybrid-reasoning output."""
    return {"think": False} if _THINKING_MODEL_RE.search(model) else {}


def _prompt_dir() -> Path:
    """Locate the prompts/ dir in both dev and py2app contexts."""
    rp = os.environ.get("RESOURCEPATH")
    if rp:
        bundled = Path(rp) / "prompts"
        if bundled.exists():
            return bundled
    return Path(__file__).parent.parent / "prompts"


PROMPT_DIR = _prompt_dir()
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
        """Force the polish model into memory before the first hotkey press."""
        model = self._config.styler.model
        try:
            await asyncio.wait_for(
                self._client.chat(
                    model=model,
                    messages=[{"role": "user", "content": "hi"}],
                    options={"num_predict": 1},
                    keep_alive=self._config.styler.keep_alive,
                    **_thinking_kwargs(model),
                ),
                timeout=self._config.styler.warmup_timeout_seconds,
            )
            log.info("Styler warmup complete (model=%s)", model)
        except asyncio.TimeoutError:
            log.warning(
                "Styler warmup timed out after %.0fs (model=%s). First "
                "dictation may fall back to raw text.",
                self._config.styler.warmup_timeout_seconds,
                model,
            )
        except Exception as exc:
            log.warning("Styler warmup failed (%s: %s)", type(exc).__name__, exc)

    async def polish(self, text: str, mode: str) -> str:
        if not text.strip():
            return text
        model = self._config.styler.model
        try:
            prompt = load_prompt(mode).format(text=text)
            response = await asyncio.wait_for(
                self._client.chat(
                    model=model,
                    messages=[{"role": "user", "content": prompt}],
                    options={"temperature": 0.2},
                    keep_alive=self._config.styler.keep_alive,
                    **_thinking_kwargs(model),
                ),
                timeout=self._config.styler.timeout_seconds,
            )
            return response["message"]["content"].strip()
        except Exception as exc:
            log.warning("Styler failed (%s). Fallback to raw.", exc)
            if self._config.styler.fallback_to_raw:
                return text
            raise
