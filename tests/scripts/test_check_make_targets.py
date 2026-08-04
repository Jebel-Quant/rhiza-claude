"""Outcome tests for the gate probe (`scripts/check_make_targets.py`).

Where the contract tests verify that a command *refers* to things that exist, these
verify what a command actually *finds* when it runs — against fixture repos in the
three states a rhiza command really meets: unmanaged, managed-but-unsynced, and synced.

The bug being pinned is concrete. `/quality` runs seven `make` targets that the sync
delivers, and it used to run them unprobed: in an unsynced repo all seven returned
"No rule to make target", were scored FAIL, and the repo was reported broken when it
was merely unsynced. Six of the seven are absent in this plugin's own repo, and nothing
caught it for however long it had been true.
"""

from __future__ import annotations

import json
import re
import shutil
from collections.abc import Iterable
from pathlib import Path

import check_make_targets as cmt
import pytest
from conftest import assert_ok, run_cmd

pytestmark = pytest.mark.skipif(shutil.which("make") is None, reason="make not available")


@pytest.fixture(scope="session")
def quality_md(repo_root: Path) -> Path:
    """`/quality`'s command file — the single source of the gate list the probe reads."""
    return repo_root / "plugin" / "commands" / "quality.md"


# --- the target list comes from the prose, not from a duplicate ---------------


def test_gate_targets_are_parsed_from_the_command(quality_md: Path):
    """Derived, so the probe cannot drift from what /quality says it runs."""
    assert cmt.gate_targets(quality_md) == [
        "fmt",
        "typecheck",
        "docs-coverage",
        "deptry",
        "security",
        "rhiza-test",
        "test",
    ]


def test_gate_order_is_preserved(quality_md: Path):
    """/quality runs cheapest-first, so the report should follow the same order."""
    targets = cmt.gate_targets(quality_md)
    assert targets.index("fmt") < targets.index("test")


def test_gate_targets_deduplicates(tmp_path):
    doc = tmp_path / "c.md"
    doc.write_text("1. `make fmt` — a\n2. `make fmt` — again\n3. `make test` — b\n")
    assert cmt.gate_targets(doc) == ["fmt", "test"]


def test_gate_targets_ignores_prose_mentions_of_make(tmp_path):
    """Only the numbered gate list counts, not every `make x` in the document."""
    doc = tmp_path / "c.md"
    doc.write_text(
        "Run `make help` first.\n\n1. `make fmt` — a\n\nLater, `make book` builds docs.\n"
    )
    assert cmt.gate_targets(doc) == ["fmt"]


def test_gate_targets_of_a_missing_file_is_empty(tmp_path):
    assert cmt.gate_targets(tmp_path / "nope.md") == []


# --- the three repo states ---------------------------------------------------


def test_an_unsynced_repo_reports_every_gate_unavailable(managed_unsynced_repo, quality_md):
    """The exact failure mode: no makefile, so nothing can be scored.

    Reported as unavailable with a pointer at /update — not as seven failures.
    """
    result = cmt.probe(managed_unsynced_repo, quality_md)
    assert result["available"] == []
    assert result["unavailable"] == cmt.gate_targets(quality_md)
    assert result["exit_code"] == cmt.EXIT_UNAVAILABLE
    assert any("not synced" in n and "/rhiza:update" in n for n in result["notes"])


def test_a_synced_repo_finds_every_gate(managed_synced_repo, quality_md):
    result = cmt.probe(managed_synced_repo, quality_md)
    assert result["available"] == cmt.gate_targets(quality_md)
    assert result["unavailable"] == []
    assert result["exit_code"] == cmt.EXIT_OK
    assert result["notes"] == []


def test_a_reduced_profile_reports_only_its_missing_gates(partial_profile_repo, quality_md):
    """Profile variation is legitimate — the tests-bundle gates are simply absent."""
    result = cmt.probe(partial_profile_repo, quality_md)
    assert set(result["available"]) == {"fmt", "deptry"}
    assert set(result["unavailable"]) == {
        "typecheck",
        "docs-coverage",
        "security",
        "rhiza-test",
        "test",
    }
    assert result["exit_code"] == cmt.EXIT_OK  # not a failure
    assert any("out-of-scope, never FAIL" in n for n in result["notes"])


