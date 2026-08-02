"""Tests for the skeleton finisher (`scripts/init_skeleton.py`) behind `/rhiza:skeleton`.

`uv init --lib` creates the project; this script closes the gap between that and the
`[project]` shape the rhiza template's synced pyproject gate requires. It must be
idempotent, additive, and must never write a `classifiers` key.
"""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

import init_skeleton as sk
import pytest
from conftest import PY, assert_ok, run_cmd

# `pyproject.toml` exactly as `uv init --lib --python 3.12` leaves it.
_UV_PYPROJECT = """\
[project]
name = "acme-tool"
version = "0.1.0"
description = "Add your description here"
readme = "README.md"
authors = [
    { name = "A Dev", email = "dev@example.com" }
]
requires-python = ">=3.12"
dependencies = []

[build-system]
requires = ["uv_build>=0.11.28,<0.12.0"]
build-backend = "uv_build"
"""

# `src/<pkg>/__init__.py` exactly as `uv init --lib` leaves it.
_UV_INIT = 'def hello() -> str:\n    return "Hello from acme-tool!"\n'


# --- is_uv_placeholder_init --------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (_UV_INIT, True),
        ('def hello() -> str:\n\n    return "Hello from x!"\n', True),  # blank lines ignored
        ('"""acme_tool package."""\n', False),  # already normalised
        ("", False),  # empty file is not the placeholder
        (_UV_INIT + "\nimport os\n", False),  # user added something
        ('def hello() -> str:\n    return "Hello!"\n\ndef other() -> None:\n    pass\n', False),
    ],
)
def test_is_uv_placeholder_init(text, expected):
    assert sk.is_uv_placeholder_init(text) is expected


# --- normalize_package_init --------------------------------------------------


def test_normalize_package_init_rewrites_placeholder(tmp_path):
    pkg = tmp_path / "src" / "acme_tool"
    pkg.mkdir(parents=True)
    (pkg / "__init__.py").write_text(_UV_INIT)
    assert sk.normalize_package_init(tmp_path) == ["src/acme_tool/__init__.py"]
    assert (pkg / "__init__.py").read_text() == '"""acme_tool package."""\n'


def test_normalize_package_init_leaves_real_code_alone(tmp_path):
    pkg = tmp_path / "src" / "acme_tool"
    pkg.mkdir(parents=True)
    real = '"""My own docstring."""\n\nVERSION = "1"\n'
    (pkg / "__init__.py").write_text(real)
    assert sk.normalize_package_init(tmp_path) == []
    assert (pkg / "__init__.py").read_text() == real


def test_normalize_package_init_without_src(tmp_path):
    assert sk.normalize_package_init(tmp_path) == []


# --- seed_readme --------------------------------------------------------------


def test_seed_readme_fills_the_empty_file_uv_leaves(tmp_path):
    """`uv init --lib` writes README.md with zero bytes; the template rejects that."""
    (tmp_path / "README.md").write_text("")

    assert sk.seed_readme(tmp_path, repo="widget", description="A widget.") is True

    body = (tmp_path / "README.md").read_text()
    assert body.startswith("# widget\n")
    assert "A widget." in body


def test_seed_readme_never_overwrites_a_real_readme(tmp_path):
    """/rhiza:docs owns the README; finding its work replaced would be the worst bug."""
    (tmp_path / "README.md").write_text("# Hand-written\n\nCarefully worded.\n")

    assert sk.seed_readme(tmp_path, repo="widget", description="A widget.") is False
    assert (tmp_path / "README.md").read_text() == "# Hand-written\n\nCarefully worded.\n"


def test_seed_readme_treats_whitespace_only_as_empty(tmp_path):
    (tmp_path / "README.md").write_text("\n\n   \n")
    assert sk.seed_readme(tmp_path, repo="widget", description=None) is True
    assert (tmp_path / "README.md").read_text().startswith("# widget\n")


def test_seed_readme_does_not_create_an_absent_readme(tmp_path):
    """Absence is a different finding, which the template reports on its own."""
    assert sk.seed_readme(tmp_path, repo="widget", description=None) is False
    assert not (tmp_path / "README.md").exists()


def test_seed_readme_writes_no_code_blocks(tmp_path):
    """The same template test *executes* fenced blocks it finds in the README."""
    (tmp_path / "README.md").write_text("")
    sk.seed_readme(tmp_path, repo="widget", description="A widget.")
    assert "```" not in (tmp_path / "README.md").read_text()


# --- set_authors -------------------------------------------------------------


def test_set_authors_inserts_when_uv_omitted_the_key():
    """`uv init` writes no `authors` at all when git has no configured identity."""
    without = _UV_PYPROJECT.replace(
        'authors = [\n    { name = "A Dev", email = "dev@example.com" }\n]\n', ""
    )
    out, changed = sk.set_authors(without, name="Ada", email="ada@example.com")
    assert changed
    assert 'authors = [{ name = "Ada", email = "ada@example.com" }]' in out


def test_set_authors_replaces_uvs_empty_list():
    empty = _UV_PYPROJECT.replace(
        'authors = [\n    { name = "A Dev", email = "dev@example.com" }\n]', "authors = []"
    )
    out, changed = sk.set_authors(empty, name="Ada", email=None)
    assert changed
    assert 'authors = [{ name = "Ada" }]' in out
    assert "authors = []" not in out


def test_set_authors_leaves_a_real_author_alone():
    """A hand-written author is the user's; the gate only needs one to exist."""
    out, changed = sk.set_authors(_UV_PYPROJECT, name="Ada", email="ada@example.com")
    assert not changed
    assert out == _UV_PYPROJECT
    assert "Ada" not in out


def test_set_authors_omits_an_absent_email():
    without = _UV_PYPROJECT.replace(
        'authors = [\n    { name = "A Dev", email = "dev@example.com" }\n]\n', ""
    )
    out, _ = sk.set_authors(without, name="jebel-quant", email=None)
    assert 'authors = [{ name = "jebel-quant" }]' in out
    assert "email" not in out.split("authors")[1].split("]")[0]


