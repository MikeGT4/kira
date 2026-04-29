"""Tests for the welcome-marker logic. UI not exercised (Qt headless setup
would be brittle in a regular pytest run); the dialog itself is covered by
the manual smoke test in scripts/install_*.ps1.
"""
from __future__ import annotations
import sys

import pytest

if sys.platform != "win32":
    pytest.skip("windows-only tests", allow_module_level=True)


def test_is_first_run_returns_true_when_marker_missing(tmp_path, monkeypatch):
    from kira.ui import welcome_dialog
    fake_marker = tmp_path / "Kira" / ".welcomed"
    monkeypatch.setattr(welcome_dialog, "_WELCOME_MARKER", fake_marker)
    assert welcome_dialog.is_first_run() is True


def test_mark_welcomed_creates_marker_and_parent(tmp_path, monkeypatch):
    from kira.ui import welcome_dialog
    fake_marker = tmp_path / "Kira" / ".welcomed"
    monkeypatch.setattr(welcome_dialog, "_WELCOME_MARKER", fake_marker)
    welcome_dialog.mark_welcomed()
    assert fake_marker.exists()
    assert fake_marker.read_text(encoding="utf-8") == "welcomed"


def test_is_first_run_returns_false_after_mark(tmp_path, monkeypatch):
    from kira.ui import welcome_dialog
    fake_marker = tmp_path / "Kira" / ".welcomed"
    monkeypatch.setattr(welcome_dialog, "_WELCOME_MARKER", fake_marker)
    assert welcome_dialog.is_first_run() is True
    welcome_dialog.mark_welcomed()
    assert welcome_dialog.is_first_run() is False
