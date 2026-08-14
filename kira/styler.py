"""Polish raw transcribed text via local Ollama with mode-specific prompts."""
from __future__ import annotations
import asyncio
import logging
import re
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

# Anteil von `size`, der mindestens im VRAM liegen muss, damit ein Load als
# „voll auf GPU" gilt. Bei 100%-GPU-Loads meldet Ollama size_vram == size;
# alles deutlich darunter ist der dokumentierte Partial-Offload (49/51-Split
# 2026-05-23: ~787 MiB Embedding-Tensor auf CPU → jede Token-Generation via
# PCIe → 14 statt 114 tok/s). 0.95 laesst Raum fuer Graph-/Rundungsanteile
# kuenftiger Ollama-Versionen, faengt aber jeden echten Layer-Offload.
GPU_RESIDENCY_FULL_RATIO = 0.95

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


# Modelle mit Hybrid-Reasoning, bei denen der Denk-Modus per Default AN ist.
# Deckt Schreibvarianten ab: gemma4:12b, gemma-4-abliterated, qwen3.6 usw.
_THINKING_MODEL_RE = re.compile(r"qwen3|gemma[-_ ]?[4-9]", re.IGNORECASE)


def _thinking_kwargs(model: str) -> dict:
    """Extra ``ollama.chat`` kwargs to suppress hybrid-reasoning output.

    Betroffen sind Qwen 3 UND Gemma 4 aufwaerts: beide starten per Default
    in einem 'thinking'-Modus, der vor der Antwort eine interne Denkkette
    erzeugt. Fuer Kiras polieren-ohne-umschreiben-Auftrag ist das doppelt
    falsch — es kostet Latenz und neigt zum Ueberschreiben des Inputs.

    Messung 2026-08-14 auf der RTX 5090 (beide Modelle zu 100 % im VRAM,
    echte Whisper-Saetze durch ``prompts/clean.md``):

    ======================  =============  =============
    Modell                  Denken an      ``think=False``
    ======================  =============  =============
    gemma4:e4b              2.60 s Median  0.38 s Median
                            (max 30.44 s)
    gemma4:26b-a4b-it-qat   14.76 s        0.38 s
                            (max 43.90 s)
    ======================  =============  =============

    Die Denkketten wurden bis zu 17 699 Zeichen lang — fuer Saetze von
    unter 80 Zeichen. Ohne das Flag lag der ``fast_mode``-Default aus
    v0.3.3 (``gemma4:e4b``) also weit ueber der Schwelle, ab der
    ``SLOW_POLISH_THRESHOLD_SEC`` den Notfall-Umschalter ausloest.

    Gemma 3 akzeptiert ``think=False`` klaglos (verifiziert), die fruehere
    Sorge vor Modellen ohne Thinking-Support traegt also nicht mehr; wir
    setzen das Flag trotzdem nur dort, wo es gebraucht wird.
    """
    return {"think": False} if _THINKING_MODEL_RE.search(model) else {}


