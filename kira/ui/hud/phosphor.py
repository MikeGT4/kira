# © 2026 Mike Pollow, Digitalroots. Alle Rechte vorbehalten.
"""Stil „Phosphor“: analoges Oszilloskop mit Nachleuchten (Standard seit v0.4.1).

Vorbild ist die Strahlphysik einer Röhre, wie sie woscope beschreibt
(m1el.github.io/woscope-how): Helligkeit umgekehrt zur Länge des Strahlwegs,
additive Überblendung, Nachleuchten. Beim Sprechen steht die Schwingung
dank Trigger still im Bild; nach dem Loslassen zeichnet der Strahl im
XY-Betrieb eine Lissajous-Figur (3:2 Entschlüsselung, 5:4 Politur); zum Schluss
geht die Röhre aus: Bild, Strich, Punkt.

Abgestimmt an Mikes echter Aufnahme (23.09.2026): Die Stimme ist glatter als
die Simulation der Muster, deshalb weiche Verstärkung (tanh, Faktor 3,5),
30 ms Zeitfenster und 0,14 s Nachleuchten; die Nulllinie leuchtet schwächer
als die Schwingung. Übersteuerung bleibt rot, gemessen am Rohsignal.
"""
from __future__ import annotations

import math

import numpy as np
from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import (
    QColor,
    QImage,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QRadialGradient,
)

from kira.ui.hud.base import (
    AMBER,
    EASE_IN_OUT,
    EASE_OUT,
    LINE,
    MARKE,
    PATINA,
    RED,
    WHITE,
    Frame,
    HudStyle,
    check_mark,
    clamp,
    fmt_db,
    fmt_time,
    glow_text,
    lerp,
    mix,
    mono,
    prog,
    qc,
    shell,
    text_width,
)

SX, SY, SW, SH = 6.0, 6.0, 248.0, 68.0
TRACE_N = 480                 # 30 ms bei 16 kHz, 3 ms je Teilung
AFTERGLOW_S = 0.14
DISPLAY_GAIN = 3.5            # weiche Verstärkung der Anzeige, der Pegel bleibt echt
AMPLITUDE = 21.0              # Ausschlag in Entwurfs-Pixeln, bleibt zwischen den Schriftzeilen
BUCKETS = 6


