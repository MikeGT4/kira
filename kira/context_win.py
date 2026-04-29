"""Detect the frontmost Windows app and map to a style mode."""
from __future__ import annotations
import logging
import win32gui
import win32process
import psutil
from kira.config import Config

log = logging.getLogger(__name__)


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
    # Browsers (plain — can't distinguish tab context without extension)
    "chrome.exe": "plain",
    "msedge.exe": "plain",
    "firefox.exe": "plain",
    "brave.exe": "plain",
}


def active_exe() -> str | None:
    """Return lowercased .exe name of foreground process, or None."""
    try:
        hwnd = win32gui.GetForegroundWindow()
        _, pid = win32process.GetWindowThreadProcessId(hwnd)
        if pid == 0:
            # desktop / lock screen — psutil would return "System Idle Process"
            return None
        return psutil.Process(pid).name().lower()
    except Exception as exc:
        log.debug("active_exe error: %s", exc)
        return None


def detect_mode(config: Config) -> str:
    """Return the style mode for the current frontmost app."""
    exe = active_exe()
    if exe is None:
        return "plain"
    return config.context_modes.get(exe, "plain")
