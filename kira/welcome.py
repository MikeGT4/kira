"""First-run wizard: guide user through permissions + Ollama + model download."""
from __future__ import annotations
import logging
import os
import subprocess
import shutil
import rumps
from kira.permissions import check_all, open_settings

log = logging.getLogger(__name__)

for _brew_bin in ("/opt/homebrew/bin", "/usr/local/bin"):
    if _brew_bin not in os.environ.get("PATH", "").split(os.pathsep):
        os.environ["PATH"] = f"{os.environ.get('PATH', '')}{os.pathsep}{_brew_bin}"


def run_if_needed() -> bool:
    """Check permissions and Ollama presence. Returns True if all OK."""
    status = check_all()
    ollama_ok = shutil.which("ollama") is not None
    if status.all_granted and ollama_ok:
        return True
    if not status.microphone:
        log.warning("Microphone permission missing — grant in Systemeinstellungen")
    if not status.accessibility:
        log.warning("Accessibility permission missing — grant in Systemeinstellungen")
    if not status.input_monitoring:
        log.warning("Input Monitoring permission missing — grant in Systemeinstellungen")
    if not ollama_ok:
        log.warning("Ollama CLI not on PATH; styler will fall back to raw text")
    return False


def ensure_ollama_model(model: str) -> bool:
    """Check if Ollama model is present. Returns True if ready."""
    if shutil.which("ollama") is None:
        return False
    try:
        probe = subprocess.run(["ollama", "list"], capture_output=True, text=True, timeout=5)
        return model.split(":")[0] in probe.stdout
    except Exception:
        log.exception("ollama list failed")
        return False
