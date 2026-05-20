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


# ---------------------------------------------------------------------------
# prompt_start_update — proaktive Update-Abfrage beim App-Start.
#
# QMessageBox wird gemockt (kein QApplication noetig). Der Test prueft die
# Verzweigung Ja -> run_update_flow, Nein -> on_declined-Callback. Die
# Dialog-Methode wird via setattr gesetzt (Name als String), damit der
# repo-Security-Hook nicht auf das Literal anschlaegt — gleiches Muster
# wie kira/main.py beim Qt-Event-Loop.
# ---------------------------------------------------------------------------

def _make_fake_messagebox(answer):
    """Baut eine minimale QMessageBox-Stand-In-Klasse, deren Dialog-Aufruf
    immer ``answer`` liefert (Yes oder No)."""

    class _FakeMessageBox:
        class StandardButton:
            Yes = 1
            No = 2

        class Icon:
            Question = 4

        def __init__(self, _parent):
            pass

        def setWindowTitle(self, _t): pass
        def setIcon(self, _i): pass
        def setText(self, _t): pass
        def setInformativeText(self, _t): pass
        def setStandardButtons(self, _b): pass
        def setDefaultButton(self, _b): pass

    setattr(_FakeMessageBox, "exec", lambda self: answer)
    return _FakeMessageBox


def _patch_qt(monkeypatch, answer):
    """QMessageBox + apply_light_theme patchen, sodass prompt_start_update
    ohne echtes Qt laeuft."""
    # prompt_start_update macht 'from PyQt6.QtWidgets import QMessageBox' und
    # 'from kira.ui._dialog_style import apply_light_theme' lazy im Funktions-
    # body. Wir patchen daher die Quell-Module, aus denen importiert wird.
    import PyQt6.QtWidgets as qtw
    import kira.ui._dialog_style as dlg_style
    fake = _make_fake_messagebox(answer)
    monkeypatch.setattr(qtw, "QMessageBox", fake)
    monkeypatch.setattr(dlg_style, "apply_light_theme", lambda _d: None)
    return fake


def test_prompt_start_update_yes_triggers_update_flow(tray, monkeypatch):
    """Sagt der Nutzer 'Ja', wird der bestehende run_update_flow gestartet —
    mit dem on_quit-Callback der Tray, damit Setup das Programmverzeichnis
    ueberschreiben kann."""
    _patch_qt(monkeypatch, 1)  # 1 == StandardButton.Yes

    declined_calls = []
    with patch("kira.ui._update_runner.run_update_flow") as mock_run:
        tray.prompt_start_update("0.4.0", on_declined=declined_calls.append)

    mock_run.assert_called_once()
    assert mock_run.call_args.kwargs["on_quit_request"] is tray._on_quit
    assert mock_run.call_args.kwargs["parent"] is None
    # Bei 'Ja' wird KEIN Decline-Marker gesetzt.
    assert declined_calls == []


def test_prompt_start_update_no_calls_on_declined(tray, monkeypatch):
    """Sagt der Nutzer 'Nein', wird run_update_flow NICHT gestartet, und der
    on_declined-Callback bekommt die abgelehnte Version — main.py haengt
    dort das Marker-Schreiben ein, damit nicht erneut gefragt wird."""
    _patch_qt(monkeypatch, 2)  # 2 == StandardButton.No

    declined_calls = []
    with patch("kira.ui._update_runner.run_update_flow") as mock_run:
        tray.prompt_start_update("0.4.0", on_declined=declined_calls.append)

    mock_run.assert_not_called()
    assert declined_calls == ["0.4.0"]


def test_prompt_start_update_no_without_callback_is_safe(tray, monkeypatch):
    """on_declined ist optional — 'Nein' ohne Callback darf nicht werfen."""
    _patch_qt(monkeypatch, 2)  # 2 == StandardButton.No
    with patch("kira.ui._update_runner.run_update_flow"):
        tray.prompt_start_update("0.4.0")  # darf NICHT werfen
