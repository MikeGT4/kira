"""First-run / setup-hint check: mic permission + Ollama reachability.

The reachability check retries with a generous total budget because a
cold Windows boot races Kira's autostart against WSL2 Ubuntu spinning
up. On Mike's box (2026-05-02 cold boot) Ollama wasn't reachable until
~27 s after Kira launched, which is well past the original 12 s budget
and tripped the SetupHintDialog every reboot even though Ollama was
about to come up. Probe aborts as soon as Ollama answers, so warm
restarts pay no penalty.

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
# 20 × 3 s sleep + 20 × 1.5 s probe = up to ~90 s wall-clock when Ollama
# is genuinely unreachable. Warm boot returns on the first probe (~50 ms).
_RETRY_ATTEMPTS = 20
_RETRY_DELAY_S = 3.0
_REQUEST_TIMEOUT_S = 1.5


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


def probe_setup_status() -> tuple[bool, bool]:
    """UI-free probe of mic permission + Ollama reachability.

    Returns ``(mic_ok, ollama_ok)``. Up to ~90 s wall-clock on a cold
    WSL2 boot (20 retries x 4.5 s). Designed to be called from a
    background thread so the up-front Ollama wait doesn't block the
    Qt event loop / tray / hotkey from coming up.
    """
    status = check_all()
    return status.microphone, _ollama_reachable()


def show_setup_hint_if_needed(mic_ok: bool, ollama_ok: bool) -> None:
    """Show the SetupHintDialog when something's missing.

    MUST run on the Qt main thread — constructs a QDialog and calls
    .exec(). Cross-thread invocation should go through
    ``MainThreadMarshal.run_on_main_thread``.
    """
    if mic_ok and ollama_ok:
        return
    log.info("Setup hint: mic_ok=%s ollama_ok=%s", mic_ok, ollama_ok)
    from kira.ui.setup_hint_dialog import SetupHintDialog

    dlg = SetupHintDialog(mic_ok=mic_ok, ollama_ok=ollama_ok)
    run_modal = getattr(dlg, "exec")
    run_modal()

    if dlg.user_clicked_open_mic_settings:
        open_microphone_settings()


def run_if_needed() -> bool:
    """Synchronous probe + dialog — kept for the macOS path.

    Returns True so startup proceeds in any case; the dialog is
    informational and Kira falls back to raw Whisper text if Ollama
    stays unreachable. The Windows path now calls
    ``probe_setup_status`` and ``show_setup_hint_if_needed`` separately
    so the slow Ollama probe can run off-main and not freeze the splash.
    """
    mic_ok, ollama_ok = probe_setup_status()
    show_setup_hint_if_needed(mic_ok, ollama_ok)
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
