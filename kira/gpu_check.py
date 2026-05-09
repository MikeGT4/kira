"""GPU-Check: passt das Whisper- + Polish-Modell auf die installierte Karte?

Pure Logic, kein UI. Ruft nvidia-smi via subprocess (kein PyTorch, kein
pynvml — Mike's Stack ist faster-whisper + Ollama, beide ohne torch),
schaetzt VRAM-Bedarf aus Modell-Namen, vergleicht.

Aufgerufen aus dem Settings-Dialog "Ueber Kira"-Card als "GPU pruefen"-
Button. Ergebnis wird via light_information / light_warning / light_critical
als Dialog gezeigt.

VRAM-Schaetzungen sind grob — Q4_K_M-Quantization fuer Ollama, float16 fuer
faster-whisper. Ueberraschungen sind moeglich (Token-Kontext, multiple
concurrent generations), daher arbeiten wir mit einem Headroom-Buffer
(>2 GB = ok, >0.5 GB = tight, sonst insufficient).
"""
from __future__ import annotations
import logging
import re
import subprocess
from dataclasses import dataclass
from typing import Literal

log = logging.getLogger(__name__)


# Whisper / faster-whisper float16 VRAM-Bedarf in GB. Eintraege gegen
# kleinste-zu-groesste sortiert; assess() iteriert in Insertion-Order
# und nimmt das erste Match — startswith semantics, so "large-v3-turbo"
# vor "large-v3" damit der Turbo-Match zuerst greift.
_WHISPER_VRAM_GB: dict[str, float] = {
    "large-v3-turbo": 1.6,
    "large-v3": 3.0,
    "large-v2": 3.0,
    "large": 3.0,
    "medium": 1.0,
    "small": 0.5,
    "base": 0.3,
    "tiny": 0.1,
}

# Ollama Q4_K_M default. Substring-Match (kein Prefix), case-insensitive.
# Eintraege mit groesseren Modellen zuerst damit "gemma3:27b" nicht von
# "gemma3:2b" gefressen wird.
_OLLAMA_VRAM_GB: dict[str, float] = {
    "llama3.3:70b": 40.0,
    "gemma3:27b": 16.0,
    "gemma2:27b": 16.0,
    "qwen3:14b": 8.5,
    "gemma3:12b": 7.0,
    "gemma2:9b": 5.5,
    "qwen3:8b": 5.0,
    "llama3.1:8b": 5.0,
    "llama3:8b": 5.0,
    "qwen3:4b": 2.5,
    "gemma3:4b": 2.5,
    "llama3.2:3b": 2.0,
    "gemma2:2b": 1.5,
    "gemma3:1b": 1.0,
    "llama3.2:1b": 1.0,
}


@dataclass(frozen=True)
class GpuInfo:
    name: str
    vram_gb: float
    cuda_available: bool


@dataclass(frozen=True)
class VramAssessment:
    """Resultat von assess(). status entscheidet ueber Dialog-Severity."""
    status: Literal["ok", "tight", "insufficient", "no_gpu"]
    gpu: GpuInfo | None
    whisper_model: str
    whisper_vram_gb: float
    polish_model: str
    polish_vram_gb: float
    total_required_gb: float
    headroom_gb: float
    message: str


