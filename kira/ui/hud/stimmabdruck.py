# © 2026 Mike Pollow, Digitalroots. Alle Rechte vorbehalten.
"""Stil „Stimmabdruck“: Spektrogramm als Wasserfall, wie bei der Stimmanalyse.

90 Hz bis 5 kHz über rund 4 s; Silben und Obertöne erscheinen als Streifen.
Darunter ein Lichtbalken mit Zielbereich −9 bis −2 dBFS, dem Lichtbalken mit
Mittelmarke der Teenage Engineering OP-1 field nachempfunden. Nach dem
Loslassen liest ein Abtaster den eingefrorenen Abdruck, zum Schluss setzt ein
Stempel „M“ den Haken.
"""
from __future__ import annotations

import numpy as np
from PyQt6.QtCore import QPointF, QRectF
from PyQt6.QtGui import QColor, QImage, QLinearGradient, QPainter, QPainterPath, QPen

from kira.ui.hud.base import (
    AMBER,
    EASE_IN_OUT,
    EASE_OUT,
    LINE,
    PATINA,
    RED,
    SHELL,
    WHITE,
    Frame,
    HudStyle,
    check_mark,
    clamp,
    draw_text,
    fmt_time,
    lerp,
    mix,
    mono,
    prog,
    qc,
    rec_square,
    shell,
    text_width,
)
from kira.ui.hud.signal import BIN_HZ

DX, DY, DW, DH = 8.0, 24.0, 244.0, 40.0
SPEED = 60.0                      # Entwurfs-Pixel je Sekunde, 244 px ≈ 4 s
F_LO, F_HI = 90.0, 5000.0


def _lut() -> np.ndarray:
    stops = [(0.0, (21, 70, 77), 0.0), (0.2, (21, 70, 77), 0.0), (0.4, (21, 70, 77), 0.9),
             (0.62, (39, 131, 144), 1.0), (0.82, (150, 205, 212), 1.0), (1.0, (255, 255, 255), 1.0)]
    out = np.zeros((256, 4), dtype=np.uint8)
    for i in range(256):
        v = i / 255
        k = 0
        while k < len(stops) - 2 and v > stops[k + 1][0]:
            k += 1
        a, b = stops[k], stops[k + 1]
        q = clamp((v - a[0]) / (b[0] - a[0] or 1), 0, 1)
        rgb = [round(lerp(a[1][c], b[1][c], q)) for c in range(3)]
        out[i] = (*rgb, round(255 * lerp(a[2], b[2], q)))
    return out


LUT = _lut()


