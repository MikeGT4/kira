"""Global hotkey listener using macOS CGEventTap."""
from __future__ import annotations
import logging
import threading
from typing import Callable
from Quartz import (
    CGEventTapCreate,
    CGEventTapEnable,
    CGEventMaskBit,
    CGEventGetIntegerValueField,
    CGEventGetFlags,
    kCGSessionEventTap,
    kCGHeadInsertEventTap,
    kCGEventTapOptionDefault,
    kCGEventKeyDown,
    kCGEventKeyUp,
    kCGEventFlagsChanged,
    kCGEventTapDisabledByTimeout,
    kCGEventTapDisabledByUserInput,
    kCGKeyboardEventKeycode,
    kCGEventFlagMaskAlternate,
    kCGEventFlagMaskControl,
    kCGEventFlagMaskShift,
    kCGEventFlagMaskCommand,
    kCGEventFlagMaskSecondaryFn,
    CFMachPortCreateRunLoopSource,
    CFRunLoopAddSource,
    CFRunLoopGetCurrent,
    CFRunLoopRun,
    CFRunLoopStop,
    kCFRunLoopCommonModes,
)

log = logging.getLogger(__name__)

KEYCODE_SPACE = 49
KEYCODE_D = 2

KEY_COMBOS: dict[str, tuple[int, int]] = {
    "ctrl+shift+d": (
        kCGEventFlagMaskControl | kCGEventFlagMaskShift,
        KEYCODE_D,
    ),
    "alt+space": (kCGEventFlagMaskAlternate, KEYCODE_SPACE),
}

MODIFIER_ONLY_COMBOS = {"fn"}

EDIT_MODIFIER_MASKS = {
    "shift": kCGEventFlagMaskShift,
    "ctrl": kCGEventFlagMaskControl,
    "alt": kCGEventFlagMaskAlternate,
    "cmd": kCGEventFlagMaskCommand,
}

MODIFIER_BITS = (
    kCGEventFlagMaskAlternate
    | kCGEventFlagMaskControl
    | kCGEventFlagMaskShift
    | kCGEventFlagMaskCommand
)


def _flags_match(flags: int, required: int) -> bool:
    """True if exactly `required` modifier bits are set (fn/caps/etc. ignored)."""
    return (flags & MODIFIER_BITS) == (required & MODIFIER_BITS)


class HotkeyListener:
    """Global hotkey listener supporting both key-combo and modifier-only modes."""

    def __init__(
        self,
        combo: str,
        on_press: Callable[[], None],
        on_release: Callable[[], None],
        on_edit_detected: Callable[[], None] | None = None,
        edit_modifier: str | None = None,
    ) -> None:
        if combo not in KEY_COMBOS and combo not in MODIFIER_ONLY_COMBOS:
            raise ValueError(f"Unsupported combo: {combo}")
        if edit_modifier is not None and edit_modifier not in EDIT_MODIFIER_MASKS:
            raise ValueError(f"Unsupported edit modifier: {edit_modifier}")
        self._combo = combo
        self._on_edit_detected = on_edit_detected
        self._edit_mask = EDIT_MODIFIER_MASKS.get(edit_modifier, 0) if edit_modifier else 0
        self._edit_fired = False
        if combo in KEY_COMBOS:
            self._required_mask, self._keycode = KEY_COMBOS[combo]
        else:
            self._required_mask, self._keycode = 0, 0
        self._on_press = on_press
        self._on_release = on_release
        self._active = False
        self._fn_held = False
        self._thread: threading.Thread | None = None
        self._runloop = None
        self._tap = None

    def _handle_keycombo(self, type_, keycode, flags, event):
        is_our_key = keycode == self._keycode
        mods_ok = _flags_match(flags, self._required_mask)

        if not is_our_key:
            return event

        if type_ == kCGEventKeyDown and mods_ok:
            if not self._active:
                self._active = True
                try:
                    self._on_press()
                except Exception:
                    log.exception("on_press raised")
            return None

        if type_ == kCGEventKeyUp and self._active:
            self._active = False
            try:
                self._on_release()
            except Exception:
                log.exception("on_release raised")
            return None

        return event

    def _handle_fn(self, type_, flags, event):
        if type_ != kCGEventFlagsChanged:
            return event
        fn_now = bool(flags & kCGEventFlagMaskSecondaryFn)
        if fn_now and not self._fn_held:
            self._fn_held = True
            self._active = True
            self._edit_fired = False
            try:
                self._on_press()
            except Exception:
                log.exception("on_press raised")
        if fn_now and self._fn_held and self._edit_mask and not self._edit_fired and (flags & self._edit_mask):
            self._edit_fired = True
            if self._on_edit_detected is not None:
                try:
                    self._on_edit_detected()
                except Exception:
                    log.exception("on_edit_detected raised")
        if (not fn_now) and self._fn_held:
            self._fn_held = False
            if self._active:
                self._active = False
                try:
                    self._on_release()
                except Exception:
                    log.exception("on_release raised")
        return event

    def _callback(self, proxy, type_, event, refcon):
        if type_ in (kCGEventTapDisabledByTimeout, kCGEventTapDisabledByUserInput):
            if self._tap is not None:
                CGEventTapEnable(self._tap, True)
            return event
        try:
            keycode = int(CGEventGetIntegerValueField(event, kCGKeyboardEventKeycode))
            flags = int(CGEventGetFlags(event))
        except Exception:
            return event

        if self._combo in MODIFIER_ONLY_COMBOS:
            return self._handle_fn(type_, flags, event)
        return self._handle_keycombo(type_, keycode, flags, event)

    def _run(self) -> None:
        mask = (
            CGEventMaskBit(kCGEventKeyDown)
            | CGEventMaskBit(kCGEventKeyUp)
            | CGEventMaskBit(kCGEventFlagsChanged)
        )
        tap = CGEventTapCreate(
            kCGSessionEventTap,
            kCGHeadInsertEventTap,
            kCGEventTapOptionDefault,
            mask,
            self._callback,
            None,
        )
        if tap is None:
            log.error(
                "CGEventTapCreate failed — grant Accessibility permission to "
                "Kira.app (or Terminal if running via python) in System Settings."
            )
            return
        self._tap = tap
        source = CFMachPortCreateRunLoopSource(None, tap, 0)
        self._runloop = CFRunLoopGetCurrent()
        CFRunLoopAddSource(self._runloop, source, kCFRunLoopCommonModes)
        CGEventTapEnable(tap, True)
        log.info("HotkeyListener running (combo=%s)", self._combo)
        CFRunLoopRun()
        log.info("HotkeyListener stopped")

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._run, daemon=True, name="kira-hotkey")
        self._thread.start()

    def stop(self) -> None:
        if self._runloop is not None:
            try:
                CFRunLoopStop(self._runloop)
            except Exception:
                log.exception("failed to stop runloop")
        self._thread = None
        self._runloop = None
        self._tap = None
