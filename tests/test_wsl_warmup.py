"""Tests for kira._wsl_warmup — fire-and-forget WSL distro kick.

WSL2 doesn't auto-start at Win-login, so on boxes with Ollama-in-WSL
the autostart races the user's first manual WSL touch. Kira fires
``wsl.exe --exec /bin/true`` non-blocking at boot so the VM is up
by the time the setup probe runs.
"""
from __future__ import annotations
import sys
from unittest.mock import patch

import pytest

if sys.platform != "win32":
    pytest.skip("windows-only tests", allow_module_level=True)

from kira import _wsl_warmup  # pyright: ignore[reportUnreachable]


def test_kick_wsl_dispatches_wsl_exe():
    with patch("kira._wsl_warmup.subprocess.Popen") as popen:
        _wsl_warmup.kick_wsl_distro()
    popen.assert_called_once()
    cmd = popen.call_args[0][0]
    assert cmd[0] == "wsl.exe"
    assert "--exec" in cmd


def test_kick_wsl_uses_create_no_window_flag():
    """The wsl.exe console flash at autostart is jarring — must be hidden."""
    with patch("kira._wsl_warmup.subprocess.Popen") as popen:
        _wsl_warmup.kick_wsl_distro()
    kwargs = popen.call_args.kwargs
    # CREATE_NO_WINDOW = 0x08000000
    assert kwargs.get("creationflags", 0) & 0x08000000


def test_kick_wsl_does_not_raise_when_wsl_missing():
    """On non-WSL boxes wsl.exe isn't on PATH — must silently skip."""
    with patch("kira._wsl_warmup.subprocess.Popen", side_effect=FileNotFoundError):
        _wsl_warmup.kick_wsl_distro()  # must not raise


def test_kick_wsl_does_not_raise_when_subprocess_blows_up():
    """Even on weird subprocess failures, Kira boot must continue."""
    with patch("kira._wsl_warmup.subprocess.Popen", side_effect=OSError("EBADF")):
        _wsl_warmup.kick_wsl_distro()  # must not raise


def test_kick_wsl_does_not_block_caller():
    """Popen + no .wait() — kick must return immediately."""
    from unittest.mock import MagicMock
    fake_proc = MagicMock()
    with patch("kira._wsl_warmup.subprocess.Popen", return_value=fake_proc):
        _wsl_warmup.kick_wsl_distro()
    fake_proc.wait.assert_not_called()
    fake_proc.communicate.assert_not_called()
