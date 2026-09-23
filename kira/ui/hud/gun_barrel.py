# © 2026 Mike Pollow, Digitalroots. Alle Rechte vorbehalten.
"""Stil „Gun Barrel“: der Blick durch den Lauf, nach Maurice Binders Titelsequenz (Dr. No, 1962).

Gemessen am Vorbild: der weiße Punkt läuft von links nach rechts und öffnet
sich zum Lauf, sechs Züge, am Ende setzt sich der Punkt in eine Ecke und
verlischt, bei Fehlern läuft die rote Blende herab. Das Licht am Ende des
Laufs folgt dem Pegel, jede Silbe schickt einen Ring durch die Züge. Das lange
Kino-Intro mit drei Punkten läuft nur beim ersten Diktat des Tages.
"""
from __future__ import annotations

import math

import numpy as np
from PyQt6.QtCore import QPointF, QRectF
from PyQt6.QtGui import QColor, QLinearGradient, QPainter, QPainterPath, QPen, QRadialGradient

from kira.ui.hud.base import (
    AMBER,
    EASE_IN_OUT,
    EASE_OUT,
    LINE,
    PATINA,
    RED,
    TIEF,
    WHITE,
    Frame,
    HudStyle,
    check_mark,
    clamp,
    draw_text,
    fmt_time,
    hash2,
    lerp,
    mix,
    mono,
    prog,
    qc,
    rec_square,
    shell,
    text_width,
)

CX, CY, RO, R0 = 220.0, 40.0, 31.0, 11.0
COLS, COL_SAMPLES = 172, 160      # 10 ms je Spalte, 1,7 s Verlauf
X0, WAVE_W, WAVE_CY = 12.0, 170.0, 41.0