class Styler:
    """Async Ollama-based text polisher."""

    def __init__(
        self,
        config: Config,
        on_slow_polish_detected: Callable[[], None] | None = None,
        on_cpu_fallback_detected: Callable[[str], None] | None = None,
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
        self._on_cpu_fallback_detected = on_cpu_fallback_detected
        self._slow_polish_count = 0
        self._force_fast_until: float | None = None
        # True sobald ein warmup()-Chat durchkam. Der Setup-Re-Probe in
        # main.py liest das Flag (Daemon-Thread, bool-Read ist GIL-atomar)
        # und holt den Warmup nur nach, wenn der Boot-Warmup scheiterte —
        # z. B. weil Ollama beim Kira-Start noch nicht oben war.
        self._warmup_succeeded = False

    def set_on_slow_polish_detected(
        self, callback: Callable[[], None] | None,
    ) -> None:
        """Late-Binding-Setter — der Tray-Callback wird in main.py erst
        nach KiraTray-Konstruktion verfuegbar, der Styler selbst wird
        davor in run() erzeugt und reicht nur die Instanz durch."""
        self._on_slow_polish_detected = callback

    def set_on_cpu_fallback_detected(
        self, callback: Callable[[str], None] | None,
    ) -> None:
        """Late-Binding-Setter analog zu set_on_slow_polish_detected — der
        Tray-Callback ist erst nach KiraTray-Konstruktion verfuegbar, der
        Styler wird davor in run() erzeugt."""
        self._on_cpu_fallback_detected = callback

    @property
    def warmup_succeeded(self) -> bool:
        """True sobald mindestens ein warmup()-Chat erfolgreich war."""
        return self._warmup_succeeded

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
        except asyncio.TimeoutError:
            log.warning(
                "Styler warmup timed out after 60 s (model=%s). "
                "Model load takes longer than expected — first dictation "
                "may still be slow. Check `ollama list` for the model.",
                model,
            )
            return
        except Exception as exc:
            log.warning(
                "Styler warmup failed (%s). First dictation will pay the "
                "cold-start cost. Polish still falls back to raw on real "
                "errors, so this is non-fatal.",
                exc,
            )
            return
        self._warmup_succeeded = True
        log.info(
            "Styler warmup complete (model=%s, keep_alive=%s)",
            model, keep_alive,
        )
        # Nach erfolgreichem Load pruefen, ob das Modell wirklich im VRAM
        # liegt — num_gpu=999 ist ab Ollama 0.30.x serverseitig wirkungslos
        # (s. verify_gpu_placement). Eigener Schutz: ein Fehler im Check darf
        # den erfolgreichen Warmup nicht nachtraeglich zum Fehler machen.
        try:
            await self.verify_gpu_placement()
        except Exception:
            log.exception("GPU-Placement-Check nach Warmup fehlgeschlagen")

    async def verify_gpu_placement(self) -> str | None:
        """Prueft nach dem Warmup via ``ollama.ps()``, ob das Polish-Modell
        im VRAM liegt oder komplett auf die CPU gefallen ist.

        Hintergrund: ``num_gpu=999`` (FORCE_ALL_LAYERS_ON_GPU) ist ab
        Ollama 0.30.x serverseitig wirkungslos (Regression, GitHub #16610) —
        das Modell landet trotz freiem VRAM komplett auf CPU. Die alte
        Latenz-Heuristik (_observe_polish_duration) erkennt das unzuverlaessig,
        weil kurze Inputs auch auf CPU unter SLOW_POLISH_THRESHOLD_SEC bleiben
        koennen. ``size_vram`` aus ps() ist dagegen ein direktes,
        deterministisches Signal.

        Returns ``"cpu"`` (geladen, 0 Byte im VRAM), ``"partial"`` (geladen,
        aber < GPU_RESIDENCY_FULL_RATIO der Load-Groesse im VRAM — der
        49/51-Split-Fall), ``"gpu"`` (voll im VRAM) oder ``None`` (Modell
        laeuft nicht / ps nicht erreichbar / size_vram unklar). Bei ``"cpu"``
        und ``"partial"`` feuert ein actionabler Tray-Toast-Callback +
        WARNING-Log.

        Kira setzt eine CUDA-GPU voraus (Whisper laeuft hardcoded auf
        device="cuda"), darum ist size_vram=0 hier immer ein echter Fehler
        und nie ein "kein-GPU"-False-Positive.
        """
        model = self._resolve_model(None)
        # Ollama normalisiert untagged Modellnamen serverseitig auf ":latest" —
        # `model: gemma3` in der Config erscheint in ps() als "gemma3:latest".
        # Ohne den Alias liefe die Detection fuer solche Configs still ins Leere.
        wanted = {model}
        if ":" not in model:
            wanted.add(f"{model}:latest")
        try:
            resp = await self._client.ps()
        except Exception as exc:
            log.warning(
                "GPU-Placement-Check uebersprungen — ollama.ps() "
                "fehlgeschlagen (%s)", exc,
            )
            return None
        for m in getattr(resp, "models", None) or []:
            if wanted.isdisjoint({getattr(m, "model", None), getattr(m, "name", None)}):
                continue
            size = m.size
            vram = m.size_vram
            if size is None or vram is None or int(size) <= 0:
                # Unklare Antwort (size=0 waere durch den Ratio-Vergleich
                # sonst faelschlich "gpu") — lieber nicht warnen als falsch.
                return None
            if int(size) > 0 and int(vram) == 0:
                log.warning(
                    "Polish-Modell %s liegt KOMPLETT auf CPU (size=%.1f GB, "
                    "size_vram=0). Polish ist dadurch ~5-10x langsamer. "
                    "Abhilfe: Ollama neu starten — Kira setzt "
                    "OLLAMA_FLASH_ATTENTION=1 + OLLAMA_KV_CACHE_TYPE=q8_0 "
                    "persistent, das senkt den VRAM-Bedarf und bringt das "
                    "Modell in den VRAM. Bleibt es auf CPU: num_gpu=999 ist ab "
                    "Ollama 0.30.x wirkungslos (Regression GitHub #16610) -> "
                    "Ollama auf 0.24.0 downgraden. Achtung: Haelt ein WSL-/"
                    "Docker-Ollama den Port 11434, gilt stattdessen die "
                    "Port-Diagnose-Zeile direkt nach dieser (Windows).",
                    model, int(size) / 1e9,
                )
                if self._on_cpu_fallback_detected is not None:
                    msg = (
                        f"Polish-Modell {model} laeuft auf CPU statt GPU — "
                        f"stark verlangsamt. Ollama neu starten (Kira hat das "
                        f"VRAM-Tuning gesetzt, es greift nach dem Neustart). "
                        f"Hilft das nicht: Ollama auf 0.24.0 downgraden."
                    )
                    try:
                        self._on_cpu_fallback_detected(msg)
                    except Exception:
                        log.exception(
                            "on_cpu_fallback_detected callback raised"
                        )
                return "cpu"
            if int(vram) < int(size) * GPU_RESIDENCY_FULL_RATIO:
                # Partial-Offload: das 49/51-Muster. size_vram > 0 sieht auf
                # den ersten Blick gesund aus, aber der CPU-Anteil bremst
                # JEDE Token-Generation (PCIe-Roundtrip) — 2026-05-23 real
                # gemessen: 14 statt 114 tok/s bei nur ~6 % Weights auf CPU.
                log.warning(
                    "Polish-Modell %s liegt nur TEILWEISE im VRAM "
                    "(%.1f/%.1f GB auf GPU). Der CPU-Anteil bremst jede "
                    "Token-Generation — Abhilfe wie beim CPU-Fallback: "
                    "Ollama neu starten (VRAM-Tuning greift), VRAM-Fresser "
                    "schliessen oder kleineres Modell waehlen.",
                    model, int(vram) / 1e9, int(size) / 1e9,
                )
                if self._on_cpu_fallback_detected is not None:
                    msg = (
                        f"Polish-Modell {model} liegt nur teilweise im VRAM "
                        f"({int(vram) / 1e9:.1f}/{int(size) / 1e9:.1f} GB) — "
                        f"Polish deutlich verlangsamt. Ollama neu starten; "
                        f"bleibt der Split, VRAM freiraeumen oder kleineres "
                        f"Modell nutzen."
                    )
                    try:
                        self._on_cpu_fallback_detected(msg)
                    except Exception:
                        log.exception(
                            "on_cpu_fallback_detected callback raised"
                        )
                return "partial"
            log.info(
                "Polish-Modell %s liegt im VRAM (%.1f/%.1f GB auf GPU)",
                model, int(vram) / 1e9, int(size) / 1e9,
            )
            return "gpu"
        return None

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
