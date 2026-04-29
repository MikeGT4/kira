"""Smoke tests for menubar — construction only, no event loop."""
from unittest.mock import patch, MagicMock


def test_menubar_imports():
    """Menubar module should import cleanly."""
    from kira.ui import menubar
    assert hasattr(menubar, "KiraMenubar")


def test_assets_exist():
    """Icon template file should exist."""
    from kira.ui.menubar import ICON_DEFAULT
    from pathlib import Path
    assert Path(ICON_DEFAULT).exists()
