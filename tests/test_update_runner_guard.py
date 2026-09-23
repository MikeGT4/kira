# © 2026 Mike Pollow, Digitalroots. Alle Rechte vorbehalten.
"""Tests für den Schutz gegen einen zweiten, parallelen Update-Ablauf (v0.4.1)."""
from __future__ import annotations

import sys

import pytest

if sys.platform != "win32":
    pytest.skip("windows-only tests", allow_module_level=True)

from kira.ui import _update_runner as runner


@pytest.fixture(autouse=True)
def _reset_flag(monkeypatch):
    monkeypatch.setattr(runner, "_flow_active", False)
    infos: list[str] = []
    monkeypatch.setattr(runner, "light_information", lambda parent, title, text: infos.append(text))
    return infos


def test_second_start_during_a_running_flow_is_refused(monkeypatch, _reset_flag):
    calls: list[str] = []

    def flow(parent, on_quit):
        calls.append("flow")
        runner.run_update_flow(None)  # zweiter Klick, während der erste Dialog offen ist
        return False

    monkeypatch.setattr(runner, "_run_update_flow", flow)
    runner.run_update_flow(None)
    assert calls == ["flow"]
    assert _reset_flag == ["Ein Update läuft bereits."]
    assert runner._flow_active is False


def test_flag_stays_set_while_the_download_runs(monkeypatch, _reset_flag):
    monkeypatch.setattr(runner, "_run_update_flow", lambda parent, on_quit: True)
    runner.run_update_flow(None)
    assert runner._flow_active is True
    runner.run_update_flow(None)
    assert _reset_flag == ["Ein Update läuft bereits."]
    runner._flow_finished()
    assert runner._flow_active is False


def test_flag_is_released_when_the_flow_raises(monkeypatch):
    def boom(parent, on_quit):
        raise RuntimeError("kaputt")

    monkeypatch.setattr(runner, "_run_update_flow", boom)
    with pytest.raises(RuntimeError):
        runner.run_update_flow(None)
    assert runner._flow_active is False


def test_failed_download_releases_the_flag(monkeypatch, qapp, tmp_path):
    """Echter Ablauf bis in den Download-Thread: Fehler dort gibt den Schutz wieder frei."""
    import time

    from PyQt6.QtCore import QCoreApplication
    from PyQt6.QtWidgets import QMessageBox

    from kira.updater import ReleaseAsset, UpdateCheckResult

    result = UpdateCheckResult(
        status="newer", remote_version="9.9.9",
        bundle_assets=[ReleaseAsset(name="Kira-Setup-v9.9.9.exe", url="https://example.invalid/s", size=1)],
    )
    monkeypatch.setattr(runner, "check_for_update", lambda **kw: result)
    monkeypatch.setattr(runner, "_bundle_dir", lambda: tmp_path)

    class _YesBox(QMessageBox):
        pass

    setattr(_YesBox, "exec", lambda self: QMessageBox.StandardButton.Yes)
    monkeypatch.setattr(runner, "QMessageBox", _YesBox)

    def no_network(*args, **kwargs):
        raise OSError("Netz weg")

    monkeypatch.setattr(runner, "download_bundle", no_network)
    critical: list[str] = []
    monkeypatch.setattr(runner, "light_critical", lambda parent, title, text: critical.append(text))

    runner.run_update_flow(None)
    assert runner._flow_active is True
    deadline = time.monotonic() + 5
    while runner._flow_active and time.monotonic() < deadline:
        QCoreApplication.processEvents()
        time.sleep(0.01)
    assert runner._flow_active is False
    assert critical and "Netz weg" in critical[0]


def test_real_early_return_releases_the_flag(monkeypatch, qapp, _reset_flag):
    """Echter Ablauf ohne neuere Version: Hinweis, danach ist die Sperre frei."""
    from kira.updater import UpdateCheckResult

    monkeypatch.setattr(runner, "check_for_update",
                        lambda **kw: UpdateCheckResult(status="current", remote_version="0.4.1"))
    runner.run_update_flow(None)
    assert runner._flow_active is False
    assert any("aktuell" in text for text in _reset_flag)


