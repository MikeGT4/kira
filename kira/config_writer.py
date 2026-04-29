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
        raise KeyError(f"path(s) not found in YAML: {sorted(missing)}")

    return "".join(out_lines)
