"""Tests for kira.main — logging setup.

kira.log wuchs unbegrenzt (13 MB nach ~7 Wochen, kein Cap). Mike will
einen harten 30-MB-Deckel. _build_log_handler() muss einen rotierenden
Handler liefern, dessen Gesamtgröße (aktuelle Datei + Backups) 30 MB
nie überschreitet, und UTF-8 schreiben, damit deutsche Umlaute in
kira.log nicht als Mojibake landen.
"""
from __future__ import annotations
import logging.handlers


def test_log_handler_is_rotating(tmp_path):
    from kira import main
    handler = main._build_log_handler(tmp_path / "kira.log")
    assert isinstance(handler, logging.handlers.RotatingFileHandler)


def test_log_handler_total_cap_at_most_30mb(tmp_path):
    """Aktuelle Datei + alle Backups dürfen zusammen ≤ 30 MB sein."""
    from kira import main
    handler = main._build_log_handler(tmp_path / "kira.log")
    total_cap = handler.maxBytes * (1 + handler.backupCount)
    assert handler.maxBytes > 0, "maxBytes=0 deaktiviert Rotation komplett"
    assert handler.backupCount >= 1, "ohne Backup geht beim Roll-Over History verloren"
    assert total_cap <= 30 * 1024 * 1024, f"Gesamt-Cap {total_cap} überschreitet 30 MB"


def test_log_handler_writes_utf8(tmp_path):
    """Umlaute (ü/ö/ä/ß) dürfen in kira.log nicht zu Mojibake werden."""
    from kira import main
    handler = main._build_log_handler(tmp_path / "kira.log")
    normalized = (handler.encoding or "").lower().replace("-", "")
    assert normalized == "utf8", f"encoding={handler.encoding!r}, erwartet utf-8"