def test_set_authors_preserves_missing_trailing_newline():
    without = _UV_PYPROJECT.replace(
        'authors = [\n    { name = "A Dev", email = "dev@example.com" }\n]\n', ""
    ).rstrip("\n")
    out, changed = sk.set_authors(without, name="Ada", email=None)
    assert changed
    assert not out.endswith("\n")


def test_finish_skeleton_falls_back_to_the_owner_without_a_git_identity(tmp_path, monkeypatch):
    """No git identity anywhere is the CI case — the gate still needs a named author."""
    without = _UV_PYPROJECT.replace(
        'authors = [\n    { name = "A Dev", email = "dev@example.com" }\n]\n', ""
    )
    (tmp_path / "pyproject.toml").write_text(without)
    monkeypatch.setattr(sk, "git_identity", lambda _t: (None, None))

    summary = sk.finish_skeleton(
        tmp_path, owner="jebel-quant", repo="acme-tool", host="github", description="d"
    )

    assert "authors" in summary["changes"]
    assert 'name = "jebel-quant"' in (tmp_path / "pyproject.toml").read_text()


def test_finish_skeleton_prefers_the_git_identity(tmp_path, monkeypatch):
    without = _UV_PYPROJECT.replace(
        'authors = [\n    { name = "A Dev", email = "dev@example.com" }\n]\n', ""
    )
    (tmp_path / "pyproject.toml").write_text(without)
    monkeypatch.setattr(sk, "git_identity", lambda _t: ("Ada Lovelace", "ada@example.com"))

    sk.finish_skeleton(tmp_path, owner="jebel-quant", repo="r", host="github", description="d")

    text = (tmp_path / "pyproject.toml").read_text()
    assert 'name = "Ada Lovelace", email = "ada@example.com"' in text


def test_git_identity_reads_the_repo_config(tmp_path):
    import subprocess as sp

    sp.run(["git", "init", "-q", "-b", "main", "."], cwd=tmp_path, check=True)
    sp.run(["git", "config", "user.name", "Grace"], cwd=tmp_path, check=True)
    sp.run(["git", "config", "user.email", "grace@example.com"], cwd=tmp_path, check=True)
    assert sk.git_identity(tmp_path) == ("Grace", "grace@example.com")


# --- set_description ---------------------------------------------------------


def test_set_description_replaces_uv_placeholder():
    out, changed = sk.set_description(_UV_PYPROJECT, "Does acme things.")
    assert changed
    assert 'description = "Does acme things."' in out
    assert "Add your description here" not in out


def test_set_description_keeps_a_real_description():
    written = _UV_PYPROJECT.replace("Add your description here", "Hand-written.")
    out, changed = sk.set_description(written, "Something else.")
    assert not changed
    assert out == written


def test_set_description_inserts_when_absent():
    without = _UV_PYPROJECT.replace('description = "Add your description here"\n', "")
    out, changed = sk.set_description(without, "Freshly added.")
    assert changed
    assert 'description = "Freshly added."' in out


def test_set_description_preserves_missing_trailing_newline():
    out, changed = sk.set_description(_UV_PYPROJECT.rstrip("\n"), "No newline.")
    assert changed
    assert not out.endswith("\n")


def test_set_description_requires_project_table():
    with pytest.raises(ValueError):
        sk.set_description("[build-system]\nrequires = []\n", "x")


# --- set_project_urls --------------------------------------------------------


def test_set_project_urls_appends_the_table():
    out, changed = sk.set_project_urls(_UV_PYPROJECT, "https://h/o/r", "https://r/o/r")
    assert changed
    assert "[project.urls]" in out
    assert 'Homepage = "https://h/o/r"' in out
    assert 'Repository = "https://r/o/r"' in out


def test_set_project_urls_adds_only_missing_keys():
    partial = _UV_PYPROJECT + '\n[project.urls]\nHomepage = "https://kept"\n'
    out, changed = sk.set_project_urls(partial, "https://new", "https://repo")
    assert changed
    assert 'Homepage = "https://kept"' in out  # existing entry wins
    assert "https://new" not in out
    assert 'Repository = "https://repo"' in out


def test_set_project_urls_is_idempotent():
    once, _ = sk.set_project_urls(_UV_PYPROJECT, "https://h", "https://r")
    twice, changed = sk.set_project_urls(once, "https://h", "https://r")
    assert not changed
    assert twice == once


def test_set_project_urls_collapses_trailing_blank_lines():
    """An appended table gets exactly one blank line before it, not a pile of them."""
    out, changed = sk.set_project_urls(_UV_PYPROJECT + "\n\n\n", "https://h", "https://r")
    assert changed
    assert 'build-backend = "uv_build"\n\n[project.urls]' in out


def test_set_project_urls_preserves_missing_trailing_newline():
    out, changed = sk.set_project_urls(_UV_PYPROJECT.rstrip("\n"), "https://h", "https://r")
    assert changed
    assert not out.endswith("\n")


# --- set_dependency_groups ---------------------------------------------------


def test_set_dependency_groups_appends_the_table():
    out, changed = sk.set_dependency_groups(_UV_PYPROJECT)
    assert changed
    assert "[dependency-groups]" in out
    assert "pytest>=8.0" in out
    assert "ruff>=0.6" in out


def test_set_dependency_groups_adds_only_missing_groups():
    partial = _UV_PYPROJECT + '\n[dependency-groups]\ntest = ["pytest>=7.0"]\n'
    out, changed = sk.set_dependency_groups(partial)
    assert changed
    assert 'test = ["pytest>=7.0"]' in out  # existing group untouched
    assert out.count("test = ") == 1
    assert "ruff>=0.6" in out


