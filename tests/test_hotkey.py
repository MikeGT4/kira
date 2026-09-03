import pytest
from kira.hotkey import HotkeyListener, _flags_match, KEY_COMBOS, MODIFIER_ONLY_COMBOS


def test_key_combo_constructs():
    h = HotkeyListener("alt+space", lambda: None, lambda: None)
    assert h is not None


def test_modifier_only_constructs():
    h = HotkeyListener("fn", lambda: None, lambda: None)
    assert h is not None


def test_unknown_combo_raises():
    with pytest.raises(ValueError):
        HotkeyListener("unknown+combo", lambda: None, lambda: None)


def test_key_combos_has_alt_space():
    assert "alt+space" in KEY_COMBOS


def test_fn_is_modifier_only():
    assert "fn" in MODIFIER_ONLY_COMBOS


def test_flags_match_ignores_other_bits():
    alt = 1 << 17
    caps = 1 << 16
    assert _flags_match(alt | caps, alt) is True


def test_flags_match_fails_on_missing_modifier():
    alt = 1 << 17
    assert _flags_match(0, alt) is False


def test_flags_match_fails_on_extra_modifier():
    alt = 1 << 17
    ctrl = 1 << 18
    assert _flags_match(alt | ctrl, alt) is False


def _fn_listener(calls, edit_modifier="shift"):
    return HotkeyListener(
        "fn",
        lambda: calls.append("press"),
        lambda: calls.append("release"),
        on_edit_detected=lambda: calls.append("edit"),
        edit_modifier=edit_modifier,
    )


def test_shift_while_fn_is_held_fires_edit_once():
    from Quartz import kCGEventFlagsChanged, kCGEventFlagMaskSecondaryFn, kCGEventFlagMaskShift
    calls = []
    h = _fn_listener(calls)
    h._handle_fn(kCGEventFlagsChanged, kCGEventFlagMaskSecondaryFn, None)
    h._handle_fn(kCGEventFlagsChanged, kCGEventFlagMaskSecondaryFn | kCGEventFlagMaskShift, None)
    h._handle_fn(kCGEventFlagsChanged, kCGEventFlagMaskSecondaryFn | kCGEventFlagMaskShift, None)
    h._handle_fn(kCGEventFlagsChanged, kCGEventFlagMaskShift, None)
    assert calls == ["press", "edit", "release"]


def test_fn_pressed_while_shift_is_held_fires_press_and_edit():
    from Quartz import kCGEventFlagsChanged, kCGEventFlagMaskSecondaryFn, kCGEventFlagMaskShift
    calls = []
    h = _fn_listener(calls)
    h._handle_fn(kCGEventFlagsChanged, kCGEventFlagMaskShift, None)
    h._handle_fn(kCGEventFlagsChanged, kCGEventFlagMaskSecondaryFn | kCGEventFlagMaskShift, None)
    h._handle_fn(kCGEventFlagsChanged, 0, None)
    assert calls == ["press", "edit", "release"]


def test_fn_alone_never_fires_edit():
    from Quartz import kCGEventFlagsChanged, kCGEventFlagMaskSecondaryFn
    calls = []
    h = _fn_listener(calls)
    h._handle_fn(kCGEventFlagsChanged, kCGEventFlagMaskSecondaryFn, None)
    h._handle_fn(kCGEventFlagsChanged, 0, None)
    assert calls == ["press", "release"]


def test_edit_modifier_off_ignores_shift():
    from Quartz import kCGEventFlagsChanged, kCGEventFlagMaskSecondaryFn, kCGEventFlagMaskShift
    calls = []
    h = _fn_listener(calls, edit_modifier=None)
    h._handle_fn(kCGEventFlagsChanged, kCGEventFlagMaskSecondaryFn | kCGEventFlagMaskShift, None)
    h._handle_fn(kCGEventFlagsChanged, 0, None)
    assert calls == ["press", "release"]


def test_unknown_edit_modifier_raises():
    with pytest.raises(ValueError):
        HotkeyListener("fn", lambda: None, lambda: None, edit_modifier="fn")
