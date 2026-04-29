"""Smoke test — construction only. Actual rendering needs an event loop."""
def test_popup_module_imports():
    from kira.ui.popup import PopupHUD, WaveformView
    assert PopupHUD is not None
    assert WaveformView is not None


def test_popup_hud_construction():
    from kira.ui.popup import PopupHUD
    hud = PopupHUD()
    assert hud._panel is None  # panel is lazy-created on first show()
