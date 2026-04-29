"""Inject text at current cursor via clipboard + Cmd+V simulation."""
from __future__ import annotations
import logging
import threading
import time
import pyperclip
from Quartz import (
    CGEventCreateKeyboardEvent,
    CGEventPost,
    CGEventSetFlags,
    kCGHIDEventTap,
    kCGEventFlagMaskCommand,
)

log = logging.getLogger(__name__)

KEYCODE_V = 9  # US keyboard layout


def _send_cmd_v() -> None:
    down = CGEventCreateKeyboardEvent(None, KEYCODE_V, True)
    CGEventSetFlags(down, kCGEventFlagMaskCommand)
    up = CGEventCreateKeyboardEvent(None, KEYCODE_V, False)
    CGEventSetFlags(up, kCGEventFlagMaskCommand)
    CGEventPost(kCGHIDEventTap, down)
    CGEventPost(kCGHIDEventTap, up)


class Injector:
    """Clipboard-based injector.

    Flow:
      1. Save current clipboard
      2. Set clipboard to our text
      3. Post Cmd+V keystroke
      4. Restore original clipboard after delay
    """

    def __init__(self, restore_after_ms: int = 100) -> None:
        self._restore_after_ms = restore_after_ms

    def inject(self, text: str) -> None:
        if not text:
            return
        try:
            saved = pyperclip.paste()
        except Exception:
            saved = ""
        try:
            pyperclip.copy(text)
        except Exception:
            log.exception("failed to set clipboard")
            return
        # Give pasteboard a moment to settle
        time.sleep(0.02)
        _send_cmd_v()
        def restore():
            try:
                pyperclip.copy(saved)
            except Exception:
                log.warning("failed to restore clipboard")
        threading.Timer(self._restore_after_ms / 1000.0, restore).start()
