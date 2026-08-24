"""Outcome tests for the gate probe (`scripts/check_make_targets.py`).

Where the contract tests verify that a command *refers* to things that exist, these
verify what a command actually *finds* when it runs — against fixture repos in the
three states a rhiza command really meets: unmanaged, managed-but-unsynced, and synced.

The bug being pinned is concrete. `/quality` runs seven `make` targets that the sync
delivers, and it used to run them unprobed: in an unsynced repo all seven returned
"No rule to make target", were scored FAIL, and the repo was reported broken when it
was merely unsynced. Six of the seven were absent in this plugin's own repo when that was
found, and nothing caught it for however long it had been true. This repo has since
adopted the v1.4 shim, so it is now a fixture for the *other* half of the problem —
a makefile that answers everything, where probing can prove nothing either way.
"""

from __future__ import annotations

import json
import re
import shutil
from collections.abc import Iterable
from pathlib import Path

import _rhiza_layout as layout
import check_make_targets as cmt
import pytest
from conftest import assert_ok, run_cmd

pytestmark = pytest.mark.skipif(shutil.which("make") is None, reason="make not available")


@pytest.fixture(scope="session")
def quality_md(repo_root: Path) -> Path:
    """`/quality`'s command file — the single source of the gate list the probe reads.

    Resolved by name rather than by path. Hardcoding one silently pointed at a file that
    no longer existed when `/quality` moved layouts, and `probe` reads a missing file as a
    repo with *no gates*: every assertion here failed with an empty target list rather
    than with "file not found", which is a slow thing to diagnose.
    """
    found = {name: path for name, path in layout.command_files(repo_root)}
    return found["quality"]


# --- the target list comes from the prose, not from a duplicate ---------------


