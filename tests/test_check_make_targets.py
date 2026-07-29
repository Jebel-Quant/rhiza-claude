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
import shutil
from pathlib import Path

import check_make_targets as cmt
import pytest
from conftest import assert_ok, run_cmd

_ROOT = Path(__file__).resolve().parents[1]
_QUALITY = _ROOT / "commands" / "quality.md"

pytestmark = pytest.mark.skipif(shutil.which("make") is None, reason="make not available")


# --- the target list comes from the prose, not from a duplicate ---------------


def test_gate_targets_are_parsed_from_the_command():
    """Derived, so the probe cannot drift from what /quality says it runs."""
    assert cmt.gate_targets(_QUALITY) == [
        "fmt",
        "typecheck",
        "docs-coverage",
        "deptry",
        "security",
        "rhiza-test",
        "test",
    ]


def test_gate_order_is_preserved():
    """/quality runs cheapest-first, so the report should follow the same order."""
    targets = cmt.gate_targets(_QUALITY)
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


def test_an_unsynced_repo_reports_every_gate_unavailable(managed_unsynced_repo):
    """The exact failure mode: no makefile, so nothing can be scored.

    Reported as unavailable with a pointer at /update — not as seven failures.
    """
    result = cmt.probe(managed_unsynced_repo, _QUALITY)
    assert result["available"] == []
    assert result["unavailable"] == cmt.gate_targets(_QUALITY)
    assert result["exit_code"] == cmt.EXIT_UNAVAILABLE
    assert any("not synced" in n and "/rhiza:update" in n for n in result["notes"])


def test_a_synced_repo_finds_every_gate(managed_synced_repo):
    result = cmt.probe(managed_synced_repo, _QUALITY)
    assert result["available"] == cmt.gate_targets(_QUALITY)
    assert result["unavailable"] == []
    assert result["exit_code"] == cmt.EXIT_OK
    assert result["notes"] == []


def test_a_reduced_profile_reports_only_its_missing_gates(partial_profile_repo):
    """Profile variation is legitimate — the tests-bundle gates are simply absent."""
    result = cmt.probe(partial_profile_repo, _QUALITY)
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


def test_an_unmanaged_repo_has_nothing_to_probe(unmanaged_repo):
    result = cmt.probe(unmanaged_repo, _QUALITY)
    assert result["unavailable"] == cmt.gate_targets(_QUALITY)
    assert result["exit_code"] == cmt.EXIT_UNAVAILABLE


def test_a_makefile_with_none_of_the_gates_is_called_out(managed_unsynced_repo):
    """A repo with its own unrelated Makefile — present, but not the template's.

    Distinct from having no makefile at all: something *is* there, so the likely cause
    is an incomplete sync rather than an unmanaged repo, and the note says so.
    """
    (managed_unsynced_repo / "Makefile").write_text(".PHONY: build\nbuild: ; @echo build\n")
    result = cmt.probe(managed_unsynced_repo, _QUALITY)
    assert result["available"] == []
    assert result["exit_code"] == cmt.EXIT_OK  # probing worked; the repo is just bare
    assert any("template sync completed" in n for n in result["notes"])


# --- this repo, which is where the bug was live ------------------------------


def test_this_plugin_repo_lacks_the_template_gates():
    """Pins the state that made /quality unrunnable here, so a future fix is visible.

    The plugin repo is not rhiza-managed, so it has only its own `test` target. If this
    ever changes — because the repo adopts the template — the assertion should be
    updated deliberately rather than silently.
    """
    result = cmt.probe(_ROOT, _QUALITY)
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


def test_main_reports_each_target(managed_synced_repo, capsys):
    rc = cmt.main(["--target-dir", str(managed_synced_repo), "--from", str(_QUALITY)])
    assert rc == cmt.EXIT_OK
    out = capsys.readouterr().out
    assert "available    make fmt" in out
    assert "available    make test" in out


def test_main_marks_missing_targets_unavailable(partial_profile_repo, capsys):
    rc = cmt.main(["--target-dir", str(partial_profile_repo), "--from", str(_QUALITY)])
    assert rc == cmt.EXIT_OK
    captured = capsys.readouterr()
    assert "unavailable  make typecheck" in captured.out
    assert "out-of-scope" in captured.err


def test_main_require_turns_a_missing_target_into_a_failure(partial_profile_repo):
    """For a repo that expects the full profile, absence should fail the run."""
    args = ["--target-dir", str(partial_profile_repo), "--from", str(_QUALITY)]
    assert cmt.main(args) == cmt.EXIT_OK
    assert cmt.main([*args, "--require"]) == cmt.EXIT_UNAVAILABLE


def test_main_json_output(managed_synced_repo, capsys):
    rc = cmt.main(["--target-dir", str(managed_synced_repo), "--from", str(_QUALITY), "--json"])
    assert rc == cmt.EXIT_OK
    payload = json.loads(capsys.readouterr().out)
    assert payload["available"] == cmt.gate_targets(_QUALITY)
    assert payload["unavailable"] == []


def test_main_defaults_to_the_bundled_quality_command(managed_synced_repo, capsys):
    """With no --from, it reads the shipped commands/quality.md."""
    rc = cmt.main(["--target-dir", str(managed_synced_repo)])
    assert rc == cmt.EXIT_OK
    assert "make fmt" in capsys.readouterr().out


def test_main_on_an_unsynced_repo_exits_1(managed_unsynced_repo, capsys):
    rc = cmt.main(["--target-dir", str(managed_unsynced_repo), "--from", str(_QUALITY)])
    assert rc == cmt.EXIT_UNAVAILABLE
    assert "not synced" in capsys.readouterr().err


# --- end-to-end: /quality's gates against a real sync -------------------------


def test_e2e_every_gate_quality_names_is_provided_by_the_template(synced_repo):
    """The assertion that would have caught /quality being unrunnable.

    /quality names seven `make` targets and used to probe none of them. Here the target
    list is read from the shipped commands/quality.md and checked against a repo synced
    from the real template — so a gate the template stops providing, or one added to the
    prose that it never provided, fails in CI instead of in front of a user.
    """
    result = cmt.probe(synced_repo, _QUALITY)
    assert result["unavailable"] == [], f"the template does not provide: {result['unavailable']}"
    assert result["available"] == cmt.gate_targets(_QUALITY)


def test_e2e_the_gates_run_and_not_just_resolve(synced_repo):
    """Resolving is not the same as working — run the cheapest real gate."""
    assert_ok(run_cmd(["make", "fmt"], synced_repo), "make fmt")


def test_e2e_quality_gates_exist_on_the_gitlab_profile_too(gitlab_synced_repo):
    """The gates come from `core`/`tests`, which both profiles include.

    Worth asserting rather than assuming: /quality names one gate list, and a
    GitLab-hosted repo must not be scored against gates it was never given.
    """
    result = cmt.probe(gitlab_synced_repo, _QUALITY)
    assert result["unavailable"] == [], f"gitlab profile lacks: {result['unavailable']}"
