"""Tests for the license engine (`scripts/set_license.py`) behind `/rhiza:license`."""

from __future__ import annotations

import json

import pytest
import set_license as sl

# A minimal pyproject.toml as `uv init --lib` would leave it.
_PYPROJECT = """\
[project]
name = "widget"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = []

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"
"""


# --- bundled texts ----------------------------------------------------------


def test_bundled_licenses_includes_offered_set():
    bundled = sl.bundled_licenses()
    assert {"MIT", "Apache-2.0", "BSD-3-Clause"} <= set(bundled)


def test_render_license_mit_substitutes_year_and_holder():
    out = sl.render_license("MIT", "acme", "2026")
    assert out is not None
    assert "MIT License" in out
    assert "Copyright (c) 2026 acme" in out
    assert "{year}" not in out and "{holder}" not in out


def test_render_license_apache_is_verbatim():
    out = sl.render_license("Apache-2.0", "acme", "2026")
    assert out is not None and "Apache License" in out and "Version 2.0" in out


def test_render_license_unknown_returns_none():
    assert sl.render_license("WTFPL", "acme", "2026") is None


# --- set_license_metadata ---------------------------------------------------


def test_set_license_metadata_applies_and_replaces():
    out, changed = sl.set_license_metadata(_PYPROJECT, "MIT")
    assert changed
    assert 'license = "MIT"' in out
    assert 'license-files = ["LICENSE"]' in out
    assert "License :: OSI Approved" not in out  # no deprecated trove classifier

    # Relicense replaces rather than duplicates.
    out2, changed2 = sl.set_license_metadata(out, "Apache-2.0")
    assert changed2
    assert 'license = "Apache-2.0"' in out2
    assert "MIT" not in out2
    assert out2.count("license = ") == 1


def test_set_license_metadata_none_clears():
    applied, _ = sl.set_license_metadata(_PYPROJECT, "MIT")
    cleared, changed = sl.set_license_metadata(applied, "none")
    assert changed
    assert "license = " not in cleared
    assert "license-files" not in cleared


def test_set_license_metadata_requires_project_table():
    with pytest.raises(ValueError):
        sl.set_license_metadata("[build-system]\nrequires = []\n", "MIT")


@pytest.mark.parametrize("license_id", ["MIT", "Apache-2.0", "BSD-3-Clause", "none"])
def test_set_license_metadata_never_writes_classifiers(license_id):
    """PEP 639: the SPDX `license` field replaces `License ::` trove classifiers.

    The license engine must never introduce a `classifiers` key, whichever SPDX id
    it applies — the template's pyproject gate still asserts one, and satisfying
    that with a deprecated classifier is explicitly not the fix.
    """
    out, _ = sl.set_license_metadata(_PYPROJECT, license_id)
    assert "classifiers" not in out
    assert "License ::" not in out


def test_set_license_metadata_leaves_existing_classifiers_untouched():
    """Classifiers are /python-version's business; relicensing must not disturb them."""
    with_classifiers = _PYPROJECT.replace(
        "dependencies = []",
        'classifiers = [\n    "Programming Language :: Python :: 3.12",\n]\ndependencies = []',
    )
    out, changed = sl.set_license_metadata(with_classifiers, "MIT")
    assert changed  # the license fields were added
    assert '"Programming Language :: Python :: 3.12",' in out
    assert out.count("classifiers = [") == 1
    assert "License ::" not in out


# --- set_license() end to end -----------------------------------------------


def test_set_license_writes_file_and_metadata(tmp_path):
    (tmp_path / "pyproject.toml").write_text(_PYPROJECT)
    summary = sl.set_license(tmp_path, license_id="MIT", holder="acme", year="2026", force=False)
    assert "LICENSE" in summary["created"]
    assert "pyproject.toml" in summary["modified"]
    assert not summary["needs_force"]
    assert "Copyright (c) 2026 acme" in (tmp_path / "LICENSE").read_text()
    assert 'license = "MIT"' in (tmp_path / "pyproject.toml").read_text()


