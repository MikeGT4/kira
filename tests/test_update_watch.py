# © 2026 Mike Pollow, Digitalroots. Alle Rechte vorbehalten.
"""Tests für kira.update_watch: wiederholte Update-Prüfung mit Tray-Meldung."""
from __future__ import annotations

import threading
from types import SimpleNamespace

from kira.update_watch import UpdateWatch, run_periodically, start_watch


class _Recorder:
    def __init__(self, results, declined=()):
        self.results = list(results)
        self.declined = set(declined)
        self.available: list[str] = []
        self.notified: list[str] = []
        self.checks = 0

    def check(self):
        self.checks += 1
        return self.results.pop(0) if self.results else SimpleNamespace(status="current")

    def watch(self) -> UpdateWatch:
        return UpdateWatch(
            check=self.check,
            is_declined=lambda v: v in self.declined,
            set_available=self.available.append,
            notify=self.notified.append,
        )


def _newer(version: str):
    return SimpleNamespace(status="newer", remote_version=version)


def test_newer_version_sets_menu_and_notifies_once():
    rec = _Recorder([_newer("0.4.2"), _newer("0.4.2")])
    w = rec.watch()
    assert w.run_once() == "0.4.2"
    assert w.run_once() == "0.4.2"
    assert rec.available == ["0.4.2", "0.4.2"]
    assert rec.notified == ["0.4.2"]


def test_next_version_notifies_again():
    rec = _Recorder([_newer("0.4.2"), _newer("0.4.3")])
    w = rec.watch()
    w.run_once()
    w.run_once()
    assert rec.notified == ["0.4.2", "0.4.3"]


def test_declined_version_shows_menu_but_no_notification():
    rec = _Recorder([_newer("0.4.2")], declined={"0.4.2"})
    rec.watch().run_once()
    assert rec.available == ["0.4.2"]
    assert rec.notified == []


def test_start_dialog_counts_as_notification():
    rec = _Recorder([_newer("0.4.2")])
    w = rec.watch()
    w.mark_notified("0.4.2")
    w.run_once()
    assert rec.notified == []
    assert rec.available == ["0.4.2"]


def test_failed_check_keeps_the_known_state():
    rec = _Recorder([_newer("0.4.2"), SimpleNamespace(status="failed")])
    w = rec.watch()
    w.run_once()
    assert w.run_once() is None
    assert rec.available == ["0.4.2"]
    assert rec.notified == ["0.4.2"]


def test_nothing_to_install_clears_the_menu_entry():
    """Release zurückgezogen, ohne Setup-Dateien oder lokal neuer: Eintrag weg."""
    for status in ("current", "no_asset", "local_newer"):
        rec = _Recorder([_newer("0.4.2"), SimpleNamespace(status=status)])
        w = rec.watch()
        w.run_once()
        assert w.run_once() is None
        assert rec.available == ["0.4.2", None], status
        assert rec.notified == ["0.4.2"]


def test_start_result_hands_over_to_the_repeated_check():
    """Startdialog hat gefragt: Menü steht, die Wiederholprüfung meldet dieselbe Version nicht."""
    rec = _Recorder([_newer("0.4.2")])
    w = rec.watch()
    assert w.start_result(_newer("0.4.2")) == "0.4.2"
    assert rec.available == ["0.4.2"]
    w.run_once()
    assert rec.notified == []


def test_start_result_for_declined_version_sets_menu_without_prompt():
    rec = _Recorder([], declined={"0.4.2"})
    w = rec.watch()
    assert w.start_result(_newer("0.4.2")) is None
    assert rec.available == ["0.4.2"]
    assert rec.notified == []


def test_start_result_without_newer_version_does_nothing():
    rec = _Recorder([])
    w = rec.watch()
    for status in ("current", "failed", "no_asset", "local_newer"):
        assert w.start_result(SimpleNamespace(status=status)) is None
    assert rec.available == [] and rec.notified == []


def test_start_watch_respects_switch_and_interval():
    rec = _Recorder([])
    assert start_watch(rec.watch(), enabled=False, interval_h=6.0) is None
    assert start_watch(rec.watch(), enabled=True, interval_h=0.0) is None
    stop = threading.Event()
    thread = start_watch(rec.watch(), enabled=True, interval_h=6.0, stop=stop)
    assert thread is not None and thread.is_alive() and thread.daemon
    stop.set()
    thread.join(timeout=5)
    assert not thread.is_alive()
    assert rec.checks == 0  # erste Prüfung erst nach dem Intervall, nicht beim Start


def test_periodic_loop_checks_until_stopped_and_survives_errors():
    calls = {"n": 0}
    stop = threading.Event()

    def check():
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("Netz weg")
        if calls["n"] >= 3:
            stop.set()
        return SimpleNamespace(status="current")

    w = UpdateWatch(check=check, is_declined=lambda v: False,
                    set_available=lambda v: None, notify=lambda v: None)
    worker = threading.Thread(target=run_periodically, args=(w, 0.01, stop))
    worker.start()
    worker.join(timeout=5)
    assert not worker.is_alive()
    assert calls["n"] >= 3
