# © 2026 Mike Pollow, Digitalroots. Alle Rechte vorbehalten.
"""Tests für kira.ui.hud.signal: Wiedergabekopf, Pegel, Warnungen, Spektrum."""
from __future__ import annotations

import numpy as np
import pytest

from kira.ui.hud.signal import (
    PLAYBACK_DELAY,
    SAMPLE_RATE,
    SignalAnalysis,
    SignalTap,
)

BLOCK = 1600
DT = 1 / 60


def _run(tap: SignalAnalysis | None, sig: SignalTap, blocks, seconds: float,
         t0: float = 0.0, recording: bool = True, rec_start: float = 0.0):
    """Blöcke im 100-ms-Takt einspeisen und Kopf plus Auswertung mitlaufen lassen."""
    t = t0
    next_block = t0
    blocks = list(blocks)
    steps = int(round(seconds / DT))
    for _ in range(steps):
        while blocks and next_block <= t + 1e-9:
            sig.push(blocks.pop(0))
            next_block += 0.1
        t += DT
        sig.advance(DT)
        if tap is not None:
            tap.update(sig, t, DT, recording=recording, rec_elapsed=t - rec_start)
    return t


def _tone(freq: float, amp: float, n: int = BLOCK, phase0: int = 0) -> np.ndarray:
    i = np.arange(phase0, phase0 + n)
    return (amp * np.sin(2 * np.pi * freq * i / SAMPLE_RATE)).astype(np.float32)


def test_tail_returns_newest_samples_in_order_and_zeros_before_data():
    sig = SignalTap()
    sig.push(np.arange(10, dtype=np.float32))
    sig.start()
    sig.advance(10.0)  # Kopf wird auf den Datenstand begrenzt
    out = sig.tail(12)
    assert out.shape == (12,)
    assert list(out[:2]) == [0.0, 0.0]
    assert list(out[2:]) == list(range(10))


def test_head_lags_by_delay_and_never_runs_past_data():
    sig = SignalTap()
    for _ in range(3):
        sig.push(np.zeros(BLOCK, dtype=np.float32))
    sig.start()
    assert sig.position == 3 * BLOCK - PLAYBACK_DELAY
    sig.advance(0.05)
    assert sig.position == 3 * BLOCK - PLAYBACK_DELAY + int(0.05 * SAMPLE_RATE)
    sig.advance(5.0)
    assert sig.position == 3 * BLOCK


def test_head_moves_smoothly_between_blocks():
    """Zwischen zwei 100-ms-Blöcken muss der Kopf in jedem Bild weiterlaufen."""
    sig = SignalTap()
    sig.push(np.zeros(BLOCK, dtype=np.float32))
    sig.push(np.zeros(BLOCK, dtype=np.float32))
    sig.start()
    positions = []
    t, next_block = 0.0, 0.1
    for _ in range(60):
        if t >= next_block:
            sig.push(np.zeros(BLOCK, dtype=np.float32))
            next_block += 0.1
        sig.advance(DT)
        t += DT
        positions.append(sig.position)
    steps = np.diff(positions)
    assert (steps > 0).all()


def test_head_catches_up_when_far_behind():
    sig = SignalTap()
    sig.push(np.zeros(BLOCK, dtype=np.float32))
    sig.start()
    for _ in range(20):  # 2 s Daten auf einmal, etwa nach einem Hänger
        sig.push(np.zeros(BLOCK, dtype=np.float32))
    sig.advance(DT)
    assert sig.position >= 21 * BLOCK - PLAYBACK_DELAY - int(0.3 * SAMPLE_RATE)


def test_clip_is_held_for_700_ms_after_last_clipped_sample():
    sig, an = SignalTap(), SignalAnalysis()
    loud = np.full(BLOCK, 0.2, dtype=np.float32)
    loud[800] = 1.0
    quiet = [np.full(BLOCK, 0.2, dtype=np.float32) for _ in range(20)]
    sig.push(np.zeros(BLOCK, dtype=np.float32))
    sig.start()
    an.reset(0.0)
    t = _run(an, sig, [loud] + quiet, 0.35)
    assert an.clip
    onset = an.clip_onset
    _run(an, sig, [], 0.9, t0=t)
    assert not an.clip
    assert onset > 0


def test_silent_after_600_ms_of_digital_silence():
    sig, an = SignalTap(), SignalAnalysis()
    sig.start()
    an.reset(0.0)
    dead = [np.full(BLOCK, 1e-4, dtype=np.float32) for _ in range(12)]
    _run(an, sig, dead, 1.0)
    assert an.silent