def test_cancel_button_stops_the_download_and_releases_the_flag(monkeypatch, qapp, tmp_path):
    """Der echte Knopf („canceled“ des Fortschrittsdialogs) beendet den Download am
    nächsten Block, nicht erst nach 3 GB. Der Test löst das Signal aus, statt
    worker.cancel() direkt zu rufen: Genau die Verbindung war der Fehler."""
    import time

    from PyQt6.QtCore import QCoreApplication
    from PyQt6.QtWidgets import QMessageBox

    import kira.updater as updater
    from kira.updater import ReleaseAsset, UpdateCheckResult

    class _Endless:
        """Liefert rund 3 s lang Daten, dann Ende (zu kurz für die angekündigten 3 GB)."""
        headers = {"Content-Length": str(3 * 1024**3)}
        reads = 0

        def read(self, n):
            self.reads += 1
            if self.reads > 1500:
                return b""
            time.sleep(0.002)
            return b"x" * min(n, 4096)

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    result = UpdateCheckResult(
        status="newer", remote_version="9.9.9",
        bundle_assets=[ReleaseAsset(name="Kira-Setup-v9.9.9.exe", url="https://example.invalid/s", size=1)],
    )
    monkeypatch.setattr(runner, "check_for_update", lambda **kw: result)
    monkeypatch.setattr(runner, "_bundle_dir", lambda: tmp_path)
    monkeypatch.setattr(updater.urllib.request, "urlopen", lambda url, timeout: _Endless())

    class _YesBox(QMessageBox):
        pass

    setattr(_YesBox, "exec", lambda self: QMessageBox.StandardButton.Yes)
    monkeypatch.setattr(runner, "QMessageBox", _YesBox)
    critical: list[str] = []
    monkeypatch.setattr(runner, "light_critical", lambda parent, title, text: critical.append(text))

    runner.run_update_flow(None)
    assert runner._flow_active is True
    thread, _worker, progress = runner._anchor
    time.sleep(0.05)
    progress.canceled.emit()
    deadline = time.monotonic() + 10
    while runner._flow_active and time.monotonic() < deadline:
        QCoreApplication.processEvents()
        time.sleep(0.01)
    assert runner._flow_active is False
    assert runner._anchor is None
    assert critical == ["Abgebrochen."]
    assert thread.isFinished()


def _newer_flow(monkeypatch, tmp_path, *, sums_url=None):
    """Gemeinsamer Aufbau: neuere Version, „Ja“ im Dialog, Setup-Start und Meldungen abgefangen."""
    from PyQt6.QtWidgets import QMessageBox

    from kira.updater import ReleaseAsset, UpdateCheckResult

    result = UpdateCheckResult(
        status="newer", remote_version="9.9.9",
        bundle_assets=[ReleaseAsset(name="Kira-Setup-v9.9.9.exe", url="https://example.invalid/s", size=1)],
        sha256sums_url=sums_url,
    )
    monkeypatch.setattr(runner, "check_for_update", lambda **kw: result)
    monkeypatch.setattr(runner, "_bundle_dir", lambda: tmp_path)
    boxes: list[str] = []

    class _YesBox(QMessageBox):
        def setWindowTitle(self, title):
            boxes.append(title)
            super().setWindowTitle(title)

    setattr(_YesBox, "exec", lambda self: QMessageBox.StandardButton.Yes)
    monkeypatch.setattr(runner, "QMessageBox", _YesBox)
    launched: list[str] = []
    monkeypatch.setattr(runner, "_launch_setup_detached", launched.append)
    critical: list[str] = []
    monkeypatch.setattr(runner, "light_critical", lambda parent, title, text: critical.append(text))
    return boxes, launched, critical


def _wait_until_released(seconds=10.0):
    import time

    from PyQt6.QtCore import QCoreApplication

    deadline = time.monotonic() + seconds
    while runner._flow_active and time.monotonic() < deadline:
        QCoreApplication.processEvents()
        time.sleep(0.01)


def test_cancel_while_the_network_hangs_says_cancelled(monkeypatch, qapp, tmp_path):
    """Abbrechen, während ein Lesevorgang hängt: nach dem Zeitlimit „Abgebrochen.“,
    keine Fehlermeldung, die nach einem Defekt aussieht."""
    import time

    import kira.updater as updater

    boxes, launched, critical = _newer_flow(monkeypatch, tmp_path)

    class _Hanging:
        headers = {"Content-Length": "100000"}
        reads = 0

        def read(self, n):
            self.reads += 1
            if self.reads > 3:
                time.sleep(0.5)
                raise TimeoutError("The read operation timed out")
            return b"x" * 4096

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    monkeypatch.setattr(updater.urllib.request, "urlopen", lambda url, timeout: _Hanging())
    runner.run_update_flow(None)
    _thread, _worker, progress = runner._anchor
    time.sleep(0.1)
    progress.canceled.emit()
    _wait_until_released()
    assert runner._flow_active is False
    assert critical == ["Abgebrochen."]
    assert launched == []


def test_cancel_after_the_worker_finished_shows_no_ready_dialog(monkeypatch, qapp, tmp_path):
    """Abbrechen in den letzten Millisekunden: „succeeded“ liegt schon in der
    Warteschlange, trotzdem kein „Update bereit“ und kein Setup-Start."""
    import io

    import kira.updater as updater

    boxes, launched, critical = _newer_flow(monkeypatch, tmp_path)

    class _Tiny(io.BytesIO):
        headers = {"Content-Length": "1"}

    monkeypatch.setattr(updater.urllib.request, "urlopen", lambda url, timeout: _Tiny(b"x"))
    import time

    runner.run_update_flow(None)
    _thread, _worker, progress = runner._anchor
    # Ohne Ereignisverarbeitung warten: Der Worker lädt das eine Byte und stellt
    # succeeded in die Warteschlange des Hauptthreads. (thread.wait() ginge nicht,
    # der Thread läuft mit seiner Ereignisschleife weiter bis quit().)
    time.sleep(0.5)
    progress.canceled.emit()
    _wait_until_released()
    assert runner._flow_active is False
    assert "Kira - Update bereit" not in boxes
    assert launched == []
    assert critical == ["Abgebrochen."]
