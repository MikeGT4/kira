from unittest.mock import patch
from kira.config import Config
from kira.context import detect_mode, active_app_bundle_id


def test_detect_mode_known_app():
    cfg = Config()
    with patch("kira.context.active_app_bundle_id", return_value="com.apple.mail"):
        assert detect_mode(cfg) == "email"


def test_detect_mode_unknown_app_defaults_to_plain():
    cfg = Config()
    with patch("kira.context.active_app_bundle_id", return_value="org.unknown.app"):
        assert detect_mode(cfg) == "plain"


def test_detect_mode_none_defaults_to_plain():
    cfg = Config()
    with patch("kira.context.active_app_bundle_id", return_value=None):
        assert detect_mode(cfg) == "plain"


def test_terminal_app_maps_to_terminal():
    cfg = Config()
    with patch("kira.context.active_app_bundle_id", return_value="com.googlecode.iterm2"):
        assert detect_mode(cfg) == "terminal"