def test_set_dependency_groups_is_idempotent():
    once, _ = sk.set_dependency_groups(_UV_PYPROJECT)
    twice, changed = sk.set_dependency_groups(once)
    assert not changed
    assert twice == once


def test_set_dependency_groups_preserves_missing_trailing_newline():
    out, changed = sk.set_dependency_groups(_UV_PYPROJECT.rstrip("\n"))
    assert changed
    assert not out.endswith("\n")


def test_dependency_group_requirements_are_lower_bounded():
    for deps in sk._DEPENDENCY_GROUPS.values():
        for dep in deps:
            assert ">=" in dep, f"{dep} must carry a lower bound"


# --- no classifiers, ever ----------------------------------------------------


def test_finish_skeleton_never_writes_classifiers(tmp_path):
    """Classifiers belong to /python-version (Python) and nobody (License ::).

    PEP 639 replaced `License :: …` with the SPDX `license` field, so neither this
    script nor /rhiza:license may write one — even though the template's pyproject
    gate still asserts it.
    """
    (tmp_path / "pyproject.toml").write_text(_UV_PYPROJECT)
    sk.finish_skeleton(tmp_path, owner="o", repo="r", host="github", description="d")
    text = (tmp_path / "pyproject.toml").read_text()
    assert "classifiers" not in text
    assert "License ::" not in text


# --- finish_skeleton() end to end -------------------------------------------


def test_finish_skeleton_completes_a_uv_project(tmp_path):
    (tmp_path / "pyproject.toml").write_text(_UV_PYPROJECT)
    pkg = tmp_path / "src" / "acme_tool"
    pkg.mkdir(parents=True)
    (pkg / "__init__.py").write_text(_UV_INIT)

    summary = sk.finish_skeleton(
        tmp_path, owner="jebel-quant", repo="acme-tool", host="github", description="Acme things."
    )

    assert summary["ok"]
    assert set(summary["modified"]) == {"src/acme_tool/__init__.py", "pyproject.toml"}
    assert summary["changes"] == [
        "description",
        "project.urls",
        "dependency-groups",
        "tool.bumpversion",
    ]
    text = (tmp_path / "pyproject.toml").read_text()
    assert 'description = "Acme things."' in text
    assert 'Homepage = "https://github.com/jebel-quant/acme-tool"' in text
    assert "[dependency-groups]" in text
    assert (pkg / "__init__.py").read_text() == '"""acme_tool package."""\n'


def test_finish_skeleton_reports_the_seeded_readme(tmp_path):
    """The README is part of the skeleton's output, so it shows in `modified`."""
    (tmp_path / "pyproject.toml").write_text(_UV_PYPROJECT)
    (tmp_path / "README.md").write_text("")

    summary = sk.finish_skeleton(
        tmp_path, owner="jebel-quant", repo="acme-tool", host="github", description="Acme things."
    )

    assert "README.md" in summary["modified"]
    assert any("README" in n for n in summary["notes"])
    assert (tmp_path / "README.md").read_text().startswith("# acme-tool\n")


def test_finish_skeleton_is_idempotent(tmp_path):
    (tmp_path / "pyproject.toml").write_text(_UV_PYPROJECT)
    kwargs = {"owner": "o", "repo": "r", "host": "github", "description": "d"}
    sk.finish_skeleton(tmp_path, **kwargs)
    first = (tmp_path / "pyproject.toml").read_text()

    second_summary = sk.finish_skeleton(tmp_path, **kwargs)
    assert second_summary["modified"] == []
    assert second_summary["changes"] == []
    assert any("already rhiza-shaped" in n for n in second_summary["notes"])
    assert (tmp_path / "pyproject.toml").read_text() == first


def test_finish_skeleton_uses_the_gitlab_host(tmp_path):
    (tmp_path / "pyproject.toml").write_text(_UV_PYPROJECT)
    sk.finish_skeleton(tmp_path, owner="grp", repo="proj", host="gitlab", description=None)
    assert "https://gitlab.com/grp/proj" in (tmp_path / "pyproject.toml").read_text()


def test_finish_skeleton_without_pyproject_reports_not_ok(tmp_path):
    summary = sk.finish_skeleton(tmp_path, owner="o", repo="r", host="github", description="d")
    assert not summary["ok"]
    assert any("uv init --lib" in n for n in summary["notes"])


def test_finish_skeleton_without_project_table_reports_not_ok(tmp_path):
    (tmp_path / "pyproject.toml").write_text("[build-system]\nrequires = []\n")
    summary = sk.finish_skeleton(tmp_path, owner="o", repo="r", host="github", description="d")
    assert not summary["ok"]
    assert any("no [project] table" in n for n in summary["notes"])


def test_finish_skeleton_flags_absent_authors(tmp_path):
    without = _UV_PYPROJECT.replace(
        'authors = [\n    { name = "A Dev", email = "dev@example.com" }\n]\n', ""
    )
    (tmp_path / "pyproject.toml").write_text(without)
    summary = sk.finish_skeleton(tmp_path, owner="o", repo="r", host="github", description=None)
    assert summary["ok"]
    assert any("authors" in n for n in summary["notes"])


def test_finish_skeleton_does_not_flag_present_authors(tmp_path):
    (tmp_path / "pyproject.toml").write_text(_UV_PYPROJECT)
    summary = sk.finish_skeleton(tmp_path, owner="o", repo="r", host="github", description=None)
    assert not any("authors" in n for n in summary["notes"])


# --- main() / CLI -----------------------------------------------------------


