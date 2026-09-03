"""Floating popup HUD near cursor. Shows live waveform + status text."""
from __future__ import annotations
import logging
import threading
from AppKit import (
    NSPanel,
    NSBackingStoreBuffered,
    NSWindowStyleMaskBorderless,
    NSFloatingWindowLevel,
    NSColor,
    NSView,
    NSBezierPath,
    NSMakeRect,
    NSMakePoint,
    NSTextField,
    NSFont,
    NSScreen,
)
from PyObjCTools import AppHelper
from Quartz import CGEventCreate, CGEventGetLocation

log = logging.getLogger(__name__)


def _on_main(fn, *args, **kwargs):
    """Run ``fn(*args, **kwargs)`` on the AppKit main thread (fire-and-forget)."""
    if threading.current_thread() is threading.main_thread():
        try:
            fn(*args, **kwargs)
        except Exception:
            log.exception("main-thread call raised")
        return
    AppHelper.callAfter(lambda: fn(*args, **kwargs))


class WaveformView(NSView):
    """Draws a simple moving waveform from RMS samples."""

    def initWithFrame_(self, frame):
        self = super().initWithFrame_(frame)
        if self is None:
            return None
        self._levels = []
        self._max_samples = 40
        return self

    def pushLevel_(self, level):
        self._levels.append(float(level))
        if len(self._levels) > self._max_samples:
            self._levels = self._levels[-self._max_samples:]
        self.setNeedsDisplay_(True)

    def drawRect_(self, dirty_rect):
        bounds = self.bounds()
        NSColor.colorWithCalibratedWhite_alpha_(0.05, 0.85).set()
        path = NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(bounds, 8.0, 8.0)
        path.fill()
        w = bounds.size.width
        h = bounds.size.height
        n = max(len(self._levels), 1)
        bar_w = w / max(n, 1)
        NSColor.colorWithCalibratedRed_green_blue_alpha_(1.0, 0.84, 0.0, 1.0).set()
        for i, lvl in enumerate(self._levels):
            bh = max(2, min(h - 4, h * lvl * 3.0))
            x = i * bar_w
            y = (h - bh) / 2
            NSBezierPath.fillRect_(NSMakeRect(x + 1, y, max(bar_w - 2, 1), bh))


class PopupHUD:
    """Floating popup positioned near cursor. Thread-safe public API."""

    def __init__(self) -> None:
        self._panel = None
        self._waveform = None
        self._label = None

    def _ensure_panel(self) -> None:
        if self._panel is not None:
            return
        rect = NSMakeRect(0, 0, 260, 80)
        self._panel = NSPanel.alloc().initWithContentRect_styleMask_backing_defer_(
            rect, NSWindowStyleMaskBorderless, NSBackingStoreBuffered, False
        )
        self._panel.setOpaque_(False)
        self._panel.setBackgroundColor_(NSColor.clearColor())
        self._panel.setLevel_(NSFloatingWindowLevel)
        self._panel.setHasShadow_(True)
        self._panel.setIgnoresMouseEvents_(True)

        content = NSView.alloc().initWithFrame_(rect)
        self._waveform = WaveformView.alloc().initWithFrame_(NSMakeRect(10, 30, 240, 40))
        content.addSubview_(self._waveform)

        self._label = NSTextField.alloc().initWithFrame_(NSMakeRect(10, 6, 240, 20))
        self._label.setStringValue_("")
        self._label.setBezeled_(False)
        self._label.setDrawsBackground_(False)
        self._label.setEditable_(False)
        self._label.setSelectable_(False)
        self._label.setTextColor_(NSColor.whiteColor())
        self._label.setFont_(NSFont.systemFontOfSize_(11))
        content.addSubview_(self._label)
        self._panel.setContentView_(content)

    def _cursor_location(self):
        """Return (x, y) in Cocoa window coords (origin bottom-left)."""
        loc = CGEventGetLocation(CGEventCreate(None))
        for screen in NSScreen.screens():
            frame = screen.frame()
            if (frame.origin.x <= loc.x < frame.origin.x + frame.size.width and
                frame.origin.y <= loc.y < frame.origin.y + frame.size.height):
                flipped_y = frame.size.height - loc.y + frame.origin.y
                return float(loc.x) + 14, float(flipped_y) - 90
        main = NSScreen.mainScreen()
        flipped_y = main.frame().size.height - loc.y
        return float(loc.x) + 14, float(flipped_y) - 90


    def _do_show(self, status: str) -> None:
        self._ensure_panel()
        x, y = self._cursor_location()
        self._panel.setFrameOrigin_(NSMakePoint(x, y))
        self._label.setStringValue_(status)
        self._waveform._levels = []
        self._waveform.setNeedsDisplay_(True)
        self._panel.orderFrontRegardless()

    def _do_update_status(self, status: str) -> None:
        if self._label:
            self._label.setStringValue_(status)

    def _do_push_level(self, level: float) -> None:
        if self._waveform:
            self._waveform.pushLevel_(level)

    def _do_hide(self) -> None:
        if self._panel:
            self._panel.orderOut_(None)


    def show(self, status: str = "Recording…") -> None:
        _on_main(self._do_show, status)

    def update_status(self, status: str) -> None:
        _on_main(self._do_update_status, status)

    def push_level(self, level: float) -> None:
        _on_main(self._do_push_level, float(level))

    def hide(self) -> None:
        _on_main(self._do_hide)