def test_an_unmanaged_repo_has_nothing_to_probe(unmanaged_repo, quality_md):
    result = cmt.probe(unmanaged_repo, quality_md)
    assert result["unavailable"] == cmt.gate_targets(quality_md)
    assert result["exit_code"] == cmt.EXIT_UNAVAILABLE


def test_a_makefile_with_none_of_the_gates_is_called_out(managed_unsynced_repo, quality_md):
    """A repo with its own unrelated Makefile — present, but not the template's.

    Distinct from having no makefile at all: something *is* there, so the likely cause
    is an incomplete sync rather than an unmanaged repo, and the note says so.
    """
    (managed_unsynced_repo / "Makefile").write_text(".PHONY: build\nbuild: ; @echo build\n")
    result = cmt.probe(managed_unsynced_repo, quality_md)
    assert result["available"] == []
    assert result["exit_code"] == cmt.EXIT_OK  # probing worked; the repo is just bare
    assert any("template sync completed" in n for n in result["notes"])


# --- this repo, which is where the bug was live ------------------------------


def test_this_plugin_repo_lacks_the_template_gates(quality_md: Path, repo_root: Path):
    """Pins the state that made /quality unrunnable here, so a future fix is visible.

    The plugin repo is not rhiza-managed, so it has only its own `test` target. If this
    ever changes — because the repo adopts the template — the assertion should be
    updated deliberately rather than silently.
    """
    result = cmt.probe(repo_root, quality_md)
    assert result["available"] == ["test"]
    assert "fmt" in result["unavailable"]
    assert result["exit_code"] == cmt.EXIT_OK


# --- probing is side-effect free ---------------------------------------------


def test_probing_runs_no_recipes(managed_synced_repo):
    """`make -n` must expand without executing, or probing would have side effects."""
    marker = managed_synced_repo / "SIDE_EFFECT"
    (managed_synced_repo / ".rhiza" / "rhiza.mk").write_text(
        ".PHONY: fmt\nfmt: ; @touch SIDE_EFFECT\n"
    )
    assert cmt.target_exists(managed_synced_repo, "fmt")
    assert not marker.exists()


def test_target_exists_is_false_for_an_undefined_target(managed_synced_repo):
    assert not cmt.target_exists(managed_synced_repo, "definitely-not-a-target")


def test_find_makefile_accepts_the_conventional_names(tmp_path):
    assert cmt.find_makefile(tmp_path) is None
    (tmp_path / "GNUmakefile").write_text("x: ; @:\n")
    assert cmt.find_makefile(tmp_path).name == "GNUmakefile"


# --- no gate list at all -----------------------------------------------------


def test_a_command_without_a_gate_list_exits_2(managed_synced_repo, tmp_path):
    doc = tmp_path / "empty.md"
    doc.write_text("# No gates here\n")
    result = cmt.probe(managed_synced_repo, doc)
    assert result["exit_code"] == cmt.EXIT_NO_GATES
    assert any("no `make <target>` gate list" in n for n in result["notes"])


# --- main() / CLI ------------------------------------------------------------


def test_main_reports_each_target(managed_synced_repo, capsys, quality_md):
    rc = cmt.main(["--target-dir", str(managed_synced_repo), "--from", str(quality_md)])
    assert rc == cmt.EXIT_OK
    out = capsys.readouterr().out
    assert "available    make fmt" in out
    assert "available    make test" in out


def test_main_marks_missing_targets_unavailable(partial_profile_repo, capsys, quality_md):
    rc = cmt.main(["--target-dir", str(partial_profile_repo), "--from", str(quality_md)])
    assert rc == cmt.EXIT_OK
    captured = capsys.readouterr()
    assert "unavailable  make typecheck" in captured.out
    assert "out-of-scope" in captured.err