def test_main_json_output(tmp_path, capsys):
    (tmp_path / "pyproject.toml").write_text(_UV_PYPROJECT)
    rc = sk.main([str(tmp_path), "--owner", "o", "--repo", "r", "--json"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"]
    assert "project.urls" in payload["changes"]


def test_main_text_output(tmp_path, capsys):
    (tmp_path / "pyproject.toml").write_text(_UV_PYPROJECT)
    rc = sk.main([str(tmp_path), "--owner", "o", "--repo", "r", "--description", "Text mode."])
    assert rc == 0
    captured = capsys.readouterr()
    assert "modified pyproject.toml" in captured.out
    assert "note" in captured.err


def test_main_exits_1_without_a_pyproject(tmp_path, capsys):
    rc = sk.main([str(tmp_path), "--owner", "o", "--repo", "r"])
    assert rc == 1
    assert "uv init --lib" in capsys.readouterr().err


# --- rust ------------------------------------------------------------------

# `Cargo.toml` exactly as `cargo init --lib` leaves it.
_CARGO = """\
[package]
name = "acme-tool"
version = "0.1.0"
edition = "2024"

[dependencies]
"""

# `src/lib.rs` exactly as `cargo init --lib` leaves it.
_CARGO_LIB = """\
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


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (_CARGO_LIB, True),
        ("", False),
        (_CARGO_LIB + "\npub fn mine() {}\n", False),
        ("//! docs\n" + _CARGO_LIB, False),
    ],
)
def test_is_cargo_placeholder_lib(text, expected):
    assert sk.is_cargo_placeholder_lib(text) is expected


def test_seed_crate_docs_prepends_and_keeps_the_placeholder_test(tmp_path):
    """The crate doc is prepended, never substituted — cargo's stub holds the only test."""
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "lib.rs").write_text(_CARGO_LIB)

    assert sk.seed_crate_docs(tmp_path) == ["src/lib.rs"]

    text = (tmp_path / "src" / "lib.rs").read_text()
    assert text.startswith("//! ")
    assert "fn it_works()" in text, "cargo's placeholder test must survive"


def test_seed_crate_docs_leaves_a_documented_crate_alone(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "lib.rs").write_text("//! Mine.\n\npub fn f() {}\n")
    assert sk.seed_crate_docs(tmp_path) == []


def test_seed_crate_docs_handles_a_binary_crate(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.rs").write_text("fn main() {}\n")
    assert sk.seed_crate_docs(tmp_path) == ["src/main.rs"]


def test_the_crate_doc_names_the_crate_not_the_directory(tmp_path):
    """`cargo init --name widget` in another folder still gets "//! widget crate."."""
    (tmp_path / "Cargo.toml").write_text('[package]\nname = "widget"\nversion = "0.1.0"\n')
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "lib.rs").write_text(_CARGO_LIB)

    sk.seed_crate_docs(tmp_path)
    assert (tmp_path / "src" / "lib.rs").read_text().startswith("//! widget crate.")


def test_crate_name_falls_back_to_the_directory(tmp_path):
    """No manifest yet (or none with a `name`) — the folder is the best guess left."""
    assert sk.crate_name(tmp_path) == tmp_path.name.replace("-", "_")
    (tmp_path / "Cargo.toml").write_text('[workspace]\nmembers = ["crates/*"]\n')
    assert sk.crate_name(tmp_path) == tmp_path.name.replace("-", "_")


def test_crate_name_falls_back_when_the_package_table_declares_no_name(tmp_path):
    """A `[package]` table is not a guarantee of a `name`, and `name` may sit elsewhere.

    `version` in `[package]` with the name inherited from a workspace is a real shape;
    scanning past the table's end to find some other `name = ` would be worse than the
    directory fallback.
    """
    (tmp_path / "Cargo.toml").write_text(
        '[package]\nversion = "0.1.0"\n\n[dependencies.serde]\nname = "serde"\n'
    )
    assert sk.crate_name(tmp_path) == tmp_path.name.replace("-", "_")


def test_crate_name_hyphens_become_underscores(tmp_path):
    """A crate's Rust identifier is its package name with `-` mapped to `_`."""
    (tmp_path / "Cargo.toml").write_text('[package]\nname = "acme-tool"\n')
    assert sk.crate_name(tmp_path) == "acme_tool"


def test_set_cargo_keys_appends_below_name_and_version():
    out, added = sk.set_cargo_keys(_CARGO, {"description": '"d"'})
    assert added == ["description"]
    lines = [line for line in out.splitlines() if line.strip()]
    assert lines.index('name = "acme-tool"') < lines.index('description = "d"')
    assert lines.index('description = "d"') < lines.index("[dependencies]")


def test_set_cargo_keys_adds_only_missing_keys_and_is_idempotent():
    wanted = {"description": '"d"', "repository": '"u"'}
    once, added = sk.set_cargo_keys(_CARGO, wanted)
    assert set(added) == {"description", "repository"}
    twice, added_again = sk.set_cargo_keys(once, wanted)
    assert added_again == []
    assert twice == once


def test_set_cargo_keys_never_overwrites_a_hand_written_value():
    manifest = _CARGO.replace("edition", 'description = "mine"\nedition')
    out, added = sk.set_cargo_keys(manifest, {"description": '"theirs"'})
    assert added == []
    assert '"mine"' in out and '"theirs"' not in out


def test_set_cargo_keys_requires_a_package_table():
    with pytest.raises(ValueError, match=r"\[package\]"):
        sk.set_cargo_keys("[workspace]\nmembers = []\n", {"description": '"d"'})


def test_finish_skeleton_rust_fills_the_manifest_and_writes_a_readme(tmp_path, monkeypatch):
    (tmp_path / "Cargo.toml").write_text(_CARGO)
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "lib.rs").write_text(_CARGO_LIB)
    monkeypatch.setattr(sk, "git_identity", lambda _t: ("Ada Lovelace", "ada@example.com"))

    summary = sk.finish_skeleton(
        tmp_path,
        owner="jebel-quant",
        repo="acme-tool",
        host="github",
        description="A crate.",
        language="rust",
    )

    assert summary["ok"]
    manifest = (tmp_path / "Cargo.toml").read_text()
    assert 'authors = ["Ada Lovelace <ada@example.com>"]' in manifest
    assert 'repository = "https://github.com/jebel-quant/acme-tool"' in manifest
    assert 'description = "A crate."' in manifest
    # cargo writes no README at all, so unlike the uv path this one creates it.
    assert (tmp_path / "README.md").read_text().startswith("# acme-tool")


