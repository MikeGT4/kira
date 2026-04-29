"""Boot splash with the Kira branding image.

Fills the visual gap between launch and tray-icon-ready (Qt init,
Whisper DLL warmup, Ollama probe, optional welcome/setup-hint dialogs)
on every launch — unlike the Welcome dialog, which only shows once per
user.

Implementation note: QSplashScreen sits on a top-level frameless window
with WindowStaysOnTop; modal dialogs (Welcome, SetupHint) still draw
above it because they're modal. The splash is dismissed manually right
before the Qt event loop starts, so it remains visible during all the
early init work.
"""
from __future__ import annotations
from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import QSplashScreen


_ASSETS = Path(__file__).resolve().parent.parent.parent / "assets"


def make_splash() -> QSplashScreen | None:
    """Build and show the splash; returns None if the splash asset is missing.

    Caller should call qt_app.processEvents() once after this so the splash
    actually paints before any blocking work (Whisper warmup etc.) starts.
    Caller is responsible for closing the splash via splash.close() when
    the tray icon is up.
    """
    splash_path = _ASSETS / "kira-splash.png"
    if not splash_path.exists():
        # Backwards-compat fallback to the bare digital-roots logo for
        # installs from older bundles that don't ship kira-splash.png yet.
        splash_path = _ASSETS / "digitalroots-logo.png"
        if not splash_path.exists():
            return None
    pix = QPixmap(str(splash_path))
    # 720 px wide gives a 16:9 splash a comfortable on-screen footprint
    # without dominating the desktop on smaller laptop displays.
    pix = pix.scaledToWidth(720, Qt.TransformationMode.SmoothTransformation)
    splash = QSplashScreen(pix, Qt.WindowType.WindowStaysOnTopHint)
    splash.show()
    return splash