def test_room_noise_is_not_silent():
    sig, an = SignalTap(), SignalAnalysis()
    sig.start()
    an.reset(0.0)
    rng = np.random.default_rng(1)
    noise = [(rng.uniform(-0.0022, 0.0022, BLOCK)).astype(np.float32) for _ in range(14)]
    _run(an, sig, noise, 1.2)
    assert not an.silent


def test_silent_clears_when_signal_returns():
    sig, an = SignalTap(), SignalAnalysis()
    sig.start()
    an.reset(0.0)
    t = _run(an, sig, [np.zeros(BLOCK, dtype=np.float32) for _ in range(10)], 0.9)
    assert an.silent
    _run(an, sig, [_tone(200, 0.3) for _ in range(4)], 0.4, t0=t)
    assert not an.silent


def test_silent_never_outside_recording():
    sig, an = SignalTap(), SignalAnalysis()
    sig.start()
    an.reset(0.0)
    _run(an, sig, [np.zeros(BLOCK, dtype=np.float32) for _ in range(10)], 0.9, recording=False)
    assert not an.silent


def test_level_rises_fast_and_falls_slowly():
    sig, an = SignalTap(), SignalAnalysis()
    sig.start()
    an.reset(0.0)
    t = _run(an, sig, [_tone(300, 0.5) for _ in range(4)], 0.35)
    assert an.level > 0.8  # −6 dBFS auf der 48-dB-Skala
    _run(an, sig, [np.zeros(BLOCK, dtype=np.float32)], 0.05, t0=t)
    assert an.level > 0.5


def test_db_hold_keeps_peak_for_one_second():
    sig, an = SignalTap(), SignalAnalysis()
    sig.start()
    an.reset(0.0)
    t = _run(an, sig, [_tone(300, 0.5), _tone(300, 0.5)], 0.3)
    assert an.db == pytest.approx(-6.0, abs=0.3)
    t = _run(an, sig, [_tone(300, 0.05)] * 6, 0.5, t0=t)
    assert an.db == pytest.approx(-6.0, abs=0.3)
    _run(an, sig, [_tone(300, 0.05)] * 12, 1.0, t0=t)
    assert an.db < -18.0


def test_voice_needs_80_ms_and_drops_after_1_2_s_quiet():
    sig, an = SignalTap(), SignalAnalysis()
    sig.start()
    an.reset(0.0)
    t = _run(an, sig, [_tone(150, 0.3) for _ in range(5)], 0.45)
    assert an.voice
    t = _run(an, sig, [np.zeros(BLOCK, dtype=np.float32) for _ in range(10)], 0.8, t0=t)
    assert an.voice
    _run(an, sig, [np.zeros(BLOCK, dtype=np.float32) for _ in range(12)], 1.0, t0=t)
    assert not an.voice


def test_onset_is_registered_on_a_syllable_start():
    sig, an = SignalTap(), SignalAnalysis()
    sig.start()
    an.reset(0.0)
    blocks = [np.zeros(BLOCK, dtype=np.float32)] * 3 + [_tone(180, 0.5)] * 3
    _run(an, sig, blocks, 0.7)
    assert len(an.onsets) >= 1


def test_spectrum_peaks_at_the_tone_frequency():
    sig, an = SignalTap(), SignalAnalysis()
    sig.start()
    an.reset(0.0)
    blocks = [_tone(1000, 0.5, phase0=k * BLOCK) for k in range(5)]
    _run(an, sig, blocks, 0.45)
    assert an.at(1000) > an.at(3000) + 0.3
    assert an.band(900, 1100) == pytest.approx(an.spectrum.max(), abs=0.05)


def test_silent_when_blocks_stop_arriving():
    """Gerät abgezogen: keine Blöcke mehr → nach dem Verzug KEIN SIGNAL statt eingefrorenem Bild."""
    sig, an = SignalTap(), SignalAnalysis()
    sig.start()
    an.reset(0.0)
    t = _run(an, sig, [_tone(200, 0.3, phase0=k * BLOCK) for k in range(10)], 1.0)
    assert not an.silent
    t = _run(an, sig, [], 0.7, t0=t)
    assert an.silent
    assert sig.stall > 0.35
    _run(an, sig, [_tone(200, 0.3) for _ in range(4)], 0.4, t0=t)
    assert not an.silent
    assert sig.stall < 0.35
