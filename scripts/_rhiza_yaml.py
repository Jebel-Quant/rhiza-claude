#!/usr/bin/env python3
"""Minimal, dependency-free YAML reader for rhiza template files.

`scripts/status.py` and `scripts/validate.py` are stdlib-only ports of the
`rhiza` CLI's commands, so they can run inside this plugin without the CLI (or
PyYAML) installed. Both need to read `.rhiza/template.yml` and
`.rhiza/template.lock`, which use a small, well-behaved subset of YAML:
top-level scalar keys, block sequences (`- item`) and inline flow sequences
(`[a, b]`), quoted/bare scalars, and `#` comments.

`load_yaml` parses exactly that subset. When PyYAML *is* importable we defer to
it (same "stdlib works, third-party enhances" posture as stats.py's
tomllib/tomli fallback), so hand-authored configs with constructs this parser
doesn't cover still validate correctly. The built-in parser deliberately does
NOT handle nested mappings, multi-line scalars, anchors, or block scalars —
none of which appear in rhiza template files.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

try:  # pragma: no cover - exercised only when PyYAML is installed
    import yaml as _pyyaml
except ModuleNotFoundError:  # pragma: no cover
    _pyyaml = None


def load_yaml(path: Path) -> dict[str, Any]:
    """Load a rhiza template/lock file into a plain dict.

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


def _scalar(raw: str) -> Any:
    """Coerce a scalar token to str/int/bool/None/list, honouring quotes."""
    s = raw.strip()
    if not s:
        return None
    if (s[0] == '"' and s[-1] == '"') or (s[0] == "'" and s[-1] == "'"):
        return s[1:-1]
    if s.startswith("[") and s.endswith("]"):
        body = s[1:-1].strip()
        return [_scalar(x) for x in _split_flow(body)] if body else []
    low = s.lower()
    if low in ("null", "~"):
        return None
    if low in ("true", "false"):
        return low == "true"
    try:
        return int(s)
    except ValueError:
        return s


def _parse_subset(text: str) -> dict[str, Any]:
    """Parse the flat scalar/list YAML subset rhiza template files use."""
    data: dict[str, Any] = {}
    current_key: str | None = None
    for raw in text.splitlines():
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped == "-" or stripped.startswith("- "):
            item = stripped[1:].strip() if stripped != "-" else ""
            if current_key is not None:
                if not isinstance(data.get(current_key), list):
                    data[current_key] = []
                data[current_key].append(_scalar(_strip_comment(item)))
            continue
        if ":" not in stripped:
            continue
        key, _, rest = stripped.partition(":")
        key = key.strip()
        rest = _strip_comment(rest).strip()
        if rest == "":
            # A bare `key:` introduces a nested block sequence (filled by the
            # following `- item` lines) or is a null scalar if none follow.
            current_key = key
            data[key] = None
        else:
            data[key] = _scalar(rest)
            current_key = None
    return data