class GunBarrel(HudStyle):
    key = "gun_barrel"

    def __init__(self) -> None:
        super().__init__()
        self._rot = 0.4
        self._om = 0.3
        self._rings: list[tuple[float, float]] = []
        self._last_onset = -1.0
        self._col = np.zeros(COLS, dtype=np.float32)
        self._frozen = np.zeros(COLS, dtype=np.float32)
        self._frac = 0.0
        self._cine = False

    def on_press(self, t: float, f: Frame) -> None:
        self._cine = f.cinema
        self._rings.clear()
        self._last_onset = t
        self._rot, self._om = 0.4, 0.3
        self._col[:] = 0.0

    def on_release(self, t: float, f: Frame) -> None:
        self._frozen[:] = self._col

    def on_clear(self, f: Frame) -> None:
        self._rings.clear()
        self._col[:] = 0.0
        self._frozen[:] = 0.0

    def _envelope(self, tap) -> None:
        pos = tap.position
        rem = pos % COL_SAMPLES
        b = tap.tail(COLS * COL_SAMPLES + rem)[:COLS * COL_SAMPLES]
        m = np.abs(b).reshape(COLS, COL_SAMPLES).max(axis=1)
        m[1:-1] = np.maximum(m[1:-1], (m[:-2] + m[2:]) * 0.42)
        self._col[:] = m
        self._frac = rem / COL_SAMPLES

    def step(self, t: float, dt: float, f: Frame, tap, an) -> None:
        if self.mode == "done" and t - self.end_t > (0.4 if f.reduced else 0.5):
            self.mode = "hidden"
            return
        if self.mode == "rec":
            self._envelope(tap)
            for ot, strength in an.onsets:
                if ot > self._last_onset:
                    self._rings.append((ot, strength))
                    self._last_onset = ot
        self._rings = [r for r in self._rings if t - r[0] < 0.5]
        if f.reduced:
            target = 0.0
        elif self.mode == "rec":
            target = 0.0 if an.silent else 0.3 + 1.1 * an.level
        elif self.mode == "proc":
            target = 5.2
        elif self.mode == "done":
            target = 2.0
        else:
            target = 0.0
        if f.reduced:
            self._om = 0.0
        else:
            self._om += (target - self._om) * (1 - math.exp(-dt / 0.18))
        self._rot += self._om * dt

    # -- Lauf ---------------------------------------------------------------------
    def _barrel(self, p: QPainter, t: float, rr: float, alpha: float, f: Frame, an) -> None:
        silent = self.mode == "rec" and an.silent
        p.save()
        p.setOpacity(p.opacity() * alpha)
        clip = QPainterPath()
        clip.addEllipse(QPointF(CX, CY), max(0.1, rr), max(0.1, rr))
        p.setClipPath(clip)
        if silent:
            light = 0.0
        elif self.mode == "rec":
            light = 0.25 + 0.75 * an.level
        else:
            light = 0.55 if f.reduced else 0.55 + 0.2 * math.sin(t * 7.85)
        wall = QRadialGradient(QPointF(CX, CY), RO, QPointF(CX, CY), R0 * 0.9)
        wall.setColorAt(0, QColor(int(26 + 46 * light), int(40 + 62 * light), int(44 + 64 * light)))
        wall.setColorAt(0.32, QColor(15, 24, 27))
        wall.setColorAt(0.75, QColor(8, 13, 15))
        wall.setColorAt(1, QColor(4, 7, 8))
        p.fillRect(QRectF(CX - RO, CY - RO, RO * 2, RO * 2), wall)

        twist, groove, steps = 0.95, 0.3, 12
        light_dir = -2.2 if f.reduced else -2.2 + 0.3 * math.sin(t * 0.7)
        for k in range(6):
            a0 = self._rot + k * math.pi / 3
            path = QPainterPath()
            for i in range(steps + 1):
                r = R0 + (RO - R0) * i / steps
                a = a0 + twist * i / steps
                pt = QPointF(CX + math.cos(a) * r, CY + math.sin(a) * r)
                path.moveTo(pt) if i == 0 else path.lineTo(pt)
            for i in range(steps, -1, -1):
                r = R0 + (RO - R0) * i / steps
                a = a0 + groove + twist * i / steps
                path.lineTo(QPointF(CX + math.cos(a) * r, CY + math.sin(a) * r))
            path.closeSubpath()
            p.fillPath(path, QColor(0, 0, 0, 107))
            shine = max(0.0, math.cos(a0 + groove + twist * 0.5 - light_dir)) ** 3
            edge = QPainterPath()
            for i in range(steps + 1):
                r = R0 + (RO - R0) * i / steps
                a = a0 + groove + twist * i / steps
                pt = QPointF(CX + math.cos(a) * r, CY + math.sin(a) * r)
                edge.moveTo(pt) if i == 0 else edge.lineTo(pt)
            p.strokePath(edge, QPen(qc(LINE, (0.07 + 0.42 * shine) * (0.55 + 0.45 * light)), 0.9))
        ring_pen = QPen(QColor(0, 0, 0, 71), 1.0)
        for r in (R0 + 2.5, R0 + 6.5, R0 + 12.5):
            p.setPen(ring_pen)
            p.setBrush(QColor(0, 0, 0, 0))
            p.drawEllipse(QPointF(CX, CY), r, r)

        opening = QPainterPath()
        opening.addEllipse(QPointF(CX, CY), R0, R0)
        p.fillPath(opening, QColor(3, 6, 7))
        og = QRadialGradient(QPointF(CX, CY), R0)
        if silent:
            og.setColorAt(0, QColor(30, 34, 34))
            og.setColorAt(1, QColor(12, 16, 17))
        else:
            og.setColorAt(0, qc(mix(PATINA, WHITE, 0.25 + 0.6 * light), 0.35 + 0.65 * light))
            og.setColorAt(0.7, qc(PATINA, 0.25 + 0.6 * light))
            og.setColorAt(1, qc(TIEF, 0.5 + 0.4 * light))
        p.fillPath(opening, og)
        if silent:
            frame = 0 if f.reduced else int(t * 24)
            for i in range(70):
                h = hash2(i, frame)
                a = (h % 628) / 100
                r = ((h >> 10) % 100) / 100 * R0
                p.fillRect(QRectF(CX + math.cos(a) * r - 0.5, CY + math.sin(a) * r - 0.5, 1, 1),
                           QColor(200, 210, 210, int(255 * (0.15 + ((h >> 20) % 50) / 100))))
        if not f.reduced:
            for ot, strength in self._rings:
                age = t - ot
                if 0 <= age <= 0.45:
                    q = age / 0.45
                    r = R0 + (RO - R0) * EASE_OUT(q)
                    p.setPen(QPen(qc(mix(PATINA, LINE, 0.4), strength * (1 - q) ** 2 * 0.85), 1.3))
                    p.drawEllipse(QPointF(CX, CY), r, r)
        if self.mode == "error":
            u = 0.0 if f.reduced else t - self.end_t
            y = CY + RO if f.reduced else CY - RO + 2 * RO * EASE_OUT(prog(u, 0, 0.55))
            wash = QLinearGradient(0, CY - RO, 0, max(y, CY - RO + 0.1))
            wash.setColorAt(0, QColor(110, 14, 20, 189))
            wash.setColorAt(1, QColor(229, 72, 77, 179))
            path = QPainterPath(QPointF(CX - RO, CY - RO))
            path.lineTo(CX + RO, CY - RO)
            x = CX + RO
            while x >= CX - RO:
                path.lineTo(x, y + 2.6 * math.sin((x - CX) / RO * 3 * math.pi + u * 5))
                x -= 2
            path.closeSubpath()
            p.fillPath(path, wash)
        p.restore()

        p.save()
        p.setOpacity(p.opacity() * alpha)
        p.setBrush(QColor(0, 0, 0, 0))
        p.setPen(QPen(qc(LINE, 0.16), 1.0))
        p.drawEllipse(QPointF(CX, CY), max(0.1, rr) - 0.5, max(0.1, rr) - 0.5)
        if self.mode == "rec" and an.clip:
            k = math.exp(-(t - an.clip_onset) / 0.3)
            p.setPen(QPen(qc(RED, 0.35 + 0.6 * k), 1.5))
            p.drawEllipse(QPointF(CX, CY), rr - 0.5, rr - 0.5)
            p.setPen(QPen(qc(RED, 0.25 * k), 4.0))
            p.drawEllipse(QPointF(CX, CY), rr - 0.5, rr - 0.5)
        p.restore()

    # -- Zeichnen -------------------------------------------------------------------
    def paint(self, p: QPainter, t: float, f: Frame, tap, an) -> None:
        reduced = f.reduced
        u = t - self.t0
        sh_a, pan_a, rr, bar_a = 1.0, 1.0, RO, 1.0
        dot = None
        dot_a = 0.0
        if self.mode in ("rec", "proc"):
            if reduced:
                sh_a = clamp(u / 0.12, 0, 1)
            elif self._cine:
                sh_a = clamp(u / 0.06, 0, 1)
                q = prog(u, 0.3, 0.24)
                rr = 0.0 if q <= 0 else lerp(2.4, RO, EASE_OUT(q))
                bar_a = 0.0 if q <= 0 else 1.0
            else:
                q = EASE_OUT(prog(u, 0, 0.16))
                rr = lerp(RO * 0.78, RO, q)
                bar_a = q
                pan_a = clamp(u / 0.08, 0, 1)
        elif self.mode == "done":
            v = t - self.end_t
            if reduced:
                sh_a = 1 - prog(v, 0.25, 0.15)
            else:
                rr = lerp(RO, 2.2, EASE_IN_OUT(prog(v, 0.12, 0.14)))
                bar_a = 1 - prog(v, 0.2, 0.06)
                if v >= 0.2:
                    q2 = EASE_IN_OUT(prog(v, 0.26, 0.14))
                    dot = (lerp(CX, 250, q2), lerp(CY, 70, q2))
                    dot_a = 1 - prog(v, 0.42, 0.08)
                pan_a = 1 - prog(v, 0.26, 0.14)
                sh_a = 1 - prog(v, 0.4, 0.1)
        elif self.mode == "error":
            sh_a = self.error_alpha(t)
        shell(p, sh_a)
        if sh_a <= 0:
            return
        p.save()
        p.setOpacity(p.opacity() * sh_a)
        if self._cine and self.mode in ("rec", "proc") and not reduced and u < 0.5:
            for i in range(3):
                ti = i * 0.08
                a = clamp((u - ti) / 0.03, 0, 1) * (1 - prog(u, ti + 0.12, 0.08))
                if a > 0:
                    self._dot(p, 30 + i * 62, CY, 2.8, 7, a)
            if 0.24 <= u < 0.32:
                self._dot(p, CX, CY, 2.4, 0, clamp((u - 0.24) / 0.03, 0, 1))
        if bar_a > 0 and rr > 0.2:
            self._barrel(p, t, rr, bar_a, f, an)
        if dot is not None:
            self._dot(p, dot[0], dot[1], 2.3, 6, dot_a)
        p.setOpacity(p.opacity() * pan_a)
        self._panel(p, t, f, an, u)
        p.restore()

    def _dot(self, p: QPainter, x: float, y: float, r: float, halo: float, a: float) -> None:
        if halo:
            path = QPainterPath()
            path.addEllipse(QPointF(x, y), halo, halo)
            p.fillPath(path, qc(WHITE, 0.14 * a))
        path = QPainterPath()
        path.addEllipse(QPointF(x, y), r, r)
        p.fillPath(path, qc(WHITE, a))

    def _panel(self, p: QPainter, t: float, f: Frame, an, u: float) -> None:
        shown, target, color = self.status_text(t, f, an)
        if self.mode == "rec":
            rec_square(p, 12, 11, t, AMBER if an.silent else RED, f.reduced)
        else:
            sq = RED if self.mode == "error" else PATINA
            p.fillRect(QRectF(12, 11, 6, 6), qc(sq, 0.9 if self.mode == "proc" else 1.0))
        font = mono(11, 500, 0.6)
        draw_text(p, 24, 17, shown, font, qc(color, 0.94))
        if self.mode == "done" and shown == target:
            check_mark(p, 24 + text_width(font, target) + 6, 9, 9, PATINA)
        if self.mode == "rec":
            draw_text(p, 182, 17, fmt_time(self.elapsed(t)), mono(11, 400, 0.2), qc(LINE, 0.66), "right")

        if self.mode == "error":
            first, second = self.message_lines()
            msg = mono(10, 400, 0.0)
            draw_text(p, X0, 40, first, msg, qc(LINE, 0.86))
            draw_text(p, X0, 55, second, msg, qc(LINE, 0.55))
        else:
            self._wave(p, t, f, an, u)

        elapsed = self.elapsed(t)
        off = (elapsed - 21) * 8 if elapsed > 21 else 0.0
        p.fillRect(QRectF(X0, 68, 170, 1), qc(LINE, 0.08))
        p.save()
        p.setClipRect(QRectF(X0 - 3, 62, 176, 12))
        for k in range(int(elapsed) + 1):
            x = X0 + k * 8 - off
            if x < X0 - 2:
                continue
            path = QPainterPath()
            path.addEllipse(QPointF(x, 68.5), 1.1, 1.1)
            p.fillPath(path, qc(LINE, 0.3))
        if self.mode == "rec" and not f.reduced:
            self._dot(p, X0 + elapsed * 8 - off, 68.5, 1.9, 4.5, 0.96)
        p.restore()

    def _wave(self, p: QPainter, t: float, f: Frame, an, u: float) -> None:
        arr = self._col if self.mode == "rec" else self._frozen
        fr = self._frac if self.mode == "rec" else 0.0
        flat = self.mode == "rec" and an.silent
        if self.mode == "rec":
            wa = 0.3 + 0.7 * prog(u, 0.26, 0.08) if (self._cine and not f.reduced and u < 0.34) else 1.0
        else:
            wa = 0.32
        p.save()
        p.setClipRect(QRectF(X0, 24, 170, 34))
        xs = X0 + np.arange(COLS) - fr - 1
        if flat:
            frame = 0 if f.reduced else int(t * 20)
            path = QPainterPath(QPointF(float(xs[0]), WAVE_CY))
            for k in range(1, COLS):
                path.lineTo(float(xs[k]), WAVE_CY + ((hash2(k, frame) % 3) - 1) * 0.35)
            p.strokePath(path, QPen(qc(AMBER, 0.9), 1.2))
        else:
            h = np.maximum(0.4, np.sqrt(np.minimum(1.0, arr)) * 14.0)
            top = QPainterPath(QPointF(float(xs[0]), WAVE_CY - float(h[0])))
            bot = QPainterPath(QPointF(float(xs[0]), WAVE_CY + float(h[0])))
            for k in range(1, COLS):
                top.lineTo(float(xs[k]), WAVE_CY - float(h[k]))
                bot.lineTo(float(xs[k]), WAVE_CY + float(h[k]))
            band = QPainterPath(top)
            for k in range(COLS - 1, -1, -1):
                band.lineTo(float(xs[k]), WAVE_CY + float(h[k]))
            band.closeSubpath()
            p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Plus)
            p.fillPath(band, qc(PATINA, 0.2 * wa))
            for path in (top, bot):
                p.strokePath(path, QPen(qc(PATINA, 0.3 * wa), 2.6))
                p.strokePath(path, QPen(qc(mix(PATINA, LINE, 0.4), 0.95 * wa), 1.0))
            p.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
        p.restore()