class Phosphor(HudStyle):
    key = "phosphor"

    def __init__(self) -> None:
        super().__init__()
        self._img: QImage | None = None
        self._img_px = 0.0
        self._lph = 0.0
        self._trig = False

    # -- Nachleucht-Puffer ------------------------------------------------------
    def _buffer(self, f: Frame) -> QImage:
        if self._img is None or self._img_px != f.px:
            w = max(1, round(SW * f.px))
            h = max(1, round(SH * f.px))
            self._img = QImage(w, h, QImage.Format.Format_ARGB32_Premultiplied)
            self._img.fill(Qt.GlobalColor.transparent)
            self._img_px = f.px
        return self._img

    def on_press(self, t: float, f: Frame) -> None:
        self.on_clear(f)

    def on_clear(self, f: Frame) -> None:
        self._buffer(f).fill(Qt.GlobalColor.transparent)
        self._lph = 0.0

    def on_error(self, t: float, f: Frame) -> None:
        img = self._buffer(f)
        g = QPainter(img)
        g.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceAtop)
        g.fillRect(img.rect(), qc(RED, 0.85))
        g.end()

    def _beam(self, g: QPainter, xs: np.ndarray, ys: np.ndarray, hot: np.ndarray,
              level: np.ndarray | None = None) -> None:
        """Strahl zeichnen: Helligkeit umgekehrt zur Segmentlänge, rote Segmente bei Übersteuerung.

        ``level`` (0..1 je Punkt) dämpft die Nulllinie, damit die Schwingung
        und nicht die Ruhelage am hellsten ist."""
        dx = np.diff(xs)
        dy = np.diff(ys)
        length = np.sqrt(dx * dx + dy * dy) + 1e-3
        inten = np.clip(1.5 / length, 0.08, 1.0)
        if level is not None:
            near = np.maximum(level[1:], level[:-1])
            inten = inten * (0.35 + 0.65 * np.clip(near * 5.0, 0.0, 1.0))
        bucket = np.minimum(BUCKETS - 1, (inten * BUCKETS).astype(int))
        clipped = hot[1:] | hot[:-1]
        bucket[clipped] = BUCKETS
        paths = [QPainterPath() for _ in range(BUCKETS + 1)]
        prev = -1
        for i in range(len(bucket)):
            b = int(bucket[i])
            path = paths[b]
            if b != prev:
                path.moveTo(float(xs[i]), float(ys[i]))
            path.lineTo(float(xs[i + 1]), float(ys[i + 1]))
            prev = b
        g.setCompositionMode(QPainter.CompositionMode.CompositionMode_Plus)
        for b, path in enumerate(paths):
            if path.isEmpty():
                continue
            is_clip = b == BUCKETS
            inten_b = 1.0 if is_clip else (b + 0.5) / BUCKETS
            base = RED if is_clip else PATINA
            core = (255, 205, 205) if is_clip else LINE
            for width, color, a in ((5.0, base, 0.08 * inten_b), (1.4, base, 0.5 * inten_b),
                                    (0.7, core, 0.42 * inten_b * inten_b)):
                pen = QPen(qc(color, a), width)
                pen.setCapStyle(Qt.PenCapStyle.RoundCap)
                pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
                g.strokePath(path, pen)
        g.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)

    def step(self, t: float, dt: float, f: Frame, tap, an) -> None:
        if self.mode == "done":
            v = t - self.end_t
            if v > (0.4 if f.reduced else 0.46):
                self.mode = "hidden"
                return
        img = self._buffer(f)
        g = QPainter(img)
        g.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        tau = 0.6 if self.mode == "error" else AFTERGLOW_S
        fade = 1.0 - math.exp(-dt / tau)
        g.setCompositionMode(QPainter.CompositionMode.CompositionMode_DestinationOut)
        g.fillRect(img.rect(), QColor(0, 0, 0, max(1, round(fade * 255))))
        g.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
        g.scale(f.px, f.px)
        if self.mode == "rec":
            b = tap.tail(TRACE_N + 1280)
            start = self._trigger(b)
            seg = b[start:start + TRACE_N]
            shown = np.tanh(seg * DISPLAY_GAIN)
            xs = 4.0 + np.arange(TRACE_N) * (240.0 / (TRACE_N - 1))
            ys = SH / 2 - shown * AMPLITUDE
            self._beam(g, xs, ys, np.abs(seg) >= 0.985, np.abs(shown))
        elif self.mode == "proc":
            self._lph += 0.0 if f.reduced else dt * 1.25
            a, bb = (5, 4) if f.polishing else (3, 2)
            w = np.linspace(0.0, 2 * math.pi, 400)
            xs = SW / 2 + 104.0 * np.sin(a * w + self._lph)
            ys = SH / 2 + 18.0 * np.sin(bb * w)
            self._beam(g, xs, ys, np.zeros(400, dtype=bool))
        g.end()

    def _trigger(self, b: np.ndarray) -> int:
        """Letzter steigender Nulldurchgang mit Hysterese; sonst frei laufen."""
        last = b.size - TRACE_N
        i = np.arange(41, last)
        cross = i[(b[i - 1] < 0) & (b[i] >= 0)]
        self._trig = False
        if cross.size:
            window_min = np.lib.stride_tricks.sliding_window_view(b, 40).min(axis=1)
            ok = cross[window_min[cross - 40] < -0.015]
            if ok.size:
                self._trig = True
                return int(ok[-1])
        return last

    # -- Zeichnen -------------------------------------------------------------------
    def paint(self, p: QPainter, t: float, f: Frame, tap, an) -> None:
        red_motion = f.reduced
        u = t - self.t0
        sh_a, vy, hx, line_a, dot_a, screen = 1.0, 1.0, 1.0, 0.0, 0.0, True
        if self.mode == "rec" and not red_motion and u < 0.16:
            q = EASE_OUT(prog(u, 0, 0.15))
            vy = lerp(0.03, 1.0, q)
            line_a = (1 - q) * 0.9
        if self.mode == "rec" and red_motion:
            sh_a = clamp(u / 0.12, 0, 1)
        if self.mode == "done":
            v = t - self.end_t
            if red_motion:
                sh_a = 1 - prog(v, 0.25, 0.15)
            else:
                q1 = EASE_IN_OUT(prog(v, 0.1, 0.1))
                vy = lerp(1.0, 0.03, q1)
                line_a = q1
                hx = lerp(1.0, 0.012, EASE_IN_OUT(prog(v, 0.2, 0.1)))
                if v > 0.2:
                    screen = False
                if v >= 0.28:
                    dot_a = 1 - prog(v, 0.3, 0.14)
                    line_a = 0.0
                sh_a = 1 - prog(v, 0.34, 0.12)
        if self.mode == "error":
            sh_a = self.error_alpha(t)
        shell(p, sh_a)
        if sh_a <= 0:
            return
        p.save()
        p.setOpacity(p.opacity() * sh_a)
        clip = QPainterPath()
        clip.addRoundedRect(QRectF(SX, SY, SW, SH), 5, 5)
        p.setClipPath(clip)
        p.fillRect(QRectF(SX, SY, SW, SH), QColor(3, 9, 10))
        cy0, cx0 = SY + SH / 2, SX + SW / 2
        if screen:
            p.save()
            p.translate(0, cy0)
            p.scale(1, vy)
            p.translate(0, -cy0)
            self._graticule(p, cx0, cy0)
            if self._img is not None:
                p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Plus)
                p.drawImage(QRectF(SX, SY, SW, SH), self._img, QRectF(self._img.rect()))
                p.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
            p.restore()
        if line_a > 0:
            w = SW * hx
            lg = QLinearGradient(cx0 - w / 2, 0, cx0 + w / 2, 0)
            lg.setColorAt(0, qc(PATINA, 0))
            lg.setColorAt(0.5, qc(mix(LINE, WHITE, 0.5), line_a))
            lg.setColorAt(1, qc(PATINA, 0))
            p.fillRect(QRectF(cx0 - w / 2, cy0 - 1, w, 2), lg)
            p.fillRect(QRectF(cx0 - w / 2, cy0 - 3, w, 6), qc(PATINA, 0.25 * line_a))
        if dot_a > 0:
            rg = QRadialGradient(QPointF(cx0, cy0), 6)
            rg.setColorAt(0, qc(WHITE, dot_a))
            rg.setColorAt(0.35, qc(LINE, 0.6 * dot_a))
            rg.setColorAt(1, qc(PATINA, 0))
            p.fillRect(QRectF(cx0 - 6, cy0 - 6, 12, 12), rg)
        p.restore()
        if screen and vy > 0.9:
            p.save()
            p.setOpacity(p.opacity() * sh_a)
            self._readouts(p, t, f, an)
            p.restore()

    def _graticule(self, p: QPainter, cx0: float, cy0: float) -> None:
        pen = QPen(qc(MARKE, 0.36), 1.0)
        p.setPen(pen)
        for i in range(1, 10):
            x = SX + i * SW / 10
            p.drawLine(QPointF(x, SY), QPointF(x, SY + SH))
        for j in range(1, 4):
            y = SY + j * SH / 4
            p.drawLine(QPointF(SX, y), QPointF(SX + SW, y))
        p.setPen(QPen(qc(MARKE, 0.6), 1.0))
        for k in range(1, 50):
            x = SX + k * SW / 50
            p.drawLine(QPointF(x, cy0 - 1.5), QPointF(x, cy0 + 1.5))
        for k in range(1, 20):
            y = SY + k * SH / 20
            p.drawLine(QPointF(cx0 - 1.5, y), QPointF(cx0 + 1.5, y))

    def _readouts(self, p: QPainter, t: float, f: Frame, an) -> None:
        glow = qc(PATINA, 0.3)
        shown, target, color = self.status_text(t, f, an)
        font = mono(10.5, 500, 0.6)
        # Statuswort so gedämpft wie die Messwerte unten (Mike 23.09.2026);
        # nur Warnungen und Fehler leuchten voll.
        signal = color in (RED, AMBER)
        glow_text(p, SX + 7, SY + 13, shown, font, qc(color, 0.95 if signal else 0.56),
                  glow if signal else qc(PATINA, 0.16))
        if self.mode == "done" and shown == target:
            check_mark(p, SX + 7 + text_width(font, target) + 6, SY + 5, 9, LINE, 0.56)
        glow_text(p, SX + SW - 7, SY + 13, fmt_time(self.elapsed(t)), mono(10.5, 400, 0.2),
                  qc(LINE, 0.56 if self.mode == "rec" else 0.4), qc(PATINA, 0.16), align="right")
        small = mono(9, 500, 0.4)
        base_y = SY + SH - 6
        if self.mode == "rec":
            if an.silent:
                glow_text(p, SX + SW - 7, base_y, "−∞ dBFS", small, qc(AMBER, 0.95), glow, "right")
            else:
                hot = an.db > -0.5
                glow_text(p, SX + SW - 7, base_y, fmt_db(an.db), small,
                          qc(RED if hot else LINE, 0.95 if hot else 0.62), glow, "right")
            p.fillRect(QRectF(SX + 7, SY + SH - 12, 5, 5),
                       qc(mix(PATINA, LINE, 0.3), 1.0) if self._trig else qc(MARKE, 0.6))
            glow_text(p, SX + 16, base_y, "TRIG", small, qc(LINE, 0.5), glow)
            glow_text(p, SX + 46, base_y, "3 ms/div", small, qc(LINE, 0.36), glow)
        elif self.mode == "proc":
            glow_text(p, SX + 7, base_y, "XY", small, qc(LINE, 0.5), glow)
            glow_text(p, SX + SW - 7, base_y, "5:4" if f.polishing else "3:2", small,
                      qc(LINE, 0.5), glow, "right")
        elif self.mode == "error":
            first, second = self.message_lines()
            msg = mono(10, 400, 0.2)
            glow_text(p, SX + 7, SY + SH - 18, first, msg, qc(LINE, 0.9), glow)
            glow_text(p, SX + 7, base_y, second, msg, qc(LINE, 0.6), glow)
