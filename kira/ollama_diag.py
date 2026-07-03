"""Diagnose: Welcher Prozess haelt den Ollama-Port 11434?

Anlass (2026-07-03): Ein Docker-Container in WSL2 (mirofish-ollama) band
``0.0.0.0:11434`` vor der Windows-Ollama-Tray-App — auf der Windows-Seite
haelt dann ``wslrelay.exe`` den Port. Kira redete wochenlang mit dem
Container-Server: Das HKCU-Env-Tuning (``kira.ollama_env``) erreicht so
einen Server nie, und der CPU-Fallback-Toast („Ollama neu starten")
empfahl die falsche Abhilfe — die Windows-App hatte den Port ja gar nicht
und spammte nur Bind-Errors in ihr server.log.

Dieses Modul identifiziert den Port-Inhaber (``GetExtendedTcpTable`` +
``QueryFullProcessImageNameW``, beides ohne Adminrechte) und liefert die
zum Inhaber passende deutsche Abhilfe fuer Log + Tray-Toast.

Windows-only I/O; die Klassifikation (``classify_port_owner``) und die
Texte (``PortDiagnosis.hint``, ``resolve_notice``) sind pure und ueberall
testbar. ``styler.py`` bleibt bewusst frei davon (shared mit dem
Mac-Branch) — verdrahtet wird das Modul im Windows-Teil von ``main.py``.
"""
from __future__ import annotations

import logging
import ntpath
import sys
from dataclasses import dataclass

log = logging.getLogger(__name__)

OLLAMA_PORT = 11434

#: Windows-Prozesse, hinter denen ein WSL2-Listener steckt (localhost-
#: Forwarding der VM). Der eigentliche Server laeuft dann IN der Distro —
#: als systemd-Service oder Docker-Container.
_WSL_IMAGES = {"wslrelay.exe", "wslhost.exe"}
#: Docker-Desktop-Prozesse, die Container-Ports auf den Host publishen.
_DOCKER_IMAGES = {"com.docker.backend.exe", "vpnkit.exe", "docker-proxy.exe"}


def classify_port_owner(image_path: str | None) -> str:
    """Pure: Image-Pfad des Port-Inhabers → Kind.

    Returns ``"win-ollama"`` | ``"wsl"`` | ``"docker"`` | ``"other"`` |
    ``"unknown"``. ``ntpath.basename`` statt ``os.path``, damit die
    Windows-Pfade auch in einer POSIX-Testumgebung korrekt zerlegt werden.
    """
    if not image_path:
        return "unknown"
    name = ntpath.basename(image_path).lower()
    if name.startswith("ollama"):
        return "win-ollama"
    if name in _WSL_IMAGES:
        return "wsl"
    if name in _DOCKER_IMAGES:
        return "docker"
    return "other"


@dataclass
class PortDiagnosis:
    """Ergebnis von :func:`diagnose_ollama_port` — Kind + Inhaber + Abhilfe."""

    kind: str                # classify_port_owner()-Kind oder "none"
    pid: int | None
    image: str | None
    port: int = OLLAMA_PORT

    @property
    def hint(self) -> str:
        """Deutsche Abhilfe-Empfehlung passend zum Port-Inhaber."""
        exe = ntpath.basename(self.image) if self.image else "unbekannter Prozess"
        if self.kind == "wsl":
            return (
                f"{exe} (PID {self.pid}) haelt Port {self.port} — der antwortende "
                f"Ollama laeuft in WSL2 (systemd-Service oder Docker-Container), "
                f"NICHT der Windows-Ollama. Neustarts der Windows-App und Kiras "
                f"VRAM-Tuning bewirken dort nichts. Abhilfe: den Ollama in WSL "
                f"stoppen oder auf einen anderen Port legen (Docker-Compose z. B. "
                f"127.0.0.1:11435:11434), dann uebernimmt der Windows-Ollama."
            )
        if self.kind == "docker":
            return (
                f"{exe} (PID {self.pid}) haelt Port {self.port} — ein Docker-"
                f"Container publisht hier seinen eigenen Ollama. Container "
                f"stoppen oder sein Port-Mapping aendern, dann uebernimmt der "
                f"Windows-Ollama den Port."
            )
        if self.kind == "win-ollama":
            return (
                f"Der Windows-Ollama ({exe}, PID {self.pid}) haelt Port "
                f"{self.port}. Ollama ueber das Tray-Icon beenden und neu "
                f"starten — Kiras VRAM-Tuning (Flash-Attention + q8-KV-Cache) "
                f"greift beim naechsten Serverstart."
            )
        if self.kind == "none":
            return (
                f"Kein Prozess lauscht auf Port {self.port} — Ollama laeuft "
                f"gerade nicht (oder wurde soeben beendet)."
            )
        if self.kind == "other":
            return (
                f"{exe} (PID {self.pid}) haelt Port {self.port} — das ist kein "
                f"Ollama-Prozess. Pruefen, welcher Dienst hier lauscht; solange "
                f"er den Port haelt, kommt der Windows-Ollama nicht zum Zug."
            )
        return (
            f"Port {self.port} ist belegt (PID {self.pid}), aber der Prozess "
            f"liess sich nicht identifizieren."
        )


