# © 2026 Mike Pollow, Digitalroots. Alle Rechte vorbehalten.
"""Stil „Klartext“: Terminal mit Entschlüsselung des erkannten Texts.

Pegel als Zeichenbalken, eine Zelle je 100 ms. Nach dem Loslassen erscheint
der Whisper-Text verschlüsselt und löst sich Zeichen für Zeichen auf. Bei der
Übergabe tauscht die Anzeige die Wörter aus, die die Politur geändert hat, und
hält den Text 0,8 s stehen; eingefügt ist er da schon. Fehler stehen im
Klartext da.
"""
from __future__ import annotations

import math

import numpy as np
from PyQt6.QtCore import QPointF, QRectF
from PyQt6.QtGui import QColor, QPainter

from kira.ui.hud.base import (
    AMBER,
    GLYPHS,
    LINE,
    PATINA,
    RED,
    WHITE,
    Frame,
    HudStyle,
    check_mark,
    clamp,
    draw_text,
    fmt_time,
    hash2,
    mix,
    mono,
    prog,
    qc,
    shell,
    text_width,
)
from kira.ui.hud.signal import level_of

CELLS, CELL_W = 33, 7.0
X0 = 12.0
LINE_CHARS = 34
BLOCK = 1600


def wrap(text: str, n: int = LINE_CHARS) -> list[str]:
    """Zwei Zeilen zu höchstens n Zeichen; was nicht passt, endet mit „…“."""
    lines = [""]
    for word in text.split():
        cur = lines[-1]
        if not cur:
            lines[-1] = word[:n]
        elif len(cur) + 1 + len(word) <= n:
            lines[-1] = cur + " " + word
        else:
            lines.append(word[:n])
    if len(lines) > 2:
        lines = lines[:2]
        lines[1] = lines[1][:n - 1] + "…"
    return lines


