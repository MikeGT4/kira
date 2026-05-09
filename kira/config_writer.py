"""Comment-preserving YAML updater for Kira's config file.

Mike's runtime config has 30+ lines of P0-lessons-learned comments
(why ROG Theta is pinned, why input_gain=2 is the sweet spot, ...).
A naive `yaml.safe_dump` round-trip would wipe all of those.

This module updates only the scalar values for explicit dotted-paths
via line-based replacement. Section-aware so duplicate keys (`model`
appears in both `whisper:` and `styler:`) can be addressed unambiguously.

Limitations:
  - Only flat scalar values (str, int, float, bool, None).
  - Multi-line values (e.g. `initial_prompt:` blocks, `context_modes:`
    dicts) are NOT supported — those should be edited in the raw YAML.
  - Trailing inline comments after a value (e.g. `key: 5  # note`) are
    NOT preserved across the value rewrite. Mike's config keeps its
    notes on lines BEFORE the keys, so this is fine in practice.
  - Adding new keys is not supported here — the section + key must
    already exist (which they always will after first install via the
    bundled config.yaml.template).
"""
from __future__ import annotations
from typing import Any
import yaml


def _format_scalar(value: Any) -> str:
    """Render a Python scalar as the string YAML would emit for it."""
    text = yaml.safe_dump(value, default_flow_style=False).strip()
    if text.endswith("..."):
        # yaml.safe_dump on null emits "null\n...\n" — strip the doc-end marker.
        text = text[:-3].strip()
    return text


def update_scalars(yaml_text: str, updates: dict[str, Any]) -> str:
    """Update <section>.<key> = value pairs in YAML, preserving comments.

    Args:
        yaml_text: full YAML file content.
        updates: flat mapping of dotted-path → new value, e.g.
                 {"audio.input_gain": 5.0, "whisper.language": "de"}.

    Returns:
        Modified YAML string. Lines that aren't being updated stay byte-
        identical (whitespace and comments preserved).

    Raises:
        KeyError: if any requested path is not found in the input YAML.
    """
    grouped: dict[str, dict[str, Any]] = {}
    for dotted, value in updates.items():
        if "." not in dotted:
            raise ValueError(f"expected 'section.key', got {dotted!r}")
        section, key = dotted.split(".", 1)
        grouped.setdefault(section, {})[key] = value

    found: set[str] = set()
    out_lines: list[str] = []
    current_section: str | None = None
    section_indent: int | None = None

    for raw_line in yaml_text.splitlines(keepends=True):
        line = raw_line.rstrip("\n")
        stripped = line.lstrip()
        leading = len(line) - len(stripped)

        if not stripped or stripped.startswith("#"):
            out_lines.append(raw_line)
            continue

        if leading == 0 and ":" in stripped:
            name = stripped.split(":", 1)[0].strip()
            current_section = name if name in grouped else None
            section_indent = None
            out_lines.append(raw_line)
            continue

        if current_section is None:
            out_lines.append(raw_line)
            continue

        if section_indent is None and leading > 0:
            section_indent = leading

        if leading == section_indent and ":" in stripped:
            key_name = stripped.split(":", 1)[0].strip()
            if key_name in grouped[current_section]:
                new_value = grouped[current_section][key_name]
                formatted = _format_scalar(new_value)
                indent = " " * leading
                tail = "\n" if raw_line.endswith("\n") else ""
                out_lines.append(f"{indent}{key_name}: {formatted}{tail}")
                found.add(f"{current_section}.{key_name}")
                continue

        if leading == 0:
            current_section = None
            section_indent = None

        out_lines.append(raw_line)

    missing = set(updates) - found
    if missing:
        # Append-Pfad seit v0.2: User-Configs aus v0.1 haben evtl. keine
        # `hotkey:`- oder `injector:`-Sections (wurden mit Defaults gefahren).
        # Alte update_scalars hat in dem Fall KeyError geworfen — der Save
        # scheiterte und der User sah nur "Config hat unbekanntes Schema".
        # Jetzt: fehlende Section -> am EOF anhaengen, fehlender Key in
        # vorhandener Section -> am Section-Ende anhaengen, mit korrekter
        # 2-Space-Einrueckung. Comments bleiben unangetastet.
        # Section-Detection an der ORIGINAL-Quelle (yaml_text), nicht an
        # out_lines: aktuell sind sie identisch (line-by-line copy mit
        # Value-Rewrite), aber wenn jemand spaeter eine Section-Rewrite-
        # Optimierung addiert, faengt die Append-Logik silent neue Sections
        # auf out_lines auf. code-reviewer 2026-05-09.
        original_lines = yaml_text.splitlines(keepends=True)
        out_lines = _append_missing(out_lines, updates, missing, original_lines)

    return "".join(out_lines)


