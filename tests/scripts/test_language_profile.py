"""Tests for the language registry (`scripts/language_profile.py`).

The registry exists because "what this language looks like" used to be written down
independently wherever it was needed, and the copies disagreed. So the tests that
matter most are the ones asserting the *registry itself* stays coherent — every
language complete, and every language `validate.py` can validate also profiled here.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import _validate_structure
import language_profile as lp
import pytest


class TestLanguage:
    """The dataclass itself: a frozen record of one ecosystem's facts."""

    def test_a_profile_is_immutable(self):
        """Frozen on purpose — a consumer must not be able to edit the shared registry."""
        language = lp.resolve("python")
        with pytest.raises(AttributeError):
            language.source_root = "lib"  # type: ignore[misc]

    def test_the_same_object_is_returned_every_time(self):
        assert lp.resolve("go") is lp.resolve("go")

    def test_optional_fields_default_to_empty(self):
        bare = lp.Language(
            name="x", manifest="m", source_root=".", lockfile=None, toolchain_pin=None
        )
        assert bare.complexity == () and bare.graph == () and bare.aliases == ()
        assert bare.test_layout is False


# --- the registry is coherent -------------------------------------------------


def test_every_known_language_has_the_facts_the_consumers_read():
    for name in lp.languages():
        language = lp.resolve(name)
        assert language is not None
        assert language.manifest and language.source_root
        assert language.complexity, f"{name} has no complexity tooling"


def test_the_registry_covers_every_language_validate_can_validate():
    """The drift this module exists to prevent, asserted directly.

    `_validate_structure.VALIDATORS` decides which languages `/rhiza:init` accepts. A
    language it validates but this registry has never heard of is exactly the half-taught
    axis that made a Go repo score as broken.
    """
    assert set(_validate_structure.VALIDATORS) <= set(lp.languages())


def test_resolve_is_case_insensitive_and_accepts_aliases():
    assert lp.resolve("Python") is lp.resolve("python")
    assert lp.resolve("  GO  ") is lp.resolve("go")
    assert lp.resolve("golang") is lp.resolve("go")


def test_resolve_returns_none_for_a_language_we_do_not_know():
    assert lp.resolve("cobol") is None


# --- detection ----------------------------------------------------------------


def test_an_explicit_language_wins(tmp_path):
    (tmp_path / "go.mod").write_text("module x\n", encoding="utf-8")
    language, reason = lp.detect(tmp_path, "rust")
    assert language is not None and language.name == "rust"
    assert "--language rust" in reason


def test_the_pointer_is_preferred_over_what_is_on_disk(tmp_path):
    """A repo mid-migration has both; the declaration is the intent."""
    (tmp_path / "pyproject.toml").write_text("[project]\n", encoding="utf-8")
    (tmp_path / ".rhiza").mkdir()
    (tmp_path / ".rhiza" / "template.yml").write_text(
        "repository: o/r\nlanguage: go\n", encoding="utf-8"
    )
    language, reason = lp.detect(tmp_path)
    assert language is not None and language.name == "go"
    assert "template.yml" in reason


@pytest.mark.parametrize(
    ("manifest", "expected"),
    [("pyproject.toml", "python"), ("go.mod", "go"), ("Cargo.toml", "rust")],
)
def test_falls_back_to_the_manifest_on_disk(tmp_path, manifest, expected):
    (tmp_path / manifest).write_text("x\n", encoding="utf-8")
    language, reason = lp.detect(tmp_path)
    assert language is not None and language.name == expected
    assert manifest in reason


def test_a_crate_with_python_bindings_resolves_to_rust(tmp_path):
    """pyo3/maturin repos carry both manifests; Cargo.toml is what makes it a crate."""
    (tmp_path / "pyproject.toml").write_text("[project]\n", encoding="utf-8")
    (tmp_path / "Cargo.toml").write_text("[package]\n", encoding="utf-8")
    language, _ = lp.detect(tmp_path)
    assert language is not None and language.name == "rust"


def test_an_unrecognisable_repo_is_unknown_rather_than_guessed(tmp_path):
    """A wrong language scores the wrong things confidently; absent is safer."""
    language, reason = lp.detect(tmp_path)
    assert language is None
    assert "no recognised manifest" in reason


def test_an_explicit_language_we_do_not_know_is_not_silently_ignored(tmp_path):
    (tmp_path / "pyproject.toml").write_text("[project]\n", encoding="utf-8")
    language, _ = lp.detect(tmp_path, "cobol")
    assert language is None


# --- reading the pointer ------------------------------------------------------


def test_declared_language_returns_none_without_a_pointer(tmp_path):
    assert lp.declared_language(tmp_path) is None


def test_declared_language_returns_none_when_the_key_is_absent(tmp_path):
    (tmp_path / ".rhiza").mkdir()
    (tmp_path / ".rhiza" / "template.yml").write_text("repository: o/r\n", encoding="utf-8")
    assert lp.declared_language(tmp_path) is None


