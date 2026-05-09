"""Tests for KiraTray._check_for_updates handler.

v0.2: ehemaliger Hint-Pfad ersetzt durch echten Update-Workflow.
Der Tray-Handler routet via _marshal_to_qt zur Qt-Mainthread und
ruft dort run_update_flow aus _update_runner. Diese Tests pruefen
nur die Tray-Wireup-Logik; der eigentliche Workflow (download,
verify, launch) lebt in test_updater.py + ggf. UI-tests.
"""
from __future__ import annotations
import sys
from unittest.mock import MagicMock, patch

import pytest

if sys.platform != "win32":
    pytest.skip("windows-only tests", allow_module_level=True)


@pytest.fixture
def tray():
    from kira.ui.tray_win import KiraTray
    quit_calls = []
    t = KiraTray(on_quit=lambda: quit_calls.append(1))
    t._quit_calls = quit_calls
    return t


def test_check_for_updates_marshals_to_qt(tray):
    """Pystray-Callback laeuft auf einem Daemon-Thread - der Handler MUSS
    via _marshal_to_qt auf die Qt-Mainthread, sonst constructed das Update-
    Dialog auf dem falschen Thread und Qt assertet."""
    tray._marshal_to_qt = MagicMock()
    tray._check_for_updates(None, None)
    tray._marshal_to_qt.assert_called_once()
    # zweites Arg ist der Label-String — sollte beschreibend sein:
    label = tray._marshal_to_qt.call_args.args[1]
    assert "update" in label.lower()


def test_run_update_flow_marshalled_calls_underlying_runner():
    """Der Static-Helper ruft run_update_flow mit den richtigen Args."""
    from kira.ui.tray_win import KiraTray

    quit_marker = MagicMock()
    with patch("kira.ui._update_runner.run_update_flow") as mock_run:
        KiraTray._run_update_flow_marshalled(quit_marker)
    mock_run.assert_called_once()
    kwargs = mock_run.call_args.kwargs
    assert kwargs["parent"] is None
    assert kwargs["on_quit_request"] is quit_marker


def test_check_for_updates_passes_quit_callback_through(tray):
    """Der durchgereichte Quit-Callback MUSS der von __init__ gesetzte
    on_quit sein — sonst kann das Update-Setup das Programmverzeichnis
    nicht ueberschreiben (Single-Instance-Mutex blockiert)."""
    captured = {}

    def fake_marshal(func, _label):
        # _marshal_to_qt nimmt einen Lambda/Callable; wir rufen sie
        # synchron um zu sehen was reingeht.
        captured["called"] = True
        # Patchen run_update_flow innerhalb dem Lambda-Aufruf
        with patch("kira.ui._update_runner.run_update_flow") as mock_run:
            func()
            captured["kwargs"] = mock_run.call_args.kwargs

    tray._marshal_to_qt = fake_marshal
    tray._check_for_updates(None, None)
    assert captured.get("called") is True
    # quit_callback IST der on_quit den wir tray.__init__ gegeben haben
    assert captured["kwargs"]["on_quit_request"] is tray._on_quit
    assert captured["kwargs"]["parent"] is None


def test_menu_includes_check_for_updates_item(tray):
    """Menue-Eintrag muss bestehen bleiben — der existing User-flow ist
    rechtsklick-Tray -> 'Updates suchen...'."""
    menu = tray._build_menu()
    labels = [getattr(item, "text", None) for item in menu.items]
    assert "Updates suchen…" in labels