def test_set_license_refuses_overwrite_without_force_and_stays_consistent(tmp_path):
    (tmp_path / "pyproject.toml").write_text(_PYPROJECT)
    sl.set_license(tmp_path, license_id="MIT", holder="acme", year="2026", force=False)

    # Relicensing must abort *before* touching pyproject when --force is absent.
    summary = sl.set_license(
        tmp_path, license_id="Apache-2.0", holder="acme", year="2026", force=False
    )
    assert summary["needs_force"]
    assert (tmp_path / "LICENSE").read_text().startswith("MIT License")  # file untouched
    assert 'license = "MIT"' in (tmp_path / "pyproject.toml").read_text()  # metadata untouched


def test_set_license_force_overwrites(tmp_path):
    (tmp_path / "pyproject.toml").write_text(_PYPROJECT)
    sl.set_license(tmp_path, license_id="MIT", holder="acme", year="2026", force=False)
    summary = sl.set_license(
        tmp_path, license_id="Apache-2.0", holder="acme", year="2026", force=True
    )
    assert "LICENSE" in summary["modified"]
    assert "Apache License" in (tmp_path / "LICENSE").read_text()
    assert 'license = "Apache-2.0"' in (tmp_path / "pyproject.toml").read_text()


def test_set_license_none_leaves_existing_file(tmp_path):
    (tmp_path / "pyproject.toml").write_text(_PYPROJECT)
    sl.set_license(tmp_path, license_id="MIT", holder="acme", year="2026", force=False)
    summary = sl.set_license(tmp_path, license_id="none", holder="acme", year="2026", force=False)
    assert "pyproject.toml" in summary["modified"]
    assert "license = " not in (tmp_path / "pyproject.toml").read_text()
    assert (tmp_path / "LICENSE").exists()  # file left in place, not deleted


def test_set_license_no_pyproject_still_writes_file(tmp_path):
    summary = sl.set_license(tmp_path, license_id="MIT", holder="acme", year="2026", force=False)
    assert "LICENSE" in summary["created"]
    assert summary["modified"] == []


def test_set_license_notes_a_pyproject_without_a_project_table(tmp_path):
    """A malformed pyproject is reported, not fatal — the LICENSE is still written."""
    (tmp_path / "pyproject.toml").write_text("[build-system]\nrequires = []\n")
    summary = sl.set_license(tmp_path, license_id="MIT", holder="acme", year="2026", force=False)
    assert "LICENSE" in summary["created"]
    assert summary["modified"] == []  # metadata untouched
    assert any("no [project] table" in n for n in summary["notes"])


def test_set_license_unbundled_id_sets_metadata_and_says_to_add_the_text(tmp_path):
    """`main()` rejects these, but `set_license()` is callable directly."""
    (tmp_path / "pyproject.toml").write_text(_PYPROJECT)
    summary = sl.set_license(
        tmp_path, license_id="MPL-2.0", holder="acme", year="2026", force=False
    )
    assert 'license = "MPL-2.0"' in (tmp_path / "pyproject.toml").read_text()
    assert not (tmp_path / "LICENSE").exists()
    assert any("no bundled text" in n for n in summary["notes"])


def test_set_license_skips_an_already_identical_license(tmp_path):
    """Re-applying the same license is a no-op needing no --force."""
    (tmp_path / "pyproject.toml").write_text(_PYPROJECT)
    kwargs = {"license_id": "MIT", "holder": "acme", "year": "2026", "force": False}
    sl.set_license(tmp_path, **kwargs)
    summary = sl.set_license(tmp_path, **kwargs)
    assert summary["skipped"] == ["LICENSE"]
    assert not summary["needs_force"]
    assert summary["created"] == []


# --- main() / CLI -----------------------------------------------------------


