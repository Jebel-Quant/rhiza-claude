#!/usr/bin/env python3
"""Finish what `go mod init` leaves out of a Go module.

The largest gap of the three languages to open, and the shortest module to close it,
because the two facts pull in opposite directions. `go mod init` writes exactly one file
— `go.mod`, holding a module path and a Go version — so almost nothing is there. But
`go.mod` has no description, repository, homepage, author or licence field either, so
there is no manifest step to write: everything the other two languages put in a manifest
is, for Go, the git remote's job or the `LICENSE` file's.

What is left is a `README.md` (go writes none) and a `doc.go` carrying the package comment
revive's `exported` rule wants — the template runs that as `make docs-coverage`, and with
no Go file at all there is nothing for the rule to find and nothing for `go test ./...`
to run.

**No version location is written here.** A Go module's version *is* its git tag, and the
`go-core` bundle owns the declaration; see `_skeleton_version` for why writing one would
be actively wrong.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _skeleton_common as common  # noqa: E402


def go_module_path(target: Path) -> str | None:
    """Return the `module` path `go.mod` declares, or None."""
    manifest = target / "go.mod"
    if not manifest.is_file():
        return None
    for line in manifest.read_text(encoding="utf-8", errors="ignore").splitlines():
        match = re.match(r"^\s*module\s+(\S+)", line)
        if match:
            return match.group(1)
    return None


def go_package_name(target: Path) -> str:
    """Return the package name for the module's root package.

    The convention is the last element of the module path, minus a major-version suffix —
    a `/v2` belongs to the *import* path and never to the package name.

    That element then has to be a Go identifier, which is narrower than a path element:
    lowercase, and no dots or hyphens. Underscores are kept, because `_` is a legal
    identifier character and renaming `example.com/my_lib`'s package to `mylib` would
    surprise anyone importing it. A name that cannot start an identifier — nothing left,
    or a leading digit — falls back to `pkg`: valid, neutral, and deliberately not `main`,
    which in Go declares an executable rather than a library.
    """
    path = go_module_path(target) or target.name
    last = path.rstrip("/").split("/")[-1]
    if re.fullmatch(r"v[0-9]+", last):
        parts = path.rstrip("/").split("/")
        last = parts[-2] if len(parts) > 1 else target.name
    cleaned = re.sub(r"[^a-z0-9_]", "", last.lower())
    return cleaned if re.fullmatch(r"[a-z_][a-z0-9_]*", cleaned) else "pkg"


def seed_package_doc(target: Path, *, description: str | None) -> str | None:
    """Write `doc.go` with the module's package comment; return the path, or None.

    `doc.go` is the convention for a package comment with no code attached, which keeps
    this from inventing API. Written only into a module with no root package yet: a
    second package comment in a package that already has one is itself a lint finding,
    so an existing `.go` file at the root means hands off.
    """
    if any(target.glob("*.go")):
        return None
    package = go_package_name(target)
    module = go_module_path(target) or package
    # Go's convention is that the first sentence is a summary beginning "Package <name>",
    # which a description pasted straight in would not be ("Package widget A widget
    # library." is a fragment). So the summary is generated and the description, if there
    # is one, becomes the paragraph under it.
    body = f"// Package {package} is the root package of {module}.\n"
    summary = description.strip() if description and description.strip() else None
    if summary:
        if not summary.endswith("."):
            summary += "."
        body += f"//\n// {summary}\n"
    (target / "doc.go").write_text(f"{body}package {package}\n", encoding="utf-8")
    return "doc.go"


def finish_go(
    target: Path,
    *,
    repo: str,
    description: str | None,
    modified: list[str],
    notes: list[str],
) -> dict[str, Any]:
    """Finish a `go mod init` skeleton; return a summary dict."""
    # `is_file`, not `exists`: a directory named go.mod would pass the gate here and then
    # be read as an absent manifest by every helper downstream.
    if not (target / "go.mod").is_file():
        notes.append("go.mod absent — run `go mod init <module path>` first")
        return {"modified": modified, "changes": [], "notes": notes, "ok": False}

    module = go_module_path(target)
    notes.append(f"module {module}" if module else "go.mod declares no module path")

    doc = seed_package_doc(target, description=description)
    if doc:
        modified.append(doc)
        notes.append(
            "wrote doc.go with the package comment revive's `exported` rule wants — "
            "`go mod init` creates no Go file at all"
        )
    else:
        notes.append("root package already has Go files — left alone")

    if common.seed_readme(target, repo=repo, description=description, create=True):
        modified.append("README.md")
        notes.append("seeded the README.md go never writes — /rhiza:docs owns the real one")

    notes.append("go.mod holds no metadata to fill in; license is /rhiza:license's job")
    return {"modified": modified, "changes": [], "notes": notes, "ok": True}
