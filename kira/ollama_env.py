"""Persistentes Ollama-VRAM-Tuning fuer den Polish-Pfad.

Setzt zwei serverseitige Ollama-Env-Vars dauerhaft in ``HKCU\\Environment``:

    OLLAMA_FLASH_ATTENTION = 1       # Flash-Attention-Kernel
    OLLAMA_KV_CACHE_TYPE   = q8_0    # KV-Cache f16 -> q8_0 (~halbe Groesse)

Wirkung: senkt den realen VRAM-Bedarf des Polish-Modells, statt seine
GPU-Platzierung mit ``num_gpu=999`` zu erzwingen (das ist ab Ollama 0.30.x
serverseitig wirkungslos, Regression GitHub #16610). Auf einer 32-GB-Karte
bringt der gesparte Headroom das Modell zuverlaessig komplett in den VRAM,
auch neben dem CUDA-Kontext von Whisper.

Wichtige Eigenschaften:

* **Server-Env, nicht per-request.** Flash-Attention und KV-Cache-Typ sind
  Eigenschaften des ``ollama serve``-Prozesses, nicht der einzelnen
  ``ollama.chat``-Anfrage (anders als ``num_gpu``). Sie muessen in der
  Umgebung stehen, *bevor* der Server startet — darum schreiben wir sie
  persistent in die Registry statt sie pro Request mitzugeben.
* **Greift nach Neustart.** Ein bereits laufender ``ollama serve`` liest die
  neuen Werte erst nach seinem naechsten Start (Ollama-App-Neustart oder
  Reboot). Kira startet den Server **bewusst nicht selbst neu** — er wird mit
  anderen Ollama-Clients geteilt, ein erzwungener Neustart wuerde die stoeren.
* **Idempotent + windows-only.** Auf Nicht-Windows ein No-op; bereits korrekt
  gesetzte Werte werden nicht erneut geschrieben (kein unnoetiger
  Neustart-Bedarf).

Aller winreg-I/O steckt in ``_read_user_env`` / ``_write_user_env`` — so
bleibt die Logik (``pending_changes``) plattformunabhaengig testbar.
"""
from __future__ import annotations

import logging
import sys
from collections.abc import Mapping

log = logging.getLogger(__name__)

#: Die zu setzenden Env-Vars. Quelle der Wahrheit fuer Check und Write.
TUNING_ENV: dict[str, str] = {
    "OLLAMA_FLASH_ATTENTION": "1",
    "OLLAMA_KV_CACHE_TYPE": "q8_0",
}

#: HKEY_CURRENT_USER-Subkey, in dem Windows die User-Env-Vars haelt.
_USER_ENV_SUBKEY = "Environment"


def pending_changes(current: Mapping[str, str]) -> dict[str, str]:
    """Welche ``TUNING_ENV``-Keys fehlen in ``current`` oder haben einen
    abweichenden Wert. Pure Funktion — keine I/O, voll testbar."""
    return {k: v for k, v in TUNING_ENV.items() if current.get(k) != v}


def _read_user_env() -> dict[str, str]:
    """Komplettes ``HKCU\\Environment`` als dict lesen. Windows-only (winreg)."""
    import winreg

    values: dict[str, str] = {}
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _USER_ENV_SUBKEY) as key:
        index = 0
        while True:
            try:
                name, data, _typ = winreg.EnumValue(key, index)
            except OSError:
                break  # Ende der Werteliste
            values[name] = str(data)
            index += 1
    return values


def _write_user_env(name: str, value: str) -> None:
    """Einen REG_SZ-Wert in ``HKCU\\Environment`` schreiben + Broadcast."""
    import winreg

    with winreg.OpenKey(
        winreg.HKEY_CURRENT_USER, _USER_ENV_SUBKEY, 0, winreg.KEY_SET_VALUE,
    ) as key:
        winreg.SetValueEx(key, name, 0, winreg.REG_SZ, value)
    _broadcast_env_change()


def _broadcast_env_change() -> None:
    """``WM_SETTINGCHANGE`` broadcasten, damit neu gestartete Prozesse die
    Env ohne Reboot sehen. Best-effort: ein Fehler ist nicht fatal, weil der
    naechste Ollama-Start/Reboot die persistente Registry ohnehin liest."""
    try:
        import ctypes

        hwnd_broadcast = 0xFFFF       # HWND_BROADCAST
        wm_settingchange = 0x001A     # WM_SETTINGCHANGE
        smto_abortifhung = 0x0002
        ctypes.windll.user32.SendMessageTimeoutW(
            hwnd_broadcast, wm_settingchange, 0, "Environment",
            smto_abortifhung, 2000, None,
        )
    except Exception:  # noqa: BLE001 - Broadcast ist Komfort, nie kritisch
        log.debug("WM_SETTINGCHANGE broadcast failed (non-fatal)", exc_info=True)


def apply_tuning_env() -> list[str]:
    """Setzt fehlende/abweichende Ollama-Tuning-Env-Vars persistent in
    ``HKCU\\Environment``.

    Returns die Liste der tatsaechlich neu geschriebenen Keys (leer = es war
    schon alles korrekt, oder wir laufen nicht auf Windows). Eine nicht-leere
    Rueckgabe signalisiert dem Aufrufer: ein Ollama-Neustart laesst das Tuning
    greifen.

    Schluckt I/O-Fehler bewusst (Registry gesperrt / kein Schreibrecht) — das
    Tuning ist eine Optimierung, kein harter Start-Vorbedingung; Kira muss auch
    ohne sie laufen.
    """
    if sys.platform != "win32":
        return []
    try:
        current = _read_user_env()
    except OSError as exc:
        log.warning(
            "HKCU\\Environment nicht lesbar — Ollama-Tuning uebersprungen (%s)",
            exc,
        )
        return []

    written: list[str] = []
    for name, value in pending_changes(current).items():
        try:
            _write_user_env(name, value)
            written.append(name)
        except OSError:
            log.exception("Konnte %s nicht in HKCU\\Environment setzen", name)

    if written:
        log.info(
            "Ollama-VRAM-Tuning gesetzt (%s) — greift nach Ollama-Neustart/Reboot",
            ", ".join(written),
        )
    return written
