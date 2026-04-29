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
