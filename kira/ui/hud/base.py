# © 2026 Mike Pollow, Digitalroots. Alle Rechte vorbehalten.
"""Zeichenbausteine der Aufnahme-Anzeige: Farben, Kurven, Schrift, Rahmen, Status.

Alle Stile zeichnen in Entwurfskoordinaten 260 × 80, der Größe bis v0.4.0.
Der Host skaliert den Maler um ``ui.hud_scale`` (Standard 1,5). Die Stile sind
Zustandsautomaten mit den Modi ``hidden``, ``rec``, ``proc``, ``done`` und
``error``; ``step`` rechnet einmal je Bild, ``paint`` zeichnet.
"""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass

from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import (
    QColor,
    QFont,
    QFontDatabase,
    QFontMetricsF,
    QPainter,
    QPainterPath,
    QPen,
)

from kira._resources import assets_dir

log = logging.getLogger(__name__)

W, H = 260, 80

PATINA = (39, 131, 144)      # #278390, Patina „mittel“
LINE = (218, 229, 231)       # #DAE5E7, Patina „Linie“
MARKE = (27, 90, 99)         # #1B5A63
TIEF = (21, 70, 77)          # #15464D
RED = (229, 72, 77)          # Signalrot, Dunkelstufe von --danger
AMBER = (198, 138, 26)       # #C68A1A, Warnung
WHITE = (255, 255, 255)
SHELL = (7, 13, 15)

FADE_S = 0.15                # Abbruch (kurzer Druck, kein Text): nur ausblenden


def clamp(v: float, lo: float, hi: float) -> float:
    return lo if v < lo else hi if v > hi else v


def lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


def mix(a, b, t: float) -> tuple[float, float, float]:
    return (lerp(a[0], b[0], t), lerp(a[1], b[1], t), lerp(a[2], b[2], t))


def prog(t: float, t0: float, d: float) -> float:
    return clamp((t - t0) / d, 0.0, 1.0) if d > 0 else (1.0 if t >= t0 else 0.0)


def qc(rgb, a: float = 1.0) -> QColor:
    return QColor(int(rgb[0]), int(rgb[1]), int(rgb[2]), int(round(clamp(a, 0.0, 1.0) * 255)))


def cubic_bezier(x1: float, y1: float, x2: float, y2: float):
    """Zeitkurve wie CSS ``cubic-bezier``; Newton-Schritte, Bisektion als Rückfall."""
    cx = 3 * x1
    bx = 3 * (x2 - x1) - cx
    ax = 1 - cx - bx
    cy = 3 * y1
    by = 3 * (y2 - y1) - cy
    ay = 1 - cy - by

    def sx(t): return ((ax * t + bx) * t + cx) * t
    def sy(t): return ((ay * t + by) * t + cy) * t
    def dx(t): return (3 * ax * t + 2 * bx) * t + cx

    def ease(x: float) -> float:
        if x <= 0:
            return 0.0
        if x >= 1:
            return 1.0
        t = x
        for _ in range(8):
            e = sx(t) - x
            if abs(e) < 1e-6:
                break
            d = dx(t)
            if abs(d) < 1e-6:
                break
            t -= e / d
        if not 0.0 <= t <= 1.0:
            lo, hi, t = 0.0, 1.0, x
            for _ in range(30):
                v = sx(t)
                if abs(v - x) < 1e-6:
                    break
                lo, hi = (t, hi) if v < x else (lo, t)
                t = (lo + hi) / 2
        return sy(t)

    return ease


EASE_OUT = cubic_bezier(0.23, 1, 0.32, 1)
EASE_IN_OUT = cubic_bezier(0.77, 0, 0.175, 1)

GLYPHS = "ABCDEFGHJKLMNPQRSTUVWXYZ0123456789#%&*+=<>/"


