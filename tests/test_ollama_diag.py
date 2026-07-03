"""Tests fuer kira.ollama_diag — wer haelt den Ollama-Port 11434?

Hintergrund (2026-07-03): Ein Docker-Container (mirofish-ollama, via
wslrelay.exe auf die Windows-Seite gemappt) hielt Port 11434 und gewann
das Bind-Race gegen die Windows-Ollama-Tray-App. Kiras CPU-Fallback-Toast
empfahl "Ollama neu starten" — wirkungslos, weil der Windows-Ollama den
Port gar nicht hatte. Die Diagnose identifiziert den Port-Inhaber, damit
Toast + Log die RICHTIGE Abhilfe nennen.

Klassifikation + Texte sind pure Funktionen (laufen ueberall); die
Socket-Integrationstests brauchen GetExtendedTcpTable und laufen nur
auf Windows.
"""
import socket
import sys

import pytest

from kira.ollama_diag import (
    PortDiagnosis,
    classify_port_owner,
    diagnose_ollama_port,
    resolve_notice,
)


# --- classify_port_owner: pure Klassifikation nach Image-Pfad ---------------

def test_classify_wslrelay_as_wsl():
    assert classify_port_owner(r"C:\Program Files\WSL\wslrelay.exe") == "wsl"


def test_classify_wslhost_as_wsl():
    assert classify_port_owner(r"C:\WINDOWS\system32\wslhost.exe") == "wsl"


def test_classify_windows_ollama():
    assert classify_port_owner(
        r"C:\Users\mike\AppData\Local\Programs\Ollama\ollama.exe"
    ) == "win-ollama"


def test_classify_ollama_tray_app_as_win_ollama():
    # "ollama app.exe" bindet selbst nie, aber falls doch mal ein
    # Ollama-benannter Prozess der Owner ist: das ist der gute Fall.
    assert classify_port_owner(
        r"C:\Users\mike\AppData\Local\Programs\Ollama\ollama app.exe"
    ) == "win-ollama"


def test_classify_docker_backend_as_docker():
    assert classify_port_owner(
        r"C:\Program Files\Docker\Docker\resources\com.docker.backend.exe"
    ) == "docker"


def test_classify_unknown_when_image_missing():
    assert classify_port_owner(None) == "unknown"


def test_classify_other_process():
    assert classify_port_owner(r"C:\tools\nginx\nginx.exe") == "other"


# --- Empfehlungs-Texte (hint ist der deutsche Log-/Toast-Text) ---------------

def test_wsl_hint_names_relay_and_advises_stopping_foreign_server():
    diag = PortDiagnosis(
        kind="wsl", pid=29408,
        image=r"C:\Program Files\WSL\wslrelay.exe", port=11434,
    )
    assert "wslrelay.exe" in diag.hint
    assert "11434" in diag.hint
    assert "WSL" in diag.hint
    # Kern der Abhilfe: Fremd-Ollama stoppen oder Port verlegen — NICHT
    # den Windows-Ollama neu starten.
    assert "stoppen" in diag.hint or "anderen Port" in diag.hint


def test_win_ollama_hint_keeps_restart_advice():
    diag = PortDiagnosis(
        kind="win-ollama", pid=1234,
        image=r"C:\Users\mike\AppData\Local\Programs\Ollama\ollama.exe",
        port=11434,
    )
    assert "neu starten" in diag.hint.lower()


def test_none_hint_says_no_listener():
    diag = PortDiagnosis(kind="none", pid=None, image=None, port=11434)
    assert "kein" in diag.hint.lower()
    assert "11434" in diag.hint


def test_docker_hint_names_container_route():
    diag = PortDiagnosis(
        kind="docker", pid=77,
        image=r"C:\Program Files\Docker\Docker\resources\com.docker.backend.exe",
        port=11434,
    )
    assert "Docker" in diag.hint
    assert "11434" in diag.hint


# --- resolve_notice: wann ersetzt die Diagnose die Basis-Meldung? ------------

def test_resolve_notice_replaces_base_for_wsl_owner():
    diag = PortDiagnosis(kind="wsl", pid=1, image="wslrelay.exe", port=11434)
    assert resolve_notice("BASIS", diag) == diag.hint


def test_resolve_notice_replaces_base_for_docker_and_other():
    for kind in ("docker", "other"):
        diag = PortDiagnosis(kind=kind, pid=7, image="x.exe", port=11434)
        assert resolve_notice("BASIS", diag) == diag.hint


def test_resolve_notice_keeps_base_for_win_ollama():
    diag = PortDiagnosis(kind="win-ollama", pid=1, image="ollama.exe", port=11434)
    assert resolve_notice("BASIS", diag) == "BASIS"


def test_resolve_notice_keeps_base_for_unknown_and_none():
    # "none": Server war beim ps() noch da — Race, Basis-Meldung ist ok.
    # "unknown": Image nicht lesbar — keine belastbare Alternative.
    for kind in ("unknown", "none"):
        diag = PortDiagnosis(kind=kind, pid=None, image=None, port=11434)
        assert resolve_notice("BASIS", diag) == "BASIS"


# --- Windows-Integration: echter Listener wird gefunden ----------------------

@pytest.mark.skipif(sys.platform != "win32", reason="GetExtendedTcpTable ist Windows-only")
def test_diagnose_finds_own_test_listener():
    import os

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.bind(("127.0.0.1", 0))
        sock.listen(1)
        port = sock.getsockname()[1]

        diag = diagnose_ollama_port(port=port)

        assert diag.pid == os.getpid()
        assert diag.image is not None
        assert diag.image.lower().endswith(("python.exe", "pythonw.exe"))
        # python.exe ist weder Ollama noch WSL/Docker:
        assert diag.kind == "other"
        assert str(port) in diag.hint
    finally:
        sock.close()


@pytest.mark.skipif(sys.platform != "win32", reason="GetExtendedTcpTable ist Windows-only")
def test_diagnose_free_port_reports_none():
    # Ephemeral-Port reservieren und sofort freigeben — danach lauscht dort
    # (mit an Sicherheit grenzender Wahrscheinlichkeit) niemand.
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    probe.bind(("127.0.0.1", 0))
    free_port = probe.getsockname()[1]
    probe.close()

    diag = diagnose_ollama_port(port=free_port)

    assert diag.kind == "none"
    assert diag.pid is None


@pytest.mark.skipif(sys.platform != "win32", reason="Windows-only")
def test_diagnose_never_raises_on_bad_port():
    # Diagnose laeuft im Toast-Pfad — sie darf unter keinen Umstaenden werfen.
    diag = diagnose_ollama_port(port=0)
    assert diag.kind in ("none", "unknown")
