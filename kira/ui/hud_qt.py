"""PyQt6-Aufnahme-Anzeige (HUD) am Mauszeiger, Windows.

Host für die Stile aus ``kira.ui.hud`` (seit v0.4.1): rahmenlos,
durchklickbar, ohne Fokus-Klau, immer oben. Zeichnet mit 60 Bildern je
Sekunde, solange die Anzeige sichtbar ist. Stil und Größe kommen aus
``ui.hud_style`` und ``ui.hud_scale`` (Standard: Phosphor, 150 % von
260 × 80 px). Ändert sich die config.yaml, über die Einstellungen oder die
Rohconfig, gilt der neue Stil ab dem nächsten Diktat, ohne Neustart.

Schnittstelle, threadsicher über Qt-Signale:
  set_phase("rec" | "trans" | "polish" | "done" | "idle" | "error", message)
  set_texts(raw=..., polished=...)
  push_samples(np.ndarray)
show / update_status / hide bleiben als Gleichlauf zur Mac-PopupHUD erhalten.
"""
from __future__ import annotations

import datetime
import logging
import sys
import time
from pathlib import Path

from PyQt6.QtCore import QObject, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QCursor, QGuiApplication, QPainter
from PyQt6.QtWidgets import QWidget

from kira.config import DEFAULT_HUD_STYLE, default_config_path, load_config
from kira.ui.hud import create_style
from kira.ui.hud.base import H, W, Frame, load_fonts
from kira.ui.hud.klassisch import WAVE_COLOR  # noqa: F401  Markenfarbe, geprüft in test_brand_assets
from kira.ui.hud.signal import SignalAnalysis, SignalTap

log = logging.getLogger(__name__)

FRAME_MS = 16
CURSOR_GAP_X, CURSOR_GAP_Y = 14, 8
_SPI_GETCLIENTAREAANIMATION = 0x1042
_STATUS_TO_PHASE = {"Transcribing…": "trans", "Polishing…": "polish"}


def animations_off() -> bool:
    """Windows-Schalter „Animationseffekte“ (Barrierefreiheit → Visuelle Effekte) aus?"""
    if sys.platform != "win32":
        return False
    try:
        import ctypes

        value = ctypes.c_int(1)
        ok = ctypes.windll.user32.SystemParametersInfoW(
            _SPI_GETCLIENTAREAANIMATION, 0, ctypes.byref(value), 0,
        )
        return bool(ok) and not value.value
    except Exception:
        log.exception("SPI_GETCLIENTAREAANIMATION nicht lesbar")
        return False


class _HudSignals(QObject):
    """Cross-thread signals to marshal calls onto the Qt main thread."""
    phase = pyqtSignal(str, str)
    texts = pyqtSignal(object, object)
    push_samples = pyqtSignal(object)  # np.ndarray


