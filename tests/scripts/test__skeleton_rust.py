"""Tests for the cargo finisher (`scripts/_skeleton_rust.py`).

Two invariants, and the first is the one worth stating twice: **cargo's placeholder is
added to, never replaced.** `src/lib.rs` carries the crate's only test, so substituting
the file — which is what the Python path does to uv's stub — would delete it and leave
the template's coverage gate measuring a crate with no tests.

The second: `-D missing_docs` fires on every public item, not just the crate root, so
cargo's own `pub fn add` needs a `///` too — while a *user's* undocumented API never gets
one invented for it.
"""

from __future__ import annotations

import _skeleton_rust as rs
import pytest

# `Cargo.toml` exactly as `cargo init --lib` leaves it.
CARGO = """\
[package]
name = "acme-tool"
version = "0.1.0"
edition = "2024"

[dependencies]
"""

# `src/lib.rs` exactly as `cargo init --lib` leaves it.
CARGO_LIB = """\
pub fn add(left: u64, right: u64) -> u64 {
    left + right
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn it_works() {
        let result = add(2, 2);
        assert_eq!(result, 4);
    }
}
"""


# --- is_cargo_placeholder_lib ------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (CARGO_LIB, True),
        ("", False),
        (CARGO_LIB + "\npub fn mine() {}\n", False),
        ("//! docs\n" + CARGO_LIB, False),
    ],
)
def test_is_cargo_placeholder_lib(text, expected):
    assert rs.is_cargo_placeholder_lib(text) is expected


# --- seed_crate_docs ---------------------------------------------------------


def test_seed_crate_docs_prepends_and_keeps_the_placeholder_test(tmp_path):
    """The crate doc is prepended, never substituted — cargo's stub holds the only test."""
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "lib.rs").write_text(CARGO_LIB, encoding="utf-8")

    assert rs.seed_crate_docs(tmp_path) == ["src/lib.rs"]

    text = (tmp_path / "src" / "lib.rs").read_text(encoding="utf-8")
    assert text.startswith("//! ")
    assert "fn it_works()" in text, "cargo's placeholder test must survive"


def test_seed_crate_docs_documents_cargos_placeholder_fn(tmp_path):
    """`-D missing_docs` covers every public item, so cargo's `add` needs a `///` too.

    The crate doc alone is not enough: the template's `make docs-coverage` runs rustdoc
    with `missing_docs` denied, and cargo's own `pub fn add` is a public item. Seeding
    only the `//!` is why a crate straight out of `/rhiza:init` failed its first gate run.
    """
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "lib.rs").write_text(CARGO_LIB, encoding="utf-8")

    assert rs.seed_crate_docs(tmp_path) == ["src/lib.rs"]

    text = (tmp_path / "src" / "lib.rs").read_text(encoding="utf-8")
    before, _, after = text.partition("pub fn add(")
    assert before.splitlines()[-1].startswith("///"), before
    assert "fn it_works()" in after, "cargo's placeholder test must survive"


def test_seed_crate_docs_never_documents_the_users_own_public_api(tmp_path):
    """The `///` is cargo's stub's due, not the user's.

    Inventing a doc comment for an API this script has never read would be confidently
    wrong; failing the gate and letting them write one is the honest outcome. Anything
    cargo did not write makes :func:`is_cargo_placeholder_lib` False, which is the guard.
    """
    (tmp_path / "src").mkdir()
    theirs = "pub fn add(a: u8) -> u8 { a }\n"
    (tmp_path / "src" / "lib.rs").write_text(theirs, encoding="utf-8")

    assert rs.seed_crate_docs(tmp_path) == ["src/lib.rs"]

    text = (tmp_path / "src" / "lib.rs").read_text(encoding="utf-8")
    assert "///" not in text, "a user's function was documented on their behalf"
    assert text.endswith(theirs), "their code must be untouched below the crate doc"


def test_seed_crate_docs_handles_an_empty_crate_root(tmp_path):
    """An empty root gets the crate doc and nothing else — there is no item to document."""
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "lib.rs").write_text("", encoding="utf-8")

    assert rs.seed_crate_docs(tmp_path) == ["src/lib.rs"]
    assert (tmp_path / "src" / "lib.rs").read_text(
        encoding="utf-8"
    ) == f"//! {rs.crate_name(tmp_path)} crate.\n"


def test_seed_crate_docs_leaves_a_documented_crate_alone(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "lib.rs").write_text("//! Mine.\n\npub fn f() {}\n", encoding="utf-8")
    assert rs.seed_crate_docs(tmp_path) == []


def test_seed_crate_docs_handles_a_binary_crate(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.rs").write_text("fn main() {}\n", encoding="utf-8")
    assert rs.seed_crate_docs(tmp_path) == ["src/main.rs"]


def test_seed_crate_docs_without_a_src_directory(tmp_path):
    assert rs.seed_crate_docs(tmp_path) == []


def test_the_crate_doc_names_the_crate_not_the_directory(tmp_path):
    """`cargo init --name widget` in another folder still gets "//! widget crate."."""
    (tmp_path / "Cargo.toml").write_text(
        '[package]\nname = "widget"\nversion = "0.1.0"\n', encoding="utf-8"
    )
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "lib.rs").write_text(CARGO_LIB, encoding="utf-8")

    rs.seed_crate_docs(tmp_path)
    assert (tmp_path / "src" / "lib.rs").read_text(encoding="utf-8").startswith("//! widget crate.")


