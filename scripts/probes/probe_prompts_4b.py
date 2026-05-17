"""Smoke-Test: alle Prompts mit inline-Beispielen gegen gemma3:4b.

Reproduziert Mike's v0.2.2-Bug-Pattern (4B fixiert sich auf inline-
Beispiele) und verifiziert, dass das Härten in `terminal.md`,
`clean.md` und `email_formal.md` greift. Aufruf:

    py -3.12 scripts\\probes\\probe_prompts_4b.py
"""
from pathlib import Path

import ollama

PROMPTS_DIR = Path(__file__).resolve().parents[2] / "prompts"

# (mode, [(input, regex_must_not_match_in_output), ...])
CASES = {
    "terminal": [
        ("Okay, das heisst, wir muessen jetzt auf der PBX schauen", "^git status$"),
        ("Heisst das, wir schauen zuerst mal, ob die 880 vergeben ist", "^git status$"),
        ("Hallo, kannst du mir helfen", "^git status$"),
        ("get status", None),  # echte Korrektur erwartet, kein Fail-Check
        ("ssh root att 192 168 1 1", None),
    ],
    "clean": [
        ("Also schau mal kurz, da ist halt was kaputt", "^ich denke"),
        ("Aehm, das ist eigentlich ganz easy", "^ich denke"),
        ("Ja naja, wir muessen das jetzt machen", "^ich denke"),
        ("ich, ich, ich denke das passt", None),  # echte Korrektur ok
    ],
    "email_formal": [
        ("Lass uns bitte morgen ein Update geben zu dem Befund", "^koennten Sie"),
        ("Der Termin am Freitag passt mir gut", "^koennten Sie"),
        ("Vielen Dank fuer die schnelle Rueckmeldung", "^koennten Sie"),
        ("kannst du mir das schicken", None),  # echte Du-zu-Sie ok
    ],
}

import re

print("Probe gemma3:4b gegen Prompts mit inline-Beispielen\n" + "=" * 70)
total_bug = 0
total = 0
for mode, cases in CASES.items():
    prompt_tpl = (PROMPTS_DIR / f"{mode}.md").read_text(encoding="utf-8")
    print(f"\n--- {mode} ---")
    for inp, bad_regex in cases:
        total += 1
        prompt = prompt_tpl.format(text=inp)
        try:
            resp = ollama.chat(
                model="gemma3:4b",
                messages=[{"role": "user", "content": prompt}],
                options={"temperature": 0.2},
                keep_alive="5m",
            )
            out = resp["message"]["content"].strip()
        except Exception as e:
            print(f"  [ERR] {inp[:50]!r}: {e}")
            continue
        is_bug = bool(bad_regex and re.search(bad_regex, out, re.IGNORECASE))
        if is_bug:
            total_bug += 1
            print(f"  [BUG] IN : {inp[:60]!r}")
            print(f"        OUT: {out[:80]!r}")
        else:
            print(f"  [OK ] IN : {inp[:50]!r:55} OUT: {out[:50]!r}")

print("\n" + "=" * 70)
print(f"Buggy outputs: {total_bug} / {total}")
