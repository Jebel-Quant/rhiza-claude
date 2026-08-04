#!/usr/bin/env python3
"""Finish an `init --lib` skeleton into a rhiza-shaped one — behind `/rhiza:skeleton`.

Three languages, one remit: close the gap between what the language's own initialiser
writes and what a rhiza-managed repo needs. ``--language rust`` finishes what
`cargo init --lib` leaves out — the doc comments it omits (a `//!` crate doc *and* a
`///` on the `pub fn add` in its own placeholder, because the template's docs gate denies
``missing_docs`` on every public item, not just the crate root), a `README.md` (cargo
creates no file at all), and the `[package]` metadata crates.io wants: `description`,
`repository`, `homepage`, `authors`. As on the Python side every key is added
**only if missing**.

``--language go`` has the largest gap to close, because `go mod init` writes exactly one
file — `go.mod`, holding a module path and a Go version and nothing else. There is no
description, repository, homepage, author or licence field for a manifest step to fill,
so what is left is a `README.md`, a `doc.go` carrying the package comment revive's
`exported` rule wants, and the version location below.

`uv init --lib` gets a Python project 90% of the way there: `pyproject.toml`,
`src/<pkg>/__init__.py`, `README.md`, `.python-version`. This script closes the
gap between that and what a rhiza-managed repo needs, so `/rhiza:update`'s synced
gates have something to pass:

  src/<pkg>/__init__.py   replace uv's undocumented `hello()` placeholder with a
                          package docstring (interrogate + coverage both fail on it)
  README.md               uv creates it **empty**, and the template's
                          test_readme_validation.py asserts it is non-empty
  [project].authors       uv omits it entirely when git has no configured identity,
                          and the template's pyproject gate requires a named author
  [project].description   fill in uv's "Add your description here" placeholder
  [project.urls]          Homepage + Repository — the template's .rhiza/tests/
                          test_pyproject.py requires both
  [dependency-groups]     a `test` group (incl. pytest) — likewise required
  [tool.bumpversion]      where the version lives, so `/rhiza:release` has something to
                          read (`.bumpversion.toml` on the Rust side)

**Why the bumpversion table is written here and not left to the prose.** It was prose —
`prompts/skeleton.md` steps 5 and R5 spell the exact block out — and prose is a step a
model can skip. What it costs when skipped is not a failed gate but a wrong release:
`bump-my-version` silently falls back to ``git describe``, so a version that already
exists can be cut again. The template's own `test_a_discoverable_config_exists` (new in
rhiza v1.3.0) fails on its absence, which is how this surfaced. The block is fixed text
with one substituted number, so by this plugin's own division of labour — deterministic
work in tested Python, judgement in markdown — it belongs here.

**Go is the exception: this script writes no version location.** A Go module's version
*is* its git tag, so there is nothing in a fresh module to anchor to, and the `go-core`
bundle owns the declaration — a root `.bumpversion.toml` (template-owned, listed in
`template.lock`) with no `current_version` key, because the current version is read from
the newest tag, plus the `internal/version/version.go` constant that lets a built binary
report itself. Writing our own would be clobbered by the first sync and would inject a
`current_version` upstream deliberately omits. So on Go the version location arrives with
`/rhiza:update`, and the skeleton says so rather than pre-empting it.

It writes **no** ``classifiers`` — not a ``License ::`` trove classifier (PEP 639
replaced it with the SPDX ``license`` field, and `/rhiza:license` owns that), and
not the ``Programming Language :: Python :: X.Y`` entries either (`/rhiza:python-version`
owns those). This script never touches the ``classifiers`` key.

Every edit is idempotent and additive: real code and hand-written metadata are
never overwritten. The placeholder `__init__.py` is only rewritten while it still
*is* uv's placeholder. Stdlib-only, so `/skeleton` can run it without the `rhiza`
CLI. Running `uv init --lib` itself is the caller's job — this script only finishes
the result, and reports what's missing when there's nothing to finish.

Usage:
  uv run --python 3.12 --no-project python \
      scripts/init_skeleton.py [TARGET] --owner OWNER --repo NAME \
      [--host github|gitlab] [--language python|rust|go] [--description TEXT] [--json]
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess  # nosec B404
import sys
from pathlib import Path
from typing import Any

_HOSTS = {"github": "github.com", "gitlab": "gitlab.com"}

# uv seeds this into `[project].description`; it is not a real description.
_UV_DESCRIPTION_PLACEHOLDER = "Add your description here"

# Dependency groups the template's pyproject gate requires, with lower bounds. `lint`
# was here until the gate dropped its required-group check (rhiza #1484): the template
# provisions every linter through prek/uvx, so nothing ever resolved that group.
_DEPENDENCY_GROUPS: dict[str, list[str]] = {
    "test": ["pytest>=8.0", "pytest-cov>=5.0"],
}

# The files `bump-my-version` searches for its config, in its own order. A
# `[tool.bumpversion]` table anywhere else — `.rhiza/.cfg.toml`, say — is never found,
# and the tool then falls back to `git describe` without saying so.
_BUMPVERSION_CONFIGS = (".bumpversion.toml", ".bumpversion.cfg", "setup.cfg", "pyproject.toml")
# `[tool.bumpversion]` in TOML; `[bumpversion]` is the legacy INI spelling in setup.cfg.
_BUMPVERSION_SECTION = re.compile(r"^\s*\[(tool\.)?bumpversion\]", re.MULTILINE)

# The version-location declarations, one per language. Fixed text apart from the current
# version (and, for Cargo.lock, the crate name), which is why they are written by the
# script rather than left to the procedure's prose.
#
# **The search patterns are anchored to their table on purpose.** `search`/`replace` apply
# to every occurrence in a file, so a bare `version = "{current_version}"` would also
# rewrite a `[tool.something].version`, or — worse, in `Cargo.lock` — every dependency
# that happens to share the number.
#
# **And the `Cargo.lock` entry needs `regex = true`.** Without it the `\n` is matched
# literally, so the entry silently does nothing: `Cargo.toml` moves, the lockfile records
# the old version, and the next `cargo build` dirties the tree — the exact failure the
# entry exists to prevent, reported as a successful release. The version this repo's own
# procedure documented had that bug until a real bump was run against it.
# Raw strings: every backslash here belongs to the regex that lands in the file, and
# `{{...}}` survives `.format()` as bump-my-version's own `{current_version}` placeholder.
_PYTHON_BUMPVERSION = r"""
[tool.bumpversion]
current_version = "{version}"
tag = false
commit = false
allow_dirty = false