# --- crate_name / cargo_package_name -----------------------------------------


def test_crate_name_falls_back_to_the_directory(tmp_path):
    """No manifest yet (or none with a `name`) — the folder is the best guess left."""
    assert rs.crate_name(tmp_path) == tmp_path.name.replace("-", "_")
    (tmp_path / "Cargo.toml").write_text('[workspace]\nmembers = ["crates/*"]\n', encoding="utf-8")
    assert rs.crate_name(tmp_path) == tmp_path.name.replace("-", "_")


def test_crate_name_falls_back_when_the_package_table_declares_no_name(tmp_path):
    """A `[package]` table is not a guarantee of a `name`, and `name` may sit elsewhere.

    `version` in `[package]` with the name inherited from a workspace is a real shape;
    scanning past the table's end to find some other `name = ` would be worse than the
    directory fallback.
    """
    (tmp_path / "Cargo.toml").write_text(
        '[package]\nversion = "0.1.0"\n\n[dependencies.serde]\nname = "serde"\n'
    )
    assert rs.crate_name(tmp_path) == tmp_path.name.replace("-", "_")


def test_crate_name_hyphens_become_underscores(tmp_path):
    """A crate's Rust identifier is its package name with `-` mapped to `_`."""
    (tmp_path / "Cargo.toml").write_text('[package]\nname = "acme-tool"\n', encoding="utf-8")
    assert rs.crate_name(tmp_path) == "acme_tool"


def test_cargo_package_name_without_a_manifest_is_none(tmp_path):
    assert rs.cargo_package_name(tmp_path) is None


# --- set_cargo_keys ----------------------------------------------------------


def test_set_cargo_keys_appends_below_name_and_version():
    out, added = rs.set_cargo_keys(CARGO, {"description": '"d"'})
    assert added == ["description"]
    lines = [line for line in out.splitlines() if line.strip()]
    assert lines.index('name = "acme-tool"') < lines.index('description = "d"')
    assert lines.index('description = "d"') < lines.index("[dependencies]")


def test_set_cargo_keys_adds_only_missing_keys_and_is_idempotent():
    wanted = {"description": '"d"', "repository": '"u"'}
    once, added = rs.set_cargo_keys(CARGO, wanted)
    assert set(added) == {"description", "repository"}
    twice, added_again = rs.set_cargo_keys(once, wanted)
    assert added_again == []
    assert twice == once


def test_set_cargo_keys_never_overwrites_a_hand_written_value():
    manifest = CARGO.replace("edition", 'description = "mine"\nedition')
    out, added = rs.set_cargo_keys(manifest, {"description": '"theirs"'})
    assert added == []
    assert '"mine"' in out and '"theirs"' not in out


def test_set_cargo_keys_requires_a_package_table():
    """A manifest with no `[package]` is a virtual workspace — report, don't invent one."""
    with pytest.raises(ValueError, match=r"\[package\]"):
        rs.set_cargo_keys("[workspace]\nmembers = []\n", {"description": '"d"'})


def test_set_cargo_keys_preserves_the_absence_of_a_trailing_newline():
    """A manifest not ending in a newline must not grow one."""
    text = '[package]\nname = "x"'
    new_text, added = rs.set_cargo_keys(text, {"edition": '"2021"'})
    assert added == ["edition"]
    assert not new_text.endswith("\n")


def test_set_cargo_keys_keeps_a_trailing_newline_when_there_was_one():
    text = '[package]\nname = "x"\n'
    new_text, _ = rs.set_cargo_keys(text, {"edition": '"2021"'})
    assert new_text.endswith("\n")


# --- fill_cargo_manifest -----------------------------------------------------


def test_fill_cargo_manifest_omits_description_when_there_is_none(tmp_path):
    """`description` is the one optional key — absent means absent, not empty-string."""
    (tmp_path / "Cargo.toml").write_text(
        '[package]\nname = "x"\nversion = "0.1.0"\n', encoding="utf-8"
    )
    result = rs.fill_cargo_manifest(
        tmp_path,
        owner="acme",
        repo="widget",
        domain="github.com",
        description=None,
        modified=[],
        notes=[],
    )
    assert result["ok"] is True
    assert "description" not in (tmp_path / "Cargo.toml").read_text(encoding="utf-8")


def test_fill_cargo_manifest_reports_an_absent_manifest(tmp_path):
    result = rs.fill_cargo_manifest(
        tmp_path, owner="o", repo="r", domain="github.com", description=None,
        modified=[], notes=[],
    )  # fmt: skip
    assert result["ok"] is False
    assert any("cargo init --lib" in note for note in result["notes"])


def test_fill_cargo_manifest_reports_a_workspace_root(tmp_path):
    """A virtual workspace has no [package] to fill in — say so instead of crashing."""
    (tmp_path / "Cargo.toml").write_text('[workspace]\nmembers = ["crates/*"]\n', encoding="utf-8")
    result = rs.fill_cargo_manifest(
        tmp_path, owner="o", repo="r", domain="github.com", description=None,
        modified=[], notes=[],
    )  # fmt: skip
    assert result["ok"] is False
    assert any("[package]" in note for note in result["notes"])
