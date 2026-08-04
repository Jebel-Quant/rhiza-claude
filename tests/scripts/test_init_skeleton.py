"""Tests for the skeleton dispatcher (`scripts/init_skeleton.py`) behind `/rhiza:skeleton`.

What is under test here is the **dispatch and the CLI**: that each language reaches its own
finisher, that the version location is declared last for all three, and that the summary
becomes the right exit code and output. Each finisher's own behaviour is asserted in the
module mirroring it — `test__skeleton_python.py`, `test__skeleton_rust.py`,
`test__skeleton_go.py`, `test__skeleton_version.py`.

The end-to-end blocks are the exception, and they belong here because they exercise the
whole chain through the CLI: everything above asserts against an initialiser's stub as
written down in a fixture, while these assert against the stub `uv`, `cargo` and `go`
actually produced — the only way placeholder recognition can be trusted, since each tool
is free to change what it writes.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import _skeleton_common as common
import _skeleton_version as ver
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

_WITHOUT_AUTHORS = _UV_PYPROJECT.replace(
    'authors = [\n    { name = "A Dev", email = "dev@example.com" }\n]\n', ""
)

# `Cargo.toml` and `src/lib.rs` exactly as `cargo init --lib` leaves them.
_CARGO = '[package]\nname = "acme-tool"\nversion = "0.1.0"\nedition = "2024"\n\n[dependencies]\n'
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

_GO_MOD = "module github.com/jebel-quant/widget\n\ngo 1.24\n"


# --- the python path, end to end --------------------------------------------


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
    (tmp_path / "pyproject.toml").write_text(_WITHOUT_AUTHORS)
    summary = sk.finish_skeleton(tmp_path, owner="o", repo="r", host="github", description=None)
    assert summary["ok"]
    assert any("authors" in n for n in summary["notes"])


def test_finish_skeleton_does_not_flag_present_authors(tmp_path):
    (tmp_path / "pyproject.toml").write_text(_UV_PYPROJECT)
    summary = sk.finish_skeleton(tmp_path, owner="o", repo="r", host="github", description=None)
    assert not any("authors" in n for n in summary["notes"])


def test_finish_skeleton_falls_back_to_the_owner_without_a_git_identity(tmp_path, monkeypatch):
    """No git identity anywhere is the CI case — the gate still needs a named author."""
    (tmp_path / "pyproject.toml").write_text(_WITHOUT_AUTHORS)
    monkeypatch.setattr(common, "git_identity", lambda _t: (None, None))

    summary = sk.finish_skeleton(
        tmp_path, owner="jebel-quant", repo="acme-tool", host="github", description="d"
    )

    assert "authors" in summary["changes"]
    assert 'name = "jebel-quant"' in (tmp_path / "pyproject.toml").read_text()


def test_finish_skeleton_prefers_the_git_identity(tmp_path, monkeypatch):
    (tmp_path / "pyproject.toml").write_text(_WITHOUT_AUTHORS)
    monkeypatch.setattr(common, "git_identity", lambda _t: ("Ada Lovelace", "ada@example.com"))

    sk.finish_skeleton(tmp_path, owner="jebel-quant", repo="r", host="github", description="d")

    text = (tmp_path / "pyproject.toml").read_text()
    assert 'name = "Ada Lovelace", email = "ada@example.com"' in text


# --- the rust path, end to end ----------------------------------------------


def test_finish_skeleton_rust_fills_the_manifest_and_writes_a_readme(tmp_path, monkeypatch):
    (tmp_path / "Cargo.toml").write_text(_CARGO)
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "lib.rs").write_text(_CARGO_LIB)
    monkeypatch.setattr(common, "git_identity", lambda _t: ("Ada Lovelace", "ada@example.com"))

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
    monkeypatch.setattr(common, "git_identity", lambda _t: ("A", None))
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


# --- the go path, end to end ------------------------------------------------


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


# --- the version location is declared for every language --------------------


def test_finish_skeleton_declares_the_version_location_for_python(tmp_path):
    (tmp_path / "pyproject.toml").write_text(_UV_PYPROJECT)
    result = sk.finish_skeleton(
        tmp_path, owner="acme", repo="widget", host="github", description="d"
    )
    assert result["ok"]
    assert "tool.bumpversion" in result["changes"]
    assert ver.bumpversion_config(tmp_path) == "pyproject.toml"


def test_finish_skeleton_declares_the_version_location_for_rust(tmp_path):
    (tmp_path / "Cargo.toml").write_text(_CARGO)
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "lib.rs").write_text(_CARGO_LIB)
    result = sk.finish_skeleton(
        tmp_path, owner="acme", repo="acme-tool", host="github", description="d", language="rust"
    )
    assert result["ok"]
    assert ver.bumpversion_config(tmp_path) == ".bumpversion.toml"


def test_finish_skeleton_go_says_where_the_version_location_comes_from(tmp_path):
    (tmp_path / "go.mod").write_text(_GO_MOD)
    result = sk.finish_skeleton(
        tmp_path, owner="a", repo="b", host="github", description=None, language="go"
    )
    assert any("arrives with the first /rhiza:update" in note for note in result["notes"])
    assert "tool.bumpversion" not in result["changes"]


@pytest.mark.parametrize("language", ["python", "rust", "go"])
def test_a_directory_named_like_the_manifest_fails_the_gate(tmp_path, language):
    """`exists()` would let a *directory* named go.mod pass, then read as absent."""
    manifest = {"python": "pyproject.toml", "rust": "Cargo.toml", "go": "go.mod"}[language]
    (tmp_path / manifest).mkdir()
    result = sk.finish_skeleton(
        tmp_path, owner="a", repo="b", host="github", description=None, language=language
    )
    assert result["ok"] is False
    assert any("absent" in note for note in result["notes"])


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


# --- end-to-end: a real crate from `cargo init --lib` -------------------------


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


def test_e2e_a_real_crate_has_no_undocumented_public_item_left(rust_crate):
    """Both items `cargo init` leaves bare are documented, against the real stub.

    This is the cheap stand-in for `make docs-coverage`, which needs rustup and a network
    fetch and so cannot run here. It caught a crate that `/rhiza:init` produced and then
    could not get through its own gate: the `//!` was seeded, the `pub fn add` was not.
    """
    lib = (rust_crate / "src" / "lib.rs").read_text()
    assert lib.startswith("//! widget crate."), lib[:80]
    before, sep, _ = lib.partition("pub fn add(")
    assert sep, f"cargo's placeholder changed shape:\n{lib}"
    assert before.splitlines()[-1].startswith("///"), before


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


def test_e2e_the_skeleton_finisher_is_idempotent_on_a_real_crate(
    rust_crate, tmp_path, plugin_scripts: Path
):
    """Running it twice must change nothing — /init can be re-run after a failed step."""
    copy = tmp_path / "widget"
    shutil.copytree(rust_crate, copy)
    before = (copy / "Cargo.toml").read_text(), (copy / "src" / "lib.rs").read_text()
    scripts = plugin_scripts
    assert_ok(
        run_cmd(
            [*PY, str(scripts / "init_skeleton.py"), str(copy), "--language", "rust",
             "--owner", "jebel-quant", "--repo", "widget", "--description", "Anything else."],
            copy,
        ),
        "init_skeleton (second run)",
    )  # fmt: skip
    assert ((copy / "Cargo.toml").read_text(), (copy / "src" / "lib.rs").read_text()) == before


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
    assert ver.bumpversion_config(go_module) is None


# --- end-to-end: a real package from `uv init --lib` --------------------------
#
# The Python counterpart of the two blocks above, and the last language to get one. Every
# other Python end-to-end fixture seeds a module and a mirrored test by hand before
# asserting anything, for good reasons of its own — with the side effect that the tree a
# bare `/init` leaves had never been looked at. `python_package` is that tree.


def test_e2e_the_placeholder_uv_writes_is_replaced_not_appended_to(python_package):
    """uv's `__init__.py` is a stub with a `hello()` in it; the skeleton substitutes it.

    The opposite of the Rust path, which must *preserve* cargo's stub because cargo's
    carries the crate's only test. Worth asserting side by side: the two languages differ
    here on purpose, and a change that unified them would silently break one of them.
    """
    init_py = (python_package / "src" / "widget" / "__init__.py").read_text()
    assert "def hello()" not in init_py, f"uv's placeholder survived:\n{init_py}"
    assert init_py.startswith('"""'), init_py[:80]