def hash2(a: int, b: int) -> int:
    """Schneller, fester Zufall aus zwei Ganzzahlen (für Rauschen und Glyphen)."""
    h = (a * 374761393 + b * 668265263) & 0xFFFFFFFF
    h = ((h ^ (h >> 13)) * 1274126177) & 0xFFFFFFFF
    return (h ^ (h >> 16)) & 0xFFFFFFFF


class Scramble:
    """Statuswort, das sich beim Wechsel von links nach rechts „entschlüsselt“."""

    DURATION = 0.24

    def __init__(self) -> None:
        self.target = ""
        self._t0 = -9.0

    def set(self, text: str, t: float, animate: bool) -> None:
        if text != self.target:
            self.target = text
            self._t0 = t if animate else -9.0

    def get(self, t: float, reduced: bool) -> str:
        p = 1.0 if reduced else clamp((t - self._t0) / self.DURATION, 0.0, 1.0)
        if p >= 1.0:
            return self.target
        n = len(self.target)
        frame = int(t * 28)
        out = []
        for i, ch in enumerate(self.target):
            locked = ch == " " or i / n < p * 1.25 - 0.25
            out.append(ch if locked else GLYPHS[hash2(i + 7, frame) % len(GLYPHS)])
        return "".join(out)


def fmt_time(seconds: float) -> str:
    s = max(0.0, seconds)
    m = int(s // 60)
    rest = s - m * 60
    whole = int(rest)
    tenth = int((rest - whole) * 10)
    return f"{m:02d}:{whole:02d},{tenth}"


def fmt_db(db: float) -> str:
    if db < -90:
        return "−∞ dBFS"
    v = min(0.0, db)
    if v > -0.05:
        return "0,0 dBFS"
    return "−" + f"{abs(v):.1f}".replace(".", ",") + " dBFS"


# ---- Schrift ----------------------------------------------------------------

_FONT_FILES = {400: "IBMPlexMono-Regular.ttf", 500: "IBMPlexMono-Medium.ttf", 600: "IBMPlexMono-SemiBold.ttf"}
_WEIGHTS = {400: QFont.Weight.Normal, 500: QFont.Weight.Medium, 600: QFont.Weight.DemiBold}
_FAMILIES: dict[int, str] = {}
_FALLBACK = "Cascadia Mono"


def load_fonts() -> None:
    """IBM Plex Mono (OFL 1.1) aus assets/fonts laden. Mehrfachaufruf ist harmlos."""
    if _FAMILIES:
        return
    base = assets_dir() / "fonts"
    for weight, name in _FONT_FILES.items():
        path = base / name
        fid = QFontDatabase.addApplicationFont(str(path)) if path.exists() else -1
        families = QFontDatabase.applicationFontFamilies(fid) if fid >= 0 else []
        if families:
            _FAMILIES[weight] = families[0]
        else:
            log.warning("HUD-Schrift nicht geladen: %s", path)
            _FAMILIES[weight] = _FALLBACK


def mono(size: float, weight: int = 500, spacing: float = 0.5) -> QFont:
    """Monospace in Entwurfs-Pixeln (Punktgröße = Pixel × 0,75 bei 96 dpi)."""
    load_fonts()
    font = QFont(_FAMILIES.get(weight, _FALLBACK))
    # Unter Windows melden alle drei Dateien dieselbe Familie; ohne Gewicht
    # nähme Qt immer den Regular-Schnitt.
    font.setWeight(_WEIGHTS.get(weight, QFont.Weight.Normal))
    font.setPointSizeF(size * 0.75)
    font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, spacing)
    font.setHintingPreference(QFont.HintingPreference.PreferNoHinting)
    return font


def text_width(font: QFont, s: str) -> float:
    return QFontMetricsF(font).horizontalAdvance(s)


def draw_text(p: QPainter, x: float, y: float, s: str, font: QFont, color: QColor,
              align: str = "left") -> float:
    """Text mit Grundlinie bei y zeichnen; gibt die Breite zurück."""
    w = text_width(font, s)
    if align == "right":
        x -= w
    elif align == "center":
        x -= w / 2
    p.setFont(font)
    p.setPen(color)
    p.drawText(QPointF(x, y), s)
    return w


