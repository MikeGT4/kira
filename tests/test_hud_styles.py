# © 2026 Mike Pollow, Digitalroots. Alle Rechte vorbehalten.
"""Tests für die Stile der Aufnahme-Anzeige und ihren Host (Windows, PyQt6).

Die Stile werden ohne Fenster in ein QImage gezeichnet; der Host läuft mit
echtem Takt. Zum Laufen ohne sichtbare Fenster: QT_QPA_PLATFORM=offscreen.
"""
from __future__ import annotations

import math
import os
import sys

import numpy as np
import pytest

if sys.platform != "win32":
    pytest.skip("windows-only tests (PyQt6)", allow_module_level=True)

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QImage, QPainter

from kira.config import HUD_STYLES
from kira.ui.hud import STYLE_LABELS, create_style
from kira.ui.hud import base as hud_base
from kira.ui.hud.base import H, W, Frame
from kira.ui.hud.signal import SAMPLE_RATE, SignalAnalysis, SignalTap

DT = 1 / 60
BLOCK = 1600


def _speech(k: int, amp: float) -> np.ndarray:
    """Silbenartiger Block: 150-Hz-Klang mit 4-Hz-Hüllkurve."""
    i = np.arange(k * BLOCK, (k + 1) * BLOCK)
    env = 0.5 + 0.5 * np.sin(2 * np.pi * 4 * i / SAMPLE_RATE)
    sig = np.sin(2 * np.pi * 150 * i / SAMPLE_RATE) + 0.4 * np.sin(2 * np.pi * 900 * i / SAMPLE_RATE)
    return np.clip(amp * env * sig / 1.4, -1, 1).astype(np.float32)


class Driver:
    """Spielt einen Stil ohne Fenster durch: Signal, Takt, Zeichnen."""

    def __init__(self, key: str, px: float = 1.5, reduced: bool = False) -> None:
        self.style = create_style(key)
        self.tap = SignalTap()
        self.an = SignalAnalysis()
        self.f = Frame(px=px, reduced=reduced)
        self.t = 100.0
        self._k = 0
        self._next = self.t

    def press(self) -> None:
        self.tap.start()
        self.an.reset(self.t)
        self.style.press(self.t, self.f)

    def run(self, seconds: float, amp: float = 0.5) -> None:
        for _ in range(int(round(seconds / DT))):
            if self.t >= self._next:
                self.tap.push(_speech(self._k, amp) if amp > 0 else np.zeros(BLOCK, np.float32))
                self._k += 1
                self._next += 0.1
            self.t += DT
            self.tap.advance(DT)
            self.an.update(self.tap, self.t, DT, recording=self.style.mode == "rec",
                           rec_elapsed=self.t - self.style.t0)
            self.style.tick(self.t, DT, self.f, self.tap, self.an)
            if self.style.visible:
                self.render()

    def render(self) -> QImage:
        img = QImage(round(W * self.f.px), round(H * self.f.px), QImage.Format.Format_ARGB32_Premultiplied)
        img.fill(Qt.GlobalColor.transparent)
        p = QPainter(img)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.scale(self.f.px, self.f.px)
        p.setOpacity(self.style.fade_alpha(self.t))
        self.style.paint(p, self.t, self.f, self.tap, self.an)
        p.end()
        return img


