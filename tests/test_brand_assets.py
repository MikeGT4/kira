# © 2026 Mike Pollow, Digitalroots. Alle Rechte vorbehalten.
"""Patina statt Waldgrün: Logo-Datei, Startbild, README-Bild, Oszilloskop.
Windows-only (PyQt6-Farben)."""
from __future__ import annotations
import sys
from collections import Counter
from pathlib import Path
import pytest

if sys.platform != "win32":
    pytest.skip("windows-only tests (PyQt6)", allow_module_level=True)

from PIL import Image

ASSETS = Path(__file__).resolve().parent.parent / "assets"
AUTHOR = "© 2026 Mike Pollow, Digitalroots"


def _greenish(rgb):
    r, g, b = rgb[:3]
    return g > r + 40 and g > b + 20


def test_logo_file_is_the_patina_version():
    img = Image.open(ASSETS / "digitalroots-logo.png").convert("RGBA")
    assert img.size == (1001, 188)
    colored = [p[:3] for p in img.get_flattened_data() if p[3] > 200 and max(p[:3]) - min(p[:3]) > 40]
    assert colored and not any(_greenish(c) for c in colored)
    bucket = Counter((c[0] // 8 * 8, c[1] // 8 * 8, c[2] // 8 * 8) for c in colored)
    assert bucket.most_common(1)[0][0] == (24, 88, 96)


@pytest.mark.parametrize("name", ["kira-splash.png", "readme-splash.jpg"])
def test_splash_images_have_no_green_logo_left(name):
    img = Image.open(ASSETS / name).convert("RGB")
    w, h = img.size
    region = img.crop((round(w * 0.28), round(h * 0.80), round(w * 0.73), round(h * 0.93)))
    assert sum(1 for p in region.get_flattened_data() if _greenish(p)) == 0


@pytest.mark.parametrize("name", ["digitalroots-logo.png", "kira-splash.png"])
def test_png_assets_have_author_metadata(name):
    img = Image.open(ASSETS / name)
    assert img.info.get("Author") == AUTHOR
    assert img.info.get("Copyright") == AUTHOR


def test_readme_jpeg_has_author_metadata():
    img = Image.open(ASSETS / "readme-splash.jpg")
    exif = img.getexif()
    assert exif[0x013B] == AUTHOR
    assert exif[0x8298] == AUTHOR


def test_oscilloscope_colors_are_patina():
    from kira.ui import _gpu_scan_dialog as scan
    from kira.ui.hud_qt import WAVE_COLOR
    assert WAVE_COLOR.name() == "#278390"
    assert scan._NEON.name() == "#278390"
    assert scan._TEXT.name() == "#dae5e7"
