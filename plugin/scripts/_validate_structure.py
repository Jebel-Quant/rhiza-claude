#!/usr/bin/env python3
"""Does the repo have the shape its language expects? — `validate.py`'s structure half.

One rule decides everything here: **the manifest is an error, the layout is a warning.**
A Python repo without `pyproject.toml` cannot be synced at all, so that fails; a Python
repo without `tests/` is merely unusual, so that warns. Each language draws the same line
in its own vocabulary, which is why they are three functions and not one parameterised
one — Go's "`pkg` or `internal`, either will do" has no analogue in Python, and a Rust
workspace root legitimately has no crate root whatsoever.

:data:`VALIDATORS` is the registry, and it is also what `_validate_fields` consults to
decide whether a declared `language:` is one this plugin knows. Adding a language means
adding one entry here.
"""

from __future__ import annotations

import sys
from collections.abc import Callable
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _validate_log import Log  # noqa: E402


def validate_python_structure(log: Log, target: Path) -> bool:
    """Python needs pyproject.toml (required); src/ and tests/ are warnings."""
    passed = True
    if not (target / "pyproject.toml").exists():
        log.error(f"pyproject.toml not found: {target / 'pyproject.toml'}")
        log.error("pyproject.toml is required for Python projects")
        log.info(
            "Run /rhiza:init — or init_skeleton.py directly — to set the repo up, "
            "which creates a pyproject.toml"
        )
        passed = False
    else:
        log.success(f"pyproject.toml exists: {target / 'pyproject.toml'}")

    for name in ("src", "tests"):
        d = target / name
        if not d.exists():
            log.warning(f"Standard '{name}' folder not found: {d}")
            log.warning(f"Consider creating a '{name}' directory")
        else:
            log.success(f"'{name}' folder exists: {d}")
    return passed


def validate_go_structure(log: Log, target: Path) -> bool:
    """Go needs go.mod (required); cmd/ and pkg/|internal/ are warnings."""
    passed = True
    if not (target / "go.mod").exists():
        log.error(f"go.mod not found: {target / 'go.mod'}")
        log.error("go.mod is required for Go projects")
        log.info("Run 'go mod init <module-name>' to create go.mod")
        passed = False
    else:
        log.success(f"go.mod exists: {target / 'go.mod'}")

    cmd_dir, pkg_dir, internal_dir = target / "cmd", target / "pkg", target / "internal"
    if not cmd_dir.exists():
        log.warning(f"Standard 'cmd' folder not found: {cmd_dir}")
        log.warning("Consider creating a 'cmd' directory for main applications")
    else:
        log.success(f"'cmd' folder exists: {cmd_dir}")

    if not pkg_dir.exists() and not internal_dir.exists():
        log.warning("Neither 'pkg' nor 'internal' folder found")
        log.warning(
            "Consider creating 'pkg' for public libraries or 'internal' for private packages"
        )
    else:
        if pkg_dir.exists():
            log.success(f"'pkg' folder exists: {pkg_dir}")
        if internal_dir.exists():
            log.success(f"'internal' folder exists: {internal_dir}")
    return passed


def validate_rust_structure(log: Log, target: Path) -> bool:
    """Rust needs Cargo.toml (required); a src/ crate root is a warning.

    Cargo puts both library and binary crates under ``src/`` — ``src/lib.rs`` for a
    library, ``src/main.rs`` for a binary, and a workspace root may legitimately have
    neither. So the crate root is checked as a warning, not an error, and a virtual
    workspace (``[workspace]`` with no ``[package]``) is recognised rather than
    reported as a malformed crate.
    """
    manifest = target / "Cargo.toml"
    if not manifest.exists():
        log.error(f"Cargo.toml not found: {manifest}")
        log.error("Cargo.toml is required for Rust projects")
        log.info(
            "Run /rhiza:init — or init_skeleton.py directly — to set the repo up, "
            "which creates a Cargo.toml"
        )
        return False

    log.success(f"Cargo.toml exists: {manifest}")
    is_workspace_root = "[workspace]" in manifest.read_text(encoding="utf-8")

    crate_roots = [target / "src" / name for name in ("lib.rs", "main.rs")]
    found = [p for p in crate_roots if p.exists()]
    if found:
        for path in found:
            log.success(f"crate root exists: {path}")
    elif is_workspace_root:
        log.success("no src/ crate root, but Cargo.toml declares a [workspace] — fine")
    else:
        log.warning(f"Neither 'src/lib.rs' nor 'src/main.rs' found under {target / 'src'}")
        log.warning("Consider creating 'src/lib.rs' for a library or 'src/main.rs' for a binary")

    return True


# Registry of language -> structure validator; extend here to add a language. Also the
# authority `_validate_fields` uses for "is this a language we know?".
VALIDATORS: dict[str, Callable[[Log, Path], bool]] = {
    "python": validate_python_structure,
    "go": validate_go_structure,
    "rust": validate_rust_structure,
}


def check_project_structure(log: Log, target: Path, language: str) -> bool:
    """Dispatch to the language validator; unsupported languages pass with a warning."""
    log.debug(f"Validating project structure for language: {language}")
    validator = VALIDATORS.get(language.lower())
    if validator is None:
        log.warning(f"No validator found for language '{language}'")
        log.warning(f"Supported languages: {', '.join(VALIDATORS)}")
        log.warning("Skipping project structure validation")
        return True
    return validator(log, target)
