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

    async def polish(self, text: str, mode: str) -> str:
        if not text.strip():
            return text
        prompt = load_prompt(mode).format(text=text)
        try:
            response = await asyncio.wait_for(
                self._client.chat(
                    model=self._config.styler.model,
                    messages=[{"role": "user", "content": prompt}],
                    options={"temperature": 0.2},
                ),
                timeout=self._config.styler.timeout_seconds,
            )
            return response["message"]["content"].strip()
        except Exception as exc:
            log.warning("Styler failed (%s). Fallback to raw.", exc)
            if self._config.styler.fallback_to_raw:
                return text
            raise
