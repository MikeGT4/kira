"""Polish raw transcribed text via local Ollama with mode-specific prompts."""
from __future__ import annotations
import asyncio
import logging
from pathlib import Path
import ollama
from kira.config import Config, ModeConfig

log = logging.getLogger(__name__)

PROMPT_DIR = Path(__file__).parent.parent / "prompts"
# Modi mit eingebauten prompt-Files. User koennen weitere Modi via eigene
# prompts/<name>.md anlegen — load_prompt faellt auf plain.md zurueck wenn
# eine Datei fehlt, also ist die Liste hier nur Doku, nicht enforced.
VALID_MODES = (
    "email", "chat", "terminal", "code", "plain",
    "clean", "translate_en", "email_formal",
)


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
        # Per-Mode-Override: model + timeout + temperature koennen je
        # Mode in StylerConfig.modes definiert sein. Fehlt der Mode dort
        # oder ist ein Feld None, faellt's auf den globalen StylerConfig
        # zurueck.
        mode_cfg = self._config.styler.modes.get(mode, ModeConfig())
        model = mode_cfg.model or self._config.styler.model
        timeout = mode_cfg.timeout_seconds or self._config.styler.timeout_seconds
        temperature = mode_cfg.temperature
        try:
            response = await asyncio.wait_for(
                self._client.chat(
                    model=model,
                    messages=[{"role": "user", "content": prompt}],
                    options={"temperature": temperature},
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
                    model, len(text),
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
                timeout, model,
            )
            if self._config.styler.fallback_to_raw:
                return text
            raise
        except Exception as exc:
            log.warning("Styler failed (%s). Fallback to raw.", exc)
            if self._config.styler.fallback_to_raw:
                return text
            raise

    async def edit_command(self, selection: str, command: str) -> str:
        """Apply an AI-Editing-Command auf eine Selektion.

        F9-Pfad: User selektiert Text, sagt einen Voice-Command
        ("mach das formeller", "uebersetz auf Englisch", "fass das in
        3 Bullets zusammen"), das LLM rewriteset die Selektion.

        Bei jedem Fehler-Pfad (Timeout, leere Antwort, Netzwerk) faellt
        die Methode auf die Original-Selection zurueck — der Injector
        kriegt also IMMER mindestens den Selection-Inhalt zurueck.
        Wuerden wir leer returnen, wuerde Strg+V die Selektion mit
        Garbage ueberschreiben.
        """
        if not selection.strip() or not command.strip():
            return selection
        template = load_prompt("edit_command")
        prompt = template.format(selection=selection, command=command)
        # Mode "edit_command" kann eigenes Modell + Timeout in
        # StylerConfig.modes haben (z.B. ein staerkeres Modell als
        # gemma3:12b fuer komplexe Edits).
        mode_cfg = self._config.styler.modes.get("edit_command", ModeConfig())
        model = mode_cfg.model or self._config.styler.model
        timeout = mode_cfg.timeout_seconds or self._config.styler.timeout_seconds
        temperature = mode_cfg.temperature
        try:
            response = await asyncio.wait_for(
                self._client.chat(
                    model=model,
                    messages=[{"role": "user", "content": prompt}],
                    options={"temperature": temperature},
                    keep_alive=self._config.styler.keep_alive,
                ),
                timeout=timeout,
            )
            edited = response["message"]["content"].strip()
            if not edited:
                log.warning(
                    "edit_command returned empty (model=%s, sel=%d chars, "
                    "cmd=%r) — returning original selection",
                    model, len(selection), command[:60],
                )
                return selection
            return edited
        except asyncio.TimeoutError:
            log.warning(
                "edit_command timed out after %.1fs (model=%s) — "
                "returning original selection",
                timeout, model,
            )
            return selection
        except Exception as exc:
            log.warning(
                "edit_command failed (%s) — returning original selection",
                exc,
            )
            return selection
