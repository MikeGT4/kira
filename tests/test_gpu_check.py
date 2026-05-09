"""Tests for kira.gpu_check. nvidia-smi via mocked subprocess."""
from __future__ import annotations
import subprocess
from unittest.mock import patch

import pytest

from kira.gpu_check import (
    GpuInfo,
    assess,
    detect_gpu,
    estimate_polish_vram,
    estimate_whisper_vram,
)


# ===== Whisper VRAM estimation =======================================


@pytest.mark.parametrize("model,expected", [
    ("large-v3-turbo", 1.6),
    ("large-v3", 3.0),
    ("large-v2", 3.0),
    ("medium", 1.0),
    ("small", 0.5),
    ("base", 0.3),
    ("tiny", 0.1),
    # MLX-Praefix wird gestripped
    ("mlx-community/whisper-large-v3-turbo", 1.6),
    ("whisper-medium", 1.0),
    # Lokale Pfade — Mike's config kann z.B. lokales-Modell-Dir referenzieren
    ("C:/Users/mike/models/faster-whisper-large-v3", 3.0),
    ("C:\\Users\\mike\\models\\faster-whisper-large-v3-turbo", 1.6),
    ("/home/user/.cache/faster-whisper/medium", 1.0),
    # 'faster-whisper-' Praefix wird gestripped
    ("faster-whisper-large-v3", 3.0),
])
def test_estimate_whisper_vram_known_models(model, expected):
    assert estimate_whisper_vram(model) == expected


def test_estimate_whisper_vram_unknown_model_uses_default():
    """Unbekannte Modelle bekommen einen konservativen 2.0 GB-Default."""
    assert estimate_whisper_vram("super-future-whisper-9000") == 2.0


def test_estimate_whisper_vram_case_insensitive():
    assert estimate_whisper_vram("LARGE-V3-TURBO") == 1.6


# ===== Polish (Ollama) VRAM estimation ===============================


@pytest.mark.parametrize("model,expected", [
    ("gemma3:12b", 7.0),
    ("gemma2:2b", 1.5),
    ("qwen3:8b", 5.0),
    ("llama3.2:3b", 2.0),
    ("gemma3:27b", 16.0),
    # Substring-Match — Tag-Suffixes wie ":latest" stoeren nicht
    ("gemma3:12b-it", 7.0),
])
def test_estimate_polish_vram_known_models(model, expected):
    assert estimate_polish_vram(model) == expected


def test_estimate_polish_vram_unknown_uses_param_count_heuristic():
    """':7b' im Namen → 7 Mrd Parameter → 0.6 GB/Mrd bei Q4 ≈ 4.2 GB."""
    assert estimate_polish_vram("custom-model:7b") == pytest.approx(4.2, abs=0.05)
    assert estimate_polish_vram("frankenstein:13b") == pytest.approx(7.8, abs=0.05)


def test_estimate_polish_vram_unknown_no_param_uses_default():
    """Modell ohne Param-Hint → 4.0 GB-Default."""
    assert estimate_polish_vram("mystery-model") == 4.0


def test_estimate_polish_vram_priority_picks_largest_match():
    """gemma3:27b muss VOR gemma3:2b matchen (sonst falsche Schaetzung)."""
    # 27b enthaelt nicht "2b" als substring (":27b" vs ":2b"), aber doppel-
    # check dass die Tabellen-Reihenfolge das gross-zuerst aufloest.
    assert estimate_polish_vram("gemma3:27b") == 16.0
    assert estimate_polish_vram("gemma3:12b") == 7.0


# ===== nvidia-smi detection ==========================================


def test_detect_gpu_parses_nvidia_smi_output():
    fake_out = "NVIDIA GeForce RTX 5090, 32607 MiB\n"
    with patch("kira.gpu_check.subprocess.run") as mock_run:
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout=fake_out, stderr="",
        )
        gpu = detect_gpu()
    assert gpu is not None
    assert gpu.name == "NVIDIA GeForce RTX 5090"
    assert gpu.vram_gb == pytest.approx(31.8, abs=0.1)
    assert gpu.cuda_available is True


