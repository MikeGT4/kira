def test_merge_settings_applies_dotted_keys_and_keeps_other_sections():
    from kira.ui.settings_window import merge_settings
    raw = {"styler": {"model": "a", "keep_alive": "1h"}, "context_modes": {"x": "chat"}}
    out = merge_settings(raw, {"styler.model": "b", "hotkey.combo": "fn", "audio.input_device": None})
    assert out["styler"] == {"model": "b", "keep_alive": "1h"}
    assert out["hotkey"] == {"combo": "fn"}
    assert out["audio"] == {"input_device": None}
    assert out["context_modes"] == {"x": "chat"}
    assert raw["styler"]["model"] == "a"


def test_parse_positive_float_accepts_comma_and_rejects_junk():
    from kira.ui.settings_window import parse_positive_float
    assert parse_positive_float("12,5") == 12.5
    assert parse_positive_float("0") is None
    assert parse_positive_float("abc") is None


def test_settings_window_constructs_without_building():
    from kira.ui.settings_window import SettingsWindow
    from pathlib import Path
    w = SettingsWindow(Path("/tmp/kira-test-config.yaml"))
    assert w._window is None