class Klartext(HudStyle):
    key = "klartext"

    def __init__(self) -> None:
        super().__init__()
        self._cells: list[tuple[int, bool]] = []
        self._block = 0

    def on_press(self, t: float, f: Frame) -> None:
        self._cells.clear()
        self._block = -1

    def step(self, t: float, dt: float, f: Frame, tap, an) -> None:
        if self.mode == "done" and t - self.end_t > (0.45 if f.reduced else 1.0):
            self.mode = "hidden"
            return
        if self.mode != "rec":
            return
        current = tap.position // BLOCK
        if self._block < 0:
            self._block = current
            return
        while self._block < current:
            end = (self._block + 1) * BLOCK
            block = tap.tail(BLOCK, end=end)
            peak = float(np.abs(block).max()) if block.size else 0.0
            self._cells.append((math.ceil(level_of(peak) * 8), peak >= 0.99))
            del self._cells[:-CELLS]
            self._block += 1

    def paint(self, p: QPainter, t: float, f: Frame, tap, an) -> None:
        reduced = f.reduced
        u = t - self.t0
        sh_a, line1, line2 = 1.0, True, True
        if self.mode == "rec" and reduced:
            sh_a = clamp(u / 0.12, 0, 1)
        if self.mode == "done":
            v = t - self.end_t
            if reduced:
                sh_a = 1 - prog(v, 0.3, 0.15)
            else:
                line2 = v < 0.8
                line1 = v < 0.86
                sh_a = 1 - prog(v, 0.9, 0.1)
        if self.mode == "error":
            sh_a = self.error_alpha(t)
        shell(p, sh_a)
        if sh_a <= 0:
            return
        p.save()
        p.setOpacity(p.opacity() * sh_a)
        body = mono(11, 400, 0.0)
        cw = text_width(body, "M")

        shown, target, color = self.status_text(t, f, an)
        if self.mode == "rec" and not reduced and u < 0.12:
            shown = target[:int(u / 0.012)]
        blink_on = reduced or self.mode != "rec" or int(t * 2) % 2 == 0
        cursor = RED if self.mode == "error" else AMBER if (self.mode == "rec" and an.silent) else LINE
        p.fillRect(QRectF(X0, 7, 6, 11), qc(cursor, 0.9 if blink_on else 0.15))
        head = mono(11, 500, 0.6)
        draw_text(p, X0 + 12, 16, shown, head, qc(color, 0.95))
        if self.mode == "done" and shown == target:
            check_mark(p, X0 + 12 + text_width(head, target) + 6, 8, 9, PATINA)
        small = mono(11, 400, 0.2)
        if self.mode == "done":
            draw_text(p, 248, 16, f"{len(f.polished_text)} ZEICHEN", small, qc(LINE, 0.55), "right")
        else:
            draw_text(p, 248, 16, fmt_time(self.elapsed(t)), small,
                      qc(LINE, 0.66 if self.mode == "rec" else 0.4), "right")

        if self.mode == "rec":
            n = len(self._cells)
            for i, (q, hot) in enumerate(self._cells):
                x = X0 + (CELLS - n + i) * CELL_W
                h = max(1.0, q / 8 * 18)
                newest = i == n - 1
                if an.silent:
                    col = qc(AMBER, 0.5)
                elif hot:
                    col = qc(RED, 0.95)
                else:
                    col = qc(LINE if newest else PATINA, 0.95 if newest else 0.75)
                p.fillRect(QRectF(x, 46 - h, 5, h), col)
            tag = mono(9.5, 500, 0.8)
            if an.silent:
                draw_text(p, X0, 65, "KEIN SIGNAL · MIKRO PRÜFEN", tag, qc(AMBER, 0.9))
            else:
                draw_text(p, X0, 65, "KANAL 08 · NUR FÜR M", tag, qc(LINE, 0.4))
        elif self.mode == "proc":
            frame = int(t * 15)
            if not f.polishing or not f.raw_text:
                for li in range(2):
                    noise = "".join(GLYPHS[hash2(i + li * 50, frame) % len(GLYPHS)] for i in range(LINE_CHARS))
                    draw_text(p, X0, 40 + li * 16, noise, body, qc(PATINA, 0.45))
            else:
                self._resolve(p, t - f.polish_t, f, body, cw, frame)
        elif self.mode == "done":
            self._handover(p, t - self.end_t, f, body, cw, int(t * 15), line1, line2)
        elif self.mode == "error":
            first, second = self.message_lines()
            msg = mono(11, 400, 0.2)
            draw_text(p, X0, 40, first, msg, qc(LINE, 0.92))
            draw_text(p, X0, 56, second, msg, qc(AMBER, 0.9))

        p.setOpacity(1.0 * sh_a)
        scan = QColor(0, 0, 0, 33)
        y = 1.0
        while y < 80:
            p.fillRect(QRectF(1, y, 258, 1), scan)
            y += 2
        p.restore()

    def _resolve(self, p: QPainter, v: float, f: Frame, font, cw: float, frame: int) -> None:
        """Whisper-Text löst sich in 0,26 s von links nach rechts aus dem Rauschen."""
        raw = f.raw_text
        p.setFont(font)
        total = max(1, len(raw))
        idx = 0
        for li, s in enumerate(wrap(raw)):
            for j, ch in enumerate(s):
                ok = f.reduced or v >= (idx / total) * 0.26
                p.setPen(qc(LINE, 0.8) if ok else qc(PATINA, 0.55))
                p.drawText(QPointF(X0 + j * cw, 40 + li * 16),
                           ch if ok else GLYPHS[hash2(idx, frame) % len(GLYPHS)])
                idx += 1
            idx += 1

    def _handover(self, p: QPainter, v: float, f: Frame, font, cw: float, frame: int,
                  line1: bool, line2: bool) -> None:
        """Übergabe: geänderte Wörter kurz verschlüsselt, dann hell; der Rest ruhig."""
        raw_words = f.raw_text.split()
        pol_words = (f.polished_text or f.raw_text).split()
        p.setFont(font)
        wi = 0
        for li, s in enumerate(wrap(" ".join(pol_words))):
            show = line1 if li == 0 else line2
            x = X0
            for word in s.split(" "):
                changed = (raw_words[wi] if wi < len(raw_words) else "") != word.rstrip("…")
                lock_t = 0.1 + (wi % 6) * 0.025
                for j, ch in enumerate(word):
                    if not show:
                        continue
                    if changed and v < lock_t and not f.reduced:
                        ch = GLYPHS[hash2(wi * 31 + j, frame) % len(GLYPHS)]
                        p.setPen(qc(PATINA, 0.7))
                    elif changed:
                        p.setPen(qc(mix(LINE, WHITE, 0.6), 1.0))
                    else:
                        p.setPen(qc(LINE, 0.8))
                    p.drawText(QPointF(x + j * cw, 40 + li * 16), ch)
                x += (len(word) + 1) * cw
                wi += 1
