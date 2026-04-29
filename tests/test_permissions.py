from unittest.mock import patch
from kira.permissions import PermissionStatus, check_all, open_settings, SETTINGS_URLS


def test_permission_status_all_granted():
    s = PermissionStatus(microphone=True, accessibility=True, input_monitoring=True)
    assert s.all_granted is True


def test_permission_status_not_all_granted():
    s = PermissionStatus(microphone=True, accessibility=False, input_monitoring=True)
    assert s.all_granted is False


def test_check_all_aggregates_individual_checks():
    with patch("kira.permissions.check_microphone", return_value=True), \
         patch("kira.permissions.check_accessibility", return_value=False), \
         patch("kira.permissions.check_input_monitoring", return_value=True):
        status = check_all()
        assert status.microphone is True
        assert status.accessibility is False
        assert status.input_monitoring is True


def test_settings_urls_has_all_panes():
    assert "microphone" in SETTINGS_URLS
    assert "accessibility" in SETTINGS_URLS
    assert "input_monitoring" in SETTINGS_URLS


def test_open_settings_invokes_open_for_known_pane():
    with patch("kira.permissions.subprocess.Popen") as popen:
        open_settings("accessibility")
        assert popen.called
        args = popen.call_args[0][0]
        assert args[0] == "open"
        assert args[1].startswith("x-apple.systempreferences:")


def test_open_settings_noop_for_unknown_pane():
    with patch("kira.permissions.subprocess.Popen") as popen:
        open_settings("bogus")
        assert not popen.called