def glow_text(p: QPainter, x: float, y: float, s: str, font: QFont, color: QColor,
              glow: QColor, align: str = "left") -> float:
    """Leuchtschrift wie auf dem Schirm: vier leise Versätze, dann der Text."""
    w = text_width(font, s)
    if align == "right":
        x -= w
    elif align == "center":
        x -= w / 2
    p.setFont(font)
    p.setPen(glow)
    for ox, oy in ((0.7, 0), (-0.7, 0), (0, 0.7), (0, -0.7)):
        p.drawText(QPointF(x + ox, y + oy), s)
    p.setPen(color)
    p.drawText(QPointF(x, y), s)
    return w


# ---- Rahmen und Kleinteile ----------------------------------------------------

def shell(p: QPainter, alpha: float) -> None:
    if alpha <= 0:
        return
    p.save()
    p.setOpacity(p.opacity() * alpha)
    path = QPainterPath()
    path.addRoundedRect(QRectF(0.5, 0.5, W - 1, H - 1), 8, 8)
    p.fillPath(path, qc(SHELL, 0.95))
    p.setPen(QPen(qc(LINE, 0.10), 1.0))
    p.drawPath(path)
    p.restore()


def rec_square(p: QPainter, x: float, y: float, t: float, color, reduced: bool) -> None:
    """Aufnahme-Quadrat (Pixelquadrat der Marke), pulsiert mit 1 Hz."""
    a = 1.0 if reduced else 0.55 + 0.45 * (0.5 + 0.5 * math.cos(2 * math.pi * t))
    p.fillRect(QRectF(x, y, 6, 6), qc(color, a))


def check_mark(p: QPainter, x: float, y: float, s: float, color, alpha: float = 1.0) -> None:
    p.save()
    pen = QPen(qc(color, alpha), 1.4)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)
    path = QPainterPath(QPointF(x, y + s * 0.55))
    path.lineTo(x + s * 0.36, y + s * 0.9)
    path.lineTo(x + s, y + s * 0.1)
    p.drawPath(path)
    p.restore()


@dataclass
class Frame:
    """Was der Host je Bild an die Stile reicht."""
    reduced: bool = False        # Windows-Schalter „Animationseffekte“ aus
    cinema: bool = False         # erstes Diktat des Tages (Kino-Intro im Stil Gun Barrel)
    polishing: bool = False      # Politur läuft (sonst Entschlüsselung)
    raw_text: str = ""           # Whisper-Text (Stil Klartext)
    polished_text: str = ""      # polierter Text (Stil Klartext)
    polish_t: float = -1.0       # Beginn der Politur
    px: float = 1.0              # Entwurfs-Pixel → Gerätepixel (Skalierung × DPI)