def test_main_require_turns_a_missing_target_into_a_failure(partial_profile_repo, quality_md):
    """For a repo that expects the full profile, absence should fail the run."""
    args = ["--target-dir", str(partial_profile_repo), "--from", str(quality_md)]
    assert cmt.main(args) == cmt.EXIT_OK
    assert cmt.main([*args, "--require"]) == cmt.EXIT_UNAVAILABLE


def test_main_json_output(managed_synced_repo, capsys, quality_md):
    rc = cmt.main(["--target-dir", str(managed_synced_repo), "--from", str(quality_md), "--json"])
    assert rc == cmt.EXIT_OK
    payload = json.loads(capsys.readouterr().out)
    assert payload["available"] == cmt.gate_targets(quality_md)
    assert payload["unavailable"] == []


def test_main_defaults_to_the_bundled_quality_command(managed_synced_repo, capsys):
    """With no --from, it reads the shipped commands/quality.md."""
    rc = cmt.main(["--target-dir", str(managed_synced_repo)])
    assert rc == cmt.EXIT_OK
    assert "make fmt" in capsys.readouterr().out


def test_main_on_an_unsynced_repo_exits_1(managed_unsynced_repo, capsys, quality_md):
    rc = cmt.main(["--target-dir", str(managed_unsynced_repo), "--from", str(quality_md)])
    assert rc == cmt.EXIT_UNAVAILABLE
    assert "not synced" in capsys.readouterr().err


# --- end-to-end: /quality's gates against a real sync -------------------------


def test_e2e_every_gate_quality_names_is_provided_by_the_template(synced_repo, quality_md):
    """The assertion that would have caught /quality being unrunnable.

    /quality names seven `make` targets and used to probe none of them. Here the target
    list is read from the shipped commands/quality.md and checked against a repo synced
    from the real template — so a gate the template stops providing, or one added to the
    prose that it never provided, fails in CI instead of in front of a user.
    """
    result = cmt.probe(synced_repo, quality_md)
    assert result["unavailable"] == [], f"the template does not provide: {result['unavailable']}"
    assert result["available"] == cmt.gate_targets(quality_md)


# `make test` is executed by tests/test_init_scaffold.py, which owns the coverage-gate
# assertion; `make rhiza-test` has its own test below because it is the one gate that
# does not pass. Everything else in /quality's list runs here.
_RUNNABLE_GATES = ("fmt", "typecheck", "security", "deptry", "docs-coverage")


@pytest.mark.parametrize("gate", _RUNNABLE_GATES)
def test_e2e_each_gate_actually_passes(gate, synced_repo):
    """Resolving is not passing.

    `probe` proves the seven gates /quality names *exist*; existing is a much weaker
    claim. A gate can resolve and still fail on a repo this plugin itself builds — and
    then /quality reports a bad score for a correctly-scaffolded project, which the user
    has every reason to believe. These run the gate for real against `synced_repo`.
    """
    assert_ok(run_cmd(["make", gate], synced_repo), f"make {gate}")


def test_e2e_no_gate_in_the_prose_goes_unrun(synced_repo, quality_md):
    """Every gate /quality names is executed by this suite, or excused by name here.

    Without this, adding a gate to `commands/quality.md` silently adds an unrun one —
    the probe would cover it and nothing would ever execute it.
    """
    covered = {*_RUNNABLE_GATES, "test", "rhiza-test"}
    named = set(cmt.gate_targets(quality_md))
    assert named <= covered, f"named in quality.md but never executed: {sorted(named - covered)}"


# Template tests that a correctly-scaffolded repo fails at `PINNED_TEMPLATE_REF`
# because the fix is merged upstream but not yet released. Tolerated **by name**, and
# each entry is asserted to still fail — so it cannot outlive its cause: the ref bump
# that ships the fix turns this test red, and the fix is deleting the entry.
_UPSTREAM_KNOWN_FAILURES = {
    # `init_skeleton.py` no longer seeds a `lint` dependency group: the template
    # provisions every linter through prek/uvx, so nothing resolved that group. Upstream
    # dropped the requirement in rhiza #1484, merged to `main` after v1.3.1 was cut.
    "TestDependencyGroups::test_lint_group_present",
}


