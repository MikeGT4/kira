"""Config loader with Pydantic validation and YAML sourcing.

Platform-aware default paths and context-mode defaults. The Mac
and Windows branches import the same module; behavior branches
inside via sys.platform.
"""
from __future__ import annotations
import os
import sys
from pathlib import Path
from typing import Literal
import yaml
from pydantic import BaseModel, Field

_HOME = Path.home()


class HotkeyConfig(BaseModel):
    combo: str = "fn"
    min_duration_ms: int = 300


class AudioConfig(BaseModel):
    """Audio input configuration.

    input_gain multiplies raw samples before VAD/Whisper. Windows setups
    with only the generic USB-Audio-Class driver (no ROG/Nahimic/Sonic
    Studio) often deliver signals 50-200x below usable level; bump this
    to compensate. Clipped to [-1.0, 1.0] after multiplication.

    input_device pins sounddevice.InputStream to a specific device by
    index OR substring match against the device name. None = use the
    Windows default. On Mike's RTX 5090 box the default routes through
    "AI Noise-Canceling Microphone (ASUS Utility)" which filters all
    speech as noise; pin to the physical device (e.g. "ROG Theta") to
    bypass. Run `python scripts/audio_diagnose.py` to list candidates.
    """

    input_gain: float = 1.0
    input_device: int | str | None = None


class WhisperConfig(BaseModel):
    model: str = "mlx-community/whisper-large-v3-turbo"
    language: Literal["auto", "de", "en"] = "auto"
    vad_threshold: float = 0.35
    condition_on_previous_text: bool = False
    initial_prompt: str | None = None


class StylerConfig(BaseModel):
    provider: Literal["ollama", "openai", "anthropic"] = "ollama"
    model: str = "gemma2:2b"
    timeout_seconds: float = 3.0
    fallback_to_raw: bool = True
    # Ollama keep_alive: how long the model stays resident after a request.
    # Default "24h" prevents the 5-minute idle eviction that adds 1-2 s of
    # cold-start latency to the first dictation after a pause. Use "-1" to
    # never unload (uses VRAM permanently); "0" to unload immediately.
    keep_alive: str = "24h"
    # Pre-load the model at app startup with a tiny warmup request so the
    # very first user dictation doesn't pay the cold-start cost either.
    warmup_on_start: bool = True


class InjectorConfig(BaseModel):
    strategy: Literal["clipboard", "keystrokes"] = "clipboard"
    # Clipboard restore delay — ground floor for short text. The
    # injector scales this up for long pastes so heavy editors (Word,
    # Outlook, Slack-web) can finish consuming the buffer before we
    # restore the user's prior clipboard content. 500 ms is the new
    # default after a 463-char dictation got truncated mid-paste at
    # the previous 100 ms.
    restore_clipboard_after_ms: int = 500


class UIConfig(BaseModel):
    popup: bool = True
    sound_feedback: bool = False


DEFAULT_CONTEXT_MODES_MAC: dict[str, str] = {
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

DEFAULT_CONTEXT_MODES_WIN: dict[str, str] = {
    # Email
    "outlook.exe": "email",
    "hxoutlook.exe": "email",
    "thunderbird.exe": "email",
    # Chat
    "slack.exe": "chat",
    "discord.exe": "chat",
    "teams.exe": "chat",
    "ms-teams.exe": "chat",
    "signal.exe": "chat",
    "telegram.exe": "chat",
    "whatsapp.exe": "chat",
    # Terminal
    "windowsterminal.exe": "terminal",
    "wt.exe": "terminal",
    "cmd.exe": "terminal",
    "powershell.exe": "terminal",
    "pwsh.exe": "terminal",
    "wsl.exe": "terminal",
    "alacritty.exe": "terminal",
    # Code
    "code.exe": "code",
    "cursor.exe": "code",
    "idea64.exe": "code",
    "pycharm64.exe": "code",
    "devenv.exe": "code",
    "sublime_text.exe": "code",
    # Notes/Plain fallback
    "notepad.exe": "plain",
    "obsidian.exe": "plain",
    "notion.exe": "plain",
    # Browsers
    "chrome.exe": "plain",
    "msedge.exe": "plain",
    "firefox.exe": "plain",
    "brave.exe": "plain",
}


def platform_context_modes() -> dict[str, str]:
    if sys.platform == "win32":
        return DEFAULT_CONTEXT_MODES_WIN.copy()
    return DEFAULT_CONTEXT_MODES_MAC.copy()


class Config(BaseModel):
    hotkey: HotkeyConfig = Field(default_factory=HotkeyConfig)
    audio: AudioConfig = Field(default_factory=AudioConfig)
    whisper: WhisperConfig = Field(default_factory=WhisperConfig)
    styler: StylerConfig = Field(default_factory=StylerConfig)
    injector: InjectorConfig = Field(default_factory=InjectorConfig)
    ui: UIConfig = Field(default_factory=UIConfig)
    context_modes: dict[str, str] = Field(default_factory=platform_context_modes)


def effective_hotkey(combo: str) -> str:
    """Map the cross-platform default ``fn`` to the actual key on this OS.

    The HotkeyConfig default is ``fn`` because that's what the Mac build
    uses (Globe/Function key). Windows can't bind ``fn`` directly, so a
    Windows install with the unset default falls back to F8. Centralised
    here so the About dialog and the hotkey listener both see the same
    string instead of one displaying ``fn`` while the other binds F8.
    """
    if sys.platform == "win32" and combo == "fn":
        return "f8"
    return combo


def default_config_path() -> Path:
    if sys.platform == "win32":
        appdata = os.environ.get("APPDATA")
        if appdata:
            return Path(appdata) / "Kira" / "config.yaml"
        return _HOME / "AppData" / "Roaming" / "Kira" / "config.yaml"
    return _HOME / ".config" / "kira" / "config.yaml"


def load_config(path: Path | None = None) -> Config:
    path = path or default_config_path()
    if not path.exists():
        return Config()
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return Config.model_validate(raw)
