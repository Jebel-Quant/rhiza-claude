#!/usr/bin/env python3
"""Edit a key in a TOML table without reformatting what the author wrote.

The shared substrate under every script here that touches a `pyproject.toml` or a
`Cargo.toml` — the three skeleton finishers, `set_license` and `set_python_version`. It
exists because all five had grown their own copy of "find the `[project]` table": three
near-identical `_table_block`/`_table_span`/`_project_block` functions, and a fourth copy
of the trailing-newline dance in every editing function.

**Text, not a parser.** `tomllib` is read-only in the stdlib, and a round-trip through
any writer would reflow the comments and key order `uv` and `cargo` put there on
purpose — turning a diff that should add three lines into one that rewrites the file.
So every function here works on ``text.splitlines()`` and preserves everything it does
not target, down to whether the file ended in a newline.

Two operations cover most callers: :func:`merge_table` adds absent keys to a table
(creating the table when that is allowed), and :func:`set_key` replaces one key whose
current value is a recognised placeholder. Both leave a value the user wrote alone —
that policy is the entire point of these scripts, and it lives here so none of them has
to restate it. :func:`require_table` and :func:`table_end` are the lower-level pair for
a caller that rewrites lines itself, as `set_license` does when it clears a key before
reinserting it.
"""

from __future__ import annotations

import re
from collections.abc import Callable

# A TOML bare key, plus the dots that make `[project.urls]`-style names. Deliberately
# wider than any single caller needs: over-matching only makes "is this key already
# here?" more accurate, while under-matching would add a duplicate key.
_KEY = re.compile(r"^\s*([A-Za-z0-9_.-]+)\s*=")


def table_span(lines: list[str], name: str) -> tuple[int, int] | None:
    """Return ``(header_idx, end_idx)`` of the top-level ``[name]`` table, or None.

    ``end_idx`` is the index of the next table header, or ``len(lines)`` when *name* is
    the last table in the document — so ``lines[header + 1 : end]`` is always the body.

    >>> lines = ["[project]", 'name = "demo"', "", "[tool.ruff]", "line-length = 100"]
    >>> table_span(lines, "project")
    (0, 3)
    >>> lines[1:3]
    ['name = "demo"', '']
    >>> table_span(lines, "missing") is None
    True
    """
    header = next((i for i, line in enumerate(lines) if line.strip() == f"[{name}]"), None)
    if header is None:
        return None
    for i in range(header + 1, len(lines)):
        if lines[i].lstrip().startswith("["):
            return header, i
    return header, len(lines)


def require_table(lines: list[str], name: str, filename: str) -> tuple[int, int]:
    """Return :func:`table_span` for *name*, raising ValueError when it is absent.

    The message names *filename* because it is reported straight to the user: a bare
    "no [package] table" leaves them guessing which file was read.
    """
    span = table_span(lines, name)
    if span is None:
        raise ValueError(f"{filename} has no [{name}] table")
    return span


def present_keys(lines: list[str], header: int, end: int) -> set[str]:
    """Return the keys assigned in the table body bounded by *header* and *end*.

    >>> sorted(present_keys(["[project]", 'name = "demo"', "version = '0.1.0'"], 0, 3))
    ['name', 'version']
    """
    return {
        match.group(1)
        for line in lines[header + 1 : end]
        if (match := _KEY.match(line)) is not None
    }


def table_end(lines: list[str], header: int, end: int) -> int:
    """Return *end* moved back past the blank lines that pad the end of a table body.

    The insertion point for a new key: inside the table, before whatever blank line
    separates it from the next header. Inserting at a raw *end* would put the key after
    that blank line — still inside the table as TOML reads it, but it looks detached.

    >>> lines = ["[project]", 'name = "demo"', "", "[tool.ruff]"]
    >>> table_end(lines, 0, 3)
    2
    """
    while end > header + 1 and not lines[end - 1].strip():
        end -= 1
    return end


def append_table(lines: list[str], header: str, body: list[str]) -> None:
    """Append a ``[header]`` table with *body* to the end of the document, in place.

    Trailing blank lines are collapsed first, so the new table is preceded by exactly one
    blank line however many the file happened to end with.
    """
    while lines and not lines[-1].strip():
        lines.pop()
    lines.extend(["", header, *body])