def test_e2e_rhiza_test_passes_on_a_repo_this_plugin_scaffolded(synced_repo):
    """`make rhiza-test` runs the *template's* own `.rhiza/tests/` against our scaffold.

    The strongest single statement about `/rhiza:init`: the template's own opinion of a
    repo this plugin built, with exemptions only by name in `_UPSTREAM_KNOWN_FAILURES`.

    The history is worth keeping because each failure was informative.
    `test_license_classifier_present` demanded a ``License :: OSI Approved :: …`` trove
    classifier that PEP 639 superseded — upstream's bug, tolerated by name until upstream
    fixed it. Then v1.3.0 added `test_a_discoverable_config_exists`, and that one was
    **ours**: the `[tool.bumpversion]` table was written by procedure prose rather than by
    `init_skeleton.py`, so a repo built from the scripts alone had no version location and
    `/rhiza:release` would have fallen back to `git describe`. Both are fixed.

    A tolerated failure that nobody re-examines becomes a permanent hole, so the
    tolerance is two-sided: an unexpected failure fails here, and so does a *tolerated*
    one that has stopped happening.

    **"No failures" is not enough on its own.** An absent target, a `uv` that cannot
    resolve pytest, or an upstream `.rhiza/tests/` that stopped being synced all yield
    zero `FAILED` lines, and the gate would read as passing while running nothing — the
    same shape as the bug `check_make_targets.py` exists to prevent. So the exit status
    and the count of tests that actually ran are asserted too.
    """
    result = run_cmd(["make", "rhiza-test"], synced_repo)
    output = result.stdout + result.stderr
    failed = set(re.findall(r"^FAILED \S+?\.py::(\S+)", output, re.MULTILINE))
    unexpected = sorted(failed - _UPSTREAM_KNOWN_FAILURES)
    assert unexpected == [], (
        f"the template's own tests reject our scaffold: {unexpected}\n{output[-3000:]}"
    )
    stale = sorted(_UPSTREAM_KNOWN_FAILURES - failed)
    assert stale == [], f"these no longer fail — drop them from _UPSTREAM_KNOWN_FAILURES: {stale}"

    # A tolerated failure makes the target exit non-zero, so the exit status is only
    # assertable while nothing is tolerated. Until then the "something actually ran"
    # assertion below carries that weight alone.
    if not failed:
        assert_ok(result, "make rhiza-test")
    passed = [int(n) for n in re.findall(r"(\d+) passed", output)]
    assert passed and passed[0] > 0, (
        f"`make rhiza-test` reported no test as having run — the gate did not execute the "
        f"template's tests, which is not the same as passing them.\n{output[-3000:]}"
    )


def test_e2e_quality_gates_exist_on_the_gitlab_profile_too(gitlab_synced_repo, quality_md):
    """The gates come from `core`/`tests`, which both profiles include.

    Worth asserting rather than assuming: /quality names one gate list, and a
    GitLab-hosted repo must not be scored against gates it was never given.
    """
    result = cmt.probe(gitlab_synced_repo, quality_md)
    assert result["unavailable"] == [], f"gitlab profile lacks: {result['unavailable']}"


# --- discovery: what the repo documents beyond the prose's list ---------------


def test_documented_targets_reads_the_help_convention(tmp_path):
    (tmp_path / "Makefile").write_text(
        "help:  ## Show this help\n\ttrue\n"
        "build:  ## Compile the crate\n\ttrue\n"
        "internal-thing:\n\ttrue\n"  # undocumented: deliberately not discovered
    )
    found = cmt.documented_targets(tmp_path)
    assert found == {"help": "Show this help", "build": "Compile the crate"}


def test_documented_targets_without_a_makefile_is_empty(tmp_path):
    assert cmt.documented_targets(tmp_path) == {}


