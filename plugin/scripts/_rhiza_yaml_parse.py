#!/usr/bin/env python3
"""The hand-rolled YAML subset parser — `load_yaml`'s fallback when PyYAML is absent.

Split from `_rhiza_yaml` because the two answer different questions: that module owns the
*public* read/write API and the emitter, while everything here exists only to read a file
with no third-party parser available. Keeping them together meant one module was
simultaneously a reader, a writer, and a parser.

**This is the reference implementation, not the fallback's poor cousin.** PyYAML applies
YAML **1.1** implicit resolution; this applies something close to YAML 1.2 core, and where
they disagreed it is PyYAML that was normalised down to match — see `_rhiza_yaml`'s
`_build_loader`. So the coercion rules here (`scalar` and friends) define what a rhiza
config *means*: scalars are strings unless they are plainly a bool, an int or null.

The subset covered: nested mappings, block and inline (`[a, b]`) sequences, inline
(`{source: x, dest: y}`) mappings, block scalars (`key: |`), quoted/bare scalars, and `#`
comments. Deliberately **not** anchors, aliases, or multiple documents — none of which
appear in rhiza template files.

Lenient by design. A malformed line is skipped rather than raised on, because the CLI
reader behaves that way and a damaged lock must degrade rather than crash.
"""

from __future__ import annotations

import re
from typing import Any

_BLOCK_SCALAR_INDICATORS = {"|", ">", "|-", ">-", "|+", ">+"}


def parse_subset(text: str) -> dict[str, Any]:
    """Parse the nested scalar/list/mapping YAML subset rhiza files use."""
    lines = text.splitlines()
    value, _ = _parse_map(lines, _next_content(lines, 0), 0)
    return value


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
            result[key.strip()] = scalar(rest.strip())
    return result


def _is_quoted(s: str) -> bool:
    """Is *s* wrapped in a matching pair of quotes? *s* must be non-empty.

    A lone quote character satisfies this — ``s[0]`` and ``s[-1]`` are then the same
    character — which is deliberate: it is malformed YAML either way, and
    :func:`_needs_quote` relies on the resulting round-trip mismatch to quote it.
    """
    return (s[0] == '"' and s[-1] == '"') or (s[0] == "'" and s[-1] == "'")


def _flow_list(body: str) -> list[Any]:
    """Parse the already-stripped body of an inline ``[a, b, c]`` list."""
    return [scalar(x) for x in _split_flow(body)] if body else []


def _plain_scalar(s: str) -> Any:
    """Coerce an unquoted, non-flow token: null, bool, int, else the string itself."""
    low = s.lower()
    if low in ("null", "~"):
        return None
    if low in ("true", "false"):
        return low == "true"
    try:
        return int(s)
    except ValueError:
        return s


def scalar(raw: str) -> Any:
    """Coerce a scalar token to str/int/bool/None/list/dict, honouring quotes.

    Shape first — quoted, then the two flow collections — and only then the unquoted
    keyword/int/string coercions, which :func:`_plain_scalar` owns. The order matters:
    a quoted ``'true'`` is the string, not the boolean.
    """
    s = raw.strip()
    if not s:
        return None
    if _is_quoted(s):
        return s[1:-1]
    if s.startswith("[") and s.endswith("]"):
        return _flow_list(s[1:-1].strip())
    if s.startswith("{") and s.endswith("}"):
        return _flow_map(s[1:-1].strip())
    return _plain_scalar(s)


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
            data[key] = scalar(rest)
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
            items.append(scalar(item))
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
