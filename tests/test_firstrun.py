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
    _kira_appdata_dir,
)


def test_first_run_true_when_marker_absent(tmp_path, monkeypatch):
    # APPDATA muss UNTER USERPROFILE liegen (F3-Defense), tmp_path
    # liegt unter $TEMP, NICHT unter USERPROFILE — also USERPROFILE
    # kuenstlich auf tmp_path setzen damit der Whitelist-Check passt.
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.setenv("APPDATA", str(tmp_path))
    kira_dir = tmp_path / "Kira"
    kira_dir.mkdir()
    assert is_first_run() is True


def test_first_run_false_when_marker_present(tmp_path, monkeypatch):
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.setenv("APPDATA", str(tmp_path))
    kira_dir = tmp_path / "Kira"
    kira_dir.mkdir()
    (kira_dir / FIRST_RUN_MARKER_NAME).write_text("done")
    assert is_first_run() is False


def test_mark_first_run_complete_creates_marker(tmp_path, monkeypatch):
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.setenv("APPDATA", str(tmp_path))
    kira_dir = tmp_path / "Kira"
    kira_dir.mkdir()
    mark_first_run_complete()
    assert (kira_dir / FIRST_RUN_MARKER_NAME).exists()


def test_mark_first_run_creates_kira_dir_if_missing(tmp_path, monkeypatch):
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.setenv("APPDATA", str(tmp_path))
    mark_first_run_complete()
    assert (tmp_path / "Kira" / FIRST_RUN_MARKER_NAME).exists()


# ---------------------------------------------------------------------------
# Phase F (2026-05-10): EnvironmentError + USERPROFILE-Whitelist
# ---------------------------------------------------------------------------

def test_kira_appdata_dir_raises_environment_error_when_appdata_missing(monkeypatch):
    """F3: APPDATA fehlt komplett — wir wollen EnvironmentError (OSError-
    Subclass), NICHT RuntimeError. Damit faengt SetupWizard.accept() das
    via existierendes `except OSError` ab.
    """
    monkeypatch.delenv("APPDATA", raising=False)
    with pytest.raises(EnvironmentError):
        _kira_appdata_dir()


def test_environment_error_is_oserror_subclass():
    """F3 invariant: EnvironmentError ist == OSError seit Py3.3 — wenn
    das mal getrennt wuerde, wuerde der `except OSError`-Catch im Wizard
    fehlschlagen. Sanity-Check.
    """
    assert issubclass(EnvironmentError, OSError)


def test_kira_appdata_dir_rejects_appdata_outside_userprofile(tmp_path, monkeypatch):
    """F3: Manipulierte Env (APPDATA zeigt auf C:/Windows oder Network-
    Share) — wir refusen den Schreibvorgang. Defense-in-Depth gegen
    Path-Traversal via Env-Var-Tampering.
    """
    user_profile = tmp_path / "UserHome"
    user_profile.mkdir()
    fake_appdata = tmp_path / "OutsideHome" / "Roaming"
    fake_appdata.mkdir(parents=True)

    monkeypatch.setenv("USERPROFILE", str(user_profile))
    monkeypatch.setenv("APPDATA", str(fake_appdata))

    with pytest.raises(EnvironmentError) as exc_info:
        _kira_appdata_dir()

    msg = str(exc_info.value)
    assert "USERPROFILE" in msg or "user scope" in msg


def test_kira_appdata_dir_accepts_appdata_under_userprofile(tmp_path, monkeypatch):
    """F3: Normaler Pfad — APPDATA unter USERPROFILE/AppData/Roaming.
    """
    user_profile = tmp_path / "UserHome"
    user_profile.mkdir()
    appdata = user_profile / "AppData" / "Roaming"
    appdata.mkdir(parents=True)

    monkeypatch.setenv("USERPROFILE", str(user_profile))
    monkeypatch.setenv("APPDATA", str(appdata))

    result = _kira_appdata_dir()
    assert result == appdata / "Kira"


def test_kira_appdata_dir_accepts_when_userprofile_unset(tmp_path, monkeypatch):
    """F3: Edge — USERPROFILE nicht gesetzt (Container, ungewoehnliche
    Setups). Wir machen den Whitelist-Check NICHT, weil wir keinen
    Vergleichswert haben — APPDATA wird akzeptiert wie vorher.
    """
    monkeypatch.delenv("USERPROFILE", raising=False)
    monkeypatch.setenv("APPDATA", str(tmp_path))

    result = _kira_appdata_dir()
    assert result == tmp_path / "Kira"
