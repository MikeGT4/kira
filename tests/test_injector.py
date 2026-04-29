from unittest.mock import patch, MagicMock
from kira.injector import Injector


def test_empty_text_does_nothing():
    inj = Injector()
    with patch("kira.injector.pyperclip") as pp, patch("kira.injector._send_cmd_v") as send:
        inj.inject("")
        assert pp.copy.call_count == 0
        assert send.call_count == 0


def test_inject_sets_clipboard_and_sends_cmd_v():
    inj = Injector(restore_after_ms=10)
    with patch("kira.injector.pyperclip") as pp, patch("kira.injector._send_cmd_v") as send:
        pp.paste.return_value = "original"
        inj.inject("new text")
        # First copy sets our text; second copy (via Timer) restores original
        assert pp.copy.call_args_list[0][0][0] == "new text"
        assert send.call_count == 1
