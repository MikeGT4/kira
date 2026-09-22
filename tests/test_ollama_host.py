# © 2026 Mike Pollow, Digitalroots. Alle Rechte vorbehalten.
"""Tests für kira.ollama_host.client_host()."""
from __future__ import annotations
import pytest
from kira.ollama_host import client_host


@pytest.mark.parametrize("value, expected", [
    ("0.0.0.0:11434", "http://127.0.0.1:11434"),
    ("0.0.0.0", "http://127.0.0.1:11434"),
    ("http://0.0.0.0:11500", "http://127.0.0.1:11500"),
    ("[::]:11434", "http://127.0.0.1:11434"),
    ("::", "http://127.0.0.1:11434"),
    (":11434", "http://127.0.0.1:11434"),
])
def test_bind_all_addresses_map_to_loopback(value, expected):
    assert client_host({"OLLAMA_HOST": value}) == expected


@pytest.mark.parametrize("value", [
    "", "   ", "127.0.0.1:11434", "10.0.0.5:11434", "localhost",
    "http://ollama.example:11434",
])
def test_other_values_are_left_to_the_library(value):
    assert client_host({"OLLAMA_HOST": value}) is None


def test_missing_variable_returns_none():
    assert client_host({}) is None


def test_reads_process_environment_by_default(monkeypatch):
    monkeypatch.setenv("OLLAMA_HOST", "0.0.0.0:11434")
    assert client_host() == "http://127.0.0.1:11434"
