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


def test_cancel_during_download_releases_the_flag(monkeypatch, qapp, tmp_path):
    """„Abbrechen“ beendet den Download am nächsten Block, nicht erst nach 3 GB."""
    import time

    from PyQt6.QtCore import QCoreApplication
    from PyQt6.QtWidgets import QMessageBox

    import kira.updater as updater
    from kira.updater import ReleaseAsset, UpdateCheckResult

    class _Endless:
        headers = {"Content-Length": str(3 * 1024**3)}

        def read(self, n):
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
    thread, worker, _progress = runner._anchor
    time.sleep(0.05)
    worker.cancel()
    deadline = time.monotonic() + 5
    while runner._flow_active and time.monotonic() < deadline:
        QCoreApplication.processEvents()
        time.sleep(0.01)
    assert runner._flow_active is False
    assert runner._anchor is None
    assert critical == ["Abgebrochen."]
    assert thread.isFinished()