def test_finish_skeleton_rust_is_idempotent(tmp_path, monkeypatch):
    (tmp_path / "Cargo.toml").write_text(_CARGO)
    monkeypatch.setattr(sk, "git_identity", lambda _t: ("A", None))
    kwargs = {
        "owner": "o",
        "repo": "r",
        "host": "github",
        "description": "d",
        "language": "rust",
    }
    sk.finish_skeleton(tmp_path, **kwargs)
    once = (tmp_path / "Cargo.toml").read_text()
    summary = sk.finish_skeleton(tmp_path, **kwargs)
    assert (tmp_path / "Cargo.toml").read_text() == once
    assert "already rhiza-shaped" in " ".join(summary["notes"])


def test_finish_skeleton_rust_exits_1_without_a_manifest(tmp_path, capsys):
    rc = sk.main([str(tmp_path), "--owner", "o", "--repo", "r", "--language", "rust"])
    assert rc == 1
    assert "cargo init --lib" in capsys.readouterr().err


def test_finish_skeleton_rust_reports_a_workspace_root_manifest(tmp_path):
    """A virtual workspace has no [package] to fill in — say so instead of crashing."""
    (tmp_path / "Cargo.toml").write_text('[workspace]\nmembers = ["crates/*"]\n')
    summary = sk.finish_skeleton(
        tmp_path, owner="o", repo="r", host="github", description="d", language="rust"
    )
    assert summary["ok"] is False
    assert any("[package]" in note for note in summary["notes"])


# --- branch coverage: the arms line coverage could not see ---------------------


def test_project_block_ends_at_eof_when_it_is_the_last_table():
    """`[project]` with nothing after it — the loop exhausts instead of breaking.

    The break path was covered; this one falls through to `end = len(lines)`, which is
    where an off-by-one would quietly eat or keep a line.
    """
    lines = ["[project]", 'name = "x"', 'version = "0.1"']
    header, end = sk._project_block(lines)
    assert (header, end) == (0, 3)


def test_table_block_ends_at_eof_when_it_is_the_last_table():
    lines = ["[package]", 'name = "x"']
    assert sk._table_block(lines, "package", "Cargo.toml") == (0, 2)


def test_set_cargo_keys_preserves_the_absence_of_a_trailing_newline():
    """A manifest not ending in a newline must not grow one."""
    text = '[package]\nname = "x"'
    new_text, added = sk.set_cargo_keys(text, {"edition": '"2021"'})
    assert added == ["edition"]
    assert not new_text.endswith("\n")


def test_set_cargo_keys_keeps_a_trailing_newline_when_there_was_one():
    text = '[package]\nname = "x"\n'
    new_text, _ = sk.set_cargo_keys(text, {"edition": '"2021"'})
    assert new_text.endswith("\n")


def test_finish_cargo_omits_description_when_there_is_none(tmp_path):
    """`description` is the one optional key — absent means absent, not empty-string."""
    (tmp_path / "Cargo.toml").write_text('[package]\nname = "x"\nversion = "0.1.0"\n')
    result = sk._finish_cargo(
        tmp_path,
        owner="acme",
        repo="widget",
        host_domain="github.com",
        description=None,
        modified=[],
        notes=[],
    )
    assert result["ok"] is True
    assert "description" not in (tmp_path / "Cargo.toml").read_text()


# --- end-to-end: a real crate from `cargo init --lib` -------------------------
#
# Everything above asserts against cargo's stub as written down here. These assert
# against the stub cargo actually produced, which is the only way the placeholder
# recognition can be trusted: `is_cargo_placeholder_lib` matches an exact set of lines,
# and cargo is free to change them.


def test_e2e_the_crate_doc_is_prepended_and_cargos_only_test_survives(rust_crate):
    """The single most destructive thing this script could do, checked for real.

    Cargo's `src/lib.rs` carries the crate's only test. Substituting the file — which is
    what the Python path does to uv's placeholder — would delete it, and the template's
    coverage gate would then measure a crate with no tests.
    """
    lib = (rust_crate / "src" / "lib.rs").read_text()
    assert lib.startswith("//! widget crate."), lib[:80]
    assert "fn it_works()" in lib, "cargo's placeholder test was lost"
    assert "pub fn add(left: u64, right: u64) -> u64" in lib


def test_e2e_the_readme_cargo_never_writes_is_seeded(rust_crate):
    """`cargo init` creates no README at all, and `/rhiza:docs` needs one to own."""
    readme = (rust_crate / "README.md").read_text()
    assert readme.startswith("# widget")
    assert "/rhiza:docs" in readme


def test_e2e_the_package_metadata_cargo_omits_is_filled_in(rust_crate):
    """`cargo init --lib` writes only name/version/edition."""
    manifest = (rust_crate / "Cargo.toml").read_text()
    for key in ("repository", "homepage", "authors", "description"):
        assert f"{key} = " in manifest, f"Cargo.toml lacks {key}:\n{manifest}"
    assert 'repository = "https://github.com/jebel-quant/widget"' in manifest
    # cargo's own keys are left exactly where cargo put them.
    lines = [line.strip() for line in manifest.splitlines() if line.strip()]
    assert lines[0] == "[package]"
    assert lines[1] == 'name = "widget"'


def test_e2e_the_skeleton_finisher_is_idempotent_on_a_real_crate(rust_crate, tmp_path):
    """Running it twice must change nothing — /init can be re-run after a failed step."""
    copy = tmp_path / "widget"
    shutil.copytree(rust_crate, copy)
    before = (copy / "Cargo.toml").read_text(), (copy / "src" / "lib.rs").read_text()
    scripts = Path(__file__).resolve().parent.parent / "scripts"
    assert_ok(
        run_cmd(
            [*PY, str(scripts / "init_skeleton.py"), str(copy), "--language", "rust",
             "--owner", "jebel-quant", "--repo", "widget", "--description", "Anything else."],
            copy,
        ),
        "init_skeleton (second run)",
    )  # fmt: skip
    assert ((copy / "Cargo.toml").read_text(), (copy / "src" / "lib.rs").read_text()) == before