def detect_gpu() -> GpuInfo | None:
    """nvidia-smi parsen. Return None wenn:
    - nvidia-smi nicht im PATH (keine NVIDIA-Treiber)
    - nvidia-smi crasht (Treiber kaputt)
    - Output unparsable

    Format: 'NVIDIA GeForce RTX 5090, 32607 MiB'.
    """
    try:
        result = subprocess.run(  # noqa: S603 - list-args, kein shell
            [
                "nvidia-smi",
                "--query-gpu=name,memory.total",
                "--format=csv,noheader",
            ],
            capture_output=True,
            text=True,
            timeout=5.0,
            check=True,
        )
    except (FileNotFoundError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        log.info("nvidia-smi not available: %s", exc)
        return None

    output = result.stdout.strip()
    if not output:
        return None
    first_line = output.splitlines()[0]
    match = re.match(r"^(.+?),\s*(\d+)\s*MiB\s*$", first_line)
    if not match:
        log.warning("nvidia-smi output unparseable: %r", first_line)
        return None
    name = match.group(1).strip()
    vram_mib = int(match.group(2))
    return GpuInfo(
        name=name, vram_gb=round(vram_mib / 1024.0, 1), cuda_available=True,
    )


def estimate_whisper_vram(model_name: str) -> float:
    """faster-whisper-Modell-Name → VRAM-Schaetzung in GB.

    Akzeptiert auch MLX-Praefix (mlx-community/whisper-large-v3-turbo)
    den der Mac-Build nutzt — Transcriber._translate_model_name strippt
    den schon, wir hier defensiv noch ein zweites Mal.
    """
    name = model_name.lower().strip()
    if "/" in name:
        name = name.split("/", 1)[1]
    if name.startswith("whisper-"):
        name = name[len("whisper-"):]
    for prefix, gb in _WHISPER_VRAM_GB.items():
        if name.startswith(prefix):
            return gb
    return 2.0  # konservativer Default fuer unbekannte Modelle


def estimate_polish_vram(model_name: str) -> float:
    """Ollama-Modell-Name → VRAM-Schaetzung in GB.

    Erst Lookup in der bekannten Tabelle (substring-match), dann Fallback
    auf Parameter-Count im Namen (z.B. ':7b' → ~4 GB bei Q4).
    """
    name = model_name.lower().strip()
    for key, gb in _OLLAMA_VRAM_GB.items():
        if key in name:
            return gb
    # Fallback: 'something:7b' → 7 Mrd Parameter → ~0.6 GB/Mrd bei Q4_K_M
    match = re.search(r":(\d+(?:\.\d+)?)b\b", name)
    if match:
        params_b = float(match.group(1))
        return round(params_b * 0.6, 1)
    return 4.0


def _suggest_smaller_polish(current: str) -> str:
    """Heuristik: bei zu wenig VRAM einen kleineren Default vorschlagen."""
    name = current.lower()
    if "gemma" in name:
        return "gemma2:2b"
    if "llama" in name:
        return "llama3.2:3b"
    if "qwen" in name:
        return "qwen3:4b"
    return "gemma2:2b"


def assess(whisper_model: str, polish_model: str) -> VramAssessment:
    """Vollstaendiger Check: GPU detect + VRAM estimate + Status-Dichotomie."""
    gpu = detect_gpu()
    w_vram = estimate_whisper_vram(whisper_model)
    p_vram = estimate_polish_vram(polish_model)
    total = round(w_vram + p_vram, 1)

    if gpu is None:
        return VramAssessment(
            status="no_gpu",
            gpu=None,
            whisper_model=whisper_model,
            whisper_vram_gb=w_vram,
            polish_model=polish_model,
            polish_vram_gb=p_vram,
            total_required_gb=total,
            headroom_gb=0.0,
            message=(
                "Keine NVIDIA-GPU erkannt (nvidia-smi nicht im PATH).\n\n"
                "Kira ist auf NVIDIA + CUDA ausgelegt. "
                f"Geschaetzter Bedarf: ~{total:.1f} GB VRAM "
                f"({whisper_model} + {polish_model}).\n\n"
                "Auf reiner CPU-Hardware waere Whisper ~10x langsamer und "
                "gemma3:12b praktisch unbenutzbar. AMD/Intel-iGPU werden "
                "nicht unterstuetzt — der Polish-Pfad wuerde scheitern."
            ),
        )

    headroom = round(gpu.vram_gb - total, 1)
    common = (
        f"GPU: {gpu.name}\n"
        f"VRAM total: {gpu.vram_gb:.1f} GB\n\n"
        f"Whisper-Modell ({whisper_model}): ~{w_vram:.1f} GB\n"
        f"Polish-LLM ({polish_model}): ~{p_vram:.1f} GB\n"
        f"Summe: ~{total:.1f} GB\n"
        f"Headroom: {headroom:+.1f} GB\n\n"
    )

    # Headroom-Schwellen: Desktop/Browser/IDE belegen 1-2 GB unsichtbar.
    # >=2 GB komfortabel, >=0.5 GB knapp aber machbar, darunter nicht.
    if headroom >= 2.0:
        return VramAssessment(
            status="ok", gpu=gpu,
            whisper_model=whisper_model, whisper_vram_gb=w_vram,
            polish_model=polish_model, polish_vram_gb=p_vram,
            total_required_gb=total, headroom_gb=headroom,
            message=common + (
                "Status: passt mit Komfort.\n"
                "Genug Reserve fuer Desktop, Browser-GPU-Acceleration und "
                "leichte parallele GPU-Last."
            ),
        )
    if headroom >= 0.5:
        return VramAssessment(
            status="tight", gpu=gpu,
            whisper_model=whisper_model, whisper_vram_gb=w_vram,
            polish_model=polish_model, polish_vram_gb=p_vram,
            total_required_gb=total, headroom_gb=headroom,
            message=common + (
                "Status: knapp.\n"
                "Funktioniert solange nichts anderes die GPU stark belastet "
                "(Spiel im Hintergrund, mehrere Browser-Fenster mit GPU-Acc, "
                "Stable-Diffusion etc.). Bei Cold-Start kann es zu OOM-Errors "
                "kommen.\n\nEmpfehlung: kleineres Polish-Modell waehlen."
            ),
        )
    suggestion = _suggest_smaller_polish(polish_model)
    return VramAssessment(
        status="insufficient", gpu=gpu,
        whisper_model=whisper_model, whisper_vram_gb=w_vram,
        polish_model=polish_model, polish_vram_gb=p_vram,
        total_required_gb=total, headroom_gb=headroom,
        message=common + (
            f"Status: nicht genug VRAM.\n\n"
            f"Empfehlung: Polish-Modell wechseln auf '{suggestion}' "
            f"(~{estimate_polish_vram(suggestion):.1f} GB statt ~{p_vram:.1f} GB).\n"
            f"Whisper-Modell {whisper_model} bleibt OK."
        ),
    )
