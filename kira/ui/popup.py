"""Floating oscilloscope HUD near the cursor: dark panel, status text, green trace."""
from __future__ import annotations
import logging
import threading
from collections import deque
import numpy as np
import objc
from AppKit import (
    NSPanel,
    NSBackingStoreBuffered,
    NSWindowStyleMaskBorderless,
    NSWindowStyleMaskNonactivatingPanel,
    NSWindowCollectionBehaviorCanJoinAllSpaces,
    NSWindowCollectionBehaviorFullScreenAuxiliary,
    NSWindowCollectionBehaviorStationary,
    NSWindowCollectionBehaviorIgnoresCycle,
    NSFloatingWindowLevel,
    NSColor,
    NSView,
    NSBezierPath,
    NSGraphicsContext,
    NSMakeRect,
    NSMakePoint,
    NSTextField,
    NSFont,
    NSScreen,
    NSSquareLineCapStyle,
    NSMiterLineJoinStyle,
)
from PyObjCTools import AppHelper
from Quartz import CGEventCreate, CGEventGetLocation

log = logging.getLogger(__name__)

HUD_W, HUD_H = 260, 80
WF_X, WF_Y, WF_W, WF_H = 10, 10, 240, 42
LABEL_Y, LABEL_H = 56, 18
MAX_WAVE_POINTS = WF_W
SAMPLES_PER_BLOCK = 30
BG_COLOR = (12 / 255, 12 / 255, 12 / 255, 220 / 255)
WAVE_COLOR = (60 / 255, 220 / 255, 110 / 255, 1.0)


def _peaks(samples, n: int = SAMPLES_PER_BLOCK) -> list[float]:
    """Downsample a block to its n most extreme samples, one per chunk."""
    arr = np.asarray(samples, dtype=np.float32).reshape(-1)
    if arr.size == 0:
        return []
    chunks = np.array_split(arr, min(n, arr.size))
    return [float(c[np.argmax(np.abs(c))]) for c in chunks]


def _on_main(fn, *args, **kwargs):
    """Run ``fn(*args, **kwargs)`` on the AppKit main thread (fire-and-forget)."""
    if threading.current_thread() is threading.main_thread():
        try:
            fn(*args, **kwargs)
        except Exception:
            log.exception("main-thread call raised")
        return
    AppHelper.callAfter(lambda: fn(*args, **kwargs))


class HudView(NSView):
    """Rounded dark background for the whole panel."""

    def drawRect_(self, dirty_rect):
        NSColor.colorWithCalibratedRed_green_blue_alpha_(*BG_COLOR).set()
        NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(self.bounds(), 8.0, 8.0).fill()


class WaveformView(NSView):
    """Rolling 2 px trace of peak samples, drawn without antialiasing."""

    def initWithFrame_(self, frame):
        self = objc.super(WaveformView, self).initWithFrame_(frame)
        if self is None:
            return None
        self._wave = deque(maxlen=MAX_WAVE_POINTS)
        return self

    def pushPeaks_(self, peaks):
        self._wave.extend(peaks)
        self.setNeedsDisplay_(True)

    def clear(self):
        self._wave.clear()
        self.setNeedsDisplay_(True)

    def drawRect_(self, dirty_rect):
        n = len(self._wave)
        if n < 2:
            return
        bounds = self.bounds()
        w, h = bounds.size.width, bounds.size.height
        cy = h / 2
        half = h / 2 - 2
        step = w / (n - 1)
        ctx = NSGraphicsContext.currentContext()
        ctx.saveGraphicsState()
        ctx.setShouldAntialias_(False)
        path = NSBezierPath.bezierPath()
        path.setLineWidth_(2.0)
        path.setLineCapStyle_(NSSquareLineCapStyle)
        path.setLineJoinStyle_(NSMiterLineJoinStyle)
        for i, s in enumerate(self._wave):
            point = NSMakePoint(i * step, cy + s * half)
            if i == 0:
                path.moveToPoint_(point)
            else:
                path.lineToPoint_(point)
        NSColor.colorWithCalibratedRed_green_blue_alpha_(*WAVE_COLOR).set()
        path.stroke()
        ctx.restoreGraphicsState()


class PopupHUD:
    """Floating panel positioned near the cursor. Thread-safe public API."""

    def __init__(self) -> None:
        self._panel = None
        self._waveform = None
        self._label = None

    def _ensure_panel(self) -> None:
        if self._panel is not None:
            return
        rect = NSMakeRect(0, 0, HUD_W, HUD_H)
        self._panel = NSPanel.alloc().initWithContentRect_styleMask_backing_defer_(
            rect, NSWindowStyleMaskBorderless | NSWindowStyleMaskNonactivatingPanel, NSBackingStoreBuffered, False
        )
        self._panel.setFloatingPanel_(True)
        self._panel.setHidesOnDeactivate_(False)
        self._panel.setCollectionBehavior_(
            NSWindowCollectionBehaviorCanJoinAllSpaces
            | NSWindowCollectionBehaviorFullScreenAuxiliary
            | NSWindowCollectionBehaviorStationary
            | NSWindowCollectionBehaviorIgnoresCycle
        )
        self._panel.setOpaque_(False)
        self._panel.setBackgroundColor_(NSColor.clearColor())
        self._panel.setLevel_(NSFloatingWindowLevel)
        self._panel.setHasShadow_(True)
        self._panel.setIgnoresMouseEvents_(True)

        content = HudView.alloc().initWithFrame_(rect)
        self._waveform = WaveformView.alloc().initWithFrame_(NSMakeRect(WF_X, WF_Y, WF_W, WF_H))
        content.addSubview_(self._waveform)

        self._label = NSTextField.alloc().initWithFrame_(NSMakeRect(WF_X, LABEL_Y, WF_W, LABEL_H))
        self._label.setStringValue_("")
        self._label.setBezeled_(False)
        self._label.setDrawsBackground_(False)
        self._label.setEditable_(False)
        self._label.setSelectable_(False)
        self._label.setTextColor_(NSColor.colorWithCalibratedWhite_alpha_(1.0, 220 / 255))
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
        self._waveform.clear()
        self._panel.orderFrontRegardless()

    def _do_update_status(self, status: str) -> None:
        if self._label:
            self._label.setStringValue_(status)

    def _do_push_peaks(self, peaks) -> None:
        if self._waveform:
            self._waveform.pushPeaks_(peaks)

    def _do_hide(self) -> None:
        if self._panel:
            self._panel.orderOut_(None)

    def show(self, status: str = "Recording…") -> None:
        _on_main(self._do_show, status)

    def update_status(self, status: str) -> None:
        _on_main(self._do_update_status, status)

    def push_samples(self, samples) -> None:
        peaks = _peaks(samples)
        if peaks:
            _on_main(self._do_push_peaks, peaks)

    def hide(self) -> None:
        _on_main(self._do_hide)
