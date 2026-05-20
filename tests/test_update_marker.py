"""Tests fuer kira._update_marker — der .update-declined-Marker.

Windows-only: das Modul resolved %APPDATA%\\Kira analog zu
kira.firstrun und ist auf Nicht-Windows nicht sinnvoll testbar.

Das Marker-File merkt sich die zuletzt vom Nutzer abgelehnte
Update-Version, damit der Start-Update-Check (kira/main.py) nicht
bei jedem Boot erneut fuer dieselbe Version fragt.
"""
from __future__ import annotations

import sys

import pytest

if sys.platform != "win32":
    pytest.skip("update-marker module is Windows-only", allow_module_level=True)

from kira._update_marker import (
    UPDATE_DECLINED_MARKER_NAME,
    _kira_appdata_dir,
    is_update_declined,
    mark_update_declined,
)


def _pin_appdata(tmp_path, monkeypatch):
    """APPDATA + USERPROFILE auf tmp_path pinnen.

    APPDATA muss UNTER USERPROFILE liegen (USERPROFILE-Whitelist-Defense,
    s. _kira_appdata_dir). tmp_path liegt sonst unter $TEMP — also beide
    Env-Vars auf tmp_path setzen damit der Whitelist-Check passt.
    """
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.setenv("APPDATA", str(tmp_path))
    kira_dir = tmp_path / "Kira"
    kira_dir.mkdir(exist_ok=True)
    return kira_dir


# ---------------------------------------------------------------------------
# is_update_declined — Default-Zustand
# ---------------------------------------------------------------------------

def test_not_declined_when_marker_absent(tmp_path, monkeypatch):
    """Frischer Zustand, kein Marker — der Nutzer wurde noch nie gefragt."""
    _pin_appdata(tmp_path, monkeypatch)
    assert is_update_declined("0.3.0") is False


def test_declined_true_for_exact_version(tmp_path, monkeypatch):
    """Marker enthaelt genau die abgefragte Version — schon abgelehnt."""
    kira_dir = _pin_appdata(tmp_path, monkeypatch)
    (kira_dir / UPDATE_DECLINED_MARKER_NAME).write_text("0.3.0\n", encoding="utf-8")
    assert is_update_declined("0.3.0") is True


def test_declined_false_for_different_version(tmp_path, monkeypatch):
    """Marker haelt 0.3.0, aber 0.4.0 erscheint — der Nutzer wird wieder
    gefragt. Der Marker speichert nur die EINE zuletzt abgelehnte Version."""
    kira_dir = _pin_appdata(tmp_path, monkeypatch)
    (kira_dir / UPDATE_DECLINED_MARKER_NAME).write_text("0.3.0\n", encoding="utf-8")
    assert is_update_declined("0.4.0") is False


def test_declined_ignores_surrounding_whitespace(tmp_path, monkeypatch):
    """Marker mit fuehrenden/folgenden Leerzeichen + die Abfrage selbst
    werden beide getrimmt, damit ' 0.3.0 ' sauber matcht."""
    kira_dir = _pin_appdata(tmp_path, monkeypatch)
    (kira_dir / UPDATE_DECLINED_MARKER_NAME).write_text(
        "  0.3.0  \n", encoding="utf-8",
    )
    assert is_update_declined(" 0.3.0 ") is True


# ---------------------------------------------------------------------------
# mark_update_declined — Schreiben
# ---------------------------------------------------------------------------

def test_mark_creates_marker_with_version(tmp_path, monkeypatch):
    kira_dir = _pin_appdata(tmp_path, monkeypatch)
    mark_update_declined("0.3.0")
    marker = kira_dir / UPDATE_DECLINED_MARKER_NAME
    assert marker.exists()
    assert marker.read_text(encoding="utf-8").strip() == "0.3.0"


def test_mark_creates_kira_dir_if_missing(tmp_path, monkeypatch):
    """Kira-Dir existiert noch nicht — mark_update_declined legt es an."""
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.setenv("APPDATA", str(tmp_path))
    # kein kira_dir.mkdir() hier — das soll mark_update_declined leisten
    mark_update_declined("0.3.0")
    assert (tmp_path / "Kira" / UPDATE_DECLINED_MARKER_NAME).exists()


def test_mark_overwrites_previous_version(tmp_path, monkeypatch):
    """Lehnt der Nutzer spaeter eine andere Version ab, ersetzt der Marker
    die alte — es bleibt immer nur die zuletzt abgelehnte Version."""
    kira_dir = _pin_appdata(tmp_path, monkeypatch)
    mark_update_declined("0.3.0")
    mark_update_declined("0.4.0")
    marker = kira_dir / UPDATE_DECLINED_MARKER_NAME
    assert marker.read_text(encoding="utf-8").strip() == "0.4.0"
    # Folge-Invariante: 0.3.0 gilt jetzt NICHT mehr als abgelehnt.
    assert is_update_declined("0.3.0") is False
    assert is_update_declined("0.4.0") is True


def test_mark_then_is_declined_roundtrip(tmp_path, monkeypatch):
    """End-to-End: ablehnen → beim naechsten Check als abgelehnt erkannt."""
    _pin_appdata(tmp_path, monkeypatch)
    assert is_update_declined("0.3.0") is False
    mark_update_declined("0.3.0")
    assert is_update_declined("0.3.0") is True


# ---------------------------------------------------------------------------
# Fehler-Robustheit — der Update-Check ist Komfort, kein Pflicht-Pfad.
# Marker-Fehler duerfen die Boot-Sequenz NICHT beeinflussen.
# ---------------------------------------------------------------------------

def test_is_declined_returns_false_on_env_error(monkeypatch):
    """APPDATA fehlt komplett — is_update_declined faengt den
    EnvironmentError ab und liefert False (= im Zweifel fragen),
    statt die Exception in die Boot-Sequenz durchschlagen zu lassen."""
    monkeypatch.delenv("APPDATA", raising=False)
    assert is_update_declined("0.3.0") is False


def test_mark_swallows_env_error(monkeypatch):
    """APPDATA fehlt — mark_update_declined schluckt den Fehler (loggt nur),
    statt zu werfen. Der naechste Start fragt dann halt erneut."""
    monkeypatch.delenv("APPDATA", raising=False)
    mark_update_declined("0.3.0")  # darf NICHT werfen


def test_kira_appdata_dir_rejects_appdata_outside_userprofile(tmp_path, monkeypatch):
    """Defense-in-Depth: manipulierte Env (APPDATA zeigt aus USERPROFILE
    heraus) → EnvironmentError. Gleiche Whitelist wie kira.firstrun."""
    user_profile = tmp_path / "UserHome"
    user_profile.mkdir()
    fake_appdata = tmp_path / "OutsideHome" / "Roaming"
    fake_appdata.mkdir(parents=True)
    monkeypatch.setenv("USERPROFILE", str(user_profile))
    monkeypatch.setenv("APPDATA", str(fake_appdata))
    with pytest.raises(EnvironmentError):
        _kira_appdata_dir()


def test_environment_error_is_oserror_subclass():
    """Invariant: is_update_declined faengt OSError — EnvironmentError ist
    seit Py3.3 ein OSError-Alias. Sanity-Check, damit der Catch greift."""
    assert issubclass(EnvironmentError, OSError)
