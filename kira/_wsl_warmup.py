"""Trigger WSL2 cold-start so backend services running inside WSL come up
before the user hits F8.

WSL2 is a Lightweight VM that does NOT auto-start at Windows login — it
spins up only when something pings it (`wsl.exe`, Docker Desktop, opening
a WSL terminal). On boxes where the polish backend lives in WSL,
Kira's autostart races the user's first manual WSL touch and the setup
probe times out at 90 s, surfacing the SetupHintDialog at every reboot
even though Ollama would come up on its own minutes later.

Firing ``wsl.exe --exec /bin/true`` non-blocking at boot forces the VM
up — systemd-enabled services (e.g. ``ollama.service``) then start
automatically inside it. By the time the setup probe runs (~5 s later)
Ollama is usually reachable.

On boxes without WSL installed (e.g. friends' setups using native
Windows Ollama), this no-ops silently — ``wsl.exe`` is missing and
``FileNotFoundError`` is swallowed.
"""
from __future__ import annotations
import logging
import subprocess

log = logging.getLogger(__name__)

# Hide the wsl.exe console flash that would otherwise briefly appear in
# the corner at autostart. Win32 only (ignored on POSIX).
_CREATE_NO_WINDOW = 0x08000000


def kick_wsl_distro() -> None:
    """Fire-and-forget ``wsl.exe`` call to spin up the default WSL distro.

    Returns immediately — the caller doesn't wait for WSL to finish
    booting. Used at Kira boot so the WSL cold-start overlaps with
    Kira's own splash + tray init.
    """
    try:
        subprocess.Popen(
            ["wsl.exe", "--exec", "/bin/true"],
            creationflags=_CREATE_NO_WINDOW,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        log.info("WSL distro warm-up dispatched (wsl.exe --exec /bin/true)")
    except FileNotFoundError:
        log.debug("wsl.exe not on PATH — skipping WSL warm-up")
    except Exception:
        log.exception("WSL warm-up failed; setup probe may time out on cold boot")