[[tool.bumpversion.files]]
filename = "pyproject.toml"
regex = true
search = '(?ms)^\[project\]((?:(?!^\[)[\s\S])*?)^version = "{{current_version}}"'
replace = '[project]\1version = "{{new_version}}"'
"""

_RUST_BUMPVERSION = r"""[tool.bumpversion]
current_version = "{version}"
tag = false
commit = false
allow_dirty = false

[[tool.bumpversion.files]]
filename = "Cargo.toml"
regex = true
search = '(?ms)^\[package\]((?:(?!^\[)[\s\S])*?)^version = "{{current_version}}"'
replace = '[package]\1version = "{{new_version}}"'

[[tool.bumpversion.files]]
filename = "Cargo.lock"
regex = true
search = '(?m)^name = "{name}"\nversion = "{{current_version}}"$'
replace = 'name = "{name}"\nversion = "{{new_version}}"'
ignore_missing_file = true
"""


# Where a Go module's version lives *in the source tree* — the constant `go-core` ships
# so a built binary can report itself. It is the template's file, not ours: absent until
# the first sync, and declared to bump-my-version by the template's own
# root-level `.bumpversion.toml`.
_GO_VERSION_FILE = Path("internal") / "version" / "version.go"
_GO_VERSION_CONST = re.compile(r'^\s*const\s+Version\s*=\s*"([^"]+)"', re.MULTILINE)


def bumpversion_config(target: Path) -> str | None:
    """Return the discoverable file declaring a bumpversion config, or None."""
    for name in _BUMPVERSION_CONFIGS:
        path = target / name
        if path.is_file() and _BUMPVERSION_SECTION.search(path.read_text(errors="ignore")):
            return name
    return None


def go_module_path(target: Path) -> str | None:
    """Return the `module` path `go.mod` declares, or None."""
    manifest = target / "go.mod"
    if not manifest.is_file():
        return None
    for line in manifest.read_text(errors="ignore").splitlines():
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


def declared_version(target: Path, language: str) -> str | None:
    """Return the version the manifest declares, or None when it declares none."""
    if language == "go":
        # Not `go.mod`: a Go module's version is its git tag, and the only copy in the
        # source tree is the constant the `go-core` bundle ships — which is absent until
        # the first sync.
        version_file = target / _GO_VERSION_FILE
        if not version_file.is_file():
            return None
        match = _GO_VERSION_CONST.search(version_file.read_text(errors="ignore"))
        return match.group(1) if match else None

    manifest = target / ("Cargo.toml" if language == "rust" else "pyproject.toml")
    if not manifest.is_file():
        return None
    lines = manifest.read_text(errors="ignore").splitlines()
    span = _table_span(lines, "package" if language == "rust" else "project")
    for line in lines[span[0] + 1 : span[1]] if span else []:
        match = re.match(r"""^\s*version\s*=\s*["']([^"']+)["']""", line)
        if match:
            return match.group(1)
    return None


def seed_bumpversion_config(target: Path, language: str) -> str | None:
    """Declare where the version lives, for `/rhiza:release`; return the file written.

    Returns None when a discoverable config already exists (the user's wins, and this is
    idempotent) or when there is no version to anchor to.

    Python appends to `pyproject.toml`, since that is both discoverable and where the
    version is. Rust gets `.bumpversion.toml`: Cargo has no `[tool]` table convention,
    and `bump-my-version` does not read `Cargo.toml`.

    Go writes nothing: `go-core` owns a root `.bumpversion.toml` of its own, and a copy
    written here would be overwritten by the first sync — see this module's docstring.
    """
    if language == "go" or bumpversion_config(target) is not None:
        return None
    version = declared_version(target, language)
    if version is None:
        return None

    if language == "rust":
        # The *package* name, not the crate identifier: `Cargo.lock` records the name as
        # written in the manifest, hyphens and all.
        name = cargo_package_name(target) or target.name
        path = target / ".bumpversion.toml"
        path.write_text(_RUST_BUMPVERSION.format(version=version, name=name))
        return ".bumpversion.toml"

    manifest = target / "pyproject.toml"
    text = manifest.read_text()
    if not text.endswith("\n"):
        text += "\n"
    manifest.write_text(text + _PYTHON_BUMPVERSION.format(version=version))
    return "pyproject.toml"


def _project_block(lines: list[str]) -> tuple[int, int]:
    """Return ``(header_idx, end_idx)`` bounding the ``[project]`` table body."""
    header = next((i for i, line in enumerate(lines) if line.strip() == "[project]"), None)
    if header is None:
        raise ValueError("pyproject.toml has no [project] table")
    end = len(lines)
    for i in range(header + 1, len(lines)):
        if lines[i].lstrip().startswith("["):
            end = i
            break
    return header, end


def is_uv_placeholder_init(text: str) -> bool:
    """Is *text* still `uv init --lib`'s untouched `hello()` placeholder?

    Conservative by design: anything the user has added (an import, a second
    function, a docstring of their own) makes this False, so real code is never
    rewritten.
    """
    body = [line for line in text.splitlines() if line.strip()]
    return bool(body) and all(
        re.match(r'^def hello\(\) -> str:$|^\s+return "Hello from .*!"$', line) for line in body
    )


def normalize_package_init(target: Path) -> list[str]:
    """Rewrite any placeholder `src/<pkg>/__init__.py` to a package docstring.

    Returns the relative paths modified (empty when there's nothing to normalise).
    """
    modified: list[str] = []
    src = target / "src"
    if not src.is_dir():
        return modified
    for init in sorted(src.glob("*/__init__.py")):
        if is_uv_placeholder_init(init.read_text()):
            init.write_text(f'"""{init.parent.name} package."""\n')
            modified.append(str(init.relative_to(target)))
    return modified


def seed_readme(target: Path, *, repo: str, description: str | None, create: bool = False) -> bool:
    """Give an empty `README.md` a title and description; return whether it was written.

    `uv init --lib` creates `README.md` **empty** — zero bytes. The template's
    `.rhiza/tests/test_readme_validation.py` asserts ``len(content) > 0``, so a repo
    built by the documented `/init` chain failed `make rhiza-test` before it had done
    anything wrong. Closing that gap is exactly this script's remit.

    Only an empty (or whitespace-only) file is written. `/rhiza:docs` owns the real
    README and must never find its work overwritten — this is a stub to clear the gate,
    not a document. Nothing is created if `README.md` is absent, since for uv its
    absence is a different failure the template reports separately — pass *create* for
    an initialiser that writes no README at all (`cargo init`), where the file being
    missing is the normal case rather than a signal.
    """
    readme = target / "README.md"
    if readme.is_file():
        if readme.read_text().strip():
            return False
    elif not create:
        return False
    body = f"# {repo}\n"
    if description:
        body += f"\n{description}\n"
    # No fenced code blocks: the same template test executes any it finds.
    body += "\nRun `/rhiza:docs` to write this properly.\n"
    readme.write_text(body)
    return True


def seed_package_doc(target: Path, *, description: str | None) -> str | None:
    """Write `doc.go` with the module's package comment; return the path, or None.

    Go's analogue of `#![warn(missing_docs)]` and interrogate is revive's `exported`
    rule, which the template runs as `make docs-coverage` — and it wants a package
    comment. `go mod init` writes no Go file at all, so there is nothing for the rule to
    find and nothing for `go test ./...` to run.

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
    (target / "doc.go").write_text(f"{body}package {package}\n")
    return "doc.go"


def git_identity(target: Path) -> tuple[str | None, str | None]:
    """Return ``(name, email)`` from git config in *target*, or ``(None, None)``.

    This is where `uv init` gets the authors entry it writes — and when git has no
    identity configured it writes **no `authors` key at all**, which the template's
    pyproject gate requires. So the same source is consulted here to fill the gap.
    """
    git = shutil.which("git")
    if git is None:  # pragma: no cover - git is present everywhere this runs
        return None, None

    def read(key: str) -> str | None:
        result = subprocess.run(  # nosec B603
            [git, "config", "--get", key], cwd=str(target), capture_output=True, text=True,
            check=False,
        )  # fmt: skip
        value = result.stdout.strip()
        return value or None

    return read("user.name"), read("user.email")


def set_authors(text: str, *, name: str, email: str | None) -> tuple[str, bool]:
    """Ensure ``[project].authors`` names at least one author; return ``(text, changed)``.

    `uv init --lib` omits the key entirely when git has no configured identity, and an
    author already written by hand is never touched. Two of the template's
    `.rhiza/tests/test_pyproject.py` assertions depend on this — the key existing, and
    its first entry having a non-empty ``name``.
    """
    lines = text.splitlines()
    header, end = _project_block(lines)
    entry = f'{{ name = "{name}"' + (f', email = "{email}"' if email else "") + " }"
    new_line = f"authors = [{entry}]"

    for i in range(header + 1, end):
        if not re.match(r"^\s*authors\s*=", lines[i]):
            continue
        # An empty inline list is uv's placeholder; anything else is the user's.
        if re.match(r"^\s*authors\s*=\s*\[\s*\]\s*$", lines[i]):
            lines[i] = new_line
            break
        return text, False
    else:
        lines.insert(header + 1, new_line)

    new_text = "\n".join(lines)
    if text.endswith("\n"):
        new_text += "\n"
    return new_text, True


def set_description(text: str, description: str) -> tuple[str, bool]:
    """Set ``[project].description``, replacing uv's placeholder or inserting it.

    A description the user has already written is left alone. Returns
    ``(new_text, changed)``.
    """
    lines = text.splitlines()
    header, end = _project_block(lines)
    pattern = re.compile(r"^\s*description\s*=\s*(.*)$")
    new_line = f'description = "{description}"'
    for i in range(header + 1, end):
        match = pattern.match(lines[i])
        if not match:
            continue
        if _UV_DESCRIPTION_PLACEHOLDER not in match.group(1):
            return text, False  # a real description — hands off
        lines[i] = new_line
        break
    else:
        lines.insert(header + 1, new_line)
    new_text = "\n".join(lines)
    if text.endswith("\n"):
        new_text += "\n"
    return new_text, True


def is_cargo_placeholder_lib(text: str) -> bool:
    """Is *text* still `cargo init --lib`'s untouched `add`/`it_works` skeleton?

    Conservative in the same way as :func:`is_uv_placeholder_init`: the whole file must
    consist of cargo's own lines, so anything the user has added makes this False and
    real code is never touched. It gates the `///` :func:`seed_crate_docs` puts on
    cargo's `pub fn add` — documenting a *user's* undocumented API on their behalf would
    be presumptuous, and wrong more often than right. The placeholder code itself is
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
    manifest = target / "Cargo.toml"
    if not manifest.is_file():
        return None
    lines = manifest.read_text(errors="ignore").splitlines()
    span = _table_span(lines, "package")
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


# The doc comment cargo's placeholder needs to clear the docs gate, and the line it goes
# above. `cargo init --lib` writes `pub fn add` with no `///`, which is a public item — so
# a crate straight out of `/rhiza:init` failed `make docs-coverage` until this was seeded.
_CARGO_PLACEHOLDER_FN = "pub fn add("
_CARGO_PLACEHOLDER_FN_DOC = "/// Returns the sum of `left` and `right`.\n"


def seed_crate_docs(target: Path) -> list[str]:
    """Document what `cargo init` leaves undocumented in a crate root.

    The Rust docs gate is ``RUSTDOCFLAGS="-D missing_docs" cargo doc`` (the template's
    `make docs-coverage`), and it fires on **every** undocumented public item — not just
    the crate root. `cargo init --lib` leaves two of them: no `//!` module doc, and an
    undocumented `pub fn add` in its placeholder. Seeding only the first is why a freshly
    scaffolded crate could not pass its own gates.

    Both edits are additive, and the second is gated on
    :func:`is_cargo_placeholder_lib` — cargo's stub gets a `///`, a user's own public API
    never does. The file is never rewritten wholesale the way the Python path rewrites
    uv's placeholder: cargo's stub carries the project's only test.

    Returns the relative paths modified (empty when both roots already have docs).
    """
    modified: list[str] = []
    crate = crate_name(target)
    for name in ("lib.rs", "main.rs"):
        root = target / "src" / name
        if not root.is_file():
            continue
        text = root.read_text()
        new_text = text
        if is_cargo_placeholder_lib(new_text):
            new_text = new_text.replace(
                _CARGO_PLACEHOLDER_FN, _CARGO_PLACEHOLDER_FN_DOC + _CARGO_PLACEHOLDER_FN, 1
            )
        if not new_text.lstrip().startswith("//!"):
            new_text = (
                f"//! {crate} crate.\n\n{new_text}" if new_text.strip() else f"//! {crate} crate.\n"
            )
        if new_text == text:
            continue
        root.write_text(new_text)
        modified.append(str(root.relative_to(target)))
    return modified


def set_cargo_keys(text: str, wanted: dict[str, str]) -> tuple[str, list[str]]:
    """Insert absent ``[package]`` keys from *wanted*; return ``(new_text, added)``.

    Only missing keys are written — a value already in the manifest is the user's and
    wins. Keys are inserted directly under the ``[package]`` header, which is valid
    wherever the table sits in the file.
    """
    lines = text.splitlines()
    header, end = _table_block(lines, "package", "Cargo.toml")
    present = {
        match.group(1)
        for line in lines[header + 1 : end]
        if (match := re.match(r"^\s*([A-Za-z0-9_-]+)\s*=", line))
    }
    added = [key for key in wanted if key not in present]
    # Append to the end of the table, not under the header: cargo puts `name` and
    # `version` first and readers expect them there.
    while end > header + 1 and not lines[end - 1].strip():
        end -= 1
    lines[end:end] = [f"{key} = {wanted[key]}" for key in added]
    new_text = "\n".join(lines)
    if text.endswith("\n"):
        new_text += "\n"
    return new_text, added


def _table_block(lines: list[str], table: str, filename: str) -> tuple[int, int]:
    """Return ``(header_idx, end_idx)`` bounding a top-level ``[table]`` body."""
    header = next((i for i, line in enumerate(lines) if line.strip() == f"[{table}]"), None)
    if header is None:
        raise ValueError(f"{filename} has no [{table}] table")
    end = len(lines)
    for i in range(header + 1, len(lines)):
        if lines[i].lstrip().startswith("["):
            end = i
            break
    return header, end


def _table_span(lines: list[str], name: str) -> tuple[int, int] | None:
    """Return ``(header_idx, end_idx)`` of a top-level ``[name]`` table, or None."""
    header = next((i for i, line in enumerate(lines) if line.strip() == f"[{name}]"), None)
    if header is None:
        return None
    end = len(lines)
    for i in range(header + 1, len(lines)):
        if lines[i].lstrip().startswith("["):
            end = i
            break
    return header, end


def _append_table(lines: list[str], header: str, body: list[str]) -> None:
    """Append a ``[header]`` table with *body* lines to the end of the document."""
    while lines and not lines[-1].strip():
        lines.pop()
    lines.extend(["", header, *body])


def set_project_urls(text: str, homepage: str, repository: str) -> tuple[str, bool]:
    """Ensure ``[project.urls]`` declares Homepage and Repository.

    Existing entries win — only missing keys are added. Returns
    ``(new_text, changed)``.
    """
    lines = text.splitlines()
    wanted = {"Homepage": homepage, "Repository": repository}
    span = _table_span(lines, "project.urls")
    if span is None:
        _append_table(lines, "[project.urls]", [f'{k} = "{v}"' for k, v in wanted.items()])
        changed = True
    else:
        header, end = span
        present = {
            match.group(1)
            for line in lines[header + 1 : end]
            if (match := re.match(r"^\s*([A-Za-z-]+)\s*=", line))
        }
        missing = [f'{k} = "{v}"' for k, v in wanted.items() if k not in present]
        lines[end:end] = missing
        changed = bool(missing)
    new_text = "\n".join(lines)
    if text.endswith("\n"):
        new_text += "\n"
    return new_text, changed


def set_dependency_groups(text: str) -> tuple[str, bool]:
    """Ensure ``[dependency-groups]`` declares the required ``test`` group.

    Existing groups are left exactly as they are — this only adds absent ones, each
    with lower-bounded requirements. Returns ``(new_text, changed)``.
    """
    lines = text.splitlines()
    span = _table_span(lines, "dependency-groups")
    if span is None:
        body = [f"{name} = {json.dumps(deps)}" for name, deps in _DEPENDENCY_GROUPS.items()]
        _append_table(lines, "[dependency-groups]", body)
        changed = True
    else:
        header, end = span
        present = {
            match.group(1)
            for line in lines[header + 1 : end]
            if (match := re.match(r"^\s*([A-Za-z0-9_-]+)\s*=", line))
        }
        missing = [
            f"{name} = {json.dumps(deps)}"
            for name, deps in _DEPENDENCY_GROUPS.items()
            if name not in present
        ]
        lines[end:end] = missing
        changed = bool(missing)
    new_text = "\n".join(lines)
    if text.endswith("\n"):
        new_text += "\n"
    return new_text, changed


def _finish_cargo(
    target: Path,
    *,
    owner: str,
    repo: str,
    host_domain: str,
    description: str | None,
    modified: list[str],
    notes: list[str],
) -> dict[str, Any]:
    """Fill in the `[package]` metadata `cargo init` omits; return a summary dict.

    `cargo init --lib` writes only ``name``/``version``/``edition``. Everything
    crates.io and the template's docs gates want — a description, the repository and
    homepage URLs, an author — is absent, and every one of them is *added only if
    missing*, so a hand-written manifest is never rewritten.
    """
    manifest = target / "Cargo.toml"
    # `is_file`, not `exists`: a directory named Cargo.toml would pass the gate here and
    # then be read as an absent manifest by every helper downstream.
    if not manifest.is_file():
        notes.append("Cargo.toml absent — run `cargo init --lib` first")
        return {"modified": modified, "changes": [], "notes": notes, "ok": False}

    url = f"https://{host_domain}/{owner}/{repo}"
    identity_name, identity_email = git_identity(target)
    author = identity_name or owner
    if identity_email:
        author += f" <{identity_email}>"
    wanted = {
        "repository": json.dumps(url),
        "homepage": json.dumps(url),
        "authors": json.dumps([author]),
    }
    if description:
        wanted["description"] = json.dumps(description)

    original = manifest.read_text()
    try:
        text, added = set_cargo_keys(original, wanted)
    except ValueError as exc:
        notes.append(f"Cargo.toml: {exc}")
        return {"modified": modified, "changes": [], "notes": notes, "ok": False}

    if text != original:
        manifest.write_text(text)
        modified.append("Cargo.toml")
        notes.append("Cargo.toml: " + ", ".join(added))
    else:
        notes.append("Cargo.toml already rhiza-shaped")

    notes.append("license is /rhiza:license's job")
    return {"modified": modified, "changes": added, "notes": notes, "ok": True}


def _finish_go(
    target: Path,
    *,
    repo: str,
    description: str | None,
    modified: list[str],
    notes: list[str],
) -> dict[str, Any]:
    """Finish what `go mod init` leaves out; return a summary dict.

    Deliberately short, because `go.mod` has nothing to fill in: no description,
    repository, homepage, author or licence field exists in the format. Everything the
    other two languages write into a manifest is, for Go, either the git remote's job or
    the `LICENSE` file's.
    """
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

    if seed_readme(target, repo=repo, description=description, create=True):
        modified.append("README.md")
        notes.append("seeded the README.md go never writes — /rhiza:docs owns the real one")

    notes.append("go.mod holds no metadata to fill in; license is /rhiza:license's job")
    return {"modified": modified, "changes": [], "notes": notes, "ok": True}


def _note_bumpversion(target: Path, language: str, result: dict[str, Any]) -> None:
    """Declare the version location and record what happened in *result*, in place.

    Runs last, and only when the manifest work succeeded: the table anchors to the version
    the manifest declares, so there is nothing to write until that manifest is sound.
    """
    if not result["ok"]:
        return
    if language == "go":
        result["notes"].append(
            "no version location written: a Go module's version is its git tag, and the "
            "template's own .bumpversion.toml (plus internal/version/version.go) arrives "
            "with the first /rhiza:update"
        )
        return
    existing = bumpversion_config(target)
    written = seed_bumpversion_config(target, language)
    if written is not None:
        if written not in result["modified"]:
            result["modified"].append(written)
        result["changes"].append("tool.bumpversion")
        result["notes"].append(
            f"declared the version location in {written} — /rhiza:release reads "
            "[tool.bumpversion] and refuses to guess"
        )
    elif existing is not None:
        result["notes"].append(f"version location already declared in {existing}")
    else:
        result["notes"].append(
            "no version declared in the manifest, so no [tool.bumpversion] was written — "
            "/rhiza:release will have nothing to read"
        )


def finish_skeleton(
    target: Path,
    *,
    owner: str,
    repo: str,
    host: str,
    description: str | None,
    language: str = "python",
) -> dict[str, Any]:
    """Finish the `uv init` / `cargo init` / `go mod init` skeleton; return a summary."""
    modified: list[str] = []
    notes: list[str] = []
    changes: list[str] = []
    host_domain = _HOSTS.get(host, _HOSTS["github"])

    if language == "go":
        result = _finish_go(
            target, repo=repo, description=description, modified=modified, notes=notes
        )
        _note_bumpversion(target, "go", result)
        return result

    if language == "rust":
        modified.extend(seed_crate_docs(target))
        if modified:
            notes.append(
                "documented what cargo leaves bare — missing_docs is denied on every "
                "public item, not just the crate root"
            )
        if seed_readme(target, repo=repo, description=description, create=True):
            modified.append("README.md")
            notes.append("seeded the README.md cargo never writes — /rhiza:docs owns the real one")
        result = _finish_cargo(
            target,
            owner=owner,
            repo=repo,
            host_domain=host_domain,
            description=description,
            modified=modified,
            notes=notes,
        )
        _note_bumpversion(target, "rust", result)
        return result

    modified.extend(normalize_package_init(target))
    if modified:
        notes.append("normalised uv's placeholder hello() to a package docstring")

    if seed_readme(target, repo=repo, description=description):
        modified.append("README.md")
        notes.append("seeded the empty README.md uv left behind — /rhiza:docs owns the real one")

    pyproject = target / "pyproject.toml"
    if not pyproject.is_file():
        notes.append("pyproject.toml absent — run `uv init --lib` first")
        return {"modified": modified, "changes": changes, "notes": notes, "ok": False}

    text = original = pyproject.read_text()
    try:
        if description:
            text, changed = set_description(text, description)
            if changed:
                changes.append("description")
        text, changed = set_project_urls(
            text,
            homepage=f"https://{host_domain}/{owner}/{repo}",
            repository=f"https://{host_domain}/{owner}/{repo}",
        )
        if changed:
            changes.append("project.urls")
        text, changed = set_dependency_groups(text)
        if changed:
            changes.append("dependency-groups")
        identity_name, identity_email = git_identity(target)
        # Falls back to the owner: the gate needs a non-empty name, and the owner is the
        # best fact available when the machine has no git identity at all.
        text, changed = set_authors(text, name=identity_name or owner, email=identity_email)
        if changed:
            changes.append("authors")
    except ValueError as exc:
        notes.append(f"pyproject.toml: {exc}")
        return {"modified": modified, "changes": changes, "notes": notes, "ok": False}

    if text != original:
        pyproject.write_text(text)
        modified.append("pyproject.toml")
        notes.append("pyproject.toml: " + ", ".join(changes))
    else:
        notes.append("pyproject.toml already rhiza-shaped")

    notes.append("license + classifiers are /rhiza:license and /rhiza:python-version's job")

    result = {"modified": modified, "changes": changes, "notes": notes, "ok": True}
    _note_bumpversion(target, "python", result)
    return result


def main(argv: list[str] | None = None) -> int:
    """Entry point: parse args, finish the skeleton, return an exit code."""
    parser = argparse.ArgumentParser(
        description="Finish a `uv init` / `cargo init` skeleton into a rhiza-shaped one.",
    )
    parser.add_argument(
        "target", nargs="?", default=".", help="Repository root (default: current directory)."
    )
    parser.add_argument("--owner", required=True, help="GitHub/GitLab owner or org.")
    parser.add_argument("--repo", required=True, help="Repository name (for the project URLs).")
    parser.add_argument(
        "--host", choices=("github", "gitlab"), default="github", help="Git hosting platform."
    )
    parser.add_argument(
        "--language",
        choices=("python", "rust", "go"),
        default="python",
        help="Which skeleton to finish: uv's pyproject.toml, cargo's Cargo.toml, "
        "or go mod init's go.mod.",
    )
    parser.add_argument("--description", help="Project description (replaces uv's placeholder).")
    parser.add_argument(
        "--json", dest="json_output", action="store_true", help="Emit the summary as JSON."
    )
    args = parser.parse_args(argv)

    summary = finish_skeleton(
        Path(args.target).resolve(),
        owner=args.owner,
        repo=args.repo,
        host=args.host,
        description=args.description,
        language=args.language,
    )

    if args.json_output:
        print(json.dumps(summary, indent=2))
    else:
        for path in summary["modified"]:
            print(f"modified {path}")
        for note in summary["notes"]:
            print(f"note     {note}", file=sys.stderr)
    return 0 if summary["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
