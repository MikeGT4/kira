"""Windows global hotkey listener using the low-level keyboard hook.

Supports F8 hold-to-talk with pass-through semantics: our handler
fires AND the key continues to the focused app. This matches the
design decision (see windows-port spec): F8 collisions are rare
in Mike's stack and pass-through avoids breaking other apps.

Press events that repeat while already active (auto-repeat) are
deduplicated by the self._active flag, matching the Mac behavior.
"""
from __future__ import annotations
import logging
import threading
from typing import Callable
import keyboard

log = logging.getLogger(__name__)

SUPPORTED_COMBOS = {"f8"}


class HotkeyListener:
    """F8 (default) hold-to-talk listener with pass-through."""

    def __init__(
        self,
        combo: str,
        on_press: Callable[[], None],
        on_release: Callable[[], None],
    ) -> None:
        if combo not in SUPPORTED_COMBOS:
            raise ValueError(
                f"Unsupported combo: {combo}. "
                f"Supported: {sorted(SUPPORTED_COMBOS)}"
            )
        self._combo = combo
        self._on_press = on_press
        self._on_release = on_release
        self._active = False
        self._started = False
        self._lock = threading.Lock()
        self._hook_handles: list = []

    def _handle_press(self, _event) -> None:
        with self._lock:
            if self._active:
                return
            self._active = True
        try:
            self._on_press()
        except Exception:
            log.exception("on_press raised")

    def _handle_release(self, _event) -> None:
        with self._lock:
            if not self._active:
                return
            self._active = False
        try:
            self._on_release()
        except Exception:
            log.exception("on_release raised")

    def start(self) -> None:
        with self._lock:
            if self._started:
                return
            # Register RELEASE first, then PRESS — see tests/test_hotkey_win.py
            # test_hotkey_double_press_ignored_while_active: the test uses a
            # shared registered["f8"] dict key for both hooks; whichever
            # registers last wins the slot. Press must win so the dedup path
            # is what the test exercises.
            h1 = keyboard.on_release_key(self._combo, self._handle_release, suppress=False)
            h2 = keyboard.on_press_key(self._combo, self._handle_press, suppress=False)
            self._hook_handles = [h1, h2]
            self._started = True
            log.info("HotkeyListener running (combo=%s, pass-through)", self._combo)

    def stop(self) -> None:
        with self._lock:
            if not self._started:
                return
            for h in self._hook_handles:
                try:
                    keyboard.unhook(h)
                except Exception:
                    log.exception("keyboard.unhook raised for handle %r", h)
            self._hook_handles = []
            self._started = False
