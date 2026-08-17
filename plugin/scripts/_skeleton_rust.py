#!/usr/bin/env python3
"""Finish what `cargo init --lib` leaves out of a crate.

Two gaps, and they are different in kind. The **manifest** is missing everything
crates.io and the template's gates want — `cargo init --lib` writes only
``name``/``version``/``edition``, so ``description``, ``repository``, ``homepage`` and
``authors`` are all absent, and every one is added only if missing.

The **crate root** is missing doc comments. The Rust docs gate is
``RUSTDOCFLAGS="-D missing_docs" cargo doc`` (the template's `make docs-coverage`) and it
fires on *every* undocumented public item, not just the crate root — so cargo's stub
needs both a `//!` module doc and a `///` on the `pub fn add` it writes. Seeding only the
first is why a crate straight out of `/rhiza:init` could not pass its own gates.

**Unlike the Python path, cargo's placeholder is never substituted** — only added to.
`src/lib.rs` carries the crate's only test, so rewriting the file the way
`_skeleton_python` rewrites uv's `__init__.py` would delete it, and the template's
coverage gate would then measure a crate with no tests.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _skeleton_common as common  # noqa: E402
from _rhiza_toml import merge_table, table_span  # noqa: E402

_CARGO = "Cargo.toml"

# The doc comment cargo's placeholder needs to clear the docs gate, and the line it goes
# above. `cargo init --lib` writes `pub fn add` with no `///`, which is a public item — so
# a crate straight out of `/rhiza:init` failed `make docs-coverage` until this was seeded.
_PLACEHOLDER_FN = "pub fn add("
_PLACEHOLDER_FN_DOC = "/// Returns the sum of `left` and `right`.\n"


def is_cargo_placeholder_lib(text: str) -> bool:
    """Is *text* still `cargo init --lib`'s untouched `add`/`it_works` skeleton?

    Conservative in the same way as `_skeleton_python.is_uv_placeholder_init`: the whole
    file must consist of cargo's own lines, so anything the user has added makes this
    False and real code is never touched. It gates the `///` :func:`seed_crate_docs` puts
    on cargo's `pub fn add` — documenting a *user's* undocumented API on their behalf
    would be presumptuous, and wrong more often than right. The placeholder code itself is
    never deleted either way, since that would take the project's only test with it.
    """
    body = [line.strip() for line in text.splitlines() if line.strip()]
    allowed = {
        "pub fn add(left: u64, right: u64) -> u64 {",
        "left + right",
        "}",
        "#[cfg(test)]",
        "mod tests {",
        "use super::*;",
        "#[test]",
        "fn it_works() {",
        "let result = add(2, 2);",
        "assert_eq!(result, 4);",
    }
    return bool(body) and all(line in allowed for line in body)


def cargo_package_name(target: Path) -> str | None:
    """Return `[package] name` exactly as `Cargo.toml` writes it, or None."""
    manifest = target / _CARGO
    if not manifest.is_file():
        return None
    lines = manifest.read_text(encoding="utf-8", errors="ignore").splitlines()
    span = table_span(lines, "package")
    for line in lines[span[0] + 1 : span[1]] if span else []:
        match = re.match(r"""^\s*name\s*=\s*["']([^"']+)["']""", line)
        if match:
            return match.group(1)
    return None


def crate_name(target: Path) -> str:
    """Return the crate's Rust identifier: `[package] name` with `-` mapped to `_`.

    The directory is only a fallback. `cargo init --lib --name widget` inside `some-dir/`
    produces a crate called `widget`, and naming its doc comment after the folder would
    describe a crate that does not exist — the same class of "confidently wrong" the
    language axis exists to avoid.
    """
    return (cargo_package_name(target) or target.name).replace("-", "_")


def seed_crate_docs(target: Path) -> list[str]:
    """Document what `cargo init` leaves undocumented in a crate root.

    Both edits are additive, and the second is gated on
    :func:`is_cargo_placeholder_lib` — cargo's stub gets a `///`, a user's own public API
    never does. The file is never rewritten wholesale.

    Returns the relative paths modified (empty when both roots already have docs).
    """
    modified: list[str] = []
    crate = crate_name(target)
    for name in ("lib.rs", "main.rs"):
        root = target / "src" / name
        if not root.is_file():
            continue
        text = root.read_text(encoding="utf-8")
        new_text = text
        if is_cargo_placeholder_lib(new_text):
            new_text = new_text.replace(_PLACEHOLDER_FN, _PLACEHOLDER_FN_DOC + _PLACEHOLDER_FN, 1)
        if not new_text.lstrip().startswith("//!"):
            new_text = (
                f"//! {crate} crate.\n\n{new_text}" if new_text.strip() else f"//! {crate} crate.\n"
            )
        if new_text == text:
            continue
        root.write_text(new_text, encoding="utf-8")
        modified.append(root.relative_to(target).as_posix())
    return modified


def set_cargo_keys(text: str, wanted: dict[str, str]) -> tuple[str, list[str]]:
    """Insert absent ``[package]`` keys from *wanted*; return ``(new_text, added)``.

    Only missing keys are written — a value already in the manifest is the user's and
    wins. An absent ``[package]`` table raises ValueError rather than being created: a
    manifest without one is a virtual workspace, which has no package to describe.
    """
    return merge_table(text, "package", wanted, filename=_CARGO, required=True)


def fill_cargo_manifest(
    target: Path,
    *,
    owner: str,
    repo: str,
    domain: str,
    description: str | None,
    modified: list[str],
    notes: list[str],
) -> dict[str, Any]:
    """Fill in the `[package]` metadata `cargo init` omits; return a summary dict."""
    manifest = target / _CARGO
    # `is_file`, not `exists`: a directory named Cargo.toml would pass the gate here and
    # then be read as an absent manifest by every helper downstream.
    if not manifest.is_file():
        notes.append("Cargo.toml absent — run `cargo init --lib` first")
        return {"modified": modified, "changes": [], "notes": notes, "ok": False}

    url = common.host_url(domain, owner, repo)
    identity_name, identity_email = common.git_identity(target)
    wanted = {
        "repository": json.dumps(url),
        "homepage": json.dumps(url),
        "authors": json.dumps([common.author_entry(owner, identity_name, identity_email)]),
    }
    if description:
        wanted["description"] = json.dumps(description)

    original = manifest.read_text(encoding="utf-8")
    try:
        text, added = set_cargo_keys(original, wanted)
    except ValueError as exc:
        notes.append(f"Cargo.toml: {exc}")
        return {"modified": modified, "changes": [], "notes": notes, "ok": False}

    if text != original:
        manifest.write_text(text, encoding="utf-8")
        modified.append(_CARGO)
        notes.append("Cargo.toml: " + ", ".join(added))
    else:
        notes.append("Cargo.toml already rhiza-shaped")

    notes.append("license is /rhiza:license's job")
    return {"modified": modified, "changes": added, "notes": notes, "ok": True}


def finish_rust(
    target: Path,
    *,
    owner: str,
    repo: str,
    domain: str,
    description: str | None,
    modified: list[str],
    notes: list[str],
) -> dict[str, Any]:
    """Finish a `cargo init --lib` skeleton; return a summary dict."""
    modified.extend(seed_crate_docs(target))
    if modified:
        notes.append(
            "documented what cargo leaves bare — missing_docs is denied on every "
            "public item, not just the crate root"
        )
    if common.seed_readme(target, repo=repo, description=description, create=True):
        modified.append("README.md")
        notes.append("seeded the README.md cargo never writes — /rhiza:docs owns the real one")
    return fill_cargo_manifest(
        target,
        owner=owner,
        repo=repo,
        domain=domain,
        description=description,
        modified=modified,
        notes=notes,
    )