def test_a_non_python_repo_yields_discovered_targets_instead_of_nothing(
    managed_unsynced_repo, quality_md
):
    """The whole point: a Go/Rust template's gates are found, not reported as absent.

    None of the prose's Python gate names exist here, which before this would have
    produced "no gate is available" and a scorecard with nothing in it.
    """
    (managed_unsynced_repo / "Makefile").write_text(
        "test:  ## go test ./...\n\ttrue\n"
        "vet:  ## go vet ./...\n\ttrue\n"
        "lint:  ## golangci-lint run\n\ttrue\n"
    )
    summary = cmt.probe(managed_unsynced_repo, quality_md)
    assert summary["undeclared"] == ["lint", "vet"]  # `test` is a named gate already
    assert summary["documented"]["vet"] == "go vet ./..."
    assert any("its real gates" in note for note in summary["notes"])


def test_the_discovery_hint_fires_even_though_test_is_a_named_gate(
    managed_unsynced_repo, quality_md
):
    """A Go or Rust template will define `test`, so "all gates missing" is too strict.

    Requiring zero matches would hide the hint from exactly the repos it exists for.
    """
    (managed_unsynced_repo / "Makefile").write_text(
        "test:  ## go test ./...\n\ttrue\nvet:  ## go vet ./...\n\ttrue\n"
    )
    summary = cmt.probe(managed_unsynced_repo, quality_md)
    assert summary["available"] == ["test"]
    assert any("its real gates" in note for note in summary["notes"])


def test_the_discovery_hint_is_silent_on_a_fully_synced_python_repo(
    managed_synced_repo, quality_md
):
    """Every named gate resolves, so there is nothing to redirect the model toward."""
    summary = cmt.probe(managed_synced_repo, quality_md)
    assert not any("its real gates" in note for note in summary["notes"])


def test_an_unsynced_repo_reports_no_discovered_targets(managed_unsynced_repo, quality_md):
    summary = cmt.probe(managed_unsynced_repo, quality_md)
    assert summary["undeclared"] == []
    assert summary["documented"] == {}


# --- discovery follows the include chain, because make does -------------------
#
# A synced repo's root Makefile is a stub: variables and `include .rhiza/rhiza.mk`,
# which itself ends in `-include .rhiza/make.d/*.mk`. Reading only the root file found
# nothing on every real repo — the one place discovery was supposed to work.


def _synced_layout(root: Path) -> None:
    """Write the include shape a rhiza sync really delivers."""
    (root / "Makefile").write_text("LOGO=x\ninclude .rhiza/rhiza.mk\n-include local.mk\n")
    (root / ".rhiza" / "make.d").mkdir(parents=True, exist_ok=True)
    (root / ".rhiza" / "rhiza.mk").write_text(
        "help:  ## Display this help message\n\ttrue\n-include .rhiza/make.d/*.mk\n"
    )
    (root / ".rhiza" / "make.d" / "rust.mk").write_text(
        "test::  ## run the test suite with nextest\n\ttrue\n"
        "deps:  ## report unused dependencies (the deptry analogue)\n\ttrue\n"
        "license:  ## run license compliance scan\n\ttrue\n"
    )


def test_documented_targets_reads_the_included_makefiles(tmp_path):
    """The regression: `deps` and `license` live two includes down, not in the Makefile."""
    _synced_layout(tmp_path)
    found = cmt.documented_targets(tmp_path)
    assert set(found) == {"help", "test", "deps", "license"}
    assert found["deps"] == "report unused dependencies (the deptry analogue)"


def test_a_double_colon_rule_is_discovered(tmp_path):
    """`test::` is how rust.mk declares its test target; a single-colon regex missed it."""
    _synced_layout(tmp_path)
    assert cmt.documented_targets(tmp_path)["test"] == "run the test suite with nextest"


def test_makefile_chain_is_ordered_root_first_and_visits_each_file_once(tmp_path):
    _synced_layout(tmp_path)
    # A second include of the same file (make tolerates it) must not duplicate.
    (tmp_path / "Makefile").write_text(
        "include .rhiza/rhiza.mk\ninclude .rhiza/rhiza.mk\n-include local.mk\n"
    )
    chain = [p.relative_to(tmp_path).as_posix() for p in cmt.makefile_chain(tmp_path)]
    assert chain == ["Makefile", ".rhiza/rhiza.mk", ".rhiza/make.d/rust.mk"]


