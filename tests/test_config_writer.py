"""Tests for the comment-preserving YAML updater."""
from __future__ import annotations
import pytest

from kira.config_writer import update_scalars


SAMPLE_CONFIG = """\
audio:
  # Software gain multiplier applied to raw mic samples.
  # Long lessons-learned comment block here.
  input_gain: 2.0
  # 2026-04-28 ROOT CAUSE: ASUS AI Noise-Cancel routing.
  input_device: "ROG Theta"

whisper:
  # Full Whisper large-v3 — tuned for RTX 5090.
  model: C:/Users/mike/models/faster-whisper-large-v3
  language: de
  vad_threshold: 0.15

styler:
  # Polish-step LLM. gemma3:12b is the sweet spot.
  model: gemma3:12b
  timeout_seconds: 30.0
"""


def test_update_single_scalar_preserves_comments():
    out = update_scalars(SAMPLE_CONFIG, {"audio.input_gain": 5.0})
    assert "# Software gain multiplier" in out
    assert "# Long lessons-learned" in out
    assert "input_gain: 5.0" in out
    assert "input_gain: 2.0" not in out


def test_update_multiple_scalars_in_one_pass():
    out = update_scalars(SAMPLE_CONFIG, {
        "audio.input_gain": 5.0,
        "whisper.language": "en",
        "styler.timeout_seconds": 60.0,
    })
    assert "input_gain: 5.0" in out
    assert "language: en" in out
    assert "timeout_seconds: 60.0" in out
    # Old values are gone
    assert "input_gain: 2.0" not in out
    assert "language: de" not in out
    assert "timeout_seconds: 30.0" not in out


def test_section_aware_updates_correct_model():
    """`model:` exists in both whisper and styler — section-aware update
    must hit the right one."""
    out = update_scalars(SAMPLE_CONFIG, {"styler.model": "qwen3:8b"})
    assert "model: qwen3:8b" in out
    # Whisper.model untouched
    assert "model: C:/Users/mike/models/faster-whisper-large-v3" in out


def test_quotes_string_with_special_chars():
    """YAML must auto-quote strings that need it (spaces, colons, etc.)."""
    out = update_scalars(SAMPLE_CONFIG, {"audio.input_device": "Headset Mic"})
    # Either bare or quoted is OK as long as it round-trips
    import yaml
    parsed = yaml.safe_load(out)
    assert parsed["audio"]["input_device"] == "Headset Mic"


def test_null_value():
    out = update_scalars(SAMPLE_CONFIG, {"audio.input_device": None})
    import yaml
    parsed = yaml.safe_load(out)
    assert parsed["audio"]["input_device"] is None


def test_int_and_float_values():
    out = update_scalars(SAMPLE_CONFIG, {
        "audio.input_gain": 10,
        "whisper.vad_threshold": 0.5,
    })
    import yaml
    parsed = yaml.safe_load(out)
    assert parsed["audio"]["input_gain"] == 10
    assert parsed["whisper"]["vad_threshold"] == 0.5


def test_unknown_section_appends_at_eof():
    """Seit v0.2 (Mike's Bug 2026-05-09): User-Configs aus v0.1 hatten
    keine `hotkey:`/`injector:`-Sections. Der alte KeyError hat den
    Save vom Settings-Dialog unterbrochen. Fehlende Section wird jetzt
    am EOF angehaengt."""
    out = update_scalars(SAMPLE_CONFIG, {"hotkey.combo": "f8"})
    assert "hotkey:" in out
    assert "  combo: f8" in out
    import yaml
    parsed = yaml.safe_load(out)
    assert parsed["hotkey"]["combo"] == "f8"
    # Original-Sections + Comments unangetastet
    assert "# Long lessons-learned" in out


def test_unknown_key_in_known_section_appends_in_section():
    """Fehlender Key in vorhandener Section wird am Section-Ende
    eingefuegt — nicht nach EOF und nicht ueber Section-Comment."""
    out = update_scalars(SAMPLE_CONFIG, {"audio.new_field": 42})
    import yaml
    parsed = yaml.safe_load(out)
    assert parsed["audio"]["new_field"] == 42
    # Section-Anker soll nicht doppelt angehangen werden
    assert out.count("audio:") == 1


def test_multiple_missing_keys_one_existing_one_new_section():
    """Gemischter Fall: ein Key in vorhandener Section + komplett neue Section."""
    out = update_scalars(SAMPLE_CONFIG, {
        "audio.gain_boost": 1.5,
        "hotkey.combo": "f8",
        "hotkey.edit_combo": "f9",
    })
    import yaml
    parsed = yaml.safe_load(out)
    assert parsed["audio"]["gain_boost"] == 1.5
    assert parsed["hotkey"]["combo"] == "f8"
    assert parsed["hotkey"]["edit_combo"] == "f9"
    # Original-Werte unveraendert
    assert parsed["audio"]["input_gain"] == 2.0


def test_existing_keys_still_updated_when_others_missing():
    """Mix: bekannter Key + fehlende Section gleichzeitig — beide muessen wirken."""
    out = update_scalars(SAMPLE_CONFIG, {
        "audio.input_gain": 5.0,
        "hotkey.edit_combo": "f9",
    })
    import yaml
    parsed = yaml.safe_load(out)
    assert parsed["audio"]["input_gain"] == 5.0
    assert parsed["hotkey"]["edit_combo"] == "f9"


def test_no_section_in_dotted_path_raises():
    with pytest.raises(ValueError):
        update_scalars(SAMPLE_CONFIG, {"flat_key": 1})


def test_idempotent_update():
    """Updating with the current value should produce identical output."""
    out = update_scalars(SAMPLE_CONFIG, {"audio.input_gain": 2.0})
    # The line gets re-rendered, but parsed content stays equal
    import yaml
    assert yaml.safe_load(out) == yaml.safe_load(SAMPLE_CONFIG)


def test_blank_lines_between_sections_preserved():
    out = update_scalars(SAMPLE_CONFIG, {"audio.input_gain": 5.0})
    # Two blank lines flank the "whisper:" section in the original
    assert "\n\nwhisper:" in out or "\n  \nwhisper:" in out
