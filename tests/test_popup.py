"""Smoke test — construction only. Actual rendering needs an event loop."""
import numpy as np


def test_popup_module_imports():
    from kira.ui.popup import PopupHUD, WaveformView
    assert PopupHUD is not None
    assert WaveformView is not None


def test_popup_hud_construction():
    from kira.ui.popup import PopupHUD
    hud = PopupHUD()
    assert hud._panel is None


def test_peaks_keep_the_extreme_sample_of_each_chunk():
    from kira.ui.popup import _peaks
    block = np.zeros(300, dtype=np.float32)
    block[15] = -0.9
    block[150] = 0.4
    peaks = _peaks(block, 30)
    assert len(peaks) == 30
    assert abs(peaks[1] + 0.9) < 1e-6
    assert abs(peaks[15] - 0.4) < 1e-6
    assert _peaks(np.zeros(0, dtype=np.float32), 30) == []
    assert len(_peaks(np.ones(5, dtype=np.float32), 30)) == 5