# --- the version location, for /rhiza:release ---------------------------------
#
# Written by the script rather than by the procedure's prose because the failure is
# silent: with no discoverable config, bump-my-version falls back to `git describe` and a
# release can be cut at a version that already exists. The template's
# test_a_discoverable_config_exists gate (rhiza v1.3.0) fails on its absence.


def test_bumpversion_config_is_found_only_where_the_tool_looks(tmp_path):
    """`.rhiza/.cfg.toml` is not one of the files bump-my-version searches."""
    assert sk.bumpversion_config(tmp_path) is None
    (tmp_path / ".rhiza").mkdir()
    (tmp_path / ".rhiza" / ".cfg.toml").write_text("[tool.bumpversion]\ncurrent_version = '1'\n")
    assert sk.bumpversion_config(tmp_path) is None
    (tmp_path / "pyproject.toml").write_text("[tool.bumpversion]\ncurrent_version = '1'\n")
    assert sk.bumpversion_config(tmp_path) == "pyproject.toml"


def test_bumpversion_config_accepts_the_legacy_ini_spelling(tmp_path):
    (tmp_path / "setup.cfg").write_text("[bumpversion]\ncurrent_version = 1.0.0\n")
    assert sk.bumpversion_config(tmp_path) == "setup.cfg"


def test_bumpversion_config_ignores_a_file_without_the_section(tmp_path):
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "x"\n')
    assert sk.bumpversion_config(tmp_path) is None


@pytest.mark.parametrize(
    ("language", "manifest", "body", "expected"),
    [
        ("python", "pyproject.toml", '[project]\nname = "x"\nversion = "1.2.3"\n', "1.2.3"),
        ("rust", "Cargo.toml", '[package]\nname = "x"\nversion = "0.4.0"\n', "0.4.0"),
        ("python", "pyproject.toml", '[project]\nname = "x"\n', None),  # no version declared
        ("rust", "Cargo.toml", "[workspace]\nmembers = []\n", None),  # no [package] table
    ],
)
def test_declared_version_reads_the_manifests_own_table(
    tmp_path, language, manifest, body, expected
):
    (tmp_path / manifest).write_text(body)
    assert sk.declared_version(tmp_path, language) == expected


def test_declared_version_without_a_manifest_is_none(tmp_path):
    assert sk.declared_version(tmp_path, "python") is None


def test_seeding_appends_the_table_to_pyproject(tmp_path):
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "x"\nversion = "1.2.3"\n')
    assert sk.seed_bumpversion_config(tmp_path, "python") == "pyproject.toml"
    body = (tmp_path / "pyproject.toml").read_text()
    assert '[tool.bumpversion]\ncurrent_version = "1.2.3"' in body
    # Anchored to [project], or it would also rewrite an unrelated table's version.
    assert r"search = " + "'" + r"(?ms)^\[project\]" in body
    assert "{current_version}" in body, "bump-my-version's own placeholder must survive"


def test_seeding_writes_bumpversion_toml_for_a_crate(tmp_path):
    (tmp_path / "Cargo.toml").write_text('[package]\nname = "acme-tool"\nversion = "0.1.0"\n')
    assert sk.seed_bumpversion_config(tmp_path, "rust") == ".bumpversion.toml"
    body = (tmp_path / ".bumpversion.toml").read_text()
    assert 'current_version = "0.1.0"' in body
    assert 'filename = "Cargo.toml"' in body
    # The lock entry must be a regex, or its `\n` is matched literally and it silently
    # does nothing — leaving the lockfile stale after a release.
    assert 'filename = "Cargo.lock"' in body
    lock_entry = body.split('filename = "Cargo.lock"')[1]
    assert "regex = true" in lock_entry
    assert "replace = " in lock_entry
    # The package name as the manifest writes it: Cargo.lock keeps the hyphens.
    assert 'name = "acme-tool"' in lock_entry


def test_seeding_is_idempotent_and_never_overwrites_the_users_config(tmp_path):
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "x"\nversion = "1.2.3"\n\n'
        '[tool.bumpversion]\ncurrent_version = "9.9.9"\n'
    )
    assert sk.seed_bumpversion_config(tmp_path, "python") is None
    assert 'current_version = "9.9.9"' in (tmp_path / "pyproject.toml").read_text()


def test_seeding_a_crate_that_already_declares_it_elsewhere_is_a_no_op(tmp_path):
    (tmp_path / "Cargo.toml").write_text('[package]\nname = "x"\nversion = "0.1.0"\n')
    (tmp_path / ".bumpversion.cfg").write_text("[bumpversion]\ncurrent_version = 0.1.0\n")
    assert sk.seed_bumpversion_config(tmp_path, "rust") is None


def test_seeding_needs_a_version_to_anchor_to(tmp_path):
    """No declared version means no table: `current_version` would have nothing to match."""
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "x"\n')
    assert sk.seed_bumpversion_config(tmp_path, "python") is None


def test_a_crate_with_no_package_name_falls_back_to_the_directory(tmp_path):
    """`cargo generate-lockfile` needs a name; a malformed manifest still gets a config."""
    (tmp_path / "Cargo.toml").write_text('[package]\nversion = "0.1.0"\n')
    assert sk.seed_bumpversion_config(tmp_path, "rust") == ".bumpversion.toml"
    assert f'name = "{tmp_path.name}"' in (tmp_path / ".bumpversion.toml").read_text()


