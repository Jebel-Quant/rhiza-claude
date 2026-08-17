"""Tests for the version-location declaration (`scripts/_skeleton_version.py`).

Written by a script rather than by the procedure's prose because the failure is
**silent**: with no discoverable config, bump-my-version falls back to `git describe` and a
release can be cut at a version that already exists. The template's
`test_a_discoverable_config_exists` gate (rhiza v1.3.0) fails on its absence.
"""

from __future__ import annotations

import _skeleton_version as ver
import pytest

GO_MOD = "module github.com/jebel-quant/widget\n\ngo 1.24\n"


# --- bumpversion_config ------------------------------------------------------


def test_bumpversion_config_is_found_only_where_the_tool_looks(tmp_path):
    """`.rhiza/.cfg.toml` is not one of the files bump-my-version searches."""
    assert ver.bumpversion_config(tmp_path) is None
    (tmp_path / ".rhiza").mkdir()
    (tmp_path / ".rhiza" / ".cfg.toml").write_text(
        "[tool.bumpversion]\ncurrent_version = '1'\n", encoding="utf-8"
    )
    assert ver.bumpversion_config(tmp_path) is None
    (tmp_path / "pyproject.toml").write_text(
        "[tool.bumpversion]\ncurrent_version = '1'\n", encoding="utf-8"
    )
    assert ver.bumpversion_config(tmp_path) == "pyproject.toml"


def test_bumpversion_config_accepts_the_legacy_ini_spelling(tmp_path):
    (tmp_path / "setup.cfg").write_text(
        "[bumpversion]\ncurrent_version = 1.0.0\n", encoding="utf-8"
    )
    assert ver.bumpversion_config(tmp_path) == "setup.cfg"


def test_bumpversion_config_ignores_a_file_without_the_section(tmp_path):
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "x"\n', encoding="utf-8")
    assert ver.bumpversion_config(tmp_path) is None


# --- declared_version --------------------------------------------------------


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
    (tmp_path / manifest).write_text(body, encoding="utf-8")
    assert ver.declared_version(tmp_path, language) == expected


def test_declared_version_without_a_manifest_is_none(tmp_path):
    assert ver.declared_version(tmp_path, "python") is None


def test_declared_version_for_go_reads_the_synced_constant(tmp_path):
    """After the sync there *is* a version in the tree: the constant go-core ships."""
    assert ver.declared_version(tmp_path, "go") is None
    version_file = tmp_path / "internal" / "version" / "version.go"
    version_file.parent.mkdir(parents=True)
    version_file.write_text('package version\n\nconst Version = "1.2.3"\n', encoding="utf-8")
    assert ver.declared_version(tmp_path, "go") == "1.2.3"


def test_declared_version_for_go_without_the_constant_is_none(tmp_path):
    version_file = tmp_path / "internal" / "version" / "version.go"
    version_file.parent.mkdir(parents=True)
    version_file.write_text("package version\n", encoding="utf-8")
    assert ver.declared_version(tmp_path, "go") is None


# --- seed_bumpversion_config -------------------------------------------------


def test_seeding_appends_the_table_to_pyproject(tmp_path):
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "x"\nversion = "1.2.3"\n', encoding="utf-8"
    )
    assert ver.seed_bumpversion_config(tmp_path, "python") == "pyproject.toml"
    body = (tmp_path / "pyproject.toml").read_text(encoding="utf-8")
    assert '[tool.bumpversion]\ncurrent_version = "1.2.3"' in body
    # Anchored to [project], or it would also rewrite an unrelated table's version.
    assert r"search = " + "'" + r"(?ms)^\[project\]" in body
    assert "{current_version}" in body, "bump-my-version's own placeholder must survive"


def test_seeding_writes_bumpversion_toml_for_a_crate(tmp_path):
    (tmp_path / "Cargo.toml").write_text(
        '[package]\nname = "acme-tool"\nversion = "0.1.0"\n', encoding="utf-8"
    )
    assert ver.seed_bumpversion_config(tmp_path, "rust") == ".bumpversion.toml"
    body = (tmp_path / ".bumpversion.toml").read_text(encoding="utf-8")
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
    assert ver.seed_bumpversion_config(tmp_path, "python") is None
    assert 'current_version = "9.9.9"' in (tmp_path / "pyproject.toml").read_text(encoding="utf-8")


