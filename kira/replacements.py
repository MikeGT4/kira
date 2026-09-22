"""Post-Whisper text replacements.

Whisper transkribiert Eigennamen, Fachbegriffe und Produktnamen oft
falsch (z.B. "auf kuh bernetes" statt "auf Kubernetes"). Diese
deterministische Find-Replace-Map korrigiert solche Fälle nach der
Transkription und VOR dem Polish, sodass das LLM nicht versucht den
falschen Namen "weichzuspülen".

Map-Format (whisper.replacements in config.yaml):

    whisper:
      replacements:
        "kuh bernetes": "Kubernetes"
        "vieh es code": "VS Code"

Seit v0.4.0 gelten dieselben Regeln wie für gelernte Ersetzungen:
- nur ganze Wörter (Umlaute und ß zählen als Buchstaben), Groß/klein egal
- längere Schlüssel zuerst, damit „vieh es code" vor „code" greift
- ein Durchgang: das Ergebnis einer Ersetzung wird nicht erneut ersetzt
- der Ersetzungstext wird wörtlich eingefügt
- ``on_replace(gefunden, ersetzt)`` meldet jeden Treffer (für das Log)
"""
from __future__ import annotations
import re
from collections.abc import Callable


def apply(
    text: str,
    mapping: dict[str, str],
    on_replace: Callable[[str, str], None] | None = None,
) -> str:
    """Ersetzungen in einem Durchgang anwenden (s. Moduldoku)."""
    if not text or not mapping:
        return text
    keys = sorted((k for k in mapping if k and k.strip()), key=len, reverse=True)
    if not keys:
        return text
    lookup = {k.lower(): mapping[k] for k in keys}
    pattern = re.compile(
        r"(?<!\w)(?:" + "|".join(re.escape(k) for k in keys) + r")(?!\w)",
        re.IGNORECASE,
    )

    def _substitute(match: re.Match) -> str:
        found = match.group(0)
        replacement = lookup.get(found.lower(), found)
        if on_replace is not None:
            on_replace(found, replacement)
        return replacement

    return pattern.sub(_substitute, text)
