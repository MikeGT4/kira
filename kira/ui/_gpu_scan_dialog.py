"""Animierter GPU-Check-Wartedialog im Kira-Oszilloskop-Look.

SettingsDialog._run_gpu_check zeigt diesen Dialog waehrend des
Hintergrund-GPU-Checks. nvidia-smi kann unter GPU-Last mehrere
Sekunden brauchen; statt eines statischen Hinweises laeuft hier eine
scrollende Neon-Sinuswelle — digitalroots-Gruen, pixel-scharf wie das
HUD-Oszilloskop (kira/ui/hud_qt.py, dieselbe Wellenfarbe).
"""
from __future__ import annotations
import math

from PyQt6.QtCore import Qt, QRect, QTimer, QPointF
from PyQt6.QtGui import QPainter, QColor, QBrush, QPen, QFont, QPolygonF
from PyQt6.QtWidgets import QDialog, QVBoxLayout, QWidget

# digitalroots-Neon-Gruen — identisch zu hud_qt.WAVE_COLOR.
_NEON = QColor(60, 220, 110)
_PANEL_W, _PANEL_H = 320, 132


class _ScanWidget(QWidget):
    """Dunkles Panel mit scrollender Neon-Sinuswelle + Statuszeile.

    Ein QTimer (~30 fps) treibt die Wellen-Phase voran; jeder Tick
    schiebt die ueberlagerten Sinusschwingungen weiter, sodass die
    Welle nach links durchlaeuft."""

    def __init__(self) -> None:
        super().__init__()
        self.setFixedSize(_PANEL_W, _PANEL_H)
        self._phase = 0.0
        self._timer = QTimer(self)
        self._timer.setInterval(33)
        self._timer.timeout.connect(self._tick)

    def start(self) -> None:
        self._timer.start()

    def stop(self) -> None:
        self._timer.stop()

    def _tick(self) -> None:
        self._phase += 0.22
        self.update()

    def paintEvent(self, _event) -> None:
        p = QPainter(self)

        # Panel + Text mit AA: glatter Rahmen, lesbare Schrift.
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setBrush(QBrush(QColor(12, 12, 12)))
        p.setPen(QPen(QColor(60, 220, 110, 110), 1))
        p.drawRect(0, 0, _PANEL_W - 1, _PANEL_H - 1)

        p.setPen(QPen(_NEON))
        p.setFont(QFont("Consolas", 10, QFont.Weight.DemiBold))
        p.drawText(
            QRect(0, 16, _PANEL_W, 20),
            Qt.AlignmentFlag.AlignHCenter,
            "GPU wird geprüft…",
        )

        # Wellenfeld.
        wf_x, wf_w = 26, _PANEL_W - 52
        cy, amp = 84, 24

        # Welle ohne AA -> pixel-scharf wie das HUD-Oszilloskop.
        p.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        poly = QPolygonF()
        for px in range(wf_w + 1):
            t = px / wf_w
            y = cy + amp * (
                0.7 * math.sin(t * 6.0 * math.pi - self._phase)
                + 0.3 * math.sin(t * 2.4 * math.pi - self._phase * 0.5)
            )
            poly.append(QPointF(float(wf_x + px), float(y)))

        # Glow (breit, transparent) + Kern (schmal, voll) = Neon-Look.
        glow = QPen(QColor(60, 220, 110, 70))
        glow.setWidth(6)
        glow.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        p.setPen(glow)
        p.drawPolyline(poly)

        core = QPen(_NEON)
        core.setWidth(2)
        core.setCapStyle(Qt.PenCapStyle.SquareCap)
        core.setJoinStyle(Qt.PenJoinStyle.MiterJoin)
        p.setPen(core)
        p.drawPolyline(poly)


class GpuScanDialog(QDialog):
    """Frameless, fenster-modaler Wartedialog mit der Scan-Animation.

    Kein Schliessen-Button — der Dialog lebt nur fuer die Dauer des
    GPU-Checks. SettingsDialog._run_gpu_check ruft start() vor dem
    Worker-Thread-Start und finish() im finished/failed-Handler."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint | Qt.WindowType.Dialog
        )
        self.setWindowModality(Qt.WindowModality.WindowModal)
        self.setFixedSize(_PANEL_W, _PANEL_H)
        self._scan = _ScanWidget()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._scan)

    def start(self) -> None:
        self._scan.start()
        self.show()

    def finish(self) -> None:
        self._scan.stop()
        self.close()