def test_main_rejects_unbundled_license(tmp_path):
    with pytest.raises(SystemExit):
        sl.main([str(tmp_path), "--license", "WTFPL"])


def test_main_json_and_exit_codes(tmp_path, capsys):
    (tmp_path / "pyproject.toml").write_text(_PYPROJECT)
    rc = sl.main(
        [str(tmp_path), "--license", "MIT", "--owner", "acme", "--license-year", "2026", "--json"]
    )
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert "LICENSE" in payload["created"]

    # Overwrite attempt without --force → exit code 3.
    rc2 = sl.main([str(tmp_path), "--license", "Apache-2.0", "--owner", "acme"])
    assert rc2 == 3


def test_main_text_output_reports_modified_and_skipped(tmp_path, capsys):
    """Text mode prints each bucket: created, modified, skipped, notes."""
    (tmp_path / "pyproject.toml").write_text(_PYPROJECT)
    args = [str(tmp_path), "--license", "MIT", "--owner", "acme", "--license-year", "2026"]
    assert sl.main(args) == 0
    first = capsys.readouterr()
    assert "created  LICENSE" in first.out
    assert "modified pyproject.toml" in first.out

    # Second run: the LICENSE is already identical, so it's skipped (stderr).
    assert sl.main(args) == 0
    second = capsys.readouterr()
    assert "skipped  LICENSE" in second.err


def test_main_text_output_reports_notes(tmp_path, capsys):
    """`none` emits a note and no file writes."""
    (tmp_path / "pyproject.toml").write_text(_PYPROJECT)
    assert sl.main([str(tmp_path), "--license", "none"]) == 0
    assert "note" in capsys.readouterr().err


# --- Cargo.toml (rust) ------------------------------------------------------

_CARGO = """\
[package]
name = "widget"
version = "0.1.0"
edition = "2024"

[dependencies]
"""


def test_set_cargo_license_metadata_applies_and_replaces():
    out, changed = sl.set_cargo_license_metadata(_CARGO, "MIT")
    assert changed
    assert 'license = "MIT"' in out
    lines = [line for line in out.splitlines() if line.strip()]
    assert (
        lines.index('name = "widget"')
        < lines.index('license = "MIT"')
        < lines.index("[dependencies]")
    )

    again, changed_again = sl.set_cargo_license_metadata(out, "Apache-2.0")
    assert changed_again
    assert 'license = "Apache-2.0"' in again
    assert "MIT" not in again


def test_set_cargo_license_metadata_is_idempotent():
    once, _ = sl.set_cargo_license_metadata(_CARGO, "MIT")
    twice, changed = sl.set_cargo_license_metadata(once, "MIT")
    assert twice == once
    assert not changed


def test_set_cargo_license_metadata_clears_license_file_too():
    """A stale `license-file` would make `cargo publish` state the wrong terms."""
    manifest = _CARGO.replace("edition", 'license-file = "COPYING"\nedition')
    out, _ = sl.set_cargo_license_metadata(manifest, "MIT")
    assert "license-file" not in out
    assert 'license = "MIT"' in out


def test_set_cargo_license_metadata_none_clears():
    once, _ = sl.set_cargo_license_metadata(_CARGO, "MIT")
    cleared, changed = sl.set_cargo_license_metadata(once, "none")
    assert changed
    assert "license" not in cleared


def test_set_cargo_license_metadata_requires_package_table():
    with pytest.raises(ValueError, match=r"\[package\]"):
        sl.set_cargo_license_metadata("[workspace]\nmembers = []\n", "MIT")


def test_set_license_writes_cargo_metadata_and_the_file(tmp_path):
    (tmp_path / "Cargo.toml").write_text(_CARGO)
    summary = sl.set_license(tmp_path, license_id="MIT", holder="Acme", year="2026", force=False)
    assert summary["created"] == ["LICENSE"]
    assert summary["modified"] == ["Cargo.toml"]
    assert 'license = "MIT"' in (tmp_path / "Cargo.toml").read_text()


