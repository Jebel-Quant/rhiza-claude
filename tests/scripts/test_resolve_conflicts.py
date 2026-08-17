"""Tests for conflict resolution (`scripts/resolve_conflicts.py`) behind `/update` step 6.

This closes the gap in #61. `sync.py` exiting **1** — a template change colliding with a
local edit — is the *normal* outcome of a real `/update`, and it had never been driven
end-to-end. Conflict handling appeared only in `test__rhiza_git.py`'s
`scan_conflict_artifacts` unit tests, never through the documented flow.

It is also the one step that rewrites files the user did not author, so the failure modes
are asymmetric: a marker left behind ships `<<<<<<<` into a repo, and a mis-parsed block
silently discards upstream's change. Both are tested here, along with a genuine
sync-conflict scenario built from a local template so all three sides are controlled.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest
import resolve_conflicts as rc
from conftest import PY, run_cmd

CONFLICT = """\
before
<<<<<<< ours
local edit
=======
upstream edit
>>>>>>> theirs
after
"""


class TestMalformedConflict:
    """The refusal signal — raised instead of writing a plausible-looking file."""

    def test_is_exception_with_message(self):
        err = rc.MalformedConflict("boom")
        assert isinstance(err, Exception)
        assert str(err) == "boom"


# --- take_theirs: the text surgery -------------------------------------------


def test_takes_the_upstream_side_and_drops_ours():
    resolved, blocks = rc.take_theirs(CONFLICT)
    assert resolved == "before\nupstream edit\nafter\n"
    assert blocks == 1


def test_a_file_without_conflicts_is_returned_unchanged():
    text = "line one\nline two\n"
    assert rc.take_theirs(text) == (text, 0)


def test_resolves_several_blocks_in_one_file():
    text = CONFLICT + "middle\n" + CONFLICT
    resolved, blocks = rc.take_theirs(text)
    assert blocks == 2
    assert "local edit" not in resolved
    assert resolved.count("upstream edit") == 2


def test_an_empty_upstream_side_deletes_the_region():
    """Upstream removing a block is a legitimate change, not a no-op."""
    text = "a\n<<<<<<< ours\nlocal\n=======\n>>>>>>> theirs\nb\n"
    assert rc.take_theirs(text) == ("a\nb\n", 1)


def test_content_outside_blocks_is_preserved_byte_for_byte():
    text = "  indented\n\ttabbed\n\n" + CONFLICT + "trailing\n"
    resolved, _ = rc.take_theirs(text)
    assert resolved.startswith("  indented\n\ttabbed\n\n")
    assert resolved.endswith("trailing\n")


def test_a_file_with_no_trailing_newline_survives():
    resolved, _ = rc.take_theirs(CONFLICT.rstrip("\n"))
    assert resolved == "before\nupstream edit\nafter"


def test_marker_lines_need_no_label():
    """git writes `<<<<<<< HEAD`, merge-file may write a bare marker."""
    text = "a\n<<<<<<<\nlocal\n=======\nupstream\n>>>>>>>\nb\n"
    assert rc.take_theirs(text) == ("a\nupstream\nb\n", 1)


# --- malformed input is refused, never guessed at -----------------------------


@pytest.mark.parametrize(
    ("text", "why"),
    [
        ("a\n<<<<<<< ours\nlocal\n", "unterminated"),
        ("a\n<<<<<<< ours\nlocal\n=======\nupstream\n", "unterminated after separator"),
        ("a\n=======\nb\n", "separator with no block"),
        ("a\n>>>>>>> theirs\nb\n", "terminator with no block"),
        ("<<<<<<< a\n<<<<<<< b\n=======\nx\n>>>>>>>\n", "nested"),
        ("<<<<<<< a\nlocal\n=======\n=======\nx\n>>>>>>>\n", "second separator"),
    ],
)
def test_malformed_blocks_raise_rather_than_produce_a_plausible_file(text, why):
    with pytest.raises(rc.MalformedConflict):
        rc.take_theirs(text)


def test_a_malformed_file_leaves_everything_on_disk_untouched(tmp_path):
    """Refusing must be atomic: a half-resolved tree is worse than an unresolved one."""
    good = tmp_path / "good.txt"
    good.write_text(CONFLICT, encoding="utf-8")
    bad = tmp_path / "bad.txt"
    bad.write_text("<<<<<<< ours\nunterminated\n", encoding="utf-8")

    summary = rc.resolve(tmp_path)

    assert summary["exit_code"] == rc.EXIT_MALFORMED
    assert summary["resolved"] == []
    assert good.read_text(encoding="utf-8") == CONFLICT, (
        "a later failure must not leave earlier writes"
    )
    assert bad.read_text(encoding="utf-8") == "<<<<<<< ours\nunterminated\n"


# --- resolve(): the directory walk --------------------------------------------


def test_resolves_every_marked_file(tmp_path):
    (tmp_path / "a.txt").write_text(CONFLICT, encoding="utf-8")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "b.txt").write_text(CONFLICT, encoding="utf-8")
    (tmp_path / "clean.txt").write_text("nothing here\n", encoding="utf-8")

    summary = rc.resolve(tmp_path)

    assert summary["exit_code"] == rc.EXIT_OK
    assert {e["path"] for e in summary["resolved"]} == {"a.txt", "sub/b.txt"}
    assert (tmp_path / "a.txt").read_text(encoding="utf-8") == "before\nupstream edit\nafter\n"
    assert (tmp_path / "clean.txt").read_text(encoding="utf-8") == "nothing here\n"


def test_rejects_are_reported_and_never_applied(tmp_path):
    """A .rej holds hunks git could not place; guessing where they go corrupts files."""
    (tmp_path / "x.txt.rej").write_text(
        "--- a/x.txt\n+++ b/x.txt\n@@ -1 +1 @@\n-a\n+b\n", encoding="utf-8"
    )

    summary = rc.resolve(tmp_path)

    assert summary["exit_code"] == rc.EXIT_REJECTS_REMAIN
    assert summary["rejects"] == ["x.txt.rej"]
    assert (tmp_path / "x.txt.rej").exists(), "the reject must survive for a human"
    assert any("by hand" in n for n in summary["notes"])


def test_markers_are_resolved_even_when_a_reject_also_remains(tmp_path):
    """Partial progress is still progress; the exit code carries the warning."""
    (tmp_path / "a.txt").write_text(CONFLICT, encoding="utf-8")
    (tmp_path / "b.txt.rej").write_text("hunk\n", encoding="utf-8")

    summary = rc.resolve(tmp_path)

    assert summary["exit_code"] == rc.EXIT_REJECTS_REMAIN
    assert (tmp_path / "a.txt").read_text(encoding="utf-8") == "before\nupstream edit\nafter\n"


def test_a_reject_is_reported_and_never_deleted(tmp_path):
    """The sync cannot create a .rej any more, so one found here has unknown provenance.

    An earlier version deleted a reject sitting beside a file it had just resolved,
    because `sync.py` emitted both artifacts for a single collision and applying the
    reject too would have applied the change twice. `git apply --reject` is gone, so
    that cause is gone — and deleting a reject nobody inspected would now be a guess.
    """
    (tmp_path / "shared.txt").write_text(CONFLICT, encoding="utf-8")
    (tmp_path / "shared.txt.rej").write_text(
        "@@ -1,3 +1,3 @@\n-base\n+upstream\n", encoding="utf-8"
    )

    summary = rc.resolve(tmp_path)

    assert summary["exit_code"] == rc.EXIT_REJECTS_REMAIN
    assert summary["rejects"] == ["shared.txt.rej"]
    assert (tmp_path / "shared.txt.rej").exists(), "a reject must survive for a human"
    # The markers are still resolved — partial progress is progress.
    assert (tmp_path / "shared.txt").read_text(encoding="utf-8") == "before\nupstream edit\nafter\n"
    assert any("no longer creates these" in n for n in summary["notes"])


def test_a_clean_tree_says_so(tmp_path):
    (tmp_path / "a.txt").write_text("fine\n", encoding="utf-8")
    summary = rc.resolve(tmp_path)
    assert summary["exit_code"] == rc.EXIT_OK
    assert any("no conflicts found" in n for n in summary["notes"])


def test_dry_run_writes_nothing(tmp_path):
    target = tmp_path / "a.txt"
    target.write_text(CONFLICT, encoding="utf-8")
    summary = rc.resolve(tmp_path, dry_run=True)
    assert summary["resolved"][0]["blocks"] == 1
    assert target.read_text(encoding="utf-8") == CONFLICT
    assert any("dry run" in n for n in summary["notes"])


def test_the_git_directory_is_never_walked(tmp_path):
    """Objects and hooks can contain anything; rewriting them would be catastrophic."""
    git = tmp_path / ".git"
    git.mkdir()
    (git / "COMMIT_EDITMSG").write_text(CONFLICT, encoding="utf-8")
    summary = rc.resolve(tmp_path)
    assert summary["resolved"] == []
    assert (git / "COMMIT_EDITMSG").read_text(encoding="utf-8") == CONFLICT


def test_binary_files_are_skipped(tmp_path):
    (tmp_path / "blob.bin").write_bytes(b"\xff\xfe<<<<<<< not really text\x00")
    assert rc.resolve(tmp_path)["exit_code"] == rc.EXIT_OK


# --- main() / CLI --------------------------------------------------------------


def test_main_reports_each_resolution(tmp_path, capsys):
    (tmp_path / "a.txt").write_text(CONFLICT, encoding="utf-8")
    assert rc.main([str(tmp_path)]) == rc.EXIT_OK
    assert "resolved a.txt: 1 block(s) -> upstream" in capsys.readouterr().out


def test_main_exits_1_with_rejects(tmp_path, capsys):
    (tmp_path / "x.rej").write_text("hunk\n", encoding="utf-8")
    assert rc.main([str(tmp_path)]) == rc.EXIT_REJECTS_REMAIN
    assert "reject   x.rej" in capsys.readouterr().err


def test_main_exits_2_on_malformed_input(tmp_path, capsys):
    (tmp_path / "a.txt").write_text("<<<<<<< ours\nunterminated\n", encoding="utf-8")
    assert rc.main([str(tmp_path)]) == rc.EXIT_MALFORMED
    assert "nothing was written" in capsys.readouterr().err


def test_main_json_output(tmp_path, capsys):
    (tmp_path / "a.txt").write_text(CONFLICT, encoding="utf-8")
    assert rc.main([str(tmp_path), "--json"]) == rc.EXIT_OK
    payload = json.loads(capsys.readouterr().out)
    assert payload["resolved"] == [{"path": "a.txt", "blocks": 1}]


# --- end-to-end: a real sync conflict, all three sides controlled --------------


def _git(repo: Path, *args: str) -> None:
    """Run a git command, raising with output on failure."""
    result = subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True)
    assert result.returncode == 0, f"git {' '.join(args)}:\n{result.stderr}"


@pytest.fixture
def conflict_scenario(tmp_path: Path, plugin_scripts: Path) -> tuple[Path, Path]:
    """A project synced from a local template, with a collision set up on both sides.

    A local template rather than the real one, because a *conflict* test needs all three
    sides — base, local, upstream — chosen deliberately. The real-template e2e already
    covers whether a genuine sync works; this covers what happens when it doesn't.
    """
    if shutil.which("git") is None:  # pragma: no cover - git is required everywhere
        pytest.skip("git not available")

    template = tmp_path / "template"
    (template / ".rhiza").mkdir(parents=True)
    (template / "shared.txt").write_text("line one\nBASE\nline three\n", encoding="utf-8")
    (template / ".rhiza" / "template-bundles.yml").write_text(
        "bundles:\n  core:\n    description: core\n"
        "profiles:\n  default:\n    bundles:\n      - core\n"
    )
    (template / "bundles").mkdir()
    (template / "bundles" / "core").mkdir()
    (template / "bundles" / "core" / "shared.txt").write_text(
        "line one\nBASE\nline three\n", encoding="utf-8"
    )
    _git(template, "init", "-q", "-b", "main")
    _git(template, "config", "user.email", "t@e.com")
    _git(template, "config", "user.name", "T")
    _git(template, "add", "-A")
    _git(template, "commit", "-qm", "base")

    project = tmp_path / "project"
    (project / ".rhiza").mkdir(parents=True)
    (project / ".rhiza" / "template.yml").write_text(
        f'repository: "{template}"\nref: main\n\nprofiles:\n  - default\n'
    )
    _git(project, "init", "-q", "-b", "main")
    _git(project, "config", "user.email", "t@e.com")
    _git(project, "config", "user.name", "T")
    _git(project, "add", "-A")
    _git(project, "commit", "-qm", "init")

    # First sync: a clean add, exit 0 — the state the existing e2e already covers.
    first = run_cmd([*PY, str(plugin_scripts / "sync.py"), "."], project)
    assert first.returncode == 0, f"first sync should be clean:\n{first.stdout}{first.stderr}"
    assert (project / "shared.txt").read_text(encoding="utf-8") == "line one\nBASE\nline three\n"
    _git(project, "add", "-A")
    _git(project, "commit", "-qm", "chore: apply sync")

    # Now both sides change the same line — the collision.
    (project / "shared.txt").write_text("line one\nLOCAL EDIT\nline three\n", encoding="utf-8")
    _git(project, "add", "-A")
    _git(project, "commit", "-qm", "local change")

    (template / "bundles" / "core" / "shared.txt").write_text(
        "line one\nUPSTREAM EDIT\nline three\n"
    )
    _git(template, "add", "-A")
    _git(template, "commit", "-qm", "upstream change")

    return project, template


def test_e2e_a_colliding_sync_exits_1_and_leaves_markers(conflict_scenario, plugin_scripts):
    """sync.py exit 1 is the normal outcome of a real /update, and was never driven."""
    project, _ = conflict_scenario

    second = run_cmd([*PY, str(plugin_scripts / "sync.py"), "."], project)

    assert second.returncode == rc.EXIT_REJECTS_REMAIN, (
        f"expected a conflict:\n{second.stdout}{second.stderr}"
    )
    marked, rejects = rc.find_conflicts(project)
    assert [p.name for p in marked] == ["shared.txt"]
    # One collision, ONE artifact. The old merge ran `git apply -3` first, which rejected
    # the hunk into `shared.txt.rej`, and only then fell back to `git merge-file` — so a
    # single collision left markers *and* a redundant reject describing the same change.
    # `_rhiza_merge.py` runs no `git apply` at all, so there is nothing to reject.
    assert rejects == [], f"the merge should no longer produce rejects: {rejects}"


def test_e2e_resolving_takes_upstream_and_clears_every_artifact(conflict_scenario, plugin_scripts):
    """/update step 6's whole contract, end to end."""
    project, _ = conflict_scenario
    run_cmd([*PY, str(plugin_scripts / "sync.py"), "."], project)

    resolved = run_cmd([*PY, str(plugin_scripts / "resolve_conflicts.py"), "."], project)
    assert resolved.returncode == rc.EXIT_OK, f"{resolved.stdout}{resolved.stderr}"

    body = (project / "shared.txt").read_text(encoding="utf-8")
    assert body == "line one\nUPSTREAM EDIT\nline three\n"
    assert "LOCAL EDIT" not in body, "the local side must be dropped for a managed file"
    assert "<<<<<<<" not in body
    # Applied exactly once. This guarded against the old double-apply (markers resolved
    # *and* the redundant reject applied); it still guards the merge itself.
    assert body.count("UPSTREAM EDIT") == 1

    # /update step 6's stated acceptance criteria, verified rather than described.
    marked, rejects = rc.find_conflicts(project)
    assert marked == [] and rejects == [], "artifacts remain after resolution"


def test_e2e_the_resolved_file_is_then_staged_as_template_owned(conflict_scenario, plugin_scripts):
    """The step-6 → step-7 handover: resolution feeds stage_synced, which stages it."""
    import stage_synced

    project, _ = conflict_scenario
    run_cmd([*PY, str(plugin_scripts / "sync.py"), "."], project)
    run_cmd([*PY, str(plugin_scripts / "resolve_conflicts.py"), "."], project)

    # A repo-owned edit alongside, which must not be swept in.
    (project / "mine.txt").write_text("my own work\n", encoding="utf-8")

    summary = stage_synced.stage_synced(project)

    assert "shared.txt" in summary["staged"], "the resolved template file was not staged"
    assert "mine.txt" in summary["unstaged"], "a repo-owned file was staged"