def _existing_top_sections(lines: list[str]) -> set[str]:
    """Sammle alle Top-Level-Section-Namen aus den Output-Zeilen."""
    found: set[str] = set()
    for raw in lines:
        line = raw.rstrip("\n")
        stripped = line.lstrip()
        if not stripped or stripped.startswith("#"):
            continue
        if ":" in stripped:
            leading = len(line) - len(stripped)
            if leading == 0:
                name = stripped.split(":", 1)[0].strip()
                found.add(name)
    return found


def _append_missing(
    out_lines: list[str],
    updates: dict[str, Any],
    missing: set[str],
    original_lines: list[str],
) -> list[str]:
    """Fehlende Keys/Sections an die richtige Position anhaengen.

    Strategie:
    - Group missing-Pfade nach Section.
    - Pro Section: existiert sie? Dann finde das Section-Ende (naechste
      Top-Level-Section oder EOF) und insert die Keys davor.
    - Section existiert nicht? Append `section:` + alle Keys am EOF.

    `original_lines` = Source-of-truth fuer Section-Existenz-Check
    (statt out_lines was schon mutiert sein koennte).
    """
    by_section: dict[str, dict[str, Any]] = {}
    for path in missing:
        section, key = path.split(".", 1)
        by_section.setdefault(section, {})[key] = updates[path]

    existing_sections = _existing_top_sections(original_lines)

    # Phase 1: Insert in existing sections (am Section-Ende, vor dem
    # Anfang der naechsten Section oder vor leeren Trailing-Zeilen).
    sections_to_insert = {
        s: kvs for s, kvs in by_section.items() if s in existing_sections
    }
    if sections_to_insert:
        out_lines = _insert_into_sections(out_lines, sections_to_insert)

    # Phase 2: Append new sections am EOF.
    new_sections = {
        s: kvs for s, kvs in by_section.items() if s not in existing_sections
    }
    if new_sections:
        # Sicherstellen dass das letzte Char ein newline ist.
        if out_lines and not out_lines[-1].endswith("\n"):
            out_lines[-1] = out_lines[-1] + "\n"
        for section, kvs in new_sections.items():
            out_lines.append(f"\n{section}:\n")
            for key, value in kvs.items():
                out_lines.append(f"  {key}: {_format_scalar(value)}\n")

    return out_lines


def _insert_into_sections(
    out_lines: list[str],
    sections_to_insert: dict[str, dict[str, Any]],
) -> list[str]:
    """Insert neue Keys am Ende der jeweiligen Section.

    Section-Ende = letzte nicht-leere Zeile bevor die naechste Top-Level-
    Section beginnt (oder das EOF wenn die Section am Ende der Datei steht).
    """
    # Pass 1: bestimme Section-Spans.
    section_spans: dict[str, tuple[int, int]] = {}  # name -> (start_idx, end_idx)
    current_section: str | None = None
    section_start = -1
    for i, raw in enumerate(out_lines):
        line = raw.rstrip("\n")
        stripped = line.lstrip()
        if not stripped or stripped.startswith("#"):
            continue
        if ":" in stripped:
            leading = len(line) - len(stripped)
            if leading == 0:
                if current_section is not None:
                    section_spans[current_section] = (section_start, i)
                name = stripped.split(":", 1)[0].strip()
                if name in sections_to_insert:
                    current_section = name
                    section_start = i
                else:
                    current_section = None
                    section_start = -1
    if current_section is not None:
        section_spans[current_section] = (section_start, len(out_lines))

    # Pass 2: rueckwaerts iterieren damit Insert-Indices nicht verschieben.
    inserts: list[tuple[int, list[str]]] = []
    for section, (start, end) in section_spans.items():
        # Insert-Punkt = nach der letzten nicht-leeren Zeile innerhalb [start, end)
        insert_at = end
        while insert_at > start + 1 and out_lines[insert_at - 1].strip() == "":
            insert_at -= 1
        # Build insert-Lines
        new_lines: list[str] = []
        for key, value in sections_to_insert[section].items():
            new_lines.append(f"  {key}: {_format_scalar(value)}\n")
        inserts.append((insert_at, new_lines))

    # Apply rueckwaerts
    inserts.sort(key=lambda t: t[0], reverse=True)
    for idx, lines_to_add in inserts:
        out_lines = out_lines[:idx] + lines_to_add + out_lines[idx:]
    return out_lines
