"""Tests for Windows Ctrl+V injector. Windows-only."""
from __future__ import annotations
import sys
import time
import pytest

if sys.platform != "win32":
    pytest.skip("windows-only tests", allow_module_level=True)


def test_inject_empty_is_noop(monkeypatch):
    from kira import injector_win

    copy_calls = {"n": 0}
    monkeypatch.setattr(injector_win.pyperclip, "paste", lambda: "saved")
    monkeypatch.setattr(
        injector_win.pyperclip, "copy",
        lambda t: copy_calls.update(n=copy_calls["n"] + 1),
    )
    monkeypatch.setattr(injector_win.keyboard, "send", lambda k: None)

    injector_win.Injector().inject("")
    assert copy_calls["n"] == 0


def test_inject_sends_ctrl_v(monkeypatch):
    from kira import injector_win

    sent = {"val": None}
    monkeypatch.setattr(injector_win.pyperclip, "paste", lambda: "saved")
    monkeypatch.setattr(injector_win.pyperclip, "copy", lambda t: None)
    monkeypatch.setattr(
        injector_win.keyboard, "send",
        lambda k: sent.update(val=k),
    )

    injector_win.Injector().inject("hello")
    assert sent["val"] == "ctrl+v"


def test_inject_sets_clipboard_to_text(monkeypatch):
    from kira import injector_win

    copies = []
    monkeypatch.setattr(injector_win.pyperclip, "paste", lambda: "saved")
    monkeypatch.setattr(injector_win.pyperclip, "copy", lambda t: copies.append(t))
    monkeypatch.setattr(injector_win.keyboard, "send", lambda k: None)

    injector_win.Injector().inject("hello world")
    assert copies[0] == "hello world"


def test_inject_restores_clipboard_after_delay(monkeypatch):
    """Restore-timer writes the original clipboard content back."""
    from kira import injector_win

    copies = []
    monkeypatch.setattr(injector_win.pyperclip, "paste", lambda: "ORIGINAL")
    monkeypatch.setattr(injector_win.pyperclip, "copy", lambda t: copies.append(t))
    monkeypatch.setattr(injector_win.keyboard, "send", lambda k: None)

    inj = injector_win.Injector(restore_after_ms=10)
    inj.inject("NEW")
    time.sleep(0.05)  # wait for timer
    assert copies[0] == "NEW"
    assert copies[-1] == "ORIGINAL"


def test_inject_survives_paste_exception(monkeypatch):
    """If pyperclip.paste raises, fall back to empty 'saved' and still inject."""
    from kira import injector_win

    def raising_paste():
        raise RuntimeError("clipboard locked")

    copies = []
    monkeypatch.setattr(injector_win.pyperclip, "paste", raising_paste)
    monkeypatch.setattr(injector_win.pyperclip, "copy", lambda t: copies.append(t))
    monkeypatch.setattr(injector_win.keyboard, "send", lambda k: None)

    inj = injector_win.Injector(restore_after_ms=10)
    inj.inject("NEW")
    time.sleep(0.05)
    assert copies[0] == "NEW"


def test_short_text_uses_base_restore_delay():
    """Texts ≤80 chars use the configured base delay verbatim."""
    from kira import injector_win

    inj = injector_win.Injector(restore_after_ms=500)
    assert inj._effective_restore_ms(0) == 500
    assert inj._effective_restore_ms(1) == 500
    assert inj._effective_restore_ms(80) == 500


def test_long_text_extends_restore_delay():
    """Texts >80 chars get an adaptive delay so slow editors finish the paste."""
    from kira import injector_win

    inj = injector_win.Injector(restore_after_ms=500)
    # 463 chars (Mike's truncated dictation): 100 + 463*2 = 1026 ms
    assert inj._effective_restore_ms(463) == 1026
    # 200 chars: 100 + 200*2 = 500 → still floored at base 500
    assert inj._effective_restore_ms(200) == 500
    # 250 chars: 100 + 250*2 = 600 → adaptive wins
    assert inj._effective_restore_ms(250) == 600


def test_long_text_respects_higher_base():
    """If user configures a higher base delay, adaptive only adds when needed."""
    from kira import injector_win

    inj = injector_win.Injector(restore_after_ms=2000)
    assert inj._effective_restore_ms(80) == 2000
    assert inj._effective_restore_ms(500) == 2000   # base wins
    assert inj._effective_restore_ms(2000) == 4100  # 100 + 2000*2 wins


def test_default_restore_after_ms_is_500():
    """Default constructor argument is 500 ms — long-text-paste safety."""
    from kira import injector_win

    inj = injector_win.Injector()
    assert inj._restore_after_ms == 500


def test_stale_restore_timer_does_not_clobber_newer_injection(monkeypatch):
    """Zwei Diktate kurz nacheinander: Vorher restaurierte Timer1 nach
    Ablauf stur sein "saved" — je nach Timing landete ORIGINAL mitten im
    zweiten Paste-Fenster oder text1 als Endzustand im Clipboard. Neu:
    Nur der NEUESTE Timer restauriert, und zwar das aelteste noch nicht
    restaurierte User-Original (die Kette text1->text2 darf das echte
    ORIGINAL nicht verlieren)."""
    from kira import injector_win

    # Restore-Timer FRUEHERER Tests (Default 500 ms) leben ueber die
    # Testgrenze weiter und schreiben via Laufzeit-Lookup von
    # pyperclip.copy durch UNSER monkeypatch — erst ausklingen lassen.
    time.sleep(0.6)

    clipboard = {"val": "ORIGINAL"}
    monkeypatch.setattr(injector_win.pyperclip, "paste", lambda: clipboard["val"])
    monkeypatch.setattr(
        injector_win.pyperclip, "copy", lambda t: clipboard.update(val=t),
    )
    monkeypatch.setattr(injector_win.keyboard, "send", lambda k: None)

    inj = injector_win.Injector(restore_after_ms=150)
    inj.inject("text1")            # merkt sich ORIGINAL
    time.sleep(0.02)
    inj.inject("text2")            # Kette laeuft — Original bleibt ORIGINAL

    time.sleep(0.5)                # beide Timer-Deadlines verstreichen lassen

    assert clipboard["val"] == "ORIGINAL"


def test_single_injection_restore_unaffected_by_generation_guard(monkeypatch):
    """Regression-Guard: Der Normalfall (ein Diktat, Timer feuert, danach
    naechstes Diktat NACH dem Restore) muss weiter beide Originale sauber
    restaurieren — der Guard darf nur ECHTE Ueberlappung unterdruecken."""
    from kira import injector_win

    clipboard = {"val": "ORIGINAL-A"}
    monkeypatch.setattr(injector_win.pyperclip, "paste", lambda: clipboard["val"])
    monkeypatch.setattr(
        injector_win.pyperclip, "copy", lambda t: clipboard.update(val=t),
    )
    monkeypatch.setattr(injector_win.keyboard, "send", lambda k: None)

    inj = injector_win.Injector(restore_after_ms=80)
    inj.inject("text1")
    time.sleep(0.4)                # Timer1 restauriert ORIGINAL-A
    assert clipboard["val"] == "ORIGINAL-A"

    clipboard["val"] = "ORIGINAL-B"
    inj.inject("text2")
    time.sleep(0.4)                # Timer2 restauriert ORIGINAL-B
    assert clipboard["val"] == "ORIGINAL-B"
