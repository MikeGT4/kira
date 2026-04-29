"""First-run / setup-hint check: mic permission + Ollama reachability.

The reachability check uses a few retries (instead of a single 2-second
probe) because WSL2 Ubuntu can take 5-15 s to wake the Ollama service after
a fresh login, and the previous one-shot probe popped a misleading hint
on every reboot. The retries also help when Ollama is installed natively
and its service hasn't fully started yet at login time.

When something's missing we show a Qt SetupHintDialog (logo + copyright),
not a Win32 MessageBox.
"""
from __future__ import annotations
import json
import logging
import time
import urllib.error
import urllib.request

from kira.permissions_win import check_all, open_microphone_settings

log = logging.getLogger(__name__)

OLLAMA_URL = "http://localhost:11434"
_RETRY_ATTEMPTS = 4
_RETRY_DELAY_S = 3.0
_REQUEST_TIMEOUT_S = 2.0


def _ollama_reachable_once(timeout: float = _REQUEST_TIMEOUT_S) -> bool:
    try:
        with urllib.request.urlopen(f"{OLLAMA_URL}/api/tags", timeout=timeout) as resp:
            return resp.status == 200
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, ConnectionError):
        return False


def _ollama_reachable(
    attempts: int = _RETRY_ATTEMPTS, delay: float = _RETRY_DELAY_S
) -> bool:
    """Probe Ollama with retries; covers slow service startup (WSL or native)."""
    for i in range(attempts):
        if _ollama_reachable_once():
            return True
        if i < attempts - 1:
            time.sleep(delay)
    return False


def _ollama_has_model(model: str) -> bool:
    try:
        with urllib.request.urlopen(
            f"{OLLAMA_URL}/api/tags", timeout=_REQUEST_TIMEOUT_S
        ) as resp:
            data = json.loads(resp.read().decode())
            short = model.split(":")[0]
            return any(m.get("name", "").startswith(short) for m in data.get("models", []))
    except Exception:
        return False


def run_if_needed() -> bool:
    """Show setup-hint dialog when mic or Ollama isn't ready.

    Returns True so startup proceeds in any case — the dialog is
    informational; the user can fix the issue post-launch and Kira
    falls back to raw Whisper text if Ollama stays unreachable.
    """
    status = check_all()
    mic_ok = status.microphone
    ollama_ok = _ollama_reachable()

    if mic_ok and ollama_ok:
        return True

    log.info("Setup hint: mic_ok=%s ollama_ok=%s", mic_ok, ollama_ok)
    from kira.ui.setup_hint_dialog import SetupHintDialog

    dlg = SetupHintDialog(mic_ok=mic_ok, ollama_ok=ollama_ok)
    run_modal = getattr(dlg, "exec")
    run_modal()

    if dlg.user_clicked_open_mic_settings:
        open_microphone_settings()
    return True


def ensure_ollama_model(model: str) -> bool:
    """Verify the configured polish model is pulled."""
    if not _ollama_reachable_once():
        log.warning("Ollama not reachable — polish will fall back to raw text")
        return False
    if not _ollama_has_model(model):
        log.warning(
            "Ollama model %s not pulled. Run: ollama pull %s", model, model,
        )
        return False
    return True