def test_an_absent_optional_include_is_skipped(tmp_path):
    """`-include local.mk` is how rhiza offers developer-local extensions."""
    _synced_layout(tmp_path)
    assert not (tmp_path / "local.mk").exists()
    assert "local.mk" not in [p.name for p in cmt.makefile_chain(tmp_path)]


def test_a_local_extension_is_read_when_present(tmp_path):
    _synced_layout(tmp_path)
    (tmp_path / "local.mk").write_text("mine:  ## my own target\n\ttrue\n")
    assert "mine" in cmt.documented_targets(tmp_path)


def test_an_include_naming_a_make_variable_is_left_alone(tmp_path):
    """`include $(EXTRA)` cannot be resolved without evaluating make — omit, don't guess."""
    (tmp_path / "Makefile").write_text("include $(EXTRA_MK)\nhelp:  ## help\n\ttrue\n")
    assert [p.name for p in cmt.makefile_chain(tmp_path)] == ["Makefile"]
    assert cmt.documented_targets(tmp_path) == {"help": "help"}


def test_a_cyclic_include_terminates(tmp_path):
    (tmp_path / "Makefile").write_text("include a.mk\n")
    (tmp_path / "a.mk").write_text("include Makefile\nlooped:  ## still found\n\ttrue\n")
    assert [p.name for p in cmt.makefile_chain(tmp_path)] == ["Makefile", "a.mk"]
    assert "looped" in cmt.documented_targets(tmp_path)


def test_include_following_is_depth_limited(tmp_path):
    (tmp_path / "Makefile").write_text("include a.mk\n")
    (tmp_path / "a.mk").write_text("include b.mk\n")
    (tmp_path / "b.mk").write_text("deep:  ## too deep\n\ttrue\n")
    assert [p.name for p in cmt.makefile_chain(tmp_path, depth=1)] == ["Makefile", "a.mk"]
    assert [p.name for p in cmt.makefile_chain(tmp_path, depth=2)] == ["Makefile", "a.mk", "b.mk"]


def test_makefile_chain_without_a_makefile_is_empty(tmp_path):
    assert cmt.makefile_chain(tmp_path) == []


def test_a_differently_named_analogue_is_pointed_at(managed_unsynced_repo, quality_md):
    """A Rust repo resolves most named gates; the one it doesn't has `deps` in its place.

    Scoring `deptry` out-of-scope and stopping there skips a concern the repo does cover.
    """
    _synced_layout(managed_unsynced_repo)
    (managed_unsynced_repo / ".rhiza" / "make.d" / "quality.mk").write_text(
        "fmt:  ## format\n\ttrue\ntypecheck:  ## clippy\n\ttrue\n"
        "docs-coverage:  ## missing_docs\n\ttrue\nsecurity:  ## advisories\n\ttrue\n"
        "rhiza-test:  ## template tests\n\ttrue\n"
    )
    summary = cmt.probe(managed_unsynced_repo, quality_md)
    assert summary["unavailable"] == ["deptry"]
    assert "deps" in summary["undeclared"]
    assert any("under a different name" in note for note in summary["notes"])


def test_a_command_without_a_gate_list_still_returns_the_discovery_keys(tmp_path):
    empty = tmp_path / "empty.md"
    empty.write_text("# no gates here\n")
    summary = cmt.probe(tmp_path, empty)
    assert summary["undeclared"] == [] and summary["documented"] == {}


def test_main_prints_discovered_targets(managed_unsynced_repo, capsys):
    (managed_unsynced_repo / "Makefile").write_text("vet:  ## go vet ./...\n\ttrue\n")
    cmt.main(["--target-dir", str(managed_unsynced_repo)])
    out = capsys.readouterr().out
    assert "discovered   make vet  # go vet ./..." in out


def test_this_repo_discovers_its_own_documented_targets(repo_root: Path):
    """rhiza-claude's own Makefile uses the convention, so this is a live check."""
    found = cmt.documented_targets(repo_root)
    assert {"lint", "test", "book", "clean"} <= set(found)
    assert found["lint"] == "Run all prek hooks against every file"


