"""PyQt6 frameless, translucent waveform HUD near cursor.

Windows port of Mac ui/popup.py (NSPanel + NSBezierPath). Same
behavior: float at cursor, show last N RMS samples as a moving
waveform, click-through, always-on-top.
"""
from __future__ import annotations
import logging
from collections import deque
from PyQt6.QtCore import Qt, QRect, QTimer, pyqtSignal, QObject
from PyQt6.QtGui import QPainter, QColor, QBrush, QPen, QCursor, QFont
from PyQt6.QtWidgets import QWidget

log = logging.getLogger(__name__)

HUD_W, HUD_H = 260, 80
MAX_SAMPLES = 40
BG_ALPHA = 220
BAR_COLOR = QColor(255, 214, 0)  # same gold as Mac HUD


class _HudSignals(QObject):
    """Cross-thread signals to marshal calls onto the Qt main thread."""
    show_at_cursor = pyqtSignal(str)
    update_status = pyqtSignal(str)
    push_level = pyqtSignal(float)
    hide_hud = pyqtSignal()


class PopupHUD(QWidget):
    """Frameless translucent HUD. Matches Mac PopupHUD public API."""

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
        self._levels: deque[float] = deque(maxlen=MAX_SAMPLES)

        self._sig = _HudSignals()
        self._sig.show_at_cursor.connect(self._on_show)
        self._sig.update_status.connect(self._on_update_status)
        self._sig.push_level.connect(self._on_push_level)
        self._sig.hide_hud.connect(self._on_hide)

        self._repaint_timer = QTimer(self)
        self._repaint_timer.setInterval(33)
        self._repaint_timer.timeout.connect(self.update)

    # ---- public API (thread-safe via signals) ----
    def show(self, status: str = "Recording…") -> None:
        self._sig.show_at_cursor.emit(status)

    def update_status(self, status: str) -> None:
        self._sig.update_status.emit(status)

    def push_level(self, level: float) -> None:
        self._sig.push_level.emit(level)

    def hide(self) -> None:
        self._sig.hide_hud.emit()

    # ---- Qt main-thread slots ----
    def _on_show(self, status: str) -> None:
        self._status = status
        self._levels.clear()
        pos = QCursor.pos()
        self.move(pos.x() + 14, pos.y() - HUD_H - 8)
        super().show()
        self._repaint_timer.start()

    def _on_update_status(self, status: str) -> None:
        self._status = status
        self.update()

    def _on_push_level(self, level: float) -> None:
        self._levels.append(float(level))

    def _on_hide(self) -> None:
        self._repaint_timer.stop()
        super().hide()

    # ---- paint ----
    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        bg = QColor(12, 12, 12, BG_ALPHA)
        p.setBrush(QBrush(bg))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawRoundedRect(self.rect(), 8.0, 8.0)

        p.setPen(QPen(QColor(255, 255, 255, 220)))
        p.setFont(QFont("Segoe UI", 9))
        p.drawText(QRect(10, 6, HUD_W - 20, 18), Qt.AlignmentFlag.AlignLeft, self._status)

        if not self._levels:
            return
        wf_rect = QRect(10, 28, HUD_W - 20, 42)
        p.setBrush(QBrush(BAR_COLOR))
        n = len(self._levels)
        bar_w = wf_rect.width() / max(n, 1)
        cy = wf_rect.center().y()
        for i, lvl in enumerate(self._levels):
            bh = max(2, min(wf_rect.height() - 4, wf_rect.height() * lvl * 3.0))
            x = int(wf_rect.left() + i * bar_w)
            y = int(cy - bh / 2)
            p.drawRect(x + 1, y, max(int(bar_w) - 2, 1), int(bh))
