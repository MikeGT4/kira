"""Tests for Config loader and platform-aware paths."""
from __future__ import annotations
import sys
import textwrap
from pathlib import Path
import pytest
from kira.config import Config, effective_hotkey, load_config


def test_load_defaults_when_no_file(tmp_path):
    cfg = load_config(tmp_path / "missing.yaml")
    assert cfg.hotkey.combo == "fn"  # changed from alt+space
    assert cfg.whisper.model == "mlx-community/whisper-large-v3-turbo"
    assert cfg.styler.provider == "ollama"
    assert cfg.styler.model == "gemma2:2b"
    assert cfg.injector.strategy == "clipboard"


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


def test_default_config_path_mac(monkeypatch):
    from kira import config as cfg_mod
    monkeypatch.setattr(cfg_mod.sys, "platform", "darwin")
    monkeypatch.setattr(cfg_mod, "_HOME", Path("/Users/fake"))
    p = cfg_mod.default_config_path()
    assert p.as_posix() == "/Users/fake/.config/kira/config.yaml"


def test_default_config_path_windows(monkeypatch):
    from kira import config as cfg_mod
    monkeypatch.setattr(cfg_mod.sys, "platform", "win32")
    monkeypatch.setenv("APPDATA", r"C:\Users\Fake\AppData\Roaming")
    p = cfg_mod.default_config_path()
    assert str(p).replace("/", "\\") == r"C:\Users\Fake\AppData\Roaming\Kira\config.yaml"


def test_config_defaults_validate():
    from kira.config import Config
    c = Config()
    assert c.whisper.model
    assert c.styler.provider == "ollama"


def test_default_context_modes_platform_specific(monkeypatch):
    from kira import config as cfg_mod
    monkeypatch.setattr(cfg_mod.sys, "platform", "win32")
    modes = cfg_mod.platform_context_modes()
    assert modes.get("outlook.exe") == "email"

    monkeypatch.setattr(cfg_mod.sys, "platform", "darwin")
    modes = cfg_mod.platform_context_modes()
    assert modes.get("com.apple.mail") == "email"


def test_effective_hotkey_maps_fn_to_f8_on_windows(monkeypatch):
    from kira import config as cfg_mod
    monkeypatch.setattr(cfg_mod.sys, "platform", "win32")
    assert cfg_mod.effective_hotkey("fn") == "f8"


def test_effective_hotkey_keeps_fn_on_mac(monkeypatch):
    from kira import config as cfg_mod
    monkeypatch.setattr(cfg_mod.sys, "platform", "darwin")
    assert cfg_mod.effective_hotkey("fn") == "fn"


def test_effective_hotkey_passes_explicit_combo_through(monkeypatch):
    """User-set combos like 'ctrl+shift+space' must not be auto-rewritten."""
    from kira import config as cfg_mod
    monkeypatch.setattr(cfg_mod.sys, "platform", "win32")
    assert cfg_mod.effective_hotkey("ctrl+shift+space") == "ctrl+shift+space"
    assert cfg_mod.effective_hotkey("f10") == "f10"
