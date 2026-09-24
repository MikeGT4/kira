"""Tests für kira.ollama_env — persistentes Ollama-VRAM-Tuning via HKCU\\Environment.

winreg ist Windows-only und in der CI/WSL nicht importierbar. Das Modul kapselt
daher allen winreg-I/O in ``_read_user_env`` / ``_write_user_env``; die Tests
mocken diese beiden + ``sys.platform`` und fassen winreg nie an.
"""
from __future__ import annotations

import kira.ollama_env as oe


# ---- TUNING_ENV ------------------------------------------------------------

def test_tuning_env_disables_llama_server_prompt_cache():
    # Ollamas Runner llama-server hält sonst bis 8 GiB Prompt-Cache im RAM.
    assert oe.TUNING_ENV["LLAMA_ARG_CACHE_RAM"] == "0"


# ---- pending_changes (pure) ------------------------------------------------

def test_pending_changes_empty_env_needs_all():
    assert oe.pending_changes({}) == oe.TUNING_ENV


def test_pending_changes_fully_set_needs_nothing():
    assert oe.pending_changes(dict(oe.TUNING_ENV)) == {}


def test_pending_changes_wrong_value_is_pending():
    current = dict(oe.TUNING_ENV)
    current["OLLAMA_KV_CACHE_TYPE"] = "f16"  # falscher Wert
    assert oe.pending_changes(current) == {
        "OLLAMA_KV_CACHE_TYPE": oe.TUNING_ENV["OLLAMA_KV_CACHE_TYPE"]
    }


def test_pending_changes_partial_only_missing():
    current = dict(oe.TUNING_ENV)
    del current["OLLAMA_KV_CACHE_TYPE"]  # einer fehlt, die übrigen stimmen
    assert oe.pending_changes(current) == {
        "OLLAMA_KV_CACHE_TYPE": oe.TUNING_ENV["OLLAMA_KV_CACHE_TYPE"]
    }


def test_pending_changes_ignores_unrelated_keys():
    current = {"PATH": "C:\\", **oe.TUNING_ENV}
    assert oe.pending_changes(current) == {}


# ---- apply_tuning_env (orchestration, I/O gemockt) -------------------------

def test_apply_noop_on_non_windows(monkeypatch):
    monkeypatch.setattr(oe.sys, "platform", "linux")
    writes: list[tuple[str, str]] = []
    monkeypatch.setattr(oe, "_write_user_env", lambda n, v: writes.append((n, v)))
    monkeypatch.setattr(oe, "_read_user_env", lambda: {})
    assert oe.apply_tuning_env() == []
    assert writes == []  # auf Nicht-Windows wird nie geschrieben


def test_apply_writes_all_when_unset(monkeypatch):
    monkeypatch.setattr(oe.sys, "platform", "win32")
    monkeypatch.setattr(oe, "_read_user_env", lambda: {})
    writes: dict[str, str] = {}
    monkeypatch.setattr(oe, "_write_user_env", lambda n, v: writes.__setitem__(n, v))
    written = oe.apply_tuning_env()
    assert set(written) == set(oe.TUNING_ENV)
    assert writes == oe.TUNING_ENV


def test_apply_noop_when_already_set(monkeypatch):
    monkeypatch.setattr(oe.sys, "platform", "win32")
    monkeypatch.setattr(oe, "_read_user_env", lambda: dict(oe.TUNING_ENV))
    writes: list[str] = []
    monkeypatch.setattr(oe, "_write_user_env", lambda n, v: writes.append(n))
    assert oe.apply_tuning_env() == []
    assert writes == []  # nichts schreiben wenn schon korrekt → kein Neustart-Bedarf


def test_apply_writes_only_missing(monkeypatch):
    monkeypatch.setattr(oe.sys, "platform", "win32")
    current = dict(oe.TUNING_ENV)
    del current["OLLAMA_KV_CACHE_TYPE"]
    monkeypatch.setattr(oe, "_read_user_env", lambda: current)
    writes: dict[str, str] = {}
    monkeypatch.setattr(oe, "_write_user_env", lambda n, v: writes.__setitem__(n, v))
    written = oe.apply_tuning_env()
    assert written == ["OLLAMA_KV_CACHE_TYPE"]
    assert writes == {"OLLAMA_KV_CACHE_TYPE": "q8_0"}


def test_apply_returns_empty_when_read_fails(monkeypatch):
    monkeypatch.setattr(oe.sys, "platform", "win32")
    def boom() -> dict[str, str]:
        raise OSError("registry locked")
    monkeypatch.setattr(oe, "_read_user_env", boom)
    writes: list[str] = []
    monkeypatch.setattr(oe, "_write_user_env", lambda n, v: writes.append(n))
    assert oe.apply_tuning_env() == []  # Lesefehler → sauberer No-op, kein Crash
    assert writes == []


def test_apply_skips_key_when_write_fails(monkeypatch):
    """Ein einzelner Schreibfehler darf die übrigen Keys nicht verhindern und
    nicht faelschlich als 'gesetzt' melden."""
    monkeypatch.setattr(oe.sys, "platform", "win32")
    monkeypatch.setattr(oe, "_read_user_env", lambda: {})
    def selective_write(name: str, value: str) -> None:
        if name == "OLLAMA_FLASH_ATTENTION":
            raise OSError("access denied")
    monkeypatch.setattr(oe, "_write_user_env", selective_write)
    written = oe.apply_tuning_env()
    # nur die erfolgreichen Keys
    assert written == [k for k in oe.TUNING_ENV if k != "OLLAMA_FLASH_ATTENTION"]
