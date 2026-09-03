"""Selection capture for the edit hotkey: Cmd+C round trip through the pasteboard."""
from __future__ import annotations
import logging
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

KEYCODE_C = 8
SETTLE_MS = 120


class ClipboardUnavailable(RuntimeError):
    """The pasteboard could not be read or written."""


def _send_cmd_c() -> None:
    down = CGEventCreateKeyboardEvent(None, KEYCODE_C, True)
    CGEventSetFlags(down, kCGEventFlagMaskCommand)
    up = CGEventCreateKeyboardEvent(None, KEYCODE_C, False)
    CGEventSetFlags(up, kCGEventFlagMaskCommand)
    CGEventPost(kCGHIDEventTap, down)
    CGEventPost(kCGHIDEventTap, up)


def read_selection() -> str | None:
    """Return the selected text of the frontmost app, or None if nothing is selected."""
    try:
        saved = pyperclip.paste()
    except Exception as exc:
        raise ClipboardUnavailable(f"pasteboard read failed: {exc}") from exc
    try:
        pyperclip.copy("")
    except Exception as exc:
        raise ClipboardUnavailable(f"pasteboard clear failed: {exc}") from exc
    try:
        _send_cmd_c()
    except Exception as exc:
        try:
            pyperclip.copy(saved)
        except Exception:
            pass
        raise ClipboardUnavailable(f"Cmd+C failed: {exc}") from exc
    time.sleep(SETTLE_MS / 1000.0)
    try:
        result = pyperclip.paste()
    except Exception as exc:
        try:
            pyperclip.copy(saved)
        except Exception:
            pass
        raise ClipboardUnavailable(f"pasteboard read after Cmd+C failed: {exc}") from exc
    try:
        pyperclip.copy(saved)
    except Exception:
        log.warning("pasteboard restore after selection capture failed")
    if not result:
        log.info("read_selection: no selection")
        return None
    log.info("read_selection: captured %d chars", len(result))
    return result