# --- end-to-end: discovery against a synced Rust repo -------------------------
#
# The first genuine test of the decision #94 made — discover the targets, never table
# them. Everything asserted here is read out of the repo the sync produced; the only
# literal is `deptry`, and that is named as *the Python gate this repo legitimately
# lacks*, not as a Rust expectation.


def _rust_make_targets(repo: Path) -> set[str]:
    """Return the documented targets the synced Rust make include really defines."""
    includes = [p for p in (repo / ".rhiza" / "make.d").glob("*.mk") if "rust" in p.name]
    assert includes, "no Rust make include in the synced repo"
    documented = re.compile(r"^([a-z][a-z0-9_-]*)::?.*?##\s*(.+)$", re.MULTILINE)
    return {m[0] for p in includes for m in documented.findall(p.read_text())}


def test_e2e_the_rust_templates_own_targets_are_all_discovered(rust_synced_repo):
    """Discovery must find what `rust-core` ships — whatever that turns out to be.

    Read from `.rhiza/make.d/rust.mk` rather than listed here on purpose: the template
    owns its gate names, and a list in this file would fail on the day upstream renames
    one, reporting a plugin bug where there is a template change.
    """
    discovered = cmt.documented_targets(rust_synced_repo)
    missing = sorted(_rust_make_targets(rust_synced_repo) - set(discovered))
    assert missing == [], f"the Rust layer defines targets discovery missed: {missing}"


def test_e2e_the_rust_gates_resolve_for_make(rust_synced_repo):
    """Discovered is not the same as runnable — `make -n` has to resolve them too."""
    for target in sorted(_rust_make_targets(rust_synced_repo)):
        assert cmt.target_exists(rust_synced_repo, target), f"make cannot resolve {target}"


def test_e2e_a_rust_repo_is_never_reported_as_having_nothing_to_check(rust_synced_repo, quality_md):
    """The failure `/quality`'s probe exists to prevent, on the language it was added for.

    Before discovery followed the include chain this repo reported six available gates and
    *zero* discovered ones, so `deps`, `license` and `coverage` were invisible: /quality
    would score `deptry` out-of-scope and never learn a Rust analogue was sitting there.
    """
    summary = cmt.probe(rust_synced_repo, quality_md)
    assert summary["undeclared"], "a synced Rust repo documents targets beyond the prose's list"
    assert summary["available"], summary["notes"]
    # The Python-only gate is absent, and that is out-of-scope rather than a failure.
    assert "deptry" in summary["unavailable"]
    assert summary["exit_code"] == cmt.EXIT_OK
    assert any("different name" in note for note in summary["notes"]), summary["notes"]


def test_e2e_the_rust_repo_reuses_the_shared_gate_names(rust_synced_repo, quality_md):
    """A language layer owns `install`/`all`/`test` so the rest of the template needn't.

    Worth asserting because it is what lets `/quality`'s prose stay language-neutral: if
    a Rust repo stopped defining `test`, the shared gate list would silently measure less.
    """
    summary = cmt.probe(rust_synced_repo, quality_md)
    assert "test" in summary["available"]
    assert {"install", "all"} <= set(summary["undeclared"] + summary["available"])


# --- end-to-end: discovery against a synced Go repo ---------------------------


def _go_make_targets(repo: Path) -> set[str]:
    """Return the documented targets the synced Go make include really defines."""
    includes = [p for p in (repo / ".rhiza" / "make.d").glob("*.mk") if "go" in p.name]
    assert includes, "no Go make include in the synced repo"
    documented = re.compile(r"^([a-z][a-z0-9_-]*)::?.*?##\s*(.+)$", re.MULTILINE)
    return {m[0] for p in includes for m in documented.findall(p.read_text())}


def test_e2e_the_go_templates_own_targets_are_all_discovered(go_synced_repo):
    """Read from `.rhiza/make.d/go.mk`, not listed here: the template owns its gate names."""
    discovered = cmt.documented_targets(go_synced_repo)
    missing = sorted(_go_make_targets(go_synced_repo) - set(discovered))
    assert missing == [], f"the Go layer defines targets discovery missed: {missing}"


