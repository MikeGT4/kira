"""Resource-Path-Resolver fuer Kira.

UI-Module brauchen alle den gleichen ``assets/``-Pfad. Vorher hatte jedes
Modul ``Path(__file__).resolve().parent.parent.parent / "assets"`` --
das funktioniert im Source-Tree (``<repo-root>/assets/``) aber NICHT im
Wheel-Install-Mode, wo ``parent.parent.parent`` zu
``site-packages/`` resolvt (``site-packages/assets/`` existiert nicht).

``pyproject.toml`` packt assets/ + prompts/ als ``kira/_assets/`` und
``kira/_prompts/`` ins wheel via ``[tool.hatch.build.targets.wheel.
force-include]``. Hier suchen wir zuerst dort, fall-back auf den
Source-Tree-Layout. Saubere zentrale Quelle, ein Helper, alle UI-
Module gehen darueber.
"""
from __future__ import annotations

from pathlib import Path

_PKG_DIR = Path(__file__).resolve().parent  # site-packages/kira/ oder repo/kira/


def assets_dir() -> Path:
    """Pfad zum assets-Verzeichnis. Wheel-Install -> ``kira/_assets/``,
    Source/Editable -> ``<repo-root>/assets/``."""
    wheel_assets = _PKG_DIR / "_assets"
    if wheel_assets.exists():
        return wheel_assets
    return _PKG_DIR.parent / "assets"


def prompts_dir() -> Path:
    """Pfad zum prompts-Verzeichnis. Wheel-Install -> ``kira/_prompts/``,
    Source/Editable -> ``<repo-root>/prompts/``."""
    wheel_prompts = _PKG_DIR / "_prompts"
    if wheel_prompts.exists():
        return wheel_prompts
    return _PKG_DIR.parent / "prompts"