def test_seeding_a_crate_that_already_declares_it_elsewhere_is_a_no_op(tmp_path):
    (tmp_path / "Cargo.toml").write_text(
        '[package]\nname = "x"\nversion = "0.1.0"\n', encoding="utf-8"
    )
    (tmp_path / ".bumpversion.cfg").write_text(
        "[bumpversion]\ncurrent_version = 0.1.0\n", encoding="utf-8"
    )
    assert ver.seed_bumpversion_config(tmp_path, "rust") is None


def test_seeding_needs_a_version_to_anchor_to(tmp_path):
    """No declared version means no table: `current_version` would have nothing to match."""
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "x"\n', encoding="utf-8")
    assert ver.seed_bumpversion_config(tmp_path, "python") is None


def test_a_crate_with_no_package_name_falls_back_to_the_directory(tmp_path):
    """`cargo generate-lockfile` needs a name; a malformed manifest still gets a config."""
    (tmp_path / "Cargo.toml").write_text('[package]\nversion = "0.1.0"\n', encoding="utf-8")
    assert ver.seed_bumpversion_config(tmp_path, "rust") == ".bumpversion.toml"
    assert f'name = "{tmp_path.name}"' in (tmp_path / ".bumpversion.toml").read_text(
        encoding="utf-8"
    )


def test_seeding_a_pyproject_without_a_trailing_newline_still_parses(tmp_path):
    """Appending straight onto the last line would fuse it with `[tool.bumpversion]`."""
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "x"\nversion = "1.0.0"', encoding="utf-8"
    )
    assert ver.seed_bumpversion_config(tmp_path, "python") == "pyproject.toml"
    body = (tmp_path / "pyproject.toml").read_text(encoding="utf-8")
    assert '\nversion = "1.0.0"\n' in body
    assert "\n[tool.bumpversion]\n" in body


def test_go_gets_no_bumpversion_config(tmp_path):
    """`go-core` ships its own root `.bumpversion.toml`; ours would be overwritten.

    Upstream's omits `current_version` on purpose — a Go module's version is its git tag —
    so writing a copy here would also inject a key the template deliberately leaves out.
    """
    (tmp_path / "go.mod").write_text(GO_MOD, encoding="utf-8")
    assert ver.seed_bumpversion_config(tmp_path, "go") is None
    assert not (tmp_path / ".bumpversion.toml").exists()


# --- note_bumpversion --------------------------------------------------------


def test_note_bumpversion_says_nothing_when_the_manifest_work_failed(tmp_path):
    """A failed manifest edit means there is no version to anchor to — stay quiet."""
    result = {"modified": [], "changes": [], "notes": [], "ok": False}
    ver.note_bumpversion(tmp_path, "python", result)
    assert result["notes"] == []


def test_note_bumpversion_reports_an_existing_declaration(tmp_path):
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nversion = "1.0.0"\n\n[tool.bumpversion]\ncurrent_version = "1.0.0"\n'
    )
    result = {"modified": [], "changes": [], "notes": [], "ok": True}
    ver.note_bumpversion(tmp_path, "python", result)
    assert any("already declared in pyproject.toml" in n for n in result["notes"])
    assert result["changes"] == []


def test_note_bumpversion_reports_that_nothing_could_be_declared(tmp_path):
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "x"\n', encoding="utf-8")
    result = {"modified": [], "changes": [], "notes": [], "ok": True}
    ver.note_bumpversion(tmp_path, "python", result)
    assert any("no version declared in the manifest" in n for n in result["notes"])


def test_note_bumpversion_does_not_list_pyproject_twice(tmp_path):
    """It is usually already in `modified` from the metadata edits."""
    (tmp_path / "pyproject.toml").write_text('[project]\nversion = "1.0.0"\n', encoding="utf-8")
    result = {"modified": ["pyproject.toml"], "changes": [], "notes": [], "ok": True}
    ver.note_bumpversion(tmp_path, "python", result)
    assert result["modified"] == ["pyproject.toml"]
    assert "tool.bumpversion" in result["changes"]


def test_note_bumpversion_explains_where_gos_comes_from(tmp_path):
    result = {"modified": [], "changes": [], "notes": [], "ok": True}
    ver.note_bumpversion(tmp_path, "go", result)
    assert any("arrives with the first /rhiza:update" in n for n in result["notes"])
    assert result["changes"] == []
