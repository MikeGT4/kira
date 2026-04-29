"""py2app build config for Kira.app"""
import sys
sys.setrecursionlimit(10000)  # py2app + Python 3.12 modulefinder needs headroom
from setuptools import setup
from py2app.build_app import py2app as _py2app_cmd


class py2app(_py2app_cmd):
    """Override to strip install_requires so py2app 0.28 works with PEP 621 pyproject.toml.

    Modern setuptools auto-populates ``install_requires`` from pyproject.toml's
    ``[project.dependencies]``. py2app 0.28 explicitly rejects that. Clearing the
    attribute on the distribution before py2app's finalize runs sidesteps the check
    without losing our pyproject.toml metadata.
    """

    def finalize_options(self):
        self.distribution.install_requires = None
        super().finalize_options()


APP = ["kira/main.py"]
DATA_FILES = [
    ("assets", [
        "assets/icon-dock.icns",
        "assets/icon-template.png",
        "assets/hero.png",
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
        "CFBundleVersion": "0.1.0",
        "CFBundleShortVersionString": "0.1.0",
        "LSUIElement": True,
        "NSMicrophoneUsageDescription": "Kira needs microphone access to transcribe your voice.",
        "NSAccessibilityUsageDescription": "Kira uses Accessibility to inject transcribed text at the cursor.",
        "NSInputMonitoringUsageDescription": "Kira listens for the global hotkey (Option+Space).",
    },
    "packages": [
        "rumps", "pynput", "sounddevice", "mlx_whisper", "numpy",
        "pydantic", "yaml", "ollama", "pyperclip",
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