def test_declared_language_strips_quotes(tmp_path):
    (tmp_path / ".rhiza").mkdir()
    (tmp_path / ".rhiza" / "template.yml").write_text('language: "rust"\n', encoding="utf-8")
    assert lp.declared_language(tmp_path) == "rust"


def test_an_empty_language_value_reads_as_absent(tmp_path):
    (tmp_path / ".rhiza").mkdir()
    (tmp_path / ".rhiza" / "template.yml").write_text("language:\n", encoding="utf-8")
    assert lp.declared_language(tmp_path) is None


def test_a_malformed_pointer_still_yields_the_language(tmp_path):
    """A broken `exclude:` block elsewhere must not hide the language."""
    (tmp_path / ".rhiza").mkdir()
    (tmp_path / ".rhiza" / "template.yml").write_text(
        "language: go\nexclude: [unclosed\n", encoding="utf-8"
    )
    assert lp.declared_language(tmp_path) == "go"


# --- facts --------------------------------------------------------------------


def test_facts_fill_the_source_root_into_the_commands(tmp_path):
    (tmp_path / "pyproject.toml").write_text("[project]\n", encoding="utf-8")
    data = lp.facts(lp.resolve("python"), tmp_path)
    assert data["manifest_present"] is True
    assert all("{src}" not in command for command in data["complexity"])
    assert any("radon cc src" in command for command in data["complexity"])


def test_facts_report_a_missing_manifest(tmp_path):
    data = lp.facts(lp.resolve("go"), tmp_path)
    assert data["manifest_present"] is False
    assert data["toolchain_pin"] is None  # go pins inside go.mod


def test_only_python_claims_the_test_layout_rule():
    """`check_test_layout.py` is built on Python module/class naming."""
    applies = {n for n in lp.languages() if lp.resolve(n).test_layout}
    assert applies == {"python"}


# --- main() / CLI -------------------------------------------------------------