class HudStyle:
    """Grundgerüst eines Stils: Modus, Zeiten, Statuswort, Abbruch-Ausblendung."""

    key = ""
    ERROR_MAX_S = 5.0            # Fehler steht, bis Kira wieder bereit ist (IDLE), höchstens so lange
    shows_errors = True          # Klassisch: Fehler wie bis v0.4.0 nur im Tray

    def __init__(self) -> None:
        self.mode = "hidden"
        self.t0 = 0.0
        self.rel_t = 0.0
        self.end_t = 0.0
        self.fade_t = -1.0
        self.msg = ""
        self.scr = Scramble()

    # -- Übergänge ------------------------------------------------------------
    def press(self, t: float, f: Frame) -> None:
        self.mode = "rec"
        self.t0 = t
        self.fade_t = -1.0
        self.on_press(t, f)

    def release(self, t: float, f: Frame) -> None:
        if self.mode == "rec":
            self.mode = "proc"
            self.rel_t = t
            self.on_release(t, f)

    def done(self, t: float, f: Frame) -> None:
        if self.mode in ("rec", "proc"):
            self.mode = "done"
            self.end_t = t
            self.on_done(t, f)

    def error(self, t: float, msg: str, f: Frame) -> None:
        if not self.shows_errors:
            self.mode = "hidden"
            return
        if self.mode in ("hidden", "done") or self.fade_t >= 0:
            # Neu ansetzen, auch wenn das vorige Diktat noch aus- oder abblendet.
            self.t0 = self.rel_t = t
            self.on_clear(f)
        elif self.mode == "rec":
            self.rel_t = t
        self.mode = "error"
        self.end_t = t
        self.fade_t = -1.0
        self.msg = msg
        self.on_error(t, f)

    def abort(self, t: float) -> None:
        """IDLE: kurzer Druck, nichts erkannt oder Fehler vorbei → ohne Übergabe ausblenden."""
        if self.mode in ("rec", "proc", "error") and self.fade_t < 0:
            if self.mode == "rec":
                self.rel_t = t
            self.fade_t = t

    def on_press(self, t: float, f: Frame) -> None: ...
    def on_clear(self, f: Frame) -> None:
        """Reste des letzten Diktats verwerfen (Fehler aus dem verborgenen Zustand)."""
    def on_release(self, t: float, f: Frame) -> None: ...
    def on_done(self, t: float, f: Frame) -> None: ...
    def on_error(self, t: float, f: Frame) -> None: ...

    # -- je Bild ------------------------------------------------------------------
    @property
    def visible(self) -> bool:
        return self.mode != "hidden"

    @property
    def leaving(self) -> bool:
        """Blendet gerade aus (Übergabe oder Abbruch); ein Fehler setzt dann neu an."""
        return self.mode == "done" or self.fade_t >= 0

    def fade_alpha(self, t: float) -> float:
        return 1.0 if self.fade_t < 0 else 1.0 - prog(t, self.fade_t, FADE_S)

    def tick(self, t: float, dt: float, f: Frame, tap, an) -> None:
        if self.fade_t >= 0 and t - self.fade_t >= FADE_S:
            self.mode = "hidden"
            return
        if self.mode == "error" and t - self.end_t > self.ERROR_MAX_S:
            self.mode = "hidden"
            return
        if self.mode != "hidden":
            self.step(t, dt, f, tap, an)
        if self.mode != "hidden":
            # Statuswort je Takt nachführen, nicht erst beim Zeichnen: sonst
            # hinge der Entschlüsselungs-Effekt davon ab, wann Qt neu zeichnet.
            text, _color, animate = self.status(f, an)
            self.scr.set(text, t, animate)

    def step(self, t: float, dt: float, f: Frame, tap, an) -> None: ...

    def paint(self, p: QPainter, t: float, f: Frame, tap, an) -> None: ...

    # -- Hilfen -----------------------------------------------------------------
    def status(self, f: Frame, an) -> tuple[str, tuple, bool]:
        if self.mode == "rec":
            if an.silent:
                return "KEIN SIGNAL", AMBER, False
            if an.clip:
                return "ZU NAH", RED, False
            return "AUFNAHME", LINE, False
        if self.mode == "proc":
            return ("POLITUR", LINE, True) if f.polishing else ("ENTSCHLÜSSELUNG", LINE, True)
        if self.mode == "done":
            return "ÜBERGABE", LINE, False
        if self.mode == "error":
            return "FEHLER", RED, False
        return "", LINE, False

    def status_text(self, t: float, f: Frame, an) -> tuple[str, str, tuple]:
        text, color, animate = self.status(f, an)
        self.scr.set(text, t, animate)
        return self.scr.get(t, f.reduced), text, color

    def elapsed(self, t: float) -> float:
        return (t if self.mode == "rec" else self.rel_t) - self.t0

    def error_alpha(self, t: float) -> float:
        return 1.0 - prog(t, self.end_t + self.ERROR_MAX_S - 0.2, 0.2)

    def message_lines(self) -> tuple[str, str]:
        first, _, second = self.msg.partition("|")
        return first, second
