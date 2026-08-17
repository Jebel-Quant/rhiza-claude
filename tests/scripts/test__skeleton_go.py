"""Tests for the go finisher (`scripts/_skeleton_go.py`).

`go mod init` writes exactly one file, and `go.mod` has no metadata field to fill in — so
what is under test is narrow: the package *name* derived from the module path (a Go
identifier, which is narrower than a path element), and the `doc.go` that gives revive's
`exported` rule something to find.
"""

from __future__ import annotations

import re

import _skeleton_go as go
import pytest

GO_MOD = "module github.com/jebel-quant/widget\n\ngo 1.24\n"


# --- go_module_path ----------------------------------------------------------


def test_go_module_path_is_read_from_go_mod(tmp_path):
    (tmp_path / "go.mod").write_text(GO_MOD, encoding="utf-8")
    assert go.go_module_path(tmp_path) == "github.com/jebel-quant/widget"


def test_go_module_path_without_go_mod_is_none(tmp_path):
    assert go.go_module_path(tmp_path) is None


def test_go_module_path_of_a_manifest_without_a_module_line_is_none(tmp_path):
    (tmp_path / "go.mod").write_text("go 1.24\n", encoding="utf-8")
    assert go.go_module_path(tmp_path) is None


# --- go_package_name --------------------------------------------------------


@pytest.mark.parametrize(
    ("module", "expected"),
    [
        ("github.com/jebel-quant/widget", "widget"),
        # A major-version suffix belongs to the import path, never the package name.
        ("github.com/jebel-quant/widget/v2", "widget"),
        # Package names are identifiers: no hyphens, no dots, lowercase.
        ("gitlab.com/acme/acme-tool", "acmetool"),
        ("example.com/Thing", "thing"),
        # `_` is a legal identifier character, so it survives.
        ("example.com/my_lib", "my_lib"),
        # Neither of these can start a Go identifier.
        ("example.com/---", "pkg"),
        ("example.com/2fa", "pkg"),
    ],
)
def test_go_package_name_is_an_identifier(tmp_path, module, expected):
    (tmp_path / "go.mod").write_text(f"module {module}\n\ngo 1.24\n", encoding="utf-8")
    assert go.go_package_name(tmp_path) == expected


def test_go_package_name_of_a_bare_version_module_falls_back_to_the_directory(tmp_path):
    """`module v2` has no element before the suffix — the folder is what is left."""
    (tmp_path / "go.mod").write_text("module v2\n", encoding="utf-8")
    assert go.go_package_name(tmp_path) == re.sub(r"[^a-z0-9_]", "", tmp_path.name.lower())


def test_go_package_name_falls_back_to_the_directory(tmp_path):
    assert go.go_package_name(tmp_path) == re.sub(r"[^a-z0-9_]", "", tmp_path.name.lower())


def test_the_package_fallback_is_never_main(tmp_path):
    """`package main` declares an executable in Go — the wrong thing for a library."""
    (tmp_path / "go.mod").write_text("module example.com/2fa\n", encoding="utf-8")
    assert go.go_package_name(tmp_path) == "pkg"


def test_go_package_name_of_a_trailing_slash_module(tmp_path):
    (tmp_path / "go.mod").write_text("module example.com/widget/\n", encoding="utf-8")
    assert go.go_package_name(tmp_path) == "widget"


# --- seed_package_doc -------------------------------------------------------


def test_seed_package_doc_writes_a_go_doc_convention_comment(tmp_path):
    """The first sentence must start "Package <name>" — a pasted description would not."""
    (tmp_path / "go.mod").write_text(GO_MOD, encoding="utf-8")
    assert go.seed_package_doc(tmp_path, description="A widget library") == "doc.go"
    body = (tmp_path / "doc.go").read_text(encoding="utf-8")
    assert body.startswith(
        "// Package widget is the root package of github.com/jebel-quant/widget."
    )
    assert "// A widget library." in body, "the description becomes the paragraph below"
    assert body.endswith("package widget\n")


def test_seed_package_doc_without_a_description(tmp_path):
    (tmp_path / "go.mod").write_text(GO_MOD, encoding="utf-8")
    go.seed_package_doc(tmp_path, description=None)
    assert (tmp_path / "doc.go").read_text(encoding="utf-8") == (
        "// Package widget is the root package of github.com/jebel-quant/widget.\npackage widget\n"
    )


def test_seed_package_doc_treats_a_blank_description_as_absent(tmp_path):
    (tmp_path / "go.mod").write_text(GO_MOD, encoding="utf-8")
    go.seed_package_doc(tmp_path, description="   ")
    assert (tmp_path / "doc.go").read_text(encoding="utf-8").count("//") == 1


def test_seed_package_doc_keeps_a_description_that_already_ends_in_a_full_stop(tmp_path):
    """No doubled period — the summary is a sentence either way."""
    (tmp_path / "go.mod").write_text(GO_MOD, encoding="utf-8")
    go.seed_package_doc(tmp_path, description="A widget library.")
    assert "// A widget library.\n" in (tmp_path / "doc.go").read_text(encoding="utf-8")
    assert ".." not in (tmp_path / "doc.go").read_text(encoding="utf-8")


def test_seed_package_doc_names_the_package_when_there_is_no_module_path(tmp_path):
    (tmp_path / "go.mod").write_text("go 1.24\n", encoding="utf-8")
    go.seed_package_doc(tmp_path, description=None)
    package = go.go_package_name(tmp_path)
    assert f"// Package {package} is the root package of {package}." in (
        tmp_path / "doc.go"
    ).read_text(encoding="utf-8")


def test_seed_package_doc_leaves_an_existing_root_package_alone(tmp_path):
    """A second package comment where one exists is itself a lint finding."""
    (tmp_path / "go.mod").write_text(GO_MOD, encoding="utf-8")
    (tmp_path / "widget.go").write_text(
        "// Package widget does things.\npackage widget\n", encoding="utf-8"
    )
    assert go.seed_package_doc(tmp_path, description="d") is None
    assert not (tmp_path / "doc.go").exists()


# --- finish_go --------------------------------------------------------------


def test_finish_go_writes_the_doc_and_readme(tmp_path):
    (tmp_path / "go.mod").write_text(GO_MOD, encoding="utf-8")
    result = go.finish_go(
        tmp_path, repo="widget", description="A widget library", modified=[], notes=[]
    )
    assert result["ok"]
    assert set(result["modified"]) == {"doc.go", "README.md"}
    assert result["changes"] == [], "go.mod has no keys to change"


def test_finish_go_without_a_module_fails_the_gate(tmp_path):
    result = go.finish_go(tmp_path, repo="r", description=None, modified=[], notes=[])
    assert result["ok"] is False
    assert any("go mod init" in note for note in result["notes"])


def test_finish_go_notes_an_existing_root_package(tmp_path):
    (tmp_path / "go.mod").write_text(GO_MOD, encoding="utf-8")
    (tmp_path / "widget.go").write_text(
        "// Package widget does things.\npackage widget\n", encoding="utf-8"
    )
    result = go.finish_go(tmp_path, repo="widget", description=None, modified=[], notes=[])
    assert result["ok"]
    assert any("already has Go files" in note for note in result["notes"])
