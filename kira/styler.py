"""Polish raw transcribed text via local Ollama with mode-specific prompts."""
from __future__ import annotations
import asyncio
import logging
import time
from pathlib import Path
from typing import Callable
import ollama
from kira.config import Config, ModeConfig

log = logging.getLogger(__name__)

# Wallclock-Schwelle ab der ein Polish-Roundtrip als „langsam" zaehlt.
# gemma3:12b auf RTX 5090 GPU liefert <1s; alles >3s deutet auf CPU-
# Offload oder gravierende GPU-Probleme.
SLOW_POLISH_THRESHOLD_SEC = 3.0
# Slow-Polishes in Folge bis ein Tray-Toast + Auto-Switch greift.
SLOW_POLISH_TRIGGER_COUNT = 3
# Wie lange der temporaere force_fast-Switch hält (Sekunden).
# 5 Min ist genug damit der User merkt "es ist wieder schnell", aber
# kurz genug damit ein vorbeigehender VRAM-Engpass danach nicht
# permanent das schwaechere Modell anbleiben laesst.
FORCE_FAST_DURATION_SEC = 5 * 60

# Forciert alle Modell-Layer auf die GPU. Ollama 0.23.x trifft auf
# Win11 + RTX 5090 bei gemma3:12b (Q4_K_M) gelegentlich die falsche
# Auto-Layer-Decision und laesst ~787 MiB Embedding-Tensor auf CPU
# trotz 28+ GiB freiem VRAM. Folge: jeder Token-Generate geht via
# PCIe zum CPU-Speicher → 14 tok/s statt 114 tok/s, Polish 5-15s
# statt <1s. Verifiziert 2026-05-23: identischer Call mit num_gpu=999
# → 100% GPU, 8x speedup. Muss konsistent an allen 3 chat-Sites
# stehen, sonst reloadet Ollama das Modell bei jedem Options-Wechsel
# (~7s pro Reload).
FORCE_ALL_LAYERS_ON_GPU = 999

from kira._resources import prompts_dir as _prompts_dir
PROMPT_DIR = _prompts_dir()
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


def _thinking_kwargs(model: str) -> dict:
    """Extra ``ollama.chat`` kwargs to suppress hybrid-reasoning output.

    Qwen 3 models default to a 'thinking' mode that emits ``<think>`` blocks
    and tends to over-rewrite the input — wrong for a faithful polish/edit
    step. ``think=False`` turns it off. Gemma and other non-thinking models
    don't need the flag, so we omit it there rather than rely on every
    Ollama build accepting ``think`` for a model without thinking support.
    """
    return {"think": False} if "qwen3" in model.lower() else {}


