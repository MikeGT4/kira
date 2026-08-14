"""Post-Whisper text replacements.

Whisper transkribiert Eigennamen, Fachbegriffe und Produktnamen oft
falsch (z.B. "auf kuh bernetes" statt "auf Kubernetes"). Diese
deterministische Find-Replace-Map korrigiert solche Faelle nach der
Transkription und VOR dem Polish, sodass das LLM nicht versucht den
falschen Namen "weichzuspuelen".

Map-Format (whisper.replacements in config.yaml):

    whisper:
      replacements:
        "kuh bernetes": "Kubernetes"
        "vieh es code": "VS Code"

Match ist case-insensitive Substring. Insertion-Order wird respektiert:
spaetere Keys sehen das Output frueherer Replacements.
"""
from __future__ import annotations
import re


def apply(text: str, mapping: dict[str, str]) -> str:
    """Apply Find/Replace-Map auf Whisper-Output.

    - Empty text or empty mapping → unchanged
    - Empty find-keys → skipped (defensive gegen leere YAML-Eintraege)
    - Case-insensitive Substring-Match via re.escape() — Sonderzeichen
      im Key werden literal behandelt, kein Regex-Footgun.
    - Replacement-String wird 1:1 eingefuegt (Casing wie konfiguriert).
    """
    if not text or not mapping:
        return text
    out = text
    for find, replace in mapping.items():
        if not find:
            continue
        out = re.sub(re.escape(find), replace, out, flags=re.IGNORECASE)
    return out
