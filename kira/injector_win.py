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
        # Restore-Generation gegen ueberlappende Diktate: Jeder inject()
        # armt einen eigenen, nicht abbrechbaren threading.Timer. Ohne
        # Guard restaurierte ein aelterer Timer sein "saved" mitten ins
        # Paste-Fenster des naechsten Diktats (oder hinterliess Kira-Text
        # von Diktat 1 als Endzustand). Nur der Timer der NEUESTEN
        # Generation darf restaurieren — und zwar das aelteste noch nicht
        # restaurierte User-Original (_pending_original), damit die Kette
        # text1->text2 das echte Original nicht verliert.
        self._lock = threading.Lock()
        self._restore_gen = 0
        self._pending_original: str | None = None

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
        with self._lock:
            self._restore_gen += 1
            gen = self._restore_gen
            if self._pending_original is None:
                # Erstes Diktat einer (potenziellen) Kette: echtes
                # User-Original sichern. Bei Ueberlappung (voriger Timer
                # hat noch nicht restauriert) laege hier schon Kira-Text
                # im Clipboard — den NICHT als "Original" uebernehmen.
                try:
                    self._pending_original = pyperclip.paste()
                except Exception:
                    self._pending_original = ""
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
            with self._lock:
                if gen != self._restore_gen:
                    # Ein neueres Diktat laeuft — dessen Timer restauriert.
                    return
                saved = self._pending_original
                self._pending_original = None
            try:
                pyperclip.copy(saved if saved is not None else "")
            except Exception:
                log.warning("failed to restore clipboard")

        threading.Timer(delay_ms / 1000.0, restore).start()