def resolve_notice(base_msg: str, diag: PortDiagnosis) -> str:
    """Welche Meldung traegt der Tray-Toast?

    Haelt ein Fremd-Prozess (WSL-Relay, Docker, Sonstiges) den Port, ist die
    Standard-Empfehlung aus dem Styler („Windows-Ollama neu starten, das
    VRAM-Tuning greift") wirkungslos — dann ersetzt die Port-Diagnose die
    Basis-Meldung. Beim Windows-Ollama selbst, ohne Listener („none": der
    Server war beim ps() noch da, Race) oder ohne belastbares Ergebnis
    („unknown") bleibt die Basis-Meldung stehen.
    """
    if diag.kind in ("wsl", "docker", "other"):
        return diag.hint
    return base_msg


# --- Windows-I/O -------------------------------------------------------------

def _listening_pid(port: int) -> int | None:
    """PID des IPv4-TCP-Listeners auf ``port`` via ``GetExtendedTcpTable``.

    Bewusst nur die IPv4-Tabelle: jeder relevante Kandidat (Windows-Ollama,
    wslrelay, Docker-Proxy) bindet mindestens 127.0.0.1 bzw. 0.0.0.0.
    Braucht keine Adminrechte. ``None`` = kein Listener gefunden.
    """
    import ctypes
    import socket
    from ctypes import wintypes

    AF_INET = 2
    TCP_TABLE_OWNER_PID_LISTENER = 3

    iphlpapi = ctypes.windll.iphlpapi
    size = wintypes.DWORD(0)
    # Erster Aufruf liefert die benoetigte Puffergroesse.
    iphlpapi.GetExtendedTcpTable(
        None, ctypes.byref(size), False, AF_INET,
        TCP_TABLE_OWNER_PID_LISTENER, 0,
    )
    buf = ctypes.create_string_buffer(size.value)
    if iphlpapi.GetExtendedTcpTable(
        buf, ctypes.byref(size), False, AF_INET,
        TCP_TABLE_OWNER_PID_LISTENER, 0,
    ) != 0:
        return None

    class _TcpRowOwnerPid(ctypes.Structure):
        # MIB_TCPROW_OWNER_PID — alle Felder DWORD, kein Padding.
        _fields_ = [
            ("state", wintypes.DWORD),
            ("local_addr", wintypes.DWORD),
            ("local_port", wintypes.DWORD),   # Network-Byte-Order im Low-Word
            ("remote_addr", wintypes.DWORD),
            ("remote_port", wintypes.DWORD),
            ("owning_pid", wintypes.DWORD),
        ]

    count = ctypes.cast(buf, ctypes.POINTER(wintypes.DWORD)).contents.value
    rows = ctypes.cast(
        ctypes.byref(buf, ctypes.sizeof(wintypes.DWORD)),
        ctypes.POINTER(_TcpRowOwnerPid * count),
    ).contents
    for row in rows:
        if socket.ntohs(row.local_port & 0xFFFF) == port:
            return int(row.owning_pid)
    return None


def _process_image(pid: int) -> str | None:
    """Voller Image-Pfad eines Prozesses via ``QueryFullProcessImageNameW``.

    ``PROCESS_QUERY_LIMITED_INFORMATION`` reicht ohne Adminrechte auch fuer
    fremde Prozesse desselben Users; bei Zugriffsverweigerung (z. B.
    SYSTEM-Dienst) → ``None`` und der Aufrufer klassifiziert „unknown".
    """
    import ctypes
    from ctypes import wintypes

    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    kernel32 = ctypes.windll.kernel32
    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return None
    try:
        buf = ctypes.create_unicode_buffer(1024)
        length = wintypes.DWORD(len(buf))
        if kernel32.QueryFullProcessImageNameW(
            handle, 0, buf, ctypes.byref(length),
        ):
            return buf.value
        return None
    finally:
        kernel32.CloseHandle(handle)


def diagnose_ollama_port(port: int = OLLAMA_PORT) -> PortDiagnosis:
    """Wer haelt ``port``? Wirft NIE — laeuft im Toast-/Boot-Pfad.

    Auf Nicht-Windows (Mac-Branch importiert dieses Modul nicht, aber
    sicher ist sicher) → ``kind="unknown"``.
    """
    if sys.platform != "win32":
        return PortDiagnosis(kind="unknown", pid=None, image=None, port=port)
    try:
        pid = _listening_pid(port)
        if pid is None:
            return PortDiagnosis(kind="none", pid=None, image=None, port=port)
        image = _process_image(pid)
        return PortDiagnosis(
            kind=classify_port_owner(image), pid=pid, image=image, port=port,
        )
    except Exception:
        log.exception("Ollama-Port-Diagnose fehlgeschlagen (port=%d)", port)
        return PortDiagnosis(kind="unknown", pid=None, image=None, port=port)
