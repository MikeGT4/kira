# © 2026 Mike Pollow, Digitalroots. Alle Rechte vorbehalten.
"""Stil „Zielerfassung“: Eckklammern suchen die Stimme und rasten ein.

Bildsprache der Film-Interfaces von Jayse Hansen (jayse.io): Eckmarken statt
Rahmen, Mikroschrift, ein einziger Akzent. 44 Frequenzbalken von 90 Hz bis
5 kHz, darüber ein Suchlauf. Sobald die Stimme 80 ms anliegt, rasten die
Klammern federnd ein (LOCK); zum Schluss schnappen sie zum Pixelquadrat aus
dem digitalroots-Logo.
"""
from __future__ import annotations

import math

import numpy as np
from PyQt6.QtCore import QRectF, Qt
from PyQt6.QtGui import QLinearGradient, QPainter, QPainterPath, QPen

from kira.ui.hud.base import (
    AMBER,
    EASE_IN_OUT,
    EASE_OUT,
    LINE,
    PATINA,
    RED,
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

BARS = 44
BX0, BW, BCY = 14.0, 232.0, 44.0
SEARCH = (3.0, 3.0, 257.0, 77.0)
LOCK = (10.0, 23.0, 250.0, 65.0)
CENTER = (112.0, 24.0, 148.0, 60.0)
EDGES = 90.0 * np.power(5000.0 / 90.0, np.arange(BARS + 1) / BARS)


def _lerp_rect(a, b, q):
    return tuple(lerp(a[i], b[i], q) for i in range(4))


class Zielerfassung(HudStyle):
    key = "zielerfassung"

    def __init__(self) -> None:
        super().__init__()
        self._bars = np.zeros(BARS, dtype=np.float32)
        self._x = 0.0
        self._v = 0.0
        self._lock_t = -9.0
        self._was_locked = False
        self._rel_rect = LOCK

    def on_press(self, t: float, f: Frame) -> None:
        self._bars[:] = 0.0
        self._x = self._v = 0.0
        self._lock_t = -9.0
        self._was_locked = False

    def on_release(self, t: float, f: Frame) -> None:
        self._rel_rect = _lerp_rect(SEARCH, LOCK, self._x)

    def step(self, t: float, dt: float, f: Frame, tap, an) -> None:
        if self.mode == "done" and t - self.end_t > (0.4 if f.reduced else 0.44):
            self.mode = "hidden"
            return
        target = 1.0 if (self.mode == "rec" and an.voice) else 0.0
        if f.reduced:
            self._x, self._v = target, 0.0
        else:
            h = dt / 4
            for _ in range(4):
                acc = -900.0 * (self._x - target) - 33.0 * self._v
                self._v += acc * h
                self._x += self._v * h
        locked = self._x > 0.5
        if locked and not self._was_locked and self.mode == "rec":
            self._lock_t = t
        self._was_locked = locked
        decay = 10.0 if self.mode == "rec" else 16.0
        if self.mode == "rec":
            vals = np.array([an.band(EDGES[i], EDGES[i + 1]) for i in range(BARS)], dtype=np.float32)
        else:
            vals = np.zeros(BARS, dtype=np.float32)
        self._bars[:] = np.where(vals > self._bars, vals, np.maximum(vals, self._bars - decay * dt))

    def _brackets(self, p: QPainter, r, color, alpha: float, angle: float) -> None:
        x0, y0, x1, y1 = r
        cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
        arm = min(12.0, (x1 - x0) * 0.3, (y1 - y0) * 0.3)
        p.save()
        p.translate(cx, cy)
        p.rotate(math.degrees(angle))
        p.translate(-cx, -cy)
        pen = QPen(qc(color, alpha), 1.5)
        pen.setCapStyle(Qt.PenCapStyle.SquareCap)
        path = QPainterPath()
        for (ax, ay), (bx, by), (cx2, cy2) in (
            ((x0, y0 + arm), (x0, y0), (x0 + arm, y0)),
            ((x1 - arm, y0), (x1, y0), (x1, y0 + arm)),
            ((x1, y1 - arm), (x1, y1), (x1 - arm, y1)),
            ((x0 + arm, y1), (x0, y1), (x0, y1 - arm)),
        ):
            path.moveTo(ax, ay)
            path.lineTo(bx, by)
            path.lineTo(cx2, cy2)
        p.strokePath(path, pen)
        p.restore()

    def paint(self, p: QPainter, t: float, f: Frame, tap, an) -> None:
        reduced = f.reduced
        u = t - self.t0
        locked = self._x > 0.5
        sh_a, rect, angle, br_a, square, sq_scale, shake = 1.0, _lerp_rect(SEARCH, LOCK, self._x), 0.0, 1.0, 0.0, 1.0, 0.0
        if self.mode == "rec" and reduced:
            sh_a = clamp(u / 0.12, 0, 1)
        if self.mode == "proc":
            v = t - self.rel_t
            q = 1.0 if reduced else EASE_OUT(prog(v, 0, 0.22))
            rect = _lerp_rect(self._rel_rect, CENTER, q)
            if not reduced and v > 0.22:
                w = (v - 0.22) / 0.5
                k = math.floor(w)
                angle = (k + EASE_IN_OUT(clamp((w - k) / 0.44, 0, 1))) * math.pi / 2
        if self.mode == "done":
            v = t - self.end_t
            if reduced:
                sh_a = 1 - prog(v, 0.25, 0.15)
                rect = CENTER
            else:
                q = EASE_OUT(prog(v, 0, 0.14))
                rect = (lerp(112, 126, q), lerp(24, 38, q), lerp(148, 134, q), lerp(60, 46, q))
                br_a = 1 - prog(v, 0.06, 0.08)
                square = prog(v, 0.08, 0.06) * (1 - prog(v, 0.3, 0.12))
                sq_scale = 1 - 0.1 * prog(v, 0.3, 0.12)
                sh_a = 1 - prog(v, 0.32, 0.12)
        if self.mode == "error":
            v = t - self.end_t
            sh_a = self.error_alpha(t)
            rect = LOCK
            if not reduced and v < 0.26:
                shake = 3 * math.sin(2 * math.pi * 14 * v) * (1 - v / 0.26)
        shell(p, sh_a)
        if sh_a <= 0:
            return
        p.save()
        p.setOpacity(p.opacity() * sh_a)

        if self.mode in ("rec", "proc"):
            sweep = -1.0 if reduced else BX0 + BW * ((t * (0.55 if locked else 1.0)) % 1.0)
            if self.mode == "rec" and sweep >= 0:
                x_from = max(BX0, sweep - 44)
                lg = QLinearGradient(sweep - 44, 0, sweep, 0)
                lg.setColorAt(0, qc(PATINA, 0))
                lg.setColorAt(1, qc(PATINA, 0.12 if locked else 0.09))
                p.fillRect(QRectF(x_from, 26, sweep - x_from, 36), lg)
                p.fillRect(QRectF(round(sweep), 25, 1, 38), qc(LINE, 0.5 if locked else 0.32))
            pitch = BW / BARS
            for i in range(BARS):
                x = BX0 + i * pitch + pitch / 2
                v = float(self._bars[i])
                h = max(0.6, v ** 1.6 * 18)
                boost = 0.0 if sweep < 0 else math.exp(-(((x - sweep) / 12) ** 2))
                col = mix(PATINA, LINE, clamp(v * v * 0.7 + boost * 0.3, 0, 1))
                a = 0.25 if (self.mode == "rec" and an.silent) else 0.42 + 0.4 * v + 0.3 * boost
                p.fillRect(QRectF(x - 1.2, BCY - h, 2.4, h * 2), qc(col, a))
            if self.mode == "proc":
                a = 0.85 if reduced else 0.55 + 0.45 * (0.5 + 0.5 * math.sin(t * 2 * math.pi * 1.25))
                p.fillRect(QRectF(128, 40, 4, 4), qc(PATINA, a))

        if self.mode == "error":
            first, second = self.message_lines()
            msg = mono(10.5, 400, 0.2)
            draw_text(p, 130, 42, first, msg, qc(LINE, 0.9), "center")
            draw_text(p, 130, 56, second, msg, qc(LINE, 0.55), "center")

        bcol, ba = LINE, 0.88
        if self.mode == "rec":
            if an.silent:
                bcol, ba = AMBER, 0.75 if reduced else 0.55 + 0.35 * (0.5 + 0.5 * math.cos(2 * math.pi * t))
            elif not locked:
                bcol, ba = PATINA, 0.7
            if an.clip:
                k = math.exp(-(t - an.clip_onset) / 0.3)
                bcol, ba = mix(bcol, RED, 0.5 + 0.5 * k), 0.95
        if self.mode == "error":
            bcol = RED
        r = rect
        if self.mode == "rec" and not locked and not reduced:
            breath = math.sin(t * 2 * math.pi * 0.8)
            r = (r[0] - breath, r[1] - breath, r[2] + breath, r[3] + breath)
        if shake:
            r = (r[0] + shake, r[1], r[2] + shake, r[3])
        if br_a > 0:
            self._brackets(p, r, bcol, ba * br_a, angle)
        if square > 0:
            s = 8 * sq_scale
            p.fillRect(QRectF(130 - s / 2, 42 - s / 2, s, s), qc(PATINA, square))
        if self.mode == "rec" and t - self._lock_t < 0.7 and not an.silent:
            a = 1 - prog(t - self._lock_t, 0.4, 0.3)
            draw_text(p, r[2] - 4, r[1] + 11, "LOCK", mono(8.5, 600, 1.0), qc(LINE, 0.8 * a), "right")

        shown, target, color = self.status_text(t, f, an)
        if self.mode == "rec":
            rec_square(p, 16, 10, t, AMBER if an.silent else RED, reduced)
        else:
            p.fillRect(QRectF(16, 10, 6, 6), qc(RED if self.mode == "error" else PATINA, 0.95))
        font = mono(11, 500, 0.6)
        draw_text(p, 28, 16, shown, font, qc(color, 0.94))
        if self.mode == "done" and shown == target:
            check_mark(p, 28 + text_width(font, target) + 6, 8, 9, PATINA)
        draw_text(p, 244, 16, fmt_time(self.elapsed(t)), mono(11, 400, 0.2),
                  qc(LINE, 0.66 if self.mode == "rec" else 0.4), "right")

        if self.mode in ("rec", "proc"):
            span = math.log(5000 / 90)
            for fr in (100, 200, 500, 1000, 2000, 5000):
                x = BX0 + BW * math.log(fr / 90) / span
                p.fillRect(QRectF(round(x), 69, 1, 3), qc(LINE, 0.22))
            tiny = mono(8, 400, 0.3)
            label = qc(LINE, 0.34)
            draw_text(p, BX0 + BW * math.log(100 / 90) / span - 2, 78, "0,1", tiny, label)
            draw_text(p, BX0 + BW * math.log(1000 / 90) / span - 2, 78, "1", tiny, label)
            draw_text(p, BX0 + BW + 2, 78, "5 kHz", tiny, label, "right")
        p.restore()
