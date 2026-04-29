"""Config loader with Pydantic validation and YAML sourcing."""
from __future__ import annotations
from pathlib import Path
from typing import Literal
import yaml
from pydantic import BaseModel, Field


class HotkeyConfig(BaseModel):
    combo: str = "fn"
    min_duration_ms: int = 300


class WhisperConfig(BaseModel):
    model: str = "mlx-community/whisper-large-v3-turbo"
    language: Literal["auto", "de", "en"] = "auto"


class StylerConfig(BaseModel):
    provider: Literal["ollama", "openai", "anthropic"] = "ollama"
    model: str = "gemma2:2b"
    timeout_seconds: float = 3.0
    fallback_to_raw: bool = True


class InjectorConfig(BaseModel):
    strategy: Literal["clipboard", "keystrokes"] = "clipboard"
    restore_clipboard_after_ms: int = 100


class UIConfig(BaseModel):
    popup: bool = True
    sound_feedback: bool = False


DEFAULT_CONTEXT_MODES = {
    "com.apple.mail": "email",
    "com.microsoft.Outlook": "email",
    "com.readdle.SparkDesktop": "email",
    "com.apple.MobileSMS": "chat",
    "com.tinyspeck.slackmacgap": "chat",
    "com.hnc.Discord": "chat",
    "com.apple.Terminal": "terminal",
    "com.googlecode.iterm2": "terminal",
    "co.zeit.hyper": "terminal",
    "com.microsoft.VSCode": "code",
    "com.apple.dt.Xcode": "code",
    "com.jetbrains.pycharm": "code",
    "com.apple.Safari": "plain",
    "com.google.Chrome": "plain",
    "org.mozilla.firefox": "plain",
}


class Config(BaseModel):
    hotkey: HotkeyConfig = Field(default_factory=HotkeyConfig)
    whisper: WhisperConfig = Field(default_factory=WhisperConfig)
    styler: StylerConfig = Field(default_factory=StylerConfig)
    injector: InjectorConfig = Field(default_factory=InjectorConfig)
    ui: UIConfig = Field(default_factory=UIConfig)
    context_modes: dict[str, str] = Field(default_factory=lambda: DEFAULT_CONTEXT_MODES.copy())


def default_config_path() -> Path:
    return Path.home() / ".config" / "kira" / "config.yaml"


def load_config(path: Path | None = None) -> Config:
    path = path or default_config_path()
    if not path.exists():
        return Config()
    raw = yaml.safe_load(path.read_text()) or {}
    return Config.model_validate(raw)
