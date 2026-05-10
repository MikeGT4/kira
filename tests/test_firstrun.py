"""Tests for first-run detection and marker file handling."""
from __future__ import annotations

import sys

import pytest

if sys.platform != "win32":
    pytest.skip("First-run module is Windows-only", allow_module_level=True)

from kira.firstrun import (
    is_first_run,
    mark_first_run_complete,
    FIRST_RUN_MARKER_NAME,
)


def test_first_run_true_when_marker_absent(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    kira_dir = tmp_path / "Kira"
    kira_dir.mkdir()
    assert is_first_run() is True


def test_first_run_false_when_marker_present(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    kira_dir = tmp_path / "Kira"
    kira_dir.mkdir()
    (kira_dir / FIRST_RUN_MARKER_NAME).write_text("done")
    assert is_first_run() is False


def test_mark_first_run_complete_creates_marker(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    kira_dir = tmp_path / "Kira"
    kira_dir.mkdir()
    mark_first_run_complete()
    assert (kira_dir / FIRST_RUN_MARKER_NAME).exists()


def test_mark_first_run_creates_kira_dir_if_missing(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    mark_first_run_complete()
    assert (tmp_path / "Kira" / FIRST_RUN_MARKER_NAME).exists()