def test_e2e_the_go_gates_resolve_for_make(go_synced_repo):
    for target in sorted(_go_make_targets(go_synced_repo)):
        assert cmt.target_exists(go_synced_repo, target), f"make cannot resolve {target}"


def test_e2e_a_go_repo_is_never_reported_as_having_nothing_to_check(go_synced_repo, quality_md):
    """The same guarantee as for Rust, on the language the discovery hint names."""
    summary = cmt.probe(go_synced_repo, quality_md)
    assert summary["undeclared"], "a synced Go repo documents targets beyond the prose's list"
    assert summary["available"], summary["notes"]
    assert "deptry" in summary["unavailable"], "deptry is Python's; Go's analogue is `deps`"
    assert "deps" in summary["undeclared"]
    assert summary["exit_code"] == cmt.EXIT_OK


# --- end-to-end: a `test` gate that resolves but measures nothing --------------
#
# One level past "the target exists". Everything above asks whether `make test` *resolves*;
# a target that resolves and then collects zero tests passes every check in this file and
# still measures nothing — which is what `go-core` was fixed for in the template's v1.3.1,
# by shipping `internal/version/version_test.go` so a fresh Go repo's test gate is not
# vacuous. Nothing was asking the same question of the other two languages.


def _collectible_tests(repo: Path, language: str) -> list[str]:
    """Return the files *language*'s `test` target would actually collect in *repo*.

    Test-local rather than a `language_profile.py` field: that registry describes the
    ecosystem facts the *commands* consume, and "what the runner would pick up" is not one
    of them — it is this suite's yardstick, and putting it in the shipped plugin would be
    inventing a consumer for it.

    `.rhiza/` is excluded deliberately, and it is the whole point on Python: the sync does
    deliver tests there (`test_pyproject.py`, `test_docstrings.py`, ...), but they are
    rhiza's own and run under the separate `rhiza-test` target. Counting them here would
    report the project's `test` gate as covered by somebody else's tests.
    """
    found: Iterable[Path]
    if language == "python":
        found = repo.glob("tests/**/test_*.py")
    elif language == "go":
        found = repo.rglob("*_test.go")
    else:
        # Rust keeps unit tests inline behind `#[cfg(test)]`, so there is no filename to
        # match: the attribute in the source is the only evidence a file carries tests.
        found = (p for p in repo.rglob("*.rs") if "#[test]" in p.read_text())
    return sorted(str(p.relative_to(repo)) for p in found if ".rhiza" not in p.parts)


_PYTHON_TEST_GATE_IS_VACUOUS = (
    "A freshly /init'd and synced Python repo has no test its `test` target can collect: "
    "`uv init --lib` writes none, /init seeds no first module by design, and rhiza's "
    "`python-core` ships none under `tests/` — so `make test` prints 'No test files found "
    "in tests, skipping tests' and exits 0. `go-core` fixed exactly this vacuity in the "
    "template's v1.3.1 by shipping internal/version/version_test.go; the Python analogue "
    "has not shipped, and the fix is upstream's rather than this plugin's. strict=True, so "
    "the day it does ship this test turns red and the marker goes with it."
)


@pytest.mark.parametrize(
    "language",
    [
        "rust",
        "go",
        pytest.param(
            "python",
            marks=pytest.mark.xfail(strict=True, reason=_PYTHON_TEST_GATE_IS_VACUOUS),
        ),
    ],
)
def test_e2e_the_test_gate_of_a_fresh_repo_collects_something(language: str, request):
    """`make test` must have something to run in a repo straight out of /init + /update.

    Asserted on the *unseeded* fixtures — `python_synced_repo`, not `synced_repo`, whose
    hand-written module is precisely what hides this.
    """
    repo = request.getfixturevalue(f"{language}_synced_repo")
    assert cmt.target_exists(repo, "test"), f"a synced {language} repo defines no `test` target"
    collectible = _collectible_tests(repo, language)
    assert collectible, (
        f"a synced {language} repo's `test` target resolves but would collect nothing, so "
        "the gate passes while measuring zero code"
    )
