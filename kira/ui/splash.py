"""Start screen: shows the splash image centred for a few seconds."""
from __future__ import annotations
import logging
from AppKit import (
    NSBackingStoreBuffered,
    NSFloatingWindowLevel,
    NSImage,
    NSImageScaleProportionallyUpOrDown,
    NSImageView,
    NSMakeRect,
    NSWindow,
    NSWindowStyleMaskBorderless,
)
from PyObjCTools import AppHelper
from kira.ui.menubar import ASSETS

log = logging.getLogger(__name__)

SPLASH_FILE = "kira-splash-macos.png"
SPLASH_W = 560
SPLASH_SECONDS = 3.0


def show_splash(seconds: float = SPLASH_SECONDS):
    """Show the splash window and schedule its removal; returns the window or None."""
    path = ASSETS / SPLASH_FILE
    image = NSImage.alloc().initWithContentsOfFile_(str(path))
    if image is None:
        log.warning("splash image missing: %s", path)
        return None
    size = image.size()
    height = SPLASH_W * size.height / size.width if size.width else SPLASH_W * 0.57
    rect = NSMakeRect(0, 0, SPLASH_W, height)
    window = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
        rect, NSWindowStyleMaskBorderless, NSBackingStoreBuffered, False
    )
    window.setLevel_(NSFloatingWindowLevel)
    window.setHidesOnDeactivate_(False)
    window.setHasShadow_(True)
    window.setIgnoresMouseEvents_(True)
    window.setReleasedWhenClosed_(False)
    view = NSImageView.alloc().initWithFrame_(rect)
    view.setImageScaling_(NSImageScaleProportionallyUpOrDown)
    view.setImage_(image)
    window.setContentView_(view)
    window.center()
    window.orderFrontRegardless()
    AppHelper.callLater(seconds, window.orderOut_, None)
    return window