def test_note_bumpversion_says_nothing_when_the_manifest_work_failed(tmp_path):
    """A failed manifest edit means there is no version to anchor to — stay quiet."""
    result = {"modified": [], "changes": [], "notes": [], "ok": False}
    sk._note_bumpversion(tmp_path, "python", result)
    assert result["notes"] == []


def test_note_bumpversion_reports_an_existing_declaration(tmp_path):
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nversion = "1.0.0"\n\n[tool.bumpversion]\ncurrent_version = "1.0.0"\n'
    )
    result = {"modified": [], "changes": [], "notes": [], "ok": True}
    sk._note_bumpversion(tmp_path, "python", result)
    assert any("already declared in pyproject.toml" in n for n in result["notes"])
    assert result["changes"] == []


def test_note_bumpversion_reports_that_nothing_could_be_declared(tmp_path):
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "x"\n')
    result = {"modified": [], "changes": [], "notes": [], "ok": True}
    sk._note_bumpversion(tmp_path, "python", result)
    assert any("no version declared in the manifest" in n for n in result["notes"])


def test_note_bumpversion_does_not_list_pyproject_twice(tmp_path):
    """It is usually already in `modified` from the metadata edits."""
    (tmp_path / "pyproject.toml").write_text('[project]\nversion = "1.0.0"\n')
    result = {"modified": ["pyproject.toml"], "changes": [], "notes": [], "ok": True}
    sk._note_bumpversion(tmp_path, "python", result)
    assert result["modified"] == ["pyproject.toml"]
    assert "tool.bumpversion" in result["changes"]


def test_finish_skeleton_declares_the_version_location_for_python(tmp_path):
    (tmp_path / "pyproject.toml").write_text(_UV_PYPROJECT)
    result = sk.finish_skeleton(
        tmp_path, owner="acme", repo="widget", host="github", description="d"
    )
    assert result["ok"]
    assert "tool.bumpversion" in result["changes"]
    assert sk.bumpversion_config(tmp_path) == "pyproject.toml"


def test_finish_skeleton_declares_the_version_location_for_rust(tmp_path):
    (tmp_path / "Cargo.toml").write_text(_CARGO)
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "lib.rs").write_text(_CARGO_LIB)
    result = sk.finish_skeleton(
        tmp_path, owner="acme", repo="acme-tool", host="github", description="d", language="rust"
    )
    assert result["ok"]
    assert sk.bumpversion_config(tmp_path) == ".bumpversion.toml"


def test_seeding_a_pyproject_without_a_trailing_newline_still_parses(tmp_path):
    """Appending straight onto the last line would fuse it with `[tool.bumpversion]`."""
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "x"\nversion = "1.0.0"')
    assert sk.seed_bumpversion_config(tmp_path, "python") == "pyproject.toml"
    body = (tmp_path / "pyproject.toml").read_text()
    assert '\nversion = "1.0.0"\n' in body
    assert "\n[tool.bumpversion]\n" in body


# --- Go: the shortest path, because `go.mod` has nothing to fill in -----------

_GO_MOD = "module github.com/jebel-quant/widget\n\ngo 1.24\n"


def test_go_module_path_is_read_from_go_mod(tmp_path):
    (tmp_path / "go.mod").write_text(_GO_MOD)
    assert sk.go_module_path(tmp_path) == "github.com/jebel-quant/widget"


def test_go_module_path_without_go_mod_is_none(tmp_path):
    assert sk.go_module_path(tmp_path) is None


def test_go_module_path_of_a_manifest_without_a_module_line_is_none(tmp_path):
    (tmp_path / "go.mod").write_text("go 1.24\n")
    assert sk.go_module_path(tmp_path) is None


@pytest.mark.parametrize(
    ("module", "expected"),
    [
        ("github.com/jebel-quant/widget", "widget"),
        # A major-version suffix belongs to the import path, never the package name.
        ("github.com/jebel-quant/widget/v2", "widget"),
        # Package names are identifiers: no hyphens, no dots, lowercase.
        ("gitlab.com/acme/acme-tool", "acmetool"),
        ("example.com/Thing", "thing"),
        ("example.com/---", "main"),  # degenerate: no identifier characters left
    ],
)
def test_go_package_name_is_an_identifier(tmp_path, module, expected):
    (tmp_path / "go.mod").write_text(f"module {module}\n\ngo 1.24\n")
    assert sk.go_package_name(tmp_path) == expected


def test_go_package_name_of_a_bare_version_module_falls_back_to_the_directory(tmp_path):
    """`module v2` has no element before the suffix — the folder is what is left."""
    (tmp_path / "go.mod").write_text("module v2\n")
    assert sk.go_package_name(tmp_path) == re.sub(r"[^a-z0-9]", "", tmp_path.name.lower())


def test_go_package_name_falls_back_to_the_directory(tmp_path):
    assert sk.go_package_name(tmp_path) == re.sub(r"[^a-z0-9]", "", tmp_path.name.lower())


def test_seed_package_doc_writes_a_go_doc_convention_comment(tmp_path):
    """The first sentence must start "Package <name>" — a pasted description would not."""
    (tmp_path / "go.mod").write_text(_GO_MOD)
    assert sk.seed_package_doc(tmp_path, description="A widget library") == "doc.go"
    body = (tmp_path / "doc.go").read_text()
    assert body.startswith(
        "// Package widget is the root package of github.com/jebel-quant/widget."
    )
    assert "// A widget library." in body, "the description becomes the paragraph below"
    assert body.endswith("package widget\n")


def test_seed_package_doc_without_a_description(tmp_path):
    (tmp_path / "go.mod").write_text(_GO_MOD)
    sk.seed_package_doc(tmp_path, description=None)
    assert (tmp_path / "doc.go").read_text() == (
        "// Package widget is the root package of github.com/jebel-quant/widget.\npackage widget\n"
    )


