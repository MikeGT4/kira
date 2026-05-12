"""PyQt6 frameless, translucent oscilloscope HUD near cursor.

Windows port of Mac ui/popup.py. Shows the last ~240 raw audio sample
peaks as a 2-px pixel-sharp polyline in digital-roots green — rendered
without antialiasing so the line stays crisp at native resolution.
Click-through, always-on-top.
"""
from __future__ import annotations
import logging
from collections import deque

import numpy as np
from PyQt6.QtCore import Qt, QRect, QTimer, pyqtSignal, QObject, QPointF
from PyQt6.QtGui import QPainter, QColor, QBrush, QPen, QCursor, QFont, QPolygonF
from PyQt6.QtWidgets import QWidget

log = logging.getLogger(__name__)

HUD_W, HUD_H = 260, 80
WF_X, WF_Y = 10, 28
WF_W, WF_H = HUD_W - 20, 42  # 240 x 42 waveform area
MAX_WAVE_POINTS = WF_W       # one sample column per pixel at fill
SAMPLES_PER_BLOCK = 30       # peak-downsample audio blocks to this many points
BG_ALPHA = 220
WAVE_COLOR = QColor(60, 220, 110)  # digitalroots green, neon variant


class _HudSignals(QObject):
    """Cross-thread signals to marshal calls onto the Qt main thread."""
    show_at_cursor = pyqtSignal(str)
    update_status = pyqtSignal(str)
    push_samples = pyqtSignal(object)  # np.ndarray
    hide_hud = pyqtSignal()


class PopupHUD(QWidget):
    """Frameless translucent oscilloscope HUD.

    Public API mirrors the Mac PopupHUD (show / update_status / hide) plus
    a Windows-specific `push_samples(np.ndarray)` that takes a raw mono
    audio block. The HUD downsamples to peak amplitudes and rolls the
    resulting points across the wave area.
    """

    def __init__(self) -> None:
        super().__init__()
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.resize(HUD_W, HUD_H)
        self._status: str = ""
        self._wave: deque[float] = deque(maxlen=MAX_WAVE_POINTS)

        self._sig = _HudSignals()
        self._sig.show_at_cursor.connect(self._on_show)
        self._sig.update_status.connect(self._on_update_status)
        self._sig.push_samples.connect(self._on_push_samples)
        self._sig.hide_hud.connect(self._on_hide)

        self._repaint_timer = QTimer(self)
        self._repaint_timer.setInterval(33)
        self._repaint_timer.timeout.connect(self.update)

    # ---- public API (thread-safe via signals) ----
    def show(self, status: str = "Recording…") -> None:
        self._sig.show_at_cursor.emit(status)

    def update_status(self, status: str) -> None:
        self._sig.update_status.emit(status)

    def push_samples(self, samples) -> None:
        """Push a block of raw audio samples (np.ndarray, 1-D, float32)."""
        self._sig.push_samples.emit(samples)

    def hide(self) -> None:
        self._sig.hide_hud.emit()

    # ---- Qt main-thread slots ----
    def _on_show(self, status: str) -> None:
        self._status = status
        self._wave.clear()
        pos = QCursor.pos()
        self.move(pos.x() + 14, pos.y() - HUD_H - 8)
        super().show()
        self._repaint_timer.start()

    def _on_update_status(self, status: str) -> None:
        self._status = status
        self.update()

    def _on_push_samples(self, samples) -> None:
        try:
            arr = np.asarray(samples, dtype=np.float32).reshape(-1)
            if arr.size == 0:
                return
            # Peak-downsample: split into N chunks, keep the most-extreme
            # sample of each. Preserves wave envelope vs. stride sampling
            # which would alias.
            n = min(SAMPLES_PER_BLOCK, arr.size)
            chunks = np.array_split(arr, n)
            peaks = [float(c[np.argmax(np.abs(c))]) for c in chunks]
        except Exception:
            log.exception("push_samples failed")
            return
        self._wave.extend(peaks)

    def _on_hide(self) -> None:
        self._repaint_timer.stop()
        super().hide()

    # ---- paint ----
    def paintEvent(self, _event) -> None:
        p = QPainter(self)

        # Background + status text use AA for smooth rounded corners and
        # readable typography.
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        bg = QColor(12, 12, 12, BG_ALPHA)
        p.setBrush(QBrush(bg))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawRoundedRect(self.rect(), 8.0, 8.0)

        p.setPen(QPen(QColor(255, 255, 255, 220)))
        p.setFont(QFont("Segoe UI", 9))
        p.drawText(QRect(10, 6, HUD_W - 20, 18), Qt.AlignmentFlag.AlignLeft, self._status)

        if len(self._wave) < 2:
            return

        # Wave: AA off so the 2-px line stays pixel-sharp instead of feathered.
        p.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        pen = QPen(WAVE_COLOR)
        pen.setWidth(2)
        pen.setCapStyle(Qt.PenCapStyle.SquareCap)
        pen.setJoinStyle(Qt.PenJoinStyle.MiterJoin)
        p.setPen(pen)

        cy = WF_Y + WF_H // 2
        half = WF_H // 2 - 2
        n = len(self._wave)
        x_step = WF_W / (n - 1)
        poly = QPolygonF()
        for i, s in enumerate(self._wave):
            x = WF_X + i * x_step
            y = cy + s * half
            poly.append(QPointF(x, y))
        p.drawPolyline(poly)
