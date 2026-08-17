"""Tests for the language structure checks (`scripts/_validate_structure.py`).

The rule being tested throughout: **the manifest is an error, the layout is a warning.**
Getting that backwards in either direction is the interesting failure — a missing
`pyproject.toml` that only warns lets a repo be synced that cannot be, and a missing
`tests/` that errors refuses a repo that is merely young.
"""

from __future__ import annotations

import _validate_structure as vs
import pytest
from _validate_log import Log


def log() -> Log:
    """A verbose sink, so debug lines are exercised too."""
    return Log(verbose=True)


def test_python_structure(tmp_path):
    lg = log()
    assert vs.validate_python_structure(lg, tmp_path) is False  # no pyproject
    (tmp_path / "pyproject.toml").write_text("[project]\n", encoding="utf-8")
    (tmp_path / "src").mkdir()
    (tmp_path / "tests").mkdir()
    lg2 = log()
    assert vs.validate_python_structure(lg2, tmp_path) is True
    assert not lg2.warnings  # src + tests present → no warnings


def test_go_structure(tmp_path):
    lg = log()
    assert vs.validate_go_structure(lg, tmp_path) is False  # no go.mod, warns on cmd/pkg
    (tmp_path / "go.mod").write_text("module x\n", encoding="utf-8")
    (tmp_path / "cmd").mkdir()
    (tmp_path / "pkg").mkdir()
    (tmp_path / "internal").mkdir()
    lg2 = log()
    assert vs.validate_go_structure(lg2, tmp_path) is True


@pytest.mark.parametrize("present", ["pkg", "internal"])
def test_go_structure_accepts_either_package_folder_alone(tmp_path, present):
    """`pkg` or `internal` — either satisfies the layout; both were always present before.

    The rule is "not neither", so each folder's success path has to be reachable on its
    own, not only when the other is there too.
    """
    (tmp_path / "go.mod").write_text("module x\n", encoding="utf-8")
    (tmp_path / present).mkdir()
    lg = log()
    assert vs.validate_go_structure(lg, tmp_path) is True


def test_rust_structure(tmp_path):
    lg = log()
    assert vs.validate_rust_structure(lg, tmp_path) is False  # no Cargo.toml
    (tmp_path / "Cargo.toml").write_text("[package]\nname = 'x'\n", encoding="utf-8")
    lg2 = log()
    assert vs.validate_rust_structure(lg2, tmp_path) is True  # manifest is enough to pass
    assert any("lib.rs" in w for w in lg2.warnings)  # ...but the missing crate root warns

    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "lib.rs").write_text("//! x\n", encoding="utf-8")
    lg3 = log()
    assert vs.validate_rust_structure(lg3, tmp_path) is True
    assert not lg3.warnings


def test_rust_workspace_root_needs_no_crate_root(tmp_path):
    """A virtual workspace has a Cargo.toml and deliberately no src/ — not a warning."""
    (tmp_path / "Cargo.toml").write_text('[workspace]\nmembers = ["crates/*"]\n', encoding="utf-8")
    lg = log()
    assert vs.validate_rust_structure(lg, tmp_path) is True
    assert not lg.warnings


def test_rust_structure_reports_a_binary_crate_root(tmp_path):
    """`src/main.rs` is as valid a crate root as `src/lib.rs`."""
    (tmp_path / "Cargo.toml").write_text("[package]\nname = 'x'\n", encoding="utf-8")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.rs").write_text("fn main() {}\n", encoding="utf-8")
    lg = log()
    assert vs.validate_rust_structure(lg, tmp_path) is True
    assert not lg.warnings


def test_check_project_structure_unknown_language(tmp_path):
    lg = log()
    assert vs.check_project_structure(lg, tmp_path, "cobol") is True
    assert lg.warnings


def test_check_project_structure_is_case_insensitive(tmp_path):
    """A `language: Python` pointer must reach the Python validator, not the fallback."""
    lg = log()
    assert vs.check_project_structure(lg, tmp_path, "Python") is False  # no pyproject
    assert any("pyproject.toml" in e for e in lg.errors)


def test_the_registry_is_the_one_list_of_supported_languages():
    """`_validate_fields` reads this to judge a declared `language:` — keep them in step."""
    assert set(vs.VALIDATORS) == {"python", "go", "rust"}
