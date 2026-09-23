# © 2026 Mike Pollow, Digitalroots. Alle Rechte vorbehalten.
"""Stil „Klassisch“: die Anzeige bis v0.4.0, unverändert im Verhalten.

Patina-Linie aus je 30 Spitzen pro 100-ms-Block, Statustext in Segoe UI,
kein Ausblenden, keine Warnungen; Fehler zeigen sich wie bisher nur im Tray.
Wie in v0.4.0 läuft die Kurve nach dem Loslassen weiter, und die Anzeige
bleibt mit „Polishing…“ stehen, bis Kira wieder bereit ist.
"""
from __future__ import annotations

import numpy as np
from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen

from kira.ui.hud.base import W, H, Frame, HudStyle

WAVE_COLOR = QColor(0x27, 0x83, 0x90)   # Patina „mittel“ #278390
MAX_POINTS = 240
PEAKS_PER_BLOCK = 30
BLOCK = 1600


class Klassisch(HudStyle):
    key = "klassisch"
    shows_errors = False

    def __init__(self) -> None:
        super().__init__()
        self._wave: list[float] = []
        self._block = 0

    def on_press(self, t: float, f: Frame) -> None:
        self._wave.clear()
        self._block = -1

    def done(self, t: float, f: Frame) -> None:
        """Beim Einfügen stehen bleiben; erst IDLE (abort) blendet aus."""

    def abort(self, t: float) -> None:
        self.mode = "hidden"

    def step(self, t: float, dt: float, f: Frame, tap, an) -> None:
        if self.mode not in ("rec", "proc"):
            return
        current = tap.position // BLOCK
        if self._block < 0:
            self._block = current
            return
        while self._block < current:
            block = tap.tail(BLOCK, end=(self._block + 1) * BLOCK)
            for chunk in np.array_split(block, PEAKS_PER_BLOCK):
                self._wave.append(float(chunk[np.argmax(np.abs(chunk))]))
            del self._wave[:-MAX_POINTS]
            self._block += 1

    def paint(self, p: QPainter, t: float, f: Frame, tap, an) -> None:
        path = QPainterPath()
        path.addRoundedRect(QRectF(0, 0, W, H), 8, 8)
        p.fillPath(path, QColor(12, 12, 12, 220))
        font = QFont("Segoe UI")
        font.setPointSize(9)
        p.setFont(font)
        p.setPen(QColor(255, 255, 255, 220))
        if self.mode == "rec":
            status = "Recording…"
        else:
            status = "Polishing…" if f.polishing else "Transcribing…"
        p.drawText(QRectF(10, 6, W - 20, 18), int(Qt.AlignmentFlag.AlignLeft), status)
        n = len(self._wave)
        if n < 2:
            return
        p.save()
        p.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        pen = QPen(WAVE_COLOR)
        pen.setWidth(2)
        pen.setCapStyle(Qt.PenCapStyle.SquareCap)
        pen.setJoinStyle(Qt.PenJoinStyle.MiterJoin)
        p.setPen(pen)
        step = 240 / (n - 1)
        points = [QPointF(10 + i * step, 49 + s * 19) for i, s in enumerate(self._wave)]
        p.drawPolyline(points)
        p.restore()