def test_main_reports_a_detected_language(tmp_path, capsys):
    (tmp_path / "Cargo.toml").write_text("[package]\n", encoding="utf-8")
    assert lp.main([str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert "language: rust" in out
    assert "Cargo.toml" in out


def test_main_emits_json(tmp_path, capsys):
    (tmp_path / "go.mod").write_text("module x\n", encoding="utf-8")
    assert lp.main([str(tmp_path), "--json"]) == 0
    assert '"language": "go"' in capsys.readouterr().out


def test_main_exits_one_when_the_language_is_undetermined(tmp_path, capsys):
    assert lp.main([str(tmp_path)]) == 1
    err = capsys.readouterr().err
    assert "could not determine the language" in err
    assert "known languages" in err


def test_main_reports_an_undetermined_language_as_json_too(tmp_path, capsys):
    assert lp.main([str(tmp_path), "--json"]) == 1
    assert '"language": null' in capsys.readouterr().out


def test_main_honours_an_explicit_language(tmp_path, capsys):
    assert lp.main([str(tmp_path), "--language", "python"]) == 0
    assert "language: python" in capsys.readouterr().out


# --- the real repo ------------------------------------------------------------


def test_this_repo_is_detected_as_python_by_census(repo_root: Path):
    """rhiza-claude has no .rhiza/ and no manifest, yet is unambiguously Python.

    This test used to assert the opposite. Detection leant on the pointer and the
    manifest, so the one repo `/quality`'s degraded mode was written for was the one it
    could not profile — no source root, no complexity commands, a subcategory silently
    unscored. The census is the fallback that closes it.
    """
    language, reason = lp.detect(repo_root)
    assert language is not None and language.name == "python"
    assert "census" in reason
    # The repo root, not `src/` — which does not exist here. A source root the tools
    # cannot point at is the same failure as no source root at all.
    assert language.source_root == "."
    assert (repo_root / language.source_root).is_dir()


def test_a_declared_language_still_beats_the_census(tmp_path):
    """The census is last for a reason: it observes, the other three signals declare."""
    (tmp_path / "main.go").write_text("package main\n", encoding="utf-8")
    (tmp_path / ".rhiza").mkdir()
    (tmp_path / ".rhiza" / "template.yml").write_text("language: rust\n", encoding="utf-8")
    language, reason = lp.detect(tmp_path)
    assert language is not None and language.name == "rust"
    assert "census" not in reason


# --- the census of last resort ------------------------------------------------


def test_the_census_finds_a_clear_majority(tmp_path):
    """Three Python files and one Go file is a Python repo with a helper script."""
    for name in ("a.py", "b.py", "c.py"):
        (tmp_path / name).write_text("", encoding="utf-8")
    (tmp_path / "tool.go").write_text("", encoding="utf-8")
    found = lp.census(tmp_path)
    assert found is not None
    winner, counts = found
    assert winner == "python"
    assert counts == {"python": 3, "go": 1}


def test_the_census_refuses_a_plurality(tmp_path):
    """An even split is not a majority — better unknown than confidently wrong."""
    (tmp_path / "a.py").write_text("", encoding="utf-8")
    (tmp_path / "b.go").write_text("", encoding="utf-8")
    assert lp.census(tmp_path) is None


def test_the_census_counts_nothing_in_an_empty_repo(tmp_path):
    """No source files at all is the plainest unknown there is."""
    assert lp.census(tmp_path) is None


def test_the_census_ignores_vendored_and_generated_trees(tmp_path):
    """A Python virtualenv must not make a Go module look like a Python project."""
    (tmp_path / "main.go").write_text("package main\n", encoding="utf-8")
    for skipped in ("node_modules", "venv", "__pycache__", ".git"):
        directory = tmp_path / skipped
        directory.mkdir()
        for index in range(5):
            (directory / f"dep{index}.py").write_text("", encoding="utf-8")
    found = lp.census(tmp_path)
    assert found is not None
    assert found == ("go", {"go": 1})


def test_the_census_descends_into_real_subdirectories(tmp_path):
    """Pruning must not become 'only look at the top level'."""
    nested = tmp_path / "plugin" / "scripts"
    nested.mkdir(parents=True)
    (nested / "deep.py").write_text("", encoding="utf-8")
    found = lp.census(tmp_path)
    assert found == ("python", {"python": 1})


def test_a_repo_with_no_majority_is_still_unknown(tmp_path):
    """The census widens detection; it must not turn every repo into a guess."""
    (tmp_path / "a.py").write_text("", encoding="utf-8")
    (tmp_path / "b.rs").write_text("", encoding="utf-8")
    language, reason = lp.detect(tmp_path)
    assert language is None
    assert "no clear majority" in reason


# --- end-to-end: a real crate -------------------------------------------------


def test_e2e_a_real_crate_is_detected_as_rust_from_its_pointer(rust_crate):
    """Detection prefers what the repo *declares* — the pointer — over what it looks like.

    This is the seam every downstream consumer crosses: `/quality` picks its complexity
    tooling here, `/docs` its badge, and `check_test_layout`'s applicability comes from
    `test_layout_applies`. Until now it had only ever been asked about repos assembled
    by these tests; this one was built by the /init chain from `cargo init --lib`.
    """
    language, reason = lp.detect(rust_crate)
    assert language is not None
    assert language.name == "rust"
    assert "template.yml declares language: rust" in reason


def test_e2e_a_real_crates_facts_come_from_the_registry(rust_crate):
    facts = lp.facts(lp.resolve("rust"), rust_crate)
    assert facts["manifest"] == "Cargo.toml"
    assert facts["manifest_present"] is True
    assert facts["source_root"] == "src"
    # The mirror rule is written around Python module/class naming; cargo puts unit tests
    # inside the module they cover, so demanding tests/ parity would fail every crate.
    assert facts["test_layout_applies"] is False
    assert all("cargo" in command for command in facts["complexity"] + facts["graph"])


def test_e2e_the_pointer_wins_over_a_second_manifest(rust_crate, tmp_path):
    """A pyo3/maturin crate carries both manifests — the one shape that could pick wrong.

    `_BY_MANIFEST` is ordered so Cargo.toml wins on a sniff, but the pointer should
    decide before sniffing ever happens.
    """
    copy = tmp_path / "widget"
    shutil.copytree(rust_crate, copy)
    (copy / "pyproject.toml").write_text(
        '[project]\nname = "widget"\nversion = "0.1.0"\n', encoding="utf-8"
    )
    language, reason = lp.detect(copy)
    assert language is not None and language.name == "rust", reason


def test_e2e_a_dual_manifest_crate_sniffs_as_rust_without_a_pointer(rust_crate, tmp_path):
    """Same repo, pointer removed: the Cargo manifest is what makes it a crate."""
    copy = tmp_path / "widget"
    shutil.copytree(rust_crate, copy)
    (copy / "pyproject.toml").write_text(
        '[project]\nname = "widget"\nversion = "0.1.0"\n', encoding="utf-8"
    )
    (copy / ".rhiza" / "template.yml").unlink()
    language, reason = lp.detect(copy)
    assert language is not None and language.name == "rust"
    assert reason == "found Cargo.toml"


def test_e2e_a_real_module_is_detected_as_go_from_its_pointer(go_module):
    """Go's facts differ from the other two in every field that matters downstream."""
    language, reason = lp.detect(go_module)
    assert language is not None and language.name == "go"
    assert "template.yml declares language: go" in reason

    facts = lp.facts(language, go_module)
    assert facts["manifest"] == "go.mod"
    assert facts["manifest_present"] is True
    # Not `src`: a Go module's packages live wherever the directory tree puts them.
    assert facts["source_root"] == "."
    # `go.mod`'s own `go` directive pins the toolchain — there is no sidecar file.
    assert facts["toolchain_pin"] is None
    assert facts["test_layout_applies"] is False
