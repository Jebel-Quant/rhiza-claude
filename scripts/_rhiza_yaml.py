#!/usr/bin/env python3
"""Minimal, dependency-free YAML reader/writer for rhiza template files.

The bundled scripts (`status.py`, `validate.py`, `sync.py`, ...) are stdlib-only
ports of the `rhiza` CLI's commands, so they can run inside this plugin without
the CLI (or PyYAML) installed. They read `.rhiza/template.yml`,
`.rhiza/template.lock`, and the upstream `.rhiza/template-bundles.yml`, and
`sync.py` writes `.rhiza/template.lock`.

`load_yaml` parses the subset of YAML those files use: nested mappings, block
and inline (`[a, b]`) sequences, inline (`{source: x, dest: y}`) mappings, block
scalars (`key: |`), quoted/bare scalars, and `#` comments. When PyYAML *is*
importable we defer to it (same "stdlib works, third-party enhances" posture as
stats.py's tomllib/tomli fallback), so hand-authored configs using constructs
this parser doesn't cover still load correctly.

`dump_yaml` emits the flat top-level scalar/sequence subset the lock file uses,
matching PyYAML's `default_flow_style=False, sort_keys=False` layout (zero-indent
list items, `[]` for empty lists, single-quoted values where a bare token would
be re-read as a non-string) so a lock this module writes round-trips through all
three readers (this parser, PyYAML, and the rhiza CLI).

The built-in parser deliberately does NOT handle anchors, aliases, or multiple
documents — none of which appear in rhiza template files.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

try:  # pragma: no cover - exercised only when PyYAML is installed
    import yaml as _pyyaml
except ModuleNotFoundError:  # pragma: no cover
    _pyyaml = None

# YAML 1.1 timestamp shapes PyYAML resolves to datetime; we must quote these on
# output (and never coerce them on input) to keep values like `synced_at` strings.
_TIMESTAMP = re.compile(
    r"^\d{4}-\d{1,2}-\d{1,2}([Tt ]\d{1,2}:\d{1,2}:\d{1,2}(\.\d+)?([Zz]|[+-]\d{1,2}(:\d{1,2})?)?)?$"
)
_BLOCK_SCALAR_INDICATORS = {"|", ">", "|-", ">-", "|+", ">+"}


def load_yaml(path: Path) -> dict[str, Any]:
    """Load a rhiza template/lock/bundles file into a plain dict.

    Prefers PyYAML when available; otherwise falls back to the built-in
    subset parser. A file whose top level is empty yields ``{}``. Raises
    ``ValueError`` when the document's top level is not a mapping, mirroring
    how the CLI treats a malformed config.
    """
    text = path.read_text(errors="ignore")
    if _pyyaml is not None:
        data = _pyyaml.safe_load(text)
        if data is None:
            return {}
        if not isinstance(data, dict):
            raise ValueError("top-level YAML is not a mapping")
        return data
    return _parse_subset(text)


def dump_yaml(data: dict[str, Any], path: Path) -> None:
    """Write *data* to *path* as YAML, matching PyYAML's block layout.

    Only the flat subset the lock file uses is supported: top-level keys whose
    values are scalars, ``None``, or lists of scalars. Nested mappings are not
    emitted (the lock has none). The output re-reads identically via this
    parser, PyYAML, and the rhiza CLI.
    """
    path.write_text(dumps_yaml(data))


def dumps_yaml(data: dict[str, Any]) -> str:
    """Serialise *data* to a YAML string (see :func:`dump_yaml`)."""
    lines: list[str] = []
    for key, value in data.items():
        if isinstance(value, list):
            if not value:
                lines.append(f"{key}: []")
            else:
                lines.append(f"{key}:")
                lines.extend(f"- {_emit_scalar(item)}" for item in value)
        else:
            lines.append(f"{key}: {_emit_scalar(value)}")
    return "\n".join(lines) + "\n" if lines else ""


def _emit_scalar(value: Any) -> str:
    """Render a scalar for output, quoting when a bare token would misparse."""
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    text = str(value)
    if _needs_quote(text):
        return "'" + text.replace("'", "''") + "'"
    return text


def _needs_quote(text: str) -> bool:
    """Return True when *text* must be single-quoted to survive a round-trip."""
    if text == "":
        return True
    if _scalar(text) != text:
        # Would be re-read as bool/int/None/list/flow-map rather than a string.
        return True
    if _TIMESTAMP.match(text) or _is_float(text):
        return True
    if text[0] in "!&*?|>%@`\"'#[]{},":
        return True
    if text[0] in "-:" and (len(text) == 1 or text[1] == " "):
        return True
    return text != text.strip() or ": " in text or text.endswith(":") or "\n" in text


def _is_float(text: str) -> bool:
    """Return True when *text* parses as a float (and so needs quoting)."""
    try:
        float(text)
    except ValueError:
        return False
    return True


def _strip_comment(value: str) -> str:
    """Drop a trailing ``# comment`` that sits outside any quotes."""
    quote: str | None = None
    for i, ch in enumerate(value):
        if quote:
            if ch == quote:
                quote = None
        elif ch in ("'", '"'):
            quote = ch
        elif ch == "#" and (i == 0 or value[i - 1] in " \t"):
            return value[:i]
    return value


