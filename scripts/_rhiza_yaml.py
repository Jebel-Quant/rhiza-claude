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
the tomllib/tomli fallback), so hand-authored configs using constructs
this parser doesn't cover still load correctly.

**Two readers means they must agree, and they did not.** PyYAML applies YAML 1.1
implicit resolution where this parser applies something close to YAML 1.2 core, so
the same file produced different answers depending only on whether PyYAML happened to
be importable — `ref: 1.20` read as the float `1.2`, `strategy: no` as `False`,
`0755` as octal 493, a timestamp as a `datetime`, and a `|` block keeping its trailing
newline. `ref` selects the template tag a sync pulls from, so that one silently
changed which release a repo tracked. `_build_loader` normalises the PyYAML path down
to this parser's rules; PyYAML is still what handles *structure* (anchors, flow
collections, quoting), which is the reason for deferring to it.

What parity guarantees: for a well-formed mapping document, both readers return equal
data. For a malformed one they differ by design — this parser is lenient, PyYAML is
strict — but both fail as `ValueError`, the error every caller guards against.

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

try:
    import yaml as _pyyaml
except ModuleNotFoundError:  # pragma: no cover - the runtime case; tests install PyYAML
    _pyyaml = None

# YAML 1.1 timestamp shapes PyYAML resolves to datetime; we must quote these on
# output (and never coerce them on input) to keep values like `synced_at` strings.
_TIMESTAMP = re.compile(
    r"^\d{4}-\d{1,2}-\d{1,2}([Tt ]\d{1,2}:\d{1,2}:\d{1,2}(\.\d+)?([Zz]|[+-]\d{1,2}(:\d{1,2})?)?)?$"
)
_BLOCK_SCALAR_INDICATORS = {"|", ">", "|-", ">-", "|+", ">+"}

# --- keeping the two readers in agreement ------------------------------------
#
# `load_yaml` has two implementations behind it, and they used to disagree. PyYAML
# applies YAML **1.1** implicit resolution; the subset parser below applies something
# close to YAML 1.2 core. On one realistic pointer file that produced four different
# answers, and one of them was not cosmetic:
#
#     ref: 1.20   ->  "1.20" (subset)  vs  1.2 (PyYAML, float)
#
# `ref` selects the template tag to sync from, so the same repo would resolve to a
# different release depending on whether PyYAML happened to be importable. The others:
# `synced_at` became a datetime, `strategy: no` became False, and `0755` was read as
# octal 493 rather than 755.
#
# The subset parser is the reference implementation — these files are configuration
# whose scalars are strings unless they are plainly a bool, an int or null — so the
# PyYAML path is normalised down to match it, rather than the reverse. Structure
# (anchors, flow collections, block scalars, quoting) still comes from PyYAML, which is
# the reason for deferring to it at all.
_DROPPED_TAGS = frozenset({"tag:yaml.org,2002:float", "tag:yaml.org,2002:timestamp"})
# YAML 1.2 core booleans only: `yes`/`no`/`on`/`off`/`y`/`n` stay strings.
_STRICT_BOOL = re.compile(r"^(?:true|True|TRUE|false|False|FALSE)$")
# Decimal only: no octal, no hex, no underscores — `int(s)` is what the subset does.
_STRICT_INT = re.compile(r"^[-+]?[0-9]+$")


def _build_loader() -> Any:
    """Return a PyYAML loader whose scalars resolve the way `_scalar` does.

    Implemented by editing the implicit-resolver table rather than post-processing the
    result, because post-processing cannot tell an unquoted ``true`` from a quoted
    ``"true"`` — by then both are the same Python string, and coercing the second
    would trade one disagreement for another.
    """
    if _pyyaml is None:  # pragma: no cover - guarded by the caller
        return None

    class _RhizaLoader(_pyyaml.SafeLoader):  # type: ignore[misc]
        """SafeLoader with YAML 1.1's scalar surprises removed."""

    table: dict[str, list[Any]] = {}
    for char, mappings in _pyyaml.SafeLoader.yaml_implicit_resolvers.items():
        kept = []
        for tag, regexp in mappings:
            if tag in _DROPPED_TAGS:
                continue
            if tag == "tag:yaml.org,2002:bool":
                regexp = _STRICT_BOOL
            elif tag == "tag:yaml.org,2002:int":
                regexp = _STRICT_INT
            kept.append((tag, regexp))
        table[char] = kept
    _RhizaLoader.yaml_implicit_resolvers = table

    # Resolving the tag is only half of it: PyYAML's int *constructor* still reads a
    # leading zero as octal, so `0755` came back as 493 even once the resolver was
    # restricted to decimal. `_STRICT_INT` has already guaranteed the token is plain
    # decimal, so `int()` is both safe here and exactly what `_scalar` does.
    _RhizaLoader.add_constructor(
        "tag:yaml.org,2002:int",
        lambda loader, node: int(loader.construct_scalar(node)),
    )

    # A fifth disagreement, found by running the existing suite with PyYAML installed:
    # `key: |` clips to one trailing newline per the YAML spec, while the subset
    # parser's `_parse_block_scalar` strips. Reconciled toward the subset parser for
    # consistency with the rows above — and only for block styles, since stripping every
    # string would destroy deliberate whitespace in a quoted one.
    def _construct_str(loader: Any, node: Any) -> str:
        value: str = loader.construct_scalar(node)
        return value.strip() if node.style in ("|", ">") else value

    _RhizaLoader.add_constructor("tag:yaml.org,2002:str", _construct_str)
    return _RhizaLoader


def load_yaml(path: Path) -> dict[str, Any]:
    """Load a rhiza template/lock/bundles file into a plain dict.

    Prefers PyYAML when available; otherwise falls back to the built-in
    subset parser. A file whose top level is empty yields ``{}``. Raises
    ``ValueError`` when the document's top level is not a mapping, mirroring
    how the CLI treats a malformed config.
    """
    text = path.read_text(errors="ignore")
    if _pyyaml is not None:
        try:
            data = _pyyaml.load(text, Loader=_build_loader())  # nosec B506 - SafeLoader subclass
        except _pyyaml.YAMLError as exc:
            # Every caller guards `load_yaml` with `except (OSError, ValueError)`, which
            # is the module's contract. PyYAML's YAMLError is neither, so on a damaged
            # lock it escaped all eight of them — and `stage_synced` stopped degrading
            # to "stage the pointer only", which is a safety property, not a nicety.
            raise ValueError(f"could not parse YAML: {exc}") from exc
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


def as_list(value: Any) -> list[str]:
    """Normalise a scalar/None/list config field into a list of strings."""
    if value is None:
        return []
    if isinstance(value, list):
        return [str(x) for x in value]
    if isinstance(value, str):
        parts = value.split("\\n") if "\\n" in value and "\n" not in value else value.split("\n")
        return [p.strip() for p in parts if p.strip()]
    return [str(value)]
