"""py2app build config for Kira.app"""
import sys
sys.setrecursionlimit(10000)

import zlib as _zlib
if not hasattr(_zlib, "__file__"):
    _zlib.__file__ = __file__

from setuptools import setup
from py2app.build_app import py2app as _py2app_cmd


class py2app(_py2app_cmd):
    """Override to strip install_requires so py2app 0.28 works with PEP 621 pyproject.toml."""

    def finalize_options(self):
        self.distribution.install_requires = None
        super().finalize_options()


APP = ["kira/main.py"]
DATA_FILES = [
    ("assets", [
        "assets/icon-dock.icns",
        "assets/icon-template.png",
    ]),
    ("prompts", [
        "prompts/email.md",
        "prompts/chat.md",
        "prompts/terminal.md",
        "prompts/code.md",
        "prompts/plain.md",
    ]),
]
OPTIONS = {
    "argv_emulation": False,
    "iconfile": "assets/icon-dock.icns",
    "plist": {
        "CFBundleName": "Kira",
        "CFBundleDisplayName": "Kira",
        "CFBundleIdentifier": "eu.pollow.kira",
        "CFBundleVersion": "0.2.0",
        "CFBundleShortVersionString": "0.2.0",
        "LSUIElement": True,
        "NSMicrophoneUsageDescription": "Kira needs microphone access to transcribe your voice.",
        "NSAccessibilityUsageDescription": "Kira uses Accessibility to inject transcribed text at the cursor.",
        "NSInputMonitoringUsageDescription": "Kira listens for the global hotkey (hold Fn / Globe).",
    },
    "packages": [
        "rumps", "pynput", "sounddevice", "mlx_whisper", "numpy",
        "pydantic", "yaml", "ollama", "pyperclip",
        "_sounddevice_data",
        "_soundfile_data",
        "llvmlite",
        "anyio",
        "httpx",
        "httpcore",
        "h11",
        "certifi",
        "idna",
    ],
    "includes": [
        "kira", "kira.ui",
    ],
}

setup(
    app=APP,
    name="Kira",
    data_files=DATA_FILES,
    options={"py2app": OPTIONS},
    setup_requires=["py2app"],
    cmdclass={"py2app": py2app},
)