def _ink(img: QImage) -> int:
    ptr = img.constBits()
    ptr.setsize(img.sizeInBytes())
    arr = np.frombuffer(ptr, np.uint8).reshape(img.height(), img.bytesPerLine() // 4, 4)
    return int((arr[..., 3] > 0).sum())


def test_registry_matches_config_and_falls_back():
    assert tuple(STYLE_LABELS) == HUD_STYLES
    for key in HUD_STYLES:
        assert create_style(key).key == key
    assert create_style("gibtsnicht").key == "phosphor"


def test_fonts_are_ibm_plex_mono(qapp):
    hud_base.load_fonts()
    assert all("IBM Plex Mono" in hud_base._FAMILIES[w] for w in (400, 500, 600))


@pytest.mark.parametrize("key", HUD_STYLES)
@pytest.mark.parametrize("reduced", [False, True])
def test_full_cycle_draws_and_ends_hidden(qapp, key, reduced):
    d = Driver(key, reduced=reduced)
    d.press()
    d.run(1.5)
    assert d.style.visible
    assert _ink(d.render()) > 2000
    d.style.release(d.t, d.f)
    d.run(0.5, amp=0.0)
    d.f.polishing = True
    d.f.polish_t = d.t
    d.f.raw_text = "kannst du mir die unterlagen bis freitag schicken"
    d.run(0.45, amp=0.0)
    assert d.style.visible
    d.f.polished_text = "Kannst du mir die Unterlagen bis Freitag schicken?"
    d.style.done(d.t, d.f)
    d.run(1.2, amp=0.0)
    assert not d.style.visible


@pytest.mark.parametrize("key", [k for k in HUD_STYLES if k != "klassisch"])
def test_error_from_hidden_shows_reason_then_hides(qapp, key):
    d = Driver(key)
    d.style.error(d.t, "Mikrofon nicht gefunden.|Gerät prüfen, dann erneut drücken.", d.f)
    assert d.style.visible
    d.run(0.3, amp=0.0)
    assert _ink(d.render()) > 2000
    d.run(1.3, amp=0.0)
    assert not d.style.visible


def test_classic_keeps_errors_in_the_tray(qapp):
    d = Driver("klassisch")
    d.style.error(d.t, "egal", d.f)
    assert not d.style.visible


@pytest.mark.parametrize("key", HUD_STYLES)
def test_abort_hides_within_200_ms(qapp, key):
    d = Driver(key)
    d.press()
    d.run(0.3)
    d.style.abort(d.t)
    d.run(0.2, amp=0.0)
    assert not d.style.visible


@pytest.mark.parametrize("key", [k for k in HUD_STYLES if k != "klassisch"])
def test_warnings_for_dead_mic_and_clipping(qapp, key):
    d = Driver(key)
    d.press()
    d.run(0.9, amp=0.0)
    assert d.style.status(d.f, d.an)[0] == "KEIN SIGNAL"
    d.render()
    d.run(0.4, amp=3.0)
    assert d.style.status(d.f, d.an)[0] == "ZU NAH"
    d.render()


def test_gun_barrel_cinema_intro_only_when_flagged(qapp):
    d = Driver("gun_barrel")
    d.f.cinema = True
    d.press()
    d.run(0.1)
    assert d.style._cine is True
    d2 = Driver("gun_barrel")
    d2.press()
    assert d2.style._cine is False


def test_scale_150_percent_is_the_default_size(qapp, tmp_path):
    from kira.ui.hud_qt import PopupHUD
    hud = PopupHUD(config_path=tmp_path / "fehlt.yaml")
    assert hud.style_key == "phosphor"
    assert (hud.width(), hud.height()) == (390, 120)


# ---- Host mit echtem Takt -------------------------------------------------------

def _write_cfg(path, style: str, scale: float = 1.5, bump: float = 0.0) -> None:
    path.write_text(f"ui:\n  hud_style: {style}\n  hud_scale: {scale}\n", encoding="utf-8")
    if bump:
        st = path.stat()
        os.utime(path, (st.st_atime + bump, st.st_mtime + bump))


def _feed(hud, blocks: int = 6) -> None:
    for k in range(blocks):
        hud.push_samples(_speech(k, 0.5))


def test_host_reads_style_and_scale(qtbot, tmp_path):
    from kira.ui.hud_qt import PopupHUD
    cfg = tmp_path / "config.yaml"
    _write_cfg(cfg, "klartext", 2.0)
    hud = PopupHUD(config_path=cfg)
    qtbot.addWidget(hud)
    assert hud.style_key == "klartext"
    assert (hud.width(), hud.height()) == (520, 160)


def test_host_switches_style_on_next_press(qtbot, tmp_path):
    from kira.ui.hud_qt import PopupHUD
    cfg = tmp_path / "config.yaml"
    _write_cfg(cfg, "phosphor")
    hud = PopupHUD(config_path=cfg)
    qtbot.addWidget(hud)
    _write_cfg(cfg, "gun_barrel", bump=5)
    hud.set_phase("rec")
    qtbot.waitUntil(lambda: hud.isVisible(), timeout=2000)
    assert hud.style_key == "gun_barrel"
    hud.set_phase("idle")
    qtbot.waitUntil(lambda: not hud.isVisible(), timeout=2000)


def test_host_full_cycle_ends_hidden(qtbot, tmp_path):
    from kira.ui.hud_qt import PopupHUD
    cfg = tmp_path / "config.yaml"
    _write_cfg(cfg, "phosphor")
    hud = PopupHUD(config_path=cfg)
    qtbot.addWidget(hud)
    hud.set_phase("rec")
    _feed(hud)
    qtbot.wait(400)
    assert hud.isVisible()
    hud.set_phase("trans")
    qtbot.wait(200)
    hud.set_texts(raw="hallo welt")
    hud.set_phase("polish")
    qtbot.wait(150)
    hud.set_texts(polished="Hallo Welt.")
    hud.set_phase("done")
    hud.set_phase("idle")
    qtbot.waitUntil(lambda: not hud.isVisible(), timeout=2000)


def test_host_error_while_hidden_shows_then_hides(qtbot, tmp_path):
    from kira.ui.hud_qt import PopupHUD
    cfg = tmp_path / "config.yaml"
    _write_cfg(cfg, "zielerfassung")
    hud = PopupHUD(config_path=cfg)
    qtbot.addWidget(hud)
    hud.set_phase("error", "Nichts markiert.|Erst Text markieren, dann erneut.")
    qtbot.waitUntil(lambda: hud.isVisible(), timeout=1000)
    qtbot.waitUntil(lambda: not hud.isVisible(), timeout=3000)


def test_legacy_api_still_drives_the_hud(qtbot, tmp_path):
    from kira.ui.hud_qt import PopupHUD
    cfg = tmp_path / "config.yaml"
    _write_cfg(cfg, "stimmabdruck")
    hud = PopupHUD(config_path=cfg)
    qtbot.addWidget(hud)
    hud.show("Recording…")
    qtbot.waitUntil(lambda: hud.isVisible(), timeout=1000)
    hud.update_status("Transcribing…")
    hud.hide()
    qtbot.waitUntil(lambda: not hud.isVisible(), timeout=2000)
    assert not math.isnan(hud.scale)