def test_seed_package_doc_leaves_an_existing_root_package_alone(tmp_path):
    """A second package comment where one exists is itself a lint finding."""
    (tmp_path / "go.mod").write_text(_GO_MOD)
    (tmp_path / "widget.go").write_text("// Package widget does things.\npackage widget\n")
    assert sk.seed_package_doc(tmp_path, description="d") is None
    assert not (tmp_path / "doc.go").exists()


def test_finish_skeleton_go_writes_the_doc_and_readme(tmp_path):
    (tmp_path / "go.mod").write_text(_GO_MOD)
    result = sk.finish_skeleton(
        tmp_path, owner="jebel-quant", repo="widget", host="github",
        description="A widget library", language="go",
    )  # fmt: skip
    assert result["ok"]
    assert set(result["modified"]) == {"doc.go", "README.md"}
    assert (tmp_path / "README.md").read_text().startswith("# widget")


def test_finish_skeleton_go_without_a_module_fails_the_gate(tmp_path):
    result = sk.finish_skeleton(
        tmp_path, owner="a", repo="b", host="github", description=None, language="go"
    )
    assert result["ok"] is False
    assert any("go mod init" in note for note in result["notes"])


def test_finish_skeleton_go_reports_a_module_without_a_path(tmp_path):
    (tmp_path / "go.mod").write_text("go 1.24\n")
    result = sk.finish_skeleton(
        tmp_path, owner="a", repo="b", host="github", description=None, language="go"
    )
    assert any("declares no module path" in note for note in result["notes"])


def test_finish_skeleton_go_is_idempotent(tmp_path):
    (tmp_path / "go.mod").write_text(_GO_MOD)
    kwargs = {
        "owner": "jebel-quant", "repo": "widget", "host": "github",
        "description": "A widget library", "language": "go",
    }  # fmt: skip
    sk.finish_skeleton(tmp_path, **kwargs)
    before = (tmp_path / "doc.go").read_text(), (tmp_path / "README.md").read_text()
    second = sk.finish_skeleton(tmp_path, **kwargs)
    assert second["modified"] == []
    assert ((tmp_path / "doc.go").read_text(), (tmp_path / "README.md").read_text()) == before


# --- Go's version location belongs to the template, not to us -----------------


def test_go_gets_no_bumpversion_config(tmp_path):
    """`go-core` ships its own root `.bumpversion.toml`; ours would be overwritten.

    Upstream's omits `current_version` on purpose — a Go module's version is its git tag —
    so writing a copy here would also inject a key the template deliberately leaves out.
    """
    (tmp_path / "go.mod").write_text(_GO_MOD)
    assert sk.seed_bumpversion_config(tmp_path, "go") is None
    assert not (tmp_path / ".bumpversion.toml").exists()


def test_finish_skeleton_go_says_where_the_version_location_comes_from(tmp_path):
    (tmp_path / "go.mod").write_text(_GO_MOD)
    result = sk.finish_skeleton(
        tmp_path, owner="a", repo="b", host="github", description=None, language="go"
    )
    assert any("arrives with the first /rhiza:update" in note for note in result["notes"])
    assert "tool.bumpversion" not in result["changes"]


def test_declared_version_for_go_reads_the_synced_constant(tmp_path):
    """After the sync there *is* a version in the tree: the constant go-core ships."""
    assert sk.declared_version(tmp_path, "go") is None
    version_file = tmp_path / "internal" / "version" / "version.go"
    version_file.parent.mkdir(parents=True)
    version_file.write_text('package version\n\nconst Version = "1.2.3"\n')
    assert sk.declared_version(tmp_path, "go") == "1.2.3"


def test_declared_version_for_go_without_the_constant_is_none(tmp_path):
    version_file = tmp_path / "internal" / "version" / "version.go"
    version_file.parent.mkdir(parents=True)
    version_file.write_text("package version\n")
    assert sk.declared_version(tmp_path, "go") is None


# --- end-to-end: a real module from `go mod init` -----------------------------


def test_e2e_the_module_gets_the_package_doc_go_mod_init_omits(go_module):
    """`go mod init` writes one file; without a Go file there is nothing to document."""
    doc = (go_module / "doc.go").read_text()
    assert doc.startswith("// Package widget is the root package of github.com/jebel-quant/widget.")
    assert doc.rstrip().endswith("package widget")


def test_e2e_the_module_compiles_and_vets_clean(go_module):
    """The package the skeleton wrote has to be real Go, not plausible-looking Go."""
    assert_ok(run_cmd(["go", "vet", "./..."], go_module), "go vet")
    assert_ok(run_cmd(["gofmt", "-l", "."], go_module), "gofmt -l")
    assert run_cmd(["gofmt", "-l", "."], go_module).stdout.strip() == "", (
        "doc.go is not gofmt-clean"
    )


def test_e2e_the_readme_go_never_writes_is_seeded(go_module):
    assert (go_module / "README.md").read_text().startswith("# widget")


def test_e2e_go_mod_is_left_exactly_as_go_wrote_it(go_module):
    """There is no metadata to add: `go.mod` has no description, URL or licence field."""
    body = (go_module / "go.mod").read_text()
    assert body.startswith("module github.com/jebel-quant/widget")
    for key in ("description", "repository", "homepage", "authors", "license"):
        assert key not in body, f"{key} is not a go.mod field"


def test_e2e_no_version_location_is_written_for_go(go_module):
    """It belongs to `go-core` and arrives with the sync — ours would be overwritten."""
    assert not (go_module / ".bumpversion.toml").exists()
    assert sk.bumpversion_config(go_module) is None


def test_seed_package_doc_keeps_a_description_that_already_ends_in_a_full_stop(tmp_path):
    """No doubled period — the summary is a sentence either way."""
    (tmp_path / "go.mod").write_text(_GO_MOD)
    sk.seed_package_doc(tmp_path, description="A widget library.")
    assert "// A widget library.\n" in (tmp_path / "doc.go").read_text()
    assert ".." not in (tmp_path / "doc.go").read_text()
