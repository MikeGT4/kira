# © 2026 Mike Pollow, Digitalroots. Alle Rechte vorbehalten.
"""Tests für scripts/build_wordlist.py, mit einer wordfreq-Attrappe."""
from __future__ import annotations
import importlib.util
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _load_script(monkeypatch, zipf):
    fake = types.ModuleType("wordfreq")
    fake.iter_wordlist = lambda lang, wordlist: iter(sorted(zipf, key=zipf.get, reverse=True))
    fake.zipf_frequency = lambda word, lang, wordlist: zipf[word]
    monkeypatch.setitem(sys.modules, "wordfreq", fake)
    spec = importlib.util.spec_from_file_location("build_wordlist", ROOT / "scripts" / "build_wordlist.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_default_min_zipf_is_the_value_of_the_shipped_list(tmp_path, monkeypatch):
    script = _load_script(monkeypatch, {"haus": 5.1, "nass": 2.6, "selten": 2.4})
    out = tmp_path / "wordlist-de.txt"
    monkeypatch.setattr(sys, "argv", ["build_wordlist.py", "--out", str(out)])
    script.main()
    lines = out.read_text(encoding="utf-8").splitlines()
    assert "# Zipf ab 2.5" in lines
    assert [line for line in lines if not line.startswith("#")] == ["haus", "nass"]
    shipped = (ROOT / "assets" / "wordlist-de.txt").read_text(encoding="utf-8").splitlines()
    assert "# Zipf ab 2.5" in shipped