def rejoin(original: str, lines: list[str]) -> str:
    r"""Join *lines*, restoring whether *original* ended in a newline.

    Every editing function routes its return value through this. A manifest that did not
    end in a newline must not grow one — the resulting one-line diff would be noise in
    somebody else's PR.

    >>> rejoin('name = "demo"\n', ["name = 'demo'", "version = '0.1.0'"])
    "name = 'demo'\nversion = '0.1.0'\n"
    >>> rejoin('name = "demo"', ["name = 'demo'", "version = '0.1.0'"])
    "name = 'demo'\nversion = '0.1.0'"
    """
    text = "\n".join(lines)
    return text + "\n" if original.endswith("\n") else text


def merge_table(
    text: str,
    table: str,
    wanted: dict[str, str],
    *,
    filename: str,
    required: bool = False,
) -> tuple[str, list[str]]:
    r"""Add the keys of *wanted* that *table* does not already declare.

    *wanted* maps a key to its **rendered** right-hand side — ``'"a string"'``, or
    whatever ``json.dumps`` produced — because callers differ on how a value should be
    written and none of that is this function's business.

    Returns ``(new_text, added)``, where *added* lists the keys written and is empty when
    the table already had them all. A key already present is never overwritten: it is the
    user's, and the skeleton's job is to close gaps, not to impose values.

    New keys go at the **end** of the table body rather than under the header, because
    `cargo` and `uv` both put `name` and `version` first and readers expect to find them
    there. With *required* set, an absent table raises ValueError instead of being
    created — a `Cargo.toml` with no ``[package]`` is a virtual workspace, which is a
    situation to report rather than a table to add.

    The key already there is the user's and survives; only the absent one is written, at
    the end of the body:

    >>> text = '[package]\nname = "demo"\n'
    >>> new, added = merge_table(
    ...     text, "package", {"name": '"other"', "edition": '"2021"'}, filename="Cargo.toml"
    ... )
    >>> added
    ['edition']
    >>> print(new, end="")
    [package]
    name = "demo"
    edition = "2021"
    """
    lines = text.splitlines()
    span = table_span(lines, table)
    if span is None:
        if required:
            raise ValueError(f"{filename} has no [{table}] table")
        append_table(lines, f"[{table}]", [f"{key} = {value}" for key, value in wanted.items()])
        return rejoin(text, lines), list(wanted)

    header, end = span
    added = [key for key in wanted if key not in present_keys(lines, header, end)]
    insert_at = table_end(lines, header, end)
    lines[insert_at:insert_at] = [f"{key} = {wanted[key]}" for key in added]
    return rejoin(text, lines), added


def set_key(
    text: str,
    table: str,
    key: str,
    rendered: str,
    *,
    filename: str,
    replaceable: Callable[[str], bool],
) -> tuple[str, bool]:
    r"""Set a single *key* in *table* to *rendered*; return ``(new_text, changed)``.

    Unlike :func:`merge_table` this one *replaces* — but only when the value already
    there is a placeholder the initialiser wrote, which is what *replaceable* decides
    from the current right-hand side. Anything else is the user's and the text comes back
    unchanged.

    An absent key is inserted directly under the table header. That differs from
    :func:`merge_table` on purpose: these are the keys the initialiser itself would have
    written near the top (`description`, `authors`), so that is where a reader looks for
    them.

    Raises ValueError when *table* is absent — there would be nowhere to put the key.

    >>> placeholder = lambda current: "Add your description" in current
    >>> text = '[project]\nname = "demo"\ndescription = "Add your description here"\n'
    >>> new, changed = set_key(
    ...     text, "project", "description", '"Drives rhiza"',
    ...     filename="pyproject.toml", replaceable=placeholder,
    ... )
    >>> changed
    True
    >>> print(new, end="")
    [project]
    name = "demo"
    description = "Drives rhiza"

    Run again, the value is no longer a placeholder — so it is the user's, and it stays:

    >>> set_key(
    ...     new, "project", "description", '"Something else"',
    ...     filename="pyproject.toml", replaceable=placeholder,
    ... )[1]
    False
    """
    lines = text.splitlines()
    header, end = require_table(lines, table, filename)
    pattern = re.compile(rf"^\s*{re.escape(key)}\s*=\s*(.*)$")
    new_line = f"{key} = {rendered}"

    for i in range(header + 1, end):
        match = pattern.match(lines[i])
        if match is None:
            continue
        if not replaceable(match.group(1)):
            return text, False
        lines[i] = new_line
        break
    else:
        lines.insert(header + 1, new_line)

    return rejoin(text, lines), True