def test_gate_targets_are_parsed_from_the_command(quality_md: Path):
    """Derived, so the probe cannot drift from what /quality says it runs."""
    assert cmt.gate_targets(quality_md) == [
        "fmt",
        "typecheck",
        "docs-coverage",
        "deps",
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
    doc.write_text(
        "1. `make fmt` — a\n2. `make fmt` — again\n3. `make test` — b\n", encoding="utf-8"
    )
    assert cmt.gate_targets(doc) == ["fmt", "test"]


def test_gate_targets_ignores_prose_mentions_of_make(tmp_path):
    """Only the numbered gate list counts, not every `make x` in the document."""
    doc = tmp_path / "c.md"
    doc.write_text(
        "Run `make help` first.\n\n1. `make fmt` — a\n\nLater, `make book` builds docs.\n",
        encoding="utf-8",
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


def test_a_synced_v14_repo_without_a_makefile_is_not_reported_unsynced(
    makeless_synced_repo, quality_md
):
    """Issue #204: `rhiza.mk` stopped being the proof of a sync, `template.lock` is.

    Template v1.4 retired the make layer and made the `Makefile` repo-owned, so a repo
    that is fully synced to the newest template can have none. Reporting that repo as
    unsynced sends the reader to `/rhiza:update`, which is already done.
    """
    result = cmt.probe(makeless_synced_repo, quality_md)
    assert result["available"] == []
    assert result["unavailable"] == []
    assert result["undetermined"] == cmt.gate_targets(quality_md)
    assert not any("not synced" in n for n in result["notes"])
    assert any("rhiza-task list" in n for n in result["notes"])
    assert any("out-of-scope, never FAIL" in n for n in result["notes"])


def test_the_unsynced_note_needs_both_the_makefile_and_the_lock_absent(
    makeless_synced_repo, quality_md
):
    """The same repo, minus the lock: back to the unsynced diagnosis.

    Pins the discriminator itself rather than the two outcomes, so a probe that reached
    the right answer by some other route (the `.rhiza/` directory, `template.yml`) fails
    here instead of passing both tests above.
    """
    (makeless_synced_repo / ".rhiza" / "template.lock").unlink()
    result = cmt.probe(makeless_synced_repo, quality_md)
    assert result["unavailable"] == cmt.gate_targets(quality_md)
    assert any("not synced" in n and "/rhiza:update" in n for n in result["notes"])


def test_a_makeless_synced_repo_reports_undetermined_in_the_text_report(
    makeless_synced_repo, capsys, quality_md
):
    """`undetermined`, not `unavailable`, is what the reader must see in the report."""
    rc = cmt.main(["--target-dir", str(makeless_synced_repo), "--from", str(quality_md)])
    assert rc == cmt.EXIT_UNAVAILABLE
    out, err = capsys.readouterr()
    assert "undetermined make fmt" in out
    assert "unavailable" not in out
    assert "rhiza-task" in err


def test_a_synced_repo_finds_every_gate(managed_synced_repo, quality_md):
    result = cmt.probe(managed_synced_repo, quality_md)
    assert result["available"] == cmt.gate_targets(quality_md)
    assert result["unavailable"] == []
    assert result["exit_code"] == cmt.EXIT_OK
    assert result["notes"] == []


def test_a_reduced_profile_reports_only_its_missing_gates(partial_profile_repo, quality_md):
    """Profile variation is legitimate — the tests-bundle gates are simply absent."""
    result = cmt.probe(partial_profile_repo, quality_md)
    assert set(result["available"]) == {"fmt", "deps"}
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
    (managed_unsynced_repo / "Makefile").write_text(
        ".PHONY: build\nbuild: ; @echo build\n", encoding="utf-8"
    )
    result = cmt.probe(managed_unsynced_repo, quality_md)
    assert result["available"] == []
    assert result["exit_code"] == cmt.EXIT_OK  # probing worked; the repo is just bare
    assert any("template sync completed" in n for n in result["notes"])


# --- this repo, which is where the bug was live ------------------------------


def test_this_plugin_repo_reports_every_gate_undetermined(quality_md: Path, repo_root: Path):
    """This repo now carries the v1.4 shim, so probing it proves nothing — by design.

    The previous assertion here was `available == ["test"]` and `"fmt" in unavailable`,
    which held while the `Makefile` defined its targets directly. Adopting the shim added a
    `%:` catch-all, so `make -n <anything>` exits 0 and the one instrument this script has
    is a tautology. That is the exact condition the script detects and reports as
    **undetermined** — neither available nor a failure — and this repo is now a real
    fixture for it rather than a hypothetical.

    Note `test` is undetermined too, despite `local.mk` genuinely defining it. Once a
    catch-all exists there is no probe that can tell a real target from a typo, so the
    honest answer is "cannot tell" for all of them. `/quality` scores undetermined
    out-of-scope, never FAIL, which is why this costs a repo nothing but a note.

    Change this deliberately, as its predecessor asked to be: it moves only if the shim or
    the gate list does.
    """
    result = cmt.probe(repo_root, quality_md)
    assert result["available"] == []
    assert result["unavailable"] == []
    assert set(result["undetermined"]) == set(result["targets"])
    assert "test" in result["undetermined"]
    assert result["exit_code"] == cmt.EXIT_OK
    assert any("catch-all rule" in n for n in result["notes"])

    # The discovery half still works, and is what a shimmed repo has instead: every
    # `##`-documented target in `local.mk` comes back as undeclared-but-real. `lint` is
    # absent from that set by design — it is delegated to the CLI, which has no task of
    # that name — so this names only targets `local.mk` actually defines.
    assert {"audit", "e2e", "install"} <= set(result["undeclared"])


# --- probing is side-effect free ---------------------------------------------


def test_probing_runs_no_recipes(managed_synced_repo):
    """`make -n` must expand without executing, or probing would have side effects."""
    marker = managed_synced_repo / "SIDE_EFFECT"
    (managed_synced_repo / ".rhiza" / "rhiza.mk").write_text(
        ".PHONY: fmt\nfmt: ; @touch SIDE_EFFECT\n", encoding="utf-8"
    )
    assert cmt.target_exists(managed_synced_repo, "fmt")
    assert not marker.exists()


def test_target_exists_is_false_for_an_undefined_target(managed_synced_repo):
    assert not cmt.target_exists(managed_synced_repo, "definitely-not-a-target")


def test_find_makefile_accepts_the_conventional_names(tmp_path):
    assert cmt.find_makefile(tmp_path) is None
    (tmp_path / "GNUmakefile").write_text("x: ; @:\n", encoding="utf-8")
    assert cmt.find_makefile(tmp_path).name == "GNUmakefile"


# --- no gate list at all -----------------------------------------------------


def test_a_command_without_a_gate_list_exits_2(managed_synced_repo, tmp_path):
    doc = tmp_path / "empty.md"
    doc.write_text("# No gates here\n", encoding="utf-8")
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
    gates = cmt.gate_targets(quality_md)
    result = cmt.probe(synced_repo, quality_md)
    assert result["unavailable"] == [], f"the template does not provide: {result['unavailable']}"
    # From template v1.4 the shim's `%:` rule answers every name, so `make -n` cannot tell
    # a gate from a typo and the probe says so rather than guessing. Asserting
    # `available` here is what would make this test vacuous.
    assert result["undetermined"] == gates, result["notes"]
    # The answer moved to the runner, so that is where it is now checked.
    missing = sorted(set(gates) - _runner_tasks(synced_repo))
    assert missing == [], f"the pinned runner does not provide: {missing}"


# `make test` is executed by tests/test_init_scaffold.py, which owns the coverage-gate
# assertion; `make rhiza-test` has its own test below because it is the one gate that
# does not pass. Everything else in /quality's list runs here.
_RUNNABLE_GATES = ("fmt", "typecheck", "security", "deps", "docs-coverage")


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
# Empty, and that is the state to keep it in: at PINNED_TEMPLATE_REF the template's own
# tests accept this plugin's scaffold outright. The last entry was
# `TestDependencyGroups::test_lint_group_present` — `init_skeleton.py` stopped seeding a
# `lint` dependency group because the template provisions every linter through prek/uvx,
# and rhiza #1484 dropped the requirement in v1.3.2, which retired the tolerance.
_UPSTREAM_KNOWN_FAILURES: set[str] = set()


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
    # assertable while nothing is tolerated — which, with `_UPSTREAM_KNOWN_FAILURES`
    # empty, is now. The guard stays so re-adding an entry needs no rework here.
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
        "internal-thing:\n\ttrue\n",  # undocumented: deliberately not discovered
        encoding="utf-8",
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
        "lint:  ## golangci-lint run\n\ttrue\n",
        encoding="utf-8",
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
        "test:  ## go test ./...\n\ttrue\nvet:  ## go vet ./...\n\ttrue\n", encoding="utf-8"
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
    (root / "Makefile").write_text(
        "LOGO=x\ninclude .rhiza/rhiza.mk\n-include local.mk\n", encoding="utf-8"
    )
    (root / ".rhiza" / "make.d").mkdir(parents=True, exist_ok=True)
    (root / ".rhiza" / "rhiza.mk").write_text(
        "help:  ## Display this help message\n\ttrue\n-include .rhiza/make.d/*.mk\n",
        encoding="utf-8",
    )
    (root / ".rhiza" / "make.d" / "rust.mk").write_text(
        "test::  ## run the test suite with nextest\n\ttrue\n"
        "deps:  ## report unused dependencies (the deptry analogue)\n\ttrue\n"
        "license:  ## run license compliance scan\n\ttrue\n",
        encoding="utf-8",
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
        "include .rhiza/rhiza.mk\ninclude .rhiza/rhiza.mk\n-include local.mk\n", encoding="utf-8"
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
    (tmp_path / "local.mk").write_text("mine:  ## my own target\n\ttrue\n", encoding="utf-8")
    assert "mine" in cmt.documented_targets(tmp_path)


def test_an_include_naming_a_make_variable_is_left_alone(tmp_path):
    """`include $(EXTRA)` cannot be resolved without evaluating make — omit, don't guess."""
    (tmp_path / "Makefile").write_text(
        "include $(EXTRA_MK)\nhelp:  ## help\n\ttrue\n", encoding="utf-8"
    )
    assert [p.name for p in cmt.makefile_chain(tmp_path)] == ["Makefile"]
    assert cmt.documented_targets(tmp_path) == {"help": "help"}


def test_a_cyclic_include_terminates(tmp_path):
    (tmp_path / "Makefile").write_text("include a.mk\n", encoding="utf-8")
    (tmp_path / "a.mk").write_text(
        "include Makefile\nlooped:  ## still found\n\ttrue\n", encoding="utf-8"
    )
    assert [p.name for p in cmt.makefile_chain(tmp_path)] == ["Makefile", "a.mk"]
    assert "looped" in cmt.documented_targets(tmp_path)


def test_include_following_is_depth_limited(tmp_path):
    (tmp_path / "Makefile").write_text("include a.mk\n", encoding="utf-8")
    (tmp_path / "a.mk").write_text("include b.mk\n", encoding="utf-8")
    (tmp_path / "b.mk").write_text("deep:  ## too deep\n\ttrue\n", encoding="utf-8")
    assert [p.name for p in cmt.makefile_chain(tmp_path, depth=1)] == ["Makefile", "a.mk"]
    assert [p.name for p in cmt.makefile_chain(tmp_path, depth=2)] == ["Makefile", "a.mk", "b.mk"]


def test_makefile_chain_without_a_makefile_is_empty(tmp_path):
    assert cmt.makefile_chain(tmp_path) == []


def test_a_differently_named_analogue_is_pointed_at(managed_unsynced_repo, quality_md):
    """Most named gates resolve; the one that doesn't has an analogue under another name.

    Scoring the absent one out-of-scope and stopping there skips a concern the repo does
    cover. `deptry`/`deps` was the case that motivated this and is no longer one — the
    prose names `deps`, which every language layer agrees on — so the fixture renames a
    different gate rather than re-enacting a rename that has since happened.
    """
    _synced_layout(managed_unsynced_repo)
    (managed_unsynced_repo / ".rhiza" / "make.d" / "quality.mk").write_text(
        "fmt:  ## format\n\ttrue\ntypecheck:  ## clippy\n\ttrue\n"
        "security:  ## advisories\n\ttrue\nrhiza-test:  ## template tests\n\ttrue\n"
        "docs:  ## docstring coverage, under this template's name for it\n\ttrue\n",
        encoding="utf-8",
    )
    summary = cmt.probe(managed_unsynced_repo, quality_md)
    assert summary["unavailable"] == ["docs-coverage"]
    assert "docs" in summary["undeclared"]
    assert any("under a different name" in note for note in summary["notes"])


def test_a_command_without_a_gate_list_still_returns_the_discovery_keys(tmp_path):
    empty = tmp_path / "empty.md"
    empty.write_text("# no gates here\n", encoding="utf-8")
    summary = cmt.probe(tmp_path, empty)
    assert summary["undeclared"] == [] and summary["documented"] == {}
    assert summary["undetermined"] == []


def test_main_prints_discovered_targets(managed_unsynced_repo, capsys):
    (managed_unsynced_repo / "Makefile").write_text(
        "vet:  ## go vet ./...\n\ttrue\n", encoding="utf-8"
    )
    cmt.main(["--target-dir", str(managed_unsynced_repo)])
    out = capsys.readouterr().out
    assert "discovered   make vet  # go vet ./..." in out


def test_this_repo_discovers_its_own_documented_targets(repo_root: Path):
    """rhiza-claude's own `local.mk` uses the convention, so this is a live check.

    `lint` used to head this list and was dropped from it deliberately: it is one of the
    three targets (`lint`, `book-serve`, `changelog`) now left to the shim's catch-all, so
    it is not defined anywhere `documented_targets` reads. The assertion on a description
    moved to `test` rather than being deleted — without one, this only checks that names
    are found and would pass with every description dropped on the floor.
    """
    found = cmt.documented_targets(repo_root)
    assert {"test", "book", "clean"} <= set(found)
    assert found["test"] == "Run the script test suite with a 100% coverage gate"


# --- a makefile that answers everything --------------------------------------
#
# Template v1.4's shim delegates through `%:`, so `make -n <anything>` exits 0 and the
# probe's one instrument stops discriminating. The bug that reached a user is the mirror
# image of the unsynced-repo bug at the top of this file: every gate came back
# available, the retired `deptry` alias included, on a repo whose only task is `deps` —
# so /quality ran a gate that does not exist and scored the runner's "unknown task"
# error as a FAIL.


def test_a_shim_reports_no_gate_as_available(shim_repo, quality_md):
    """The defect, pinned: an answer of "yes to everything" is not availability."""
    summary = cmt.probe(shim_repo, quality_md)
    assert summary["available"] == []
    assert summary["unavailable"] == []
    assert summary["undetermined"] == cmt.gate_targets(quality_md)


def test_a_shim_is_not_scored_as_a_failure(shim_repo, quality_md):
    """Undetermined is neither available nor absent, and never an error exit."""
    assert cmt.probe(shim_repo, quality_md)["exit_code"] == cmt.EXIT_OK


def test_the_shim_notes_name_the_file_the_task_list_and_how_to_score_a_miss(shim_repo, quality_md):
    """Three things a model needs: why, how to enumerate, and how to score a miss."""
    notes = cmt.probe(shim_repo, quality_md)["notes"]
    assert any("catch-all rule in Makefile" in note for note in notes)
    assert any("`uvx rhiza-task@0.3.1 list`" in note and "`make help`" in note for note in notes)
    assert any("out-of-scope, never FAIL" in note for note in notes)


def test_the_shim_note_enumerates_at_the_pin_the_makefile_carries(shim_repo, quality_md):
    """The version is the point, not decoration.

    `uvx rhiza-task list` answers for whatever release is current; the gates this repo
    actually runs are the ones its pin names. Enumerating against the wrong catalogue is
    the same class of error as probing a file the template stopped shipping — plausible
    output, silently about a different thing.
    """
    (shim_repo / "Makefile").write_text(
        (shim_repo / "Makefile").read_text(encoding="utf-8").replace("0.3.1", "9.9.9"),
        encoding="utf-8",
    )
    notes = cmt.probe(shim_repo, quality_md)["notes"]
    assert any("`uvx rhiza-task@9.9.9 list`" in note for note in notes)


def test_a_shim_without_a_pin_names_the_unpinned_runner(managed_unsynced_repo, quality_md):
    """A catch-all with no `RHIZA_TASK` line: still enumerable, just not at a version."""
    (managed_unsynced_repo / "Makefile").write_text("%: ; @uvx rhiza-task $@\n", encoding="utf-8")
    notes = cmt.probe(managed_unsynced_repo, quality_md)["notes"]
    assert any("`uvx rhiza-task list`" in note for note in notes)
    assert not any("@" in note and "rhiza-task@" in note for note in notes)


def test_pinned_task_runner_reads_the_chain_not_just_the_root(tmp_path):
    """The pin can arrive through an include, the same as any other make variable."""
    (tmp_path / "Makefile").write_text("include shared.mk\n%: ; @uvx $(RHIZA_TASK) $@\n")
    (tmp_path / "shared.mk").write_text("RHIZA_TASK ?= rhiza-task@1.1.0\n")
    assert cmt.pinned_task_runner(tmp_path) == "rhiza-task@1.1.0"


def test_pinned_task_runner_is_none_without_a_makefile(tmp_path):
    assert cmt.pinned_task_runner(tmp_path) is None


# --- the seam to the task runner --------------------------------------------------
#
# `_make_targets_runner` owns the pin pattern, the table parse and the subprocess, and
# `test__make_targets_runner.py` tests them. What is this module's is the *seam*: that the
# chain walk feeds the pin reader, that the pin and the repo reach the runner, and that
# `--tasks` reports both outcomes.


def test_runner_tasks_hands_the_chains_pin_and_the_repo_to_the_runner(tmp_path, monkeypatch):
    """The wrapper's whole job, asserted as the two arguments it composes.

    The pin has to come from the *chain* rather than the root file, and the repo has to be
    passed through — a bare `uvx rhiza-task list` answers for the current release and the
    wrong language layer. Both were separately wrong at some point in the make layer's
    retirement, so both are named here.
    """
    (tmp_path / "Makefile").write_text("-include local.mk\n%: ; @uvx $@\n", encoding="utf-8")
    (tmp_path / "local.mk").write_text("RHIZA_TASK ?= rhiza-task@9.9.9\n", encoding="utf-8")
    seen: dict[str, object] = {}

    def fake_tasks(pin, cwd):
        seen["pin"], seen["cwd"] = pin, cwd
        return ["fmt", "test"]

    monkeypatch.setattr(cmt._runner, "tasks", fake_tasks)
    assert cmt.runner_tasks(tmp_path) == ["fmt", "test"]
    assert seen == {"pin": "rhiza-task@9.9.9", "cwd": tmp_path}


def test_runner_tasks_is_none_when_the_repo_does_not_delegate(tmp_path):
    """No pin, no runner to ask — and that is not the same as having no gates."""
    (tmp_path / "Makefile").write_text("test: ; @pytest\n", encoding="utf-8")
    assert cmt.runner_tasks(tmp_path) is None


def test_delegating_notes_reads_the_catch_all_file_and_the_pin_off_disk(tmp_path):
    """The two facts this module contributes to the runner's wording.

    The note names the file the catch-all is in, which only a makefile read can supply, so
    a shim whose delegation moved into an include still gets named correctly.
    """
    (tmp_path / "Makefile").write_text(
        "RHIZA_TASK ?= rhiza-task@1.1.0\n%: ; @uvx $@\n", encoding="utf-8"
    )
    notes = cmt._delegating_notes(tmp_path, ["fmt", "test"])
    assert "a catch-all rule in Makefile" in notes[0]
    assert "uvx rhiza-task@1.1.0 list" in notes[1]


def test_main_tasks_prints_one_task_per_line(tmp_path, monkeypatch, capsys):
    """`--tasks` is the supported way to get the list without parsing the runner."""
    monkeypatch.setattr(cmt, "runner_tasks", lambda _d: ["fmt", "test"])
    assert cmt.main(["--target-dir", str(tmp_path), "--tasks"]) == cmt.EXIT_OK
    assert capsys.readouterr().out.split() == ["fmt", "test"]


def test_main_tasks_says_so_when_it_cannot_enumerate(tmp_path, monkeypatch, capsys):
    """Exit 1 with a reason, rather than printing nothing and exiting 0.

    Silence at exit 0 reads as "this repo has no tasks", which is the misreading the None
    return exists to prevent — so the CLI must not launder it into an empty list.
    """
    monkeypatch.setattr(cmt, "runner_tasks", lambda _d: None)
    assert cmt.main(["--target-dir", str(tmp_path), "--tasks"]) == cmt.EXIT_UNAVAILABLE
    assert "could not enumerate tasks" in capsys.readouterr().err


# --- end-to-end: gate discovery on a synced Rust and Go repo -------------------
#
# The decision #94 made was: discover the gates, never table them. That still holds, but
# *where* they are discovered moved. Through template v1.3 each language shipped a
# `.rhiza/make.d/<lang>.mk` and these tests read the names out of it. v1.4 retired the
# make layer, so there is no include to read and — because the shim answers every target
# — nothing make can be asked either. The catalogue is the pinned `rhiza-task`'s, and
# `cmt.runner_tasks` is how it is read. Nothing below names a gate as a language
# expectation; every name is either read from the runner or read from `/quality`'s prose.


def _runner_tasks(repo: Path) -> set[str]:
    """The task names the repo's own pinned runner provides.

    Asserted non-empty rather than returned raw: an empty set would let every membership
    check below pass trivially, which is the shape of the bug these tests exist to catch.
    """
    tasks = cmt.runner_tasks(repo)
    assert tasks, f"could not enumerate the pinned runner's tasks in {repo}"
    return set(tasks)


@pytest.mark.parametrize("fixture", ["rust_synced_repo", "go_synced_repo"])
def test_e2e_a_non_python_repo_is_never_reported_as_having_nothing_to_check(
    fixture, request, quality_md
):
    """The failure `/quality`'s probe exists to prevent, on the languages it was added for.

    Before discovery followed the include chain, a synced Rust repo reported zero
    discoverable gates and `/quality` scored their concerns out-of-scope while the
    analogues sat there. The include chain is gone; the guarantee is not, so it is now
    measured against the runner.
    """
    repo = request.getfixturevalue(fixture)
    summary = cmt.probe(repo, quality_md)
    assert summary["exit_code"] == cmt.EXIT_OK, summary["notes"]
    assert summary["unavailable"] == [], summary["notes"]
    assert summary["undetermined"] == cmt.gate_targets(quality_md), summary["notes"]
    assert cmt.pinned_task_runner(repo), "a synced repo carries no rhiza-task pin"
    assert _runner_tasks(repo), "the runner enumerates no tasks at all"


@pytest.mark.parametrize("fixture", ["rust_synced_repo", "go_synced_repo"])
def test_e2e_every_gate_the_prose_names_is_provided_in_every_language(fixture, request, quality_md):
    """`/quality`'s gate list is language-neutral, and now that is true rather than hoped.

    Under the make layer most of the seven were simply absent outside Python, which is why
    the prose carries a whole section on scoring an unavailable gate out-of-scope. The
    runner ships them in every layer, so a language that stops providing one is a real
    regression in `/quality`'s reach and fails here.
    """
    repo = request.getfixturevalue(fixture)
    missing = sorted(set(cmt.gate_targets(quality_md)) - _runner_tasks(repo))
    assert missing == [], f"{fixture} does not provide: {missing}"


@pytest.mark.parametrize("fixture", ["rust_synced_repo", "go_synced_repo"])
def test_e2e_the_language_layers_reuse_the_shared_gate_names(fixture, request):
    """A language layer owns `install`/`all`/`test` so the rest of the template needn't.

    Worth asserting because it is what lets `/quality`'s prose stay language-neutral: if
    a layer stopped defining `test`, the shared gate list would silently measure less.
    """
    shared = {"install", "all", "test"}
    repo = request.getfixturevalue(fixture)
    assert shared <= _runner_tasks(repo), sorted(shared - _runner_tasks(repo))


def test_e2e_each_language_layer_contributes_something_of_its_own(rust_synced_repo, go_synced_repo):
    """The layers are not one catalogue wearing three hats.

    Deliberately stated as a *difference* rather than by naming the Rust and Go tasks:
    naming them would be the tabling #94 rejected, and would fail the day upstream renames
    one. That the two sets differ at all is what proves a language layer is being
    resolved, which is the property `/quality` depends on when it says the gates are the
    repo's own.
    """
    rust, go = _runner_tasks(rust_synced_repo), _runner_tasks(go_synced_repo)
    assert rust != go, "the Rust and Go layers resolve to an identical task set"
    assert rust - go, "the Rust layer contributes no task the Go layer lacks"
    assert go - rust, "the Go layer contributes no task the Rust layer lacks"


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
        found = (p for p in repo.rglob("*.rs") if "#[test]" in p.read_text(encoding="utf-8"))
    return sorted(str(p.relative_to(repo)) for p in found if ".rhiza" not in p.parts)


# Python was the last language to answer this. `uv init --lib` writes no test and /init
# seeds no first module by design, so a fresh Python repo's `test` target printed 'No test
# files found in tests, skipping tests' and exited 0 — measuring nothing while reading
# green. That was carried here as a `strict=True` xfail, because the fix was upstream's
# rather than this plugin's: `go-core` had already shipped internal/version/version_test.go
# in v1.3.1. rhiza #1479 shipped the Python analogue, `tests/test_rhiza_packaging.py`, in
# v1.3.2 — the xfail turned XPASS at the ref bump, and the marker went with it. All three
# languages are now asserted the same way, with no exemption.
@pytest.mark.parametrize("language", ["rust", "go", "python"])
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
