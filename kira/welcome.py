"""First-run wizard: guide user through permissions + Ollama + model download."""
from __future__ import annotations
import logging
import subprocess
import shutil
import rumps
from kira.permissions import check_all, open_settings

log = logging.getLogger(__name__)


def run_if_needed() -> bool:
    """Show welcome if any permission missing or Ollama absent.
    Returns True if all OK to proceed."""
    status = check_all()
    ollama_ok = shutil.which("ollama") is not None
    if status.all_granted and ollama_ok:
        return True

    msg_parts = ["Kira needs a quick setup:\n"]
    if not status.microphone:
        msg_parts.append("• Microphone permission")
    if not status.accessibility:
        msg_parts.append("• Accessibility permission")
    if not status.input_monitoring:
        msg_parts.append("• Input Monitoring permission")
    if not ollama_ok:
        msg_parts.append("• Ollama installed (brew install ollama)")

    msg_parts.append("\nOpen the relevant System Settings pane now?")
    response = rumps.alert(
        title="Welcome to Kira",
        message="\n".join(msg_parts),
        ok="Open Settings",
        cancel="Later",
    )
    if response == 1:
        if not status.accessibility:
            open_settings("accessibility")
        elif not status.input_monitoring:
            open_settings("input_monitoring")
        elif not status.microphone:
            open_settings("microphone")
        elif not ollama_ok:
            subprocess.Popen(["open", "https://ollama.com/download"])
    return False


def ensure_ollama_model(model: str) -> bool:
    """Check if Ollama model is present. Returns True if ready.
    Does NOT pull in foreground — that blocks the event loop. Caller should
    pull in background if returning False."""
    if shutil.which("ollama") is None:
        return False
    try:
        probe = subprocess.run(["ollama", "list"], capture_output=True, text=True, timeout=5)
        return model.split(":")[0] in probe.stdout
    except Exception:
        log.exception("ollama list failed")
        return False