def test_detect_gpu_returns_none_when_smi_missing():
    """ALLE Kandidaten-Pfade (PATH-name + System32 + Program Files) failen."""
    with patch(
        "kira.gpu_check.subprocess.run",
        side_effect=FileNotFoundError("nvidia-smi"),
    ):
        assert detect_gpu() is None


def test_detect_gpu_falls_back_to_system32_when_path_missing():
    """1. Versuch (bare 'nvidia-smi' im PATH) failt → 2. Versuch
    (C:\\Windows\\System32\\nvidia-smi.exe) klappt. Behebt Mike's Bug
    wo pythonw.exe einen reduzierten PATH ohne System32 hatte."""
    fake_out = "NVIDIA GeForce RTX 5090, 32607 MiB\n"
    call_count = {"n": 0}

    def fake_run(cmd, **kwargs):
        call_count["n"] += 1
        if call_count["n"] == 1:
            # Erster Aufruf (bare 'nvidia-smi') failt mit FileNotFoundError
            raise FileNotFoundError("nvidia-smi")
        # Zweiter Aufruf (System32-Pfad) erfolgreich
        return subprocess.CompletedProcess(
            args=cmd, returncode=0, stdout=fake_out, stderr="",
        )

    with patch("kira.gpu_check.subprocess.run", side_effect=fake_run):
        gpu = detect_gpu()
    assert gpu is not None
    assert gpu.name == "NVIDIA GeForce RTX 5090"
    assert call_count["n"] >= 2  # mind. der Fallback wurde probiert


def test_detect_gpu_returns_none_when_smi_crashes():
    with patch(
        "kira.gpu_check.subprocess.run",
        side_effect=subprocess.CalledProcessError(1, ["nvidia-smi"]),
    ):
        assert detect_gpu() is None


def test_detect_gpu_returns_none_on_unparseable_output():
    with patch("kira.gpu_check.subprocess.run") as mock_run:
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="GIBBERISH\n", stderr="",
        )
        assert detect_gpu() is None


# ===== Full assessment flow ==========================================


def _fake_gpu(vram_gb: float) -> GpuInfo:
    return GpuInfo(name="NVIDIA RTX TestCard", vram_gb=vram_gb, cuda_available=True)


def test_assess_ok_status_when_plenty_of_headroom():
    """RTX 5090 mit 32 GB + Mike's Standard-Stack (large-v3-turbo + gemma3:12b
    = 1.6 + 7.0 = 8.6 GB benoetigt) → 23 GB Headroom → 'ok'."""
    with patch("kira.gpu_check.detect_gpu", return_value=_fake_gpu(32.0)):
        result = assess("large-v3-turbo", "gemma3:12b")
    assert result.status == "ok"
    assert result.headroom_gb == pytest.approx(23.4, abs=0.1)
    assert "passt mit Komfort" in result.message


def test_assess_tight_status_when_headroom_under_2gb():
    """8 GB GPU + gemma3:12b (~7 GB) + large-v3-turbo (~1.6 GB) =
    8.6 GB benoetigt → -0.6 GB Headroom → 'insufficient'.
    Test mit 9 GB GPU statt → 0.4 GB headroom → noch insufficient (<0.5).
    Statt: 9.5 GB GPU → 0.9 GB headroom → tight."""
    with patch("kira.gpu_check.detect_gpu", return_value=_fake_gpu(9.5)):
        result = assess("large-v3-turbo", "gemma3:12b")
    assert result.status == "tight"
    assert "knapp" in result.message.lower()


def test_assess_insufficient_status_suggests_smaller_model():
    """6 GB GPU + Mike's Stack braucht 8.6 GB → 'insufficient' + Empfehlung."""
    with patch("kira.gpu_check.detect_gpu", return_value=_fake_gpu(6.0)):
        result = assess("large-v3-turbo", "gemma3:12b")
    assert result.status == "insufficient"
    assert "gemma2:2b" in result.message  # Vorschlag fuer kleineres Modell


def test_assess_no_gpu_when_nvidia_smi_missing():
    with patch("kira.gpu_check.detect_gpu", return_value=None):
        result = assess("large-v3-turbo", "gemma3:12b")
    assert result.status == "no_gpu"
    assert result.gpu is None
    assert "Keine NVIDIA-GPU" in result.message
