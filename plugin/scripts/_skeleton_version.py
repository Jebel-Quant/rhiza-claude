#!/usr/bin/env python3
"""Declare where the version lives, so `/rhiza:release` has something to read.

**Why this is a script and not prose.** It was prose — `prompts/skeleton.md` steps 5 and
R5 spell the exact block out — and prose is a step a model can skip. What it costs when
skipped is not a failed gate but a wrong release: `bump-my-version` silently falls back to
``git describe``, so a version that already exists can be cut again. The template's own
`test_a_discoverable_config_exists` (new in rhiza v1.3.0) fails on its absence, which is
how this surfaced. The block is fixed text with one substituted number, so by this
plugin's own division of labour — deterministic work in tested Python, judgement in
markdown — it belongs here.

**Go is the exception: nothing is written.** A Go module's version *is* its git tag, so
there is nothing in a fresh module to anchor to, and the `go-core` bundle owns the
declaration — a root `.bumpversion.toml` (template-owned, listed in `template.lock`) with
no `current_version` key, because the current version is read from the newest tag, plus
the `internal/version/version.go` constant that lets a built binary report itself. Writing
our own would be clobbered by the first sync *and* would inject a `current_version`
upstream deliberately omits. So on Go the version location arrives with `/rhiza:update`,
and the skeleton says so rather than pre-empting it.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _rhiza_toml import table_span  # noqa: E402
from _skeleton_rust import cargo_package_name  # noqa: E402

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

_GO_NOTE = (
    "no version location written: a Go module's version is its git tag, and the "
    "template's own .bumpversion.toml (plus internal/version/version.go) arrives "
    "with the first /rhiza:update"
)


def bumpversion_config(target: Path) -> str | None:
    """Return the discoverable file declaring a bumpversion config, or None."""
    for name in _BUMPVERSION_CONFIGS:
        path = target / name
        if path.is_file() and _BUMPVERSION_SECTION.search(
            path.read_text(encoding="utf-8", errors="ignore")
        ):
            return name
    return None


def _go_declared_version(target: Path) -> str | None:
    """Return the version the `go-core` constant declares, or None before the first sync.

    Not `go.mod`: a Go module's version is its git tag, and the only copy in the source
    tree is the constant the `go-core` bundle ships — which is absent until the sync.
    """
    version_file = target / _GO_VERSION_FILE
    if not version_file.is_file():
        return None
    match = _GO_VERSION_CONST.search(version_file.read_text(encoding="utf-8", errors="ignore"))
    return match.group(1) if match else None


def declared_version(target: Path, language: str) -> str | None:
    """Return the version the manifest declares, or None when it declares none."""
    if language == "go":
        return _go_declared_version(target)

    manifest = target / ("Cargo.toml" if language == "rust" else "pyproject.toml")
    if not manifest.is_file():
        return None
    lines = manifest.read_text(encoding="utf-8", errors="ignore").splitlines()
    span = table_span(lines, "package" if language == "rust" else "project")
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
    and `bump-my-version` does not read `Cargo.toml`. Go writes nothing — see this
    module's docstring.
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
        path.write_text(_RUST_BUMPVERSION.format(version=version, name=name), encoding="utf-8")
        return ".bumpversion.toml"

    manifest = target / "pyproject.toml"
    text = manifest.read_text(encoding="utf-8")
    if not text.endswith("\n"):
        text += "\n"
    manifest.write_text(text + _PYTHON_BUMPVERSION.format(version=version), encoding="utf-8")
    return "pyproject.toml"


def note_bumpversion(target: Path, language: str, result: dict[str, Any]) -> None:
    """Declare the version location and record what happened in *result*, in place.

    Runs last, and only when the manifest work succeeded: the table anchors to the version
    the manifest declares, so there is nothing to write until that manifest is sound.
    """
    if not result["ok"]:
        return
    if language == "go":
        result["notes"].append(_GO_NOTE)
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
