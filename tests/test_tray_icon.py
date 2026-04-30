"""Tests for the branded tray-icon generation in kira.ui.tray_win.

Pillow renders deterministically, so a pixel-snapshot test for each
state catches regressions like swapped overlay-dot colors or a
missing background. The caching layer is exercised directly so that
a future refactor that breaks memoization fails loudly instead of
silently regressing UNC-IO performance on Mike's box.
"""
from __future__ import annotations
import sys

import pytest

if sys.platform != "win32":
    pytest.skip("windows-only tests", allow_module_level=True)

from kira.app import State
from kira.ui import tray_win
from kira.ui.tray_win import (
    ICON_SIZE,
    _build_icon,
    _load_or_generate_icon,
)


@pytest.fixture(autouse=True)
def _reset_caches():
    """Each test starts with a clean module-level cache so order doesn't
    matter and the logo-load path is exercised fresh."""
    tray_win._LOGO_CACHE = None
    tray_win._LOGO_CACHE_FAILED = False
    tray_win._ICON_CACHE.clear()
    yield
    tray_win._LOGO_CACHE = None
    tray_win._LOGO_CACHE_FAILED = False
    tray_win._ICON_CACHE.clear()


def _bottom_right_dot_pixel(img):
    """Sample the center of the overlay-dot region (bottom-right quadrant)."""
    # Overlay dot occupies the bottom-right square of side ICON_SIZE//5.
    # Sample a few pixels into the dot interior to avoid antialias edges.
    offset = ICON_SIZE // 10
    return img.getpixel((ICON_SIZE - offset, ICON_SIZE - offset))


def _center_pixel(img):
    return img.getpixel((ICON_SIZE // 2, ICON_SIZE // 2))


def test_idle_icon_has_yellow_background_no_overlay():
    img = _load_or_generate_icon(State.IDLE)
    assert img.size == (ICON_SIZE, ICON_SIZE)
    # Bottom-right area should still be the BG yellow, not red/orange.
    r, g, b, a = _bottom_right_dot_pixel(img)
    assert a == 255, "BG must be opaque inside the rounded square"
    assert r > 200 and g > 150 and b < 80, (
        f"expected yellow-ish BG, got RGBA=({r},{g},{b},{a})"
    )


def test_recording_icon_has_red_overlay_dot():
    img = _load_or_generate_icon(State.RECORDING)
    r, g, b, _ = _bottom_right_dot_pixel(img)
    assert r > 180 and g < 80 and b < 80, (
        f"expected red overlay dot, got RGB=({r},{g},{b})"
    )


def test_error_icon_has_orange_overlay_dot():
    img = _load_or_generate_icon(State.ERROR)
    r, g, b, _ = _bottom_right_dot_pixel(img)
    assert r > 200 and 40 < g < 120 and b < 50, (
        f"expected red-orange overlay dot, got RGB=({r},{g},{b})"
    )


def test_pipeline_states_have_no_overlay():
    """TRANSCRIBING/STYLING/INJECTING render identically to IDLE — only
    RECORDING and ERROR get a corner dot. Verifying so a future state
    addition with a wrong overlay color fails loudly."""
    idle = _load_or_generate_icon(State.IDLE)
    for s in (State.TRANSCRIBING, State.STYLING, State.INJECTING):
        img = _load_or_generate_icon(s)
        # Pixel-level equivalence: same BG, same logo, no overlay
        assert _bottom_right_dot_pixel(img) == _bottom_right_dot_pixel(idle)
        assert _center_pixel(img) == _center_pixel(idle)


def test_load_or_generate_icon_is_memoized_per_state():
    """Cache hit: second call for the same state returns the same Image
    object — no rebuild, no re-resize, no UNC IO."""
    first = _load_or_generate_icon(State.IDLE)
    second = _load_or_generate_icon(State.IDLE)
    assert first is second
    # Different state must NOT collide on the cache key.
    other = _load_or_generate_icon(State.RECORDING)
    assert other is not first


def test_logo_is_loaded_only_once_across_states(monkeypatch):
    """_get_logo is the only consumer of Image.open(icon.ico). We count
    Image.open calls across multiple state requests to confirm the
    UNC-IO hit happens at most once."""
    open_calls = []
    real_open = tray_win.Image.open

    def _counting_open(*args, **kwargs):
        open_calls.append(args[0] if args else None)
        return real_open(*args, **kwargs)

    monkeypatch.setattr("kira.ui.tray_win.Image.open", _counting_open)
    _load_or_generate_icon(State.IDLE)
    _load_or_generate_icon(State.RECORDING)
    _load_or_generate_icon(State.ERROR)
    _load_or_generate_icon(State.STYLING)
    assert len(open_calls) <= 1, (
        f"Expected logo loaded at most once, got {len(open_calls)} Image.open calls"
    )


def test_build_icon_bypasses_cache():
    """_build_icon is the uncached primitive; useful for tests and any
    future caller that needs a fresh image (e.g. resizing for a
    different DPI). Two calls return distinct objects."""
    a = _build_icon(State.IDLE)
    b = _build_icon(State.IDLE)
    assert a is not b
    # ...but pixel-identical
    assert _center_pixel(a) == _center_pixel(b)