class Stimmabdruck(HudStyle):
    key = "stimmabdruck"

    def __init__(self) -> None:
        super().__init__()
        self._buf: np.ndarray | None = None
        self._img: QImage | None = None
        self._px = 0.0
        self._bins: np.ndarray | None = None
        self._acc = 0.0

    def _ensure(self, f: Frame) -> None:
        if self._buf is not None and self._px == f.px:
            return
        w = max(1, round(DW * f.px))
        h = max(1, round(DH * f.px))
        self._buf = np.zeros((h, w, 4), dtype=np.uint8)
        rows = 1 - (np.arange(h) + 0.5) / h
        self._bins = F_LO * np.power(F_HI / F_LO, rows) / BIN_HZ
        self._px = f.px
        self._img = QImage(self._buf.data, w, h, w * 4, QImage.Format.Format_RGBA8888)
        self._acc = 0.0

    def on_press(self, t: float, f: Frame) -> None:
        self._ensure(f)
        self._buf[:] = 0
        self._acc = 0.0

    def on_error(self, t: float, f: Frame) -> None:
        if self._buf is None:
            return
        rgb = self._buf[..., :3].astype(np.float32)
        red = np.array(RED, dtype=np.float32)
        self._buf[..., :3] = (rgb * 0.25 + red * 0.75).astype(np.uint8)

    def step(self, t: float, dt: float, f: Frame, tap, an) -> None:
        if self.mode == "done" and t - self.end_t > (0.4 if f.reduced else 0.46):
            self.mode = "hidden"
            return
        self._ensure(f)
        if self.mode != "rec":
            return
        self._acc += SPEED * dt * f.px
        n = int(self._acc)
        if n <= 0:
            return
        self._acc -= n
        buf = self._buf
        n = min(n, buf.shape[1])
        buf[:, :-n] = buf[:, n:]
        vals = np.interp(self._bins, np.arange(an.spectrum.size), an.spectrum)
        col = LUT[np.minimum(255, (vals * 255).astype(int))]
        buf[:, -n:] = col[:, None, :]

    def paint(self, p: QPainter, t: float, f: Frame, tap, an) -> None:
        reduced = f.reduced
        u = t - self.t0
        sh_a, wipe, stamp = 1.0, 1.0, 0.0
        if self.mode == "rec" and reduced:
            sh_a = clamp(u / 0.12, 0, 1)
        if self.mode == "done":
            v = t - self.end_t
            if reduced:
                sh_a, stamp = 1 - prog(v, 0.25, 0.15), 1.0
            else:
                stamp = EASE_OUT(prog(v, 0, 0.12))
                wipe = 1 - EASE_IN_OUT(prog(v, 0.18, 0.18))
                sh_a = 1 - prog(v, 0.34, 0.12)
        if self.mode == "error":
            sh_a = self.error_alpha(t)
        shell(p, sh_a)
        if sh_a <= 0:
            return
        p.save()
        p.setOpacity(p.opacity() * sh_a)
        area = QPainterPath()
        area.addRoundedRect(QRectF(DX, DY, DW, DH), 3, 3)
        p.fillPath(area, qc(LINE, 0.035))

        p.save()
        p.setClipRect(QRectF(DX, DY, DW * wipe, DH))
        if self._img is not None:
            p.setOpacity(p.opacity() * (0.78 if self.mode == "proc" else 1.0))
            p.drawImage(QRectF(DX, DY, DW, DH), self._img, QRectF(self._img.rect()))
        p.restore()
        if self.mode == "rec" and an.silent:
            pen = QPen(qc(AMBER, 0.5), 1.0)
            pen.setDashPattern([2.0, 3.0])
            p.setPen(pen)
            p.drawLine(QPointF(DX, DY + DH / 2 + 0.5), QPointF(DX + DW, DY + DH / 2 + 0.5))
        if self.mode == "proc" and not reduced:
            x = DX + DW * (((t - self.rel_t) / 0.9) % 1.0)
            p.save()
            p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Plus)
            lg = QLinearGradient(x - 26, 0, x, 0)
            lg.setColorAt(0, qc(PATINA, 0))
            lg.setColorAt(1, qc(PATINA, 0.42))
            p.fillRect(QRectF(max(DX, x - 26), DY, min(26.0, x - DX), DH), lg)
            p.fillRect(QRectF(x, DY, 1, DH), qc(LINE, 0.85))
            p.restore()
        if self.mode == "rec":
            head = RED if an.clip else LINE
            p.fillRect(QRectF(DX + DW - 1, DY, 1, DH), qc(head, 0.35 + 0.6 * an.level))
            tri = QPainterPath(QPointF(DX + DW - 4, DY - 3))
            tri.lineTo(DX + DW + 2, DY - 3)
            tri.lineTo(DX + DW - 1, DY + 0.5)
            tri.closeSubpath()
            p.fillPath(tri, qc(head, 0.35 + 0.6 * an.level))
        if stamp > 0:
            s = lerp(0.92, 1.0, stamp)
            bx, by = DX + DW - 40, DY + DH / 2 - 9
            p.save()
            p.translate(bx + 18, by + 9)
            p.scale(s, s)
            p.translate(-(bx + 18), -(by + 9))
            p.setOpacity(p.opacity() * stamp)
            box = QPainterPath()
            box.addRoundedRect(QRectF(bx, by, 36, 18), 3, 3)
            p.fillPath(box, qc(SHELL, 0.85))
            p.strokePath(box, QPen(qc(LINE, 0.9), 1.0))
            draw_text(p, bx + 7, by + 13, "M", mono(11, 600, 0.0), qc(LINE, 1.0))
            check_mark(p, bx + 19, by + 5, 9, LINE)
            p.restore()
        if self.mode == "error":
            p.fillRect(QRectF(DX, DY, DW, DH), qc(SHELL, 0.74))
            first, second = self.message_lines()
            msg = mono(10.5, 400, 0.2)
            draw_text(p, DX + DW / 2, DY + 17, first, msg, qc(WHITE, 0.95), "center")
            draw_text(p, DX + DW / 2, DY + 31, second, msg, qc(WHITE, 0.7), "center")

        ty = 71.0

        def pos(db: float) -> float:
            return DX + DW * clamp((db + 48) / 48, 0, 1)

        p.fillRect(QRectF(DX, ty, DW, 2), qc(LINE, 0.08))
        p.fillRect(QRectF(pos(-9), ty - 2, pos(-2) - pos(-9), 6), qc(LINE, 0.07))
        p.fillRect(QRectF(round(pos(-9)), ty - 3, 1, 8), qc(LINE, 0.42))
        p.fillRect(QRectF(round(pos(-2)), ty - 3, 1, 8), qc(LINE, 0.42))
        if self.mode == "rec" and not an.silent:
            length = DW * an.level
            lg = QLinearGradient(DX, 0, DX + max(1.0, length), 0)
            lg.setColorAt(0, qc(PATINA, 0.1))
            lg.setColorAt(0.75, qc(PATINA, 0.9))
            lg.setColorAt(1, qc(RED if an.clip else mix(LINE, WHITE, 0.3), 1.0))
            p.fillRect(QRectF(DX, ty, length, 2), lg)
            p.fillRect(QRectF(DX, ty - 1, length, 4), qc(RED if an.clip else PATINA, 0.25))

        shown, target, color = self.status_text(t, f, an)
        if self.mode == "rec":
            rec_square(p, DX + 2, 9, t, AMBER if an.silent else RED, reduced)
        else:
            p.fillRect(QRectF(DX + 2, 9, 6, 6), qc(RED if self.mode == "error" else PATINA, 0.95))
        font = mono(11, 500, 0.6)
        draw_text(p, DX + 14, 15, shown, font, qc(color, 0.94))
        if self.mode == "done" and shown == target:
            check_mark(p, DX + 14 + text_width(font, target) + 6, 7, 9, PATINA)
        draw_text(p, DX + DW, 15, fmt_time(self.elapsed(t)), mono(11, 400, 0.2),
                  qc(LINE, 0.66 if self.mode == "rec" else 0.4), "right")
        p.restore()
