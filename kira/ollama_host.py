# © 2026 Mike Pollow, Digitalroots. Alle Rechte vorbehalten.
"""Zieladresse für Kiras Ollama-Client.

``OLLAMA_HOST`` ist für den Ollama-Server die Adresse, an die er sich bindet,
für die Python-Bibliothek aber die Adresse, die sie anspricht. Steht dort eine
Bind-alles-Adresse wie ``0.0.0.0:11434`` (gesetzt, damit andere Rechner im LAN
den Server erreichen), scheitert unter Windows jede Verbindung mit „Failed to
connect to Ollama". Seit dem 17.09.2026 fiel deshalb jede Politur auf den
Rohtext zurück. Für diesen Fall liefert ``client_host()`` die
Loopback-Adresse, jede andere Angabe bleibt der Bibliothek überlassen.
"""
from __future__ import annotations
import os
from collections.abc import Mapping

DEFAULT_PORT = 11434
_BIND_ALL = frozenset({"", "0.0.0.0", "::"})


def client_host(env: Mapping[str, str] | None = None) -> str | None:
    """``http://127.0.0.1:<port>`` bei Bind-alles-Adressen, sonst ``None``.

    ``None`` heißt: Die Bibliothek wertet ``OLLAMA_HOST`` selbst aus.
    """
    raw = (os.environ if env is None else env).get("OLLAMA_HOST", "").strip()
    if not raw:
        return None
    scheme, sep, rest = raw.partition("://")
    if not sep:
        scheme, rest = "http", raw
    rest = rest.rstrip("/")
    if rest.startswith("["):
        host, _, tail = rest[1:].partition("]")
        port = tail.lstrip(":")
    elif rest.count(":") > 1:
        host, port = rest, ""
    else:
        host, _, port = rest.partition(":")
    if host not in _BIND_ALL:
        return None
    return f"{scheme}://127.0.0.1:{port or DEFAULT_PORT}"