class PopupHUD(QWidget):
    """Rahmenloses Overlay; der aktive Stil zeichnet, der Host liefert Takt und Signal."""

    def __init__(self, config_path: Path | None = None) -> None:
        super().__init__()
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        load_fonts()

        self._cfg_path = config_path or default_config_path()
        self._cfg_mtime: float | None = None
        self._style_key = DEFAULT_HUD_STYLE
        self._scale = 1.5
        self._style = create_style(DEFAULT_HUD_STYLE)
        self._reload_config(force=True)

        self._tap = SignalTap()
        self._an = SignalAnalysis()
        self._frame = Frame()
        self._cinema_day: datetime.date | None = None
        self._t_last = time.monotonic()
        self._paint_t = self._t_last
        self._failed = False

        self._sig = _HudSignals()
        self._sig.phase.connect(self._on_phase)
        self._sig.texts.connect(self._on_texts)
        self._sig.push_samples.connect(self._on_push_samples)

        self._timer = QTimer(self)
        self._timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._timer.setInterval(FRAME_MS)
        self._timer.timeout.connect(self._tick)

    # ---- öffentliche Schnittstelle (threadsicher) ----
    def set_phase(self, phase: str, message: str | None = None) -> None:
        self._sig.phase.emit(phase, message or "")

    def set_texts(self, raw: str | None = None, polished: str | None = None) -> None:
        self._sig.texts.emit(raw, polished)

    def push_samples(self, samples) -> None:
        """Einen Block roher Mono-Samples (np.ndarray, float32) übergeben."""
        self._sig.push_samples.emit(samples)

    def show(self, status: str = "Recording…") -> None:
        self.set_phase("rec")

    def update_status(self, status: str) -> None:
        self.set_phase(_STATUS_TO_PHASE.get(status, "trans"))

    def hide(self) -> None:
        self.set_phase("idle")

    @property
    def style_key(self) -> str:
        return self._style_key

    @property
    def scale(self) -> float:
        return self._scale

    # ---- Qt-Hauptthread ----
    def _on_push_samples(self, samples) -> None:
        try:
            self._tap.push(samples)
        except Exception:
            log.exception("push_samples failed")

    def _on_texts(self, raw, polished) -> None:
        if raw is not None:
            self._frame.raw_text = str(raw)
        if polished is not None:
            self._frame.polished_text = str(polished)

    def _on_phase(self, phase: str, message: str) -> None:
        t = time.monotonic()
        style = self._style
        if phase == "rec":
            self._prepare(t)
            self._frame.raw_text = ""
            self._frame.polished_text = ""
            today = datetime.date.today()
            self._frame.cinema = self._cinema_day != today
            self._cinema_day = today
            self._tap.start()
            self._an.reset(t)
            self._style.press(t, self._frame)
        elif phase == "trans":
            style.release(t, self._frame)
        elif phase == "polish":
            self._frame.polishing = True
            self._frame.polish_t = t
        elif phase == "done":
            style.done(t, self._frame)
        elif phase == "error":
            if not style.visible:
                self._prepare(t)
            self._style.error(t, message or "Details im Log.", self._frame)
        elif phase == "idle":
            style.abort(t)
        if self._style.visible:
            self._start()
        else:
            self._stop()

    def _prepare(self, t: float) -> None:
        """Vor dem Einblenden: Config prüfen, Schalter lesen, am Zeiger platzieren."""
        self._reload_config()
        self._frame.reduced = animations_off()
        self._frame.polishing = False
        self._frame.polish_t = -1.0
        self._failed = False
        self._place_at_cursor()

    def _place_at_cursor(self) -> None:
        pos = QCursor.pos()
        w, h = self.width(), self.height()
        x = pos.x() + CURSOR_GAP_X
        y = pos.y() - h - CURSOR_GAP_Y
        screen = QGuiApplication.screenAt(pos) or QGuiApplication.primaryScreen()
        dpr = 1.0
        if screen is not None:
            area = screen.availableGeometry()
            if y < area.top():
                y = pos.y() + 24
            x = max(area.left(), min(x, area.right() - w + 1))
            y = max(area.top(), min(y, area.bottom() - h + 1))
            dpr = screen.devicePixelRatio()
        self._frame.px = self._scale * dpr
        self.move(x, y)

    def _reload_config(self, force: bool = False) -> None:
        try:
            mtime: float | None = self._cfg_path.stat().st_mtime
        except OSError:
            mtime = None
        if not force and mtime == self._cfg_mtime:
            return
        self._cfg_mtime = mtime
        try:
            ui = load_config(self._cfg_path).ui
        except Exception:
            log.exception("config.yaml nicht lesbar, Anzeige bleibt bei %s", self._style_key)
            return
        if ui.hud_style != self._style_key:
            log.info("Aufnahme-Anzeige: Stil %s → %s", self._style_key, ui.hud_style)
            self._style_key = ui.hud_style
            self._style = create_style(ui.hud_style)
        if ui.hud_scale != self._scale or force:
            self._scale = ui.hud_scale
            self.setFixedSize(round(W * self._scale), round(H * self._scale))

    def _start(self) -> None:
        if not self.isVisible():
            super().show()
            self._t_last = time.monotonic()
        if not self._timer.isActive():
            self._timer.start()
        self.update()

    def _stop(self) -> None:
        self._timer.stop()
        super().hide()

    def _tick(self) -> None:
        t = time.monotonic()
        dt = min(0.05, max(0.0, t - self._t_last))
        self._t_last = t
        style = self._style
        self._tap.advance(dt)
        self._an.update(self._tap, t, dt, recording=style.mode == "rec", rec_elapsed=t - style.t0)
        try:
            style.tick(t, dt, self._frame, self._tap, self._an)
        except Exception:
            self._fail("Rechenschritt")
        if not style.visible:
            self._stop()
            return
        self._paint_t = t
        self.update()

    def _fail(self, where: str) -> None:
        if not self._failed:
            log.exception("Aufnahme-Anzeige %s: %s fehlgeschlagen", self._style_key, where)
        self._failed = True
        self._style.mode = "hidden"

    def paintEvent(self, _event) -> None:
        style = self._style
        if not style.visible:
            return
        p = QPainter(self)
        try:
            p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            p.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
            p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
            p.scale(self._scale, self._scale)
            p.setOpacity(style.fade_alpha(self._paint_t))
            style.paint(p, self._paint_t, self._frame, self._tap, self._an)
        except Exception:
            self._fail("Zeichnen")
        finally:
            p.end()
