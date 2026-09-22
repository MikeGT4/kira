# © 2026 Mike Pollow, Digitalroots. Alle Rechte vorbehalten.
"""Erzeugt assets/wordlist-de.txt aus wordfreq (Deutsch).

Einmal pro Release in einer Bau-Umgebung mit ``pip install wordfreq==3.1.1``:
    python scripts/build_wordlist.py --min-zipf 3.0
Zur Laufzeit braucht Kira wordfreq nicht.
"""
from __future__ import annotations
import argparse
import re
from pathlib import Path
from wordfreq import iter_wordlist, zipf_frequency

HEADER = (
    "# Deutsche Wortliste für Kira, erzeugt aus wordfreq (Robyn Speer u. a.).",
    "# Daten: Creative Commons Attribution-ShareAlike 4.0,",
    "# https://creativecommons.org/licenses/by-sa/4.0/",
    "# Quelle: https://github.com/rspeer/wordfreq",
)
_GERMAN_WORD = re.compile(r"[a-zäöüß]+")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--min-zipf", type=float, required=True)
    parser.add_argument(
        "--out", type=Path,
        default=Path(__file__).resolve().parent.parent / "assets" / "wordlist-de.txt",
    )
    args = parser.parse_args()
    words: set[str] = set()
    for word in iter_wordlist("de", wordlist="large"):
        if zipf_frequency(word, "de", wordlist="large") < args.min_zipf:
            break
        if _GERMAN_WORD.fullmatch(word):
            words.add(word)
    lines = [*HEADER, f"# Zipf ab {args.min_zipf}", *sorted(words)]
    args.out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"{len(words)} Wörter nach {args.out}")


if __name__ == "__main__":
    main()
