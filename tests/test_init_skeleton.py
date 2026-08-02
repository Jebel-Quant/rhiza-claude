"""Tests for the skeleton finisher (`scripts/init_skeleton.py`) behind `/rhiza:skeleton`.

`uv init --lib` creates the project; this script closes the gap between that and the
`[project]` shape the rhiza template's synced pyproject gate requires. It must be
idempotent, additive, and must never write a `classifiers` key.
"""

from __future__ import annotations

import json

import init_skeleton as sk
import pytest

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
    assert summary["changes"] == ["description", "project.urls", "dependency-groups"]
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