def test_e2e_the_metadata_uv_leaves_as_a_placeholder_is_filled_in(python_package):
    """`uv init` writes "Add your description here" and no URLs at all."""
    manifest = (python_package / "pyproject.toml").read_text()
    assert "Add your description here" not in manifest
    assert 'Homepage = "https://github.com/jebel-quant/widget"' in manifest
    assert 'Repository = "https://github.com/jebel-quant/widget"' in manifest
    assert "[dependency-groups]" in manifest


def test_e2e_the_python_version_reaches_the_real_package(python_package):
    """/init applies it through `/python-version`, so the classifiers are its evidence."""
    manifest = (python_package / "pyproject.toml").read_text()
    assert 'requires-python = ">=3.12"' in manifest
    assert "Programming Language :: Python :: 3.12" in manifest
    assert (python_package / ".python-version").read_text().strip() == "3.12"


def test_e2e_the_version_location_for_python_is_the_manifest_itself(python_package):
    """No `.bumpversion.toml`: `[project] version` is the location, unlike Rust and Go."""
    assert not (python_package / ".bumpversion.toml").exists()
    assert ver.bumpversion_config(python_package) == "pyproject.toml"
    assert "[tool.bumpversion]" in (python_package / "pyproject.toml").read_text()


def test_e2e_a_fresh_python_package_has_no_test_of_its_own(python_package):
    """The cause of the vacuous `make test` gate, recorded next to where it originates.

    `uv init --lib` writes no test and `/init` seeds no first module — deliberately: the
    package is empty by design, and `/init`'s own report says so. Both halves are fine on
    their own; together they mean the `test` gate the sync delivers has nothing to collect.
    The effect is pinned in `test_check_make_targets.py`; this is the antecedent, and if a
    future skeleton *does* seed a test, this is the test that says so out loud.
    """
    assert not list(python_package.glob("tests/**/*.py")), "a test appeared; the gap may be closed"
    assert (python_package / "src" / "widget" / "__init__.py").is_file()


def test_e2e_the_skeleton_finisher_is_idempotent_on_a_real_package(
    python_package, tmp_path, plugin_scripts: Path
):
    """The Python half of the Rust idempotence check — /init can be re-run after a failure."""
    copy = tmp_path / "widget"
    shutil.copytree(python_package, copy)
    before = (copy / "pyproject.toml").read_text()
    assert_ok(
        run_cmd(
            [*PY, str(plugin_scripts / "init_skeleton.py"), str(copy), "--language", "python",
             "--owner", "jebel-quant", "--repo", "widget", "--description", "Anything else."],
            copy,
        ),
        "init_skeleton (second run)",
    )  # fmt: skip
    assert (copy / "pyproject.toml").read_text() == before
