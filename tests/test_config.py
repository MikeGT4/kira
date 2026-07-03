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


def test_styler_fast_mode_defaults_off():
    """Beim Upgrade darf Default-Behavior nicht aendern — fast_mode muss aus sein."""
    c = Config()
    assert c.styler.fast_mode is False
    assert c.styler.fast_model == "gemma3:4b"


def test_styler_fast_mode_loaded_from_yaml(tmp_path):
    yaml_file = tmp_path / "config.yaml"
    yaml_file.write_text(textwrap.dedent("""
        styler:
          model: gemma3:12b
          fast_mode: true
          fast_model: gemma3:4b
    """))
    cfg = load_config(yaml_file)
    assert cfg.styler.fast_mode is True
    assert cfg.styler.fast_model == "gemma3:4b"
    assert cfg.styler.model == "gemma3:12b"


def test_updates_check_on_start_defaults_on():
    """Default: der automatische Start-Update-Check ist aktiv."""
    c = Config()
    assert c.updates.check_on_start is True


def test_updates_check_on_start_can_be_disabled_via_yaml(tmp_path):
    """Nutzer kann den Start-Update-Check via config.yaml abschalten."""
    yaml_file = tmp_path / "config.yaml"
    yaml_file.write_text(textwrap.dedent("""
        updates:
          check_on_start: false
    """))
    cfg = load_config(yaml_file)
    assert cfg.updates.check_on_start is False


def test_updates_section_optional_in_yaml(tmp_path):
    """Fehlt die updates-Section komplett (alte config.yaml), greift der
    Default — kein Validierungsfehler beim Upgrade auf diese Version."""
    yaml_file = tmp_path / "config.yaml"
    yaml_file.write_text("styler:\n  model: gemma3:12b\n")
    cfg = load_config(yaml_file)
    assert cfg.updates.check_on_start is True


def test_context_modes_yaml_merges_with_builtin_table(tmp_path, monkeypatch):
    """Ein user-definierter context_modes-Block ERGAENZT die eingebaute
    App-Tabelle, statt sie zu ersetzen. Vorher verlor ein User, der (wie
    von Settings-Dialog + config_writer dokumentiert empfohlen) einen
    einzelnen Custom-Eintrag in die Roh-YAML schrieb, still saemtliche
    Default-Mappings (outlook->email, cmd->terminal, ...) — alle Apps
    fielen auf plain zurueck."""
    monkeypatch.setattr("sys.platform", "win32")
    yaml_file = tmp_path / "config.yaml"
    yaml_file.write_text(
        "context_modes:\n"
        "  mychat.exe: chat\n"
        "  outlook.exe: plain\n"
    )
    cfg = load_config(yaml_file)
    # Custom-Eintrag da:
    assert cfg.context_modes["mychat.exe"] == "chat"
    # User-Override eines Default-Keys gewinnt:
    assert cfg.context_modes["outlook.exe"] == "plain"
    # Und die restliche Built-in-Tabelle lebt noch:
    assert "cmd.exe" in cfg.context_modes


def test_context_modes_absent_yields_full_builtin_table(tmp_path):
    """Ohne context_modes-Block in der YAML bleibt alles wie gehabt."""
    yaml_file = tmp_path / "config.yaml"
    yaml_file.write_text("styler:\n  model: gemma3:12b\n")
    cfg = load_config(yaml_file)
    assert len(cfg.context_modes) > 5