def test_set_license_covers_both_manifests_in_a_mixed_repo(tmp_path):
    """A pyo3/maturin repo has both manifests; the licence must not disagree."""
    (tmp_path / "pyproject.toml").write_text(_PYPROJECT)
    (tmp_path / "Cargo.toml").write_text(_CARGO)
    summary = sl.set_license(tmp_path, license_id="MIT", holder="Acme", year="2026", force=False)
    assert summary["modified"] == ["pyproject.toml", "Cargo.toml"]
    assert 'license = "MIT"' in (tmp_path / "pyproject.toml").read_text()
    assert 'license = "MIT"' in (tmp_path / "Cargo.toml").read_text()


def test_set_license_notes_a_cargo_toml_without_a_package_table(tmp_path):
    (tmp_path / "Cargo.toml").write_text("[workspace]\nmembers = []\n")
    summary = sl.set_license(tmp_path, license_id="MIT", holder="Acme", year="2026", force=False)
    assert any("Cargo.toml" in note for note in summary["notes"])
    assert summary["created"] == ["LICENSE"]


# --- branch coverage: the arms line coverage could not see ---------------------


def test_table_block_ends_at_eof_when_it_is_the_last_table():
    """The loop exhausts rather than breaking on a following `[table]`."""
    assert sl._table_block(["[package]", 'name = "x"'], "package", "Cargo.toml") == (0, 2)


def test_set_license_metadata_preserves_the_absence_of_a_trailing_newline():
    text = '[project]\nname = "x"'
    new_text, changed = sl.set_license_metadata(text, "MIT")
    assert changed and not new_text.endswith("\n")


def test_set_cargo_license_metadata_preserves_the_absence_of_a_trailing_newline():
    text = '[package]\nname = "x"'
    new_text, changed = sl.set_cargo_license_metadata(text, "MIT")
    assert changed and not new_text.endswith("\n")


# --- end-to-end: a real crate, and the dual-manifest case ---------------------


def test_e2e_a_real_crate_gets_the_spdx_expression_cargo_wants(rust_crate):
    """`/rhiza:license` ran as part of the fixture chain; this is its outcome.

    `license` in `[package]` is what `cargo publish` and the template's licence gate
    read, and it is the only place a crate's terms are declared.
    """
    manifest = (rust_crate / "Cargo.toml").read_text()
    assert 'license = "MIT"' in manifest
    assert "license-file" not in manifest
    assert (rust_crate / "LICENSE").read_text().startswith("MIT License")


def test_e2e_both_manifests_are_visited_so_they_cannot_disagree(rust_crate, tmp_path):
    """A pyo3/maturin repo carries a Cargo.toml *and* a pyproject.toml.

    Dispatching on the declared language would leave one of them stale, and two manifests
    declaring different terms is worse than one declaring none.
    """
    import shutil

    repo = tmp_path / "widget"
    shutil.copytree(rust_crate, repo)
    (repo / "pyproject.toml").write_text(
        '[project]\nname = "widget"\nversion = "0.1.0"\nlicense = "Apache-2.0"\n'
    )
    # A stale `license-file` is the trap: left behind, `cargo publish` describes terms
    # the repo no longer ships.
    (repo / "Cargo.toml").write_text(
        (repo / "Cargo.toml").read_text().replace('license = "MIT"', 'license-file = "COPYING"')
    )

    summary = sl.set_license(repo, license_id="MIT", holder="jebel-quant", year="2026", force=True)

    assert set(summary["modified"]) == {"pyproject.toml", "Cargo.toml"}
    cargo, pyproject = (repo / "Cargo.toml").read_text(), (repo / "pyproject.toml").read_text()
    assert 'license = "MIT"' in cargo and "license-file" not in cargo
    assert 'license = "MIT"' in pyproject and "Apache-2.0" not in pyproject
