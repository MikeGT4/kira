"""Inject text at cursor via clipboard roundtrip + Ctrl+V.

Windows equivalent of the Mac injector. Same flow:
  1. Save current clipboard
  2. Set clipboard to our text
  3. Send Ctrl+V keystroke
  4. Restore original clipboard after restore_after_ms

Long-text caveat: heavy editors (Word, browser-based chats with
auto-format) need many ms per character to commit a paste. If the
restore timer fires while the editor is still consuming the buffer,
the tail of the text is replaced by the original clipboard content
mid-paste — symptom: long dictations get truncated. The effective
delay scales with text length to give the receiving app enough time.
"""
from __future__ import annotations
import logging
import threading
import time
import pyperclip
import keyboard

log = logging.getLogger(__name__)

_LONG_TEXT_THRESHOLD = 80
_PER_CHAR_PASTE_MS = 2  # empirical headroom for slow editors
_PASTE_OVERHEAD_MS = 100


class Injector:
    """Clipboard-based text injector for Windows."""

    def __init__(self, restore_after_ms: int = 500) -> None:
        self._restore_after_ms = restore_after_ms

    def _effective_restore_ms(self, text_len: int) -> int:
        """Adaptive restore delay: scales with text length for long pastes.

        Short texts (≤80 chars) use the configured base delay so the
        clipboard is freed up quickly. Longer texts add ~2 ms/char on
        top of a 100 ms overhead — enough margin for Word, Outlook,
        Slack-web, etc. to consume the whole buffer before we wipe it.
        """
        if text_len <= _LONG_TEXT_THRESHOLD:
            return self._restore_after_ms
        return max(
            self._restore_after_ms,
            _PASTE_OVERHEAD_MS + text_len * _PER_CHAR_PASTE_MS,
        )

    def inject(self, text: str) -> None:
        if not text:
            return
        delay_ms = self._effective_restore_ms(len(text))
        log.info(
            "Injecting %d chars (restore in %d ms): %r",
            len(text), delay_ms, text[:80],
        )
        try:
            saved = pyperclip.paste()
        except Exception:
            saved = ""
            log.warning("pyperclip.paste failed, restore will be empty")
        try:
            pyperclip.copy(text)
        except Exception:
            log.exception("pyperclip.copy failed")
            return
        time.sleep(0.02)  # pasteboard settle
        try:
            keyboard.send("ctrl+v")
        except Exception:
            log.exception("keyboard.send(ctrl+v) failed")

        def restore():
            try:
                pyperclip.copy(saved)
            except Exception:
                log.warning("failed to restore clipboard")

        threading.Timer(delay_ms / 1000.0, restore).start()