def _split_flow(inner: str) -> list[str]:
    """Split the body of an inline ``[a, b, c]`` list on top-level commas."""
    items: list[str] = []
    buf = ""
    quote: str | None = None
    for ch in inner:
        if quote:
            buf += ch
            if ch == quote:
                quote = None
        elif ch in ("'", '"'):
            quote = ch
            buf += ch
        elif ch == ",":
            items.append(buf)
            buf = ""
        else:
            buf += ch
    if buf.strip():
        items.append(buf)
    return items


def _flow_map(inner: str) -> dict[str, Any]:
    """Parse the body of an inline ``{a: x, b: y}`` mapping into a dict."""
    result: dict[str, Any] = {}
    for part in _split_flow(inner):
        key, sep, rest = part.partition(":")
        if sep:
            result[key.strip()] = _scalar(rest.strip())
    return result


def _scalar(raw: str) -> Any:
    """Coerce a scalar token to str/int/bool/None/list/dict, honouring quotes."""
    s = raw.strip()
    if not s:
        return None
    if (s[0] == '"' and s[-1] == '"') or (s[0] == "'" and s[-1] == "'"):
        return s[1:-1]
    if s.startswith("[") and s.endswith("]"):
        body = s[1:-1].strip()
        return [_scalar(x) for x in _split_flow(body)] if body else []
    if s.startswith("{") and s.endswith("}"):
        return _flow_map(s[1:-1].strip())
    low = s.lower()
    if low in ("null", "~"):
        return None
    if low in ("true", "false"):
        return low == "true"
    try:
        return int(s)
    except ValueError:
        return s


def _indent_of(line: str) -> int:
    """Return the number of leading spaces on *line*."""
    return len(line) - len(line.lstrip(" "))


def _next_content(lines: list[str], i: int) -> int:
    """Return the index of the next non-blank, non-comment line at or after *i*."""
    while i < len(lines):
        stripped = lines[i].strip()
        if stripped and not stripped.startswith("#"):
            return i
        i += 1
    return len(lines)


def _parse_subset(text: str) -> dict[str, Any]:
    """Parse the nested scalar/list/mapping YAML subset rhiza files use."""
    lines = text.splitlines()
    value, _ = _parse_map(lines, _next_content(lines, 0), 0)
    return value


def _parse_map(lines: list[str], i: int, indent: int) -> tuple[dict[str, Any], int]:
    """Parse a block mapping whose keys sit at *indent*, returning it and the next index."""
    data: dict[str, Any] = {}
    while True:
        i = _next_content(lines, i)
        if i >= len(lines) or _indent_of(lines[i]) < indent:
            break
        stripped = lines[i].strip()
        if stripped.startswith("- ") or stripped == "-":
            break  # a sequence at this level is not part of a mapping
        if ":" not in stripped:
            i += 1  # tolerate a stray non-mapping line, as the CLI reader does
            continue
        key, _, rest = stripped.partition(":")
        key = key.strip()
        rest = _strip_comment(rest).strip()
        i += 1
        if rest in _BLOCK_SCALAR_INDICATORS:
            data[key], i = _parse_block_scalar(lines, i, indent)
        elif rest == "":
            data[key], i = _parse_child(lines, i, indent)
        else:
            data[key] = _scalar(rest)
    return data, i


def _parse_child(lines: list[str], i: int, parent_indent: int) -> tuple[Any, int]:
    """Parse the value introduced by a bare ``key:`` line, or ``None`` when absent."""
    j = _next_content(lines, i)
    if j >= len(lines):
        return None, i
    child_indent = _indent_of(lines[j])
    child = lines[j].strip()
    is_seq = child.startswith("- ") or child == "-"
    # Block sequences may sit at the parent's indent (zero-indent style); block
    # mappings must be strictly deeper.
    if is_seq and child_indent >= parent_indent:
        return _parse_seq(lines, j, child_indent)
    if not is_seq and child_indent > parent_indent:
        return _parse_map(lines, j, child_indent)
    return None, i


def _parse_seq(lines: list[str], i: int, indent: int) -> tuple[list[Any], int]:
    """Parse a block sequence whose ``- `` items sit at *indent*."""
    items: list[Any] = []
    while True:
        i = _next_content(lines, i)
        if i >= len(lines) or _indent_of(lines[i]) < indent:
            break
        stripped = lines[i].strip()
        if not (stripped.startswith("- ") or stripped == "-"):
            break
        item = "" if stripped == "-" else stripped[2:]
        item = _strip_comment(item).strip()
        if item and item[0] not in "[{'\"" and re.match(r"[^:\s]+:(\s|$)", item):
            # A block mapping under this item: reparse from the "- " column.
            lines[i] = lines[i].replace("- ", "  ", 1)
            value, i = _parse_map(lines, i, _indent_of(lines[i]))
            items.append(value)
        else:
            items.append(_scalar(item))
            i += 1
    return items, i


def _parse_block_scalar(lines: list[str], i: int, parent_indent: int) -> tuple[str, int]:
    """Consume the indented body of a ``key: |`` block scalar into a string."""
    body: list[str] = []
    while i < len(lines):
        line = lines[i]
        if line.strip() and _indent_of(line) <= parent_indent:
            break
        body.append(line.strip())
        i += 1
    return "\n".join(body).strip(), i