class Styler:
    """Async Ollama-based text polisher."""

    def __init__(
        self,
        config: Config,
        on_slow_polish_detected: Callable[[], None] | None = None,
    ):
        self._config = config
        self._client = ollama.AsyncClient()
        # Polish-Latenz-Detection (v0.2.6): Wenn das Polish-Modell auf
        # CPU rutscht (Ollama-Bug auf Win11, bekannt seit v0.2.5), dauert
        # Polish 10-15s statt <1s. Wir zaehlen Slow-Polishes in Folge
        # und triggern bei SLOW_POLISH_TRIGGER_COUNT einen Tray-Toast +
        # temporaeren Switch auf fast_model. Reset auf 0 bei jedem
        # schnellen Polish, sodass voruebergehende Spikes (z.B. eine
        # einzelne 4s-Antwort bei langem Input) nicht den Override
        # ausloesen.
        self._on_slow_polish_detected = on_slow_polish_detected
        self._slow_polish_count = 0
        self._force_fast_until: float | None = None

    def set_on_slow_polish_detected(
        self, callback: Callable[[], None] | None,
    ) -> None:
        """Late-Binding-Setter — der Tray-Callback wird in main.py erst
        nach KiraTray-Konstruktion verfuegbar, der Styler selbst wird
        davor in run() erzeugt und reicht nur die Instanz durch."""
        self._on_slow_polish_detected = callback

    def _resolve_model(self, mode: str | None = None) -> str:
        """Welches Modell faerbt der naechste LLM-Call.

        Hierarchie (hoechste Prio zuerst):
        1. Per-Mode-Override (styler.modes[mode].model) — User-explizit
           in YAML eingestellt, schlaegt alles.
        2. styler.fast_model bei fast_mode=True ODER aktivem temporaeren
           force_fast (v0.2.6 Auto-Switch nach SLOW_POLISH_TRIGGER_COUNT
           langsamen Polishes in Folge).
        3. styler.model — Default.
        """
        if mode is not None:
            mode_cfg = self._config.styler.modes.get(mode, ModeConfig())
            if mode_cfg.model:
                return mode_cfg.model
        if self._config.styler.fast_mode or self._is_force_fast_active():
            return self._config.styler.fast_model
        return self._config.styler.model

    def _is_force_fast_active(self) -> bool:
        """True wenn der temporaere force_fast-Override noch laeuft.

        Bei Ablauf wird _force_fast_until auf None gesetzt, damit der
        naechste Aufruf wieder direkt False liefert und nicht weiter
        time.monotonic() vergleicht.
        """
        if self._force_fast_until is None:
            return False
        if time.monotonic() < self._force_fast_until:
            return True
        self._force_fast_until = None
        return False

    def _activate_force_fast(self) -> None:
        self._force_fast_until = time.monotonic() + FORCE_FAST_DURATION_SEC
        log.warning(
            "Polish-Latenz ueber Schwelle (%d in Folge > %.1fs) — switche "
            "temporaer auf fast_model=%s fuer %d s. Pruefe `ollama ps` und "
            "GPU-Auslastung (Polish-Modell duerfte auf CPU geladen sein).",
            SLOW_POLISH_TRIGGER_COUNT,
            SLOW_POLISH_THRESHOLD_SEC,
            self._config.styler.fast_model,
            FORCE_FAST_DURATION_SEC,
        )

    def _observe_polish_duration(self, duration: float) -> None:
        """Counter fuehren + ggf. Tray-Toast & force_fast triggern.

        Reset auf 0 bei schnellem Polish, sodass nur echte Stroms von
        langsamen Polishes (CPU-Offload) den Switch ausloesen.
        """
        if duration <= SLOW_POLISH_THRESHOLD_SEC:
            self._slow_polish_count = 0
            return
        self._slow_polish_count += 1
        if (
            self._slow_polish_count < SLOW_POLISH_TRIGGER_COUNT
            or self._is_force_fast_active()
        ):
            return
        # Nur switchen wenn User fast_mode nicht eh schon manuell an hat;
        # sonst waere der Override no-op. Toast feuern wir trotzdem,
        # damit User merkt dass auch das schnelle Modell langsam ist —
        # dann ist Ollama/GPU komplett am Boden und manueller Eingriff
        # noetig.
        if not self._config.styler.fast_mode:
            self._activate_force_fast()
        if self._on_slow_polish_detected is not None:
            try:
                self._on_slow_polish_detected()
            except Exception:
                log.exception("on_slow_polish_detected callback raised")
        self._slow_polish_count = 0

    async def warmup(self) -> None:
        """Issue a tiny chat request to force Ollama to load the model now.

        Without this, the very first F8 dictation after app start pays the
        full cold-start cost (cuBLAS init + weight load — typically 1-2 s
        for gemma2:2b, much more for 27B-class models). Combined with
        ``keep_alive`` on the polish path, this keeps the model resident
        from boot to quit.
        """
        model = self._resolve_model(None)
        keep_alive = self._config.styler.keep_alive
        try:
            await asyncio.wait_for(
                self._client.chat(
                    model=model,
                    messages=[{"role": "user", "content": "ok"}],
                    options={
                        "temperature": 0.0,
                        "num_predict": 1,
                        "num_gpu": FORCE_ALL_LAYERS_ON_GPU,
                    },
                    keep_alive=keep_alive,
                    **_thinking_kwargs(model),
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
        # Per-Mode-Override: timeout + temperature koennen je Mode in
        # StylerConfig.modes definiert sein. Fehlt der Mode dort oder ist
        # ein Feld None, faellt's auf den globalen StylerConfig zurueck.
        # temperature-Default 0.2 wird nur bei nicht-gesetztem Mode-Override
        # angewendet (vorher war 0.2 hardcoded als Mode-Field-Default —
        # code-reviewer Karpathy 2026-05-09). Modell-Resolution ist im
        # _resolve_model()-Helper gekapselt: Per-Mode > fast_mode > model.
        mode_cfg = self._config.styler.modes.get(mode, ModeConfig())
        model = self._resolve_model(mode)
        timeout = mode_cfg.timeout_seconds or self._config.styler.timeout_seconds
        temperature = (
            mode_cfg.temperature if mode_cfg.temperature is not None else 0.2
        )
        start = time.monotonic()
        try:
            response = await asyncio.wait_for(
                self._client.chat(
                    model=model,
                    messages=[{"role": "user", "content": prompt}],
                    options={
                        "temperature": temperature,
                        "num_gpu": FORCE_ALL_LAYERS_ON_GPU,
                    },
                    keep_alive=self._config.styler.keep_alive,
                    **_thinking_kwargs(model),
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
                # Symmetric mit TimeoutError-branch unten: bei deaktiviertem
                # Fallback raise statt empty-Polished-zurückgeben. Sonst
                # wäre der Contract der Funktion asymmetrisch (Timeout
                # raised, empty-response gibt leise "" zurück) — silent-
                # failure-hunt 2026-05-09.
                raise RuntimeError(
                    f"Styler returned empty response (model={model})"
                )
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
        finally:
            self._observe_polish_duration(time.monotonic() - start)

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
        # gemma3:12b fuer komplexe Edits). Modell-Resolution via Helper
        # respektiert auch fast_mode wenn kein Per-Mode-Override gesetzt.
        mode_cfg = self._config.styler.modes.get("edit_command", ModeConfig())
        model = self._resolve_model("edit_command")
        timeout = mode_cfg.timeout_seconds or self._config.styler.timeout_seconds
        temperature = (
            mode_cfg.temperature if mode_cfg.temperature is not None else 0.2
        )
        try:
            response = await asyncio.wait_for(
                self._client.chat(
                    model=model,
                    messages=[{"role": "user", "content": prompt}],
                    options={
                        "temperature": temperature,
                        "num_gpu": FORCE_ALL_LAYERS_ON_GPU,
                    },
                    keep_alive=self._config.styler.keep_alive,
                    **_thinking_kwargs(model),
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
