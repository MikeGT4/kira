import textwrap
from pathlib import Path
import pytest
from kira.config import Config, load_config


def test_load_defaults_when_no_file(tmp_path):
    cfg = load_config(tmp_path / "missing.yaml")
    assert cfg.hotkey.combo == "fn"  # changed from alt+space
    assert cfg.whisper.model == "mlx-community/whisper-large-v3-turbo"
    assert cfg.styler.provider == "ollama"
    assert cfg.styler.model == "gemma2:2b"
    assert cfg.injector.strategy == "clipboard"
    assert "com.apple.mail" in cfg.context_modes
    assert cfg.context_modes["com.apple.mail"] == "email"


def test_load_from_yaml(tmp_path):
    yaml_file = tmp_path / "config.yaml"
    yaml_file.write_text(textwrap.dedent("""
        hotkey:
          combo: ctrl+shift+d
          min_duration_ms: 500
        styler:
          provider: ollama
          model: llama3.2:3b
          timeout_seconds: 5
          fallback_to_raw: true
    """))
    cfg = load_config(yaml_file)
    assert cfg.hotkey.combo == "ctrl+shift+d"
    assert cfg.hotkey.min_duration_ms == 500
    assert cfg.styler.model == "llama3.2:3b"


def test_invalid_provider_raises(tmp_path):
    yaml_file = tmp_path / "config.yaml"
    yaml_file.write_text("styler:\n  provider: invalid\n")
    with pytest.raises(ValueError):
        load_config(yaml_file)
