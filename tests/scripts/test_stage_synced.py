"""Tests for the staging engine (`scripts/stage_synced.py`) behind `/rhiza:update`.

The invariant: a template bump PR contains **only** files the sync materialized.
`.rhiza/template.lock`'s `files` list is the authority; everything else must be left
in the working tree, never swept in by a blanket `git add --all`.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest
import stage_synced as st

_GIT_MISSING = shutil.which("git") is None
pytestmark = pytest.mark.skipif(_GIT_MISSING, reason="git not available")


def _git(repo: Path, *args: str) -> None:
    """Run a git command, raising with output on failure."""
    result = subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True)
    assert result.returncode == 0, f"git {' '.join(args)}:\n{result.stderr}"


def _staged(repo: Path) -> list[str]:
    """Return the staged paths, as git sees them."""
    out = subprocess.run(
        ["git", "diff", "--cached", "--name-only"], cwd=repo, capture_output=True, text=True
    )
    return sorted(p for p in out.stdout.splitlines() if p.strip())


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A git repo with one committed template file and one committed repo-owned file."""
    _git(tmp_path, "init", "-q", "-b", "main")
    _git(tmp_path, "config", "user.email", "t@example.com")
    _git(tmp_path, "config", "user.name", "T")
    (tmp_path / ".rhiza").mkdir()
    (tmp_path / ".rhiza" / "template.yml").write_text('repository: "o/r"\nref: "v1"\n')
    (tmp_path / "ruff.toml").write_text("# template-owned\n")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.py").write_text('"""Repo-owned."""\n')
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-qm", "initial")
    return tmp_path


def _write_lock(repo: Path, files: list[str], *, sha: str = "abc123") -> None:
    """Write a `.rhiza/template.lock` recording *files* as template-owned."""
    body = f'sha: "{sha}"\nstrategy: merge\nfiles:\n' + "".join(f"  - {f}\n" for f in files)
    (repo / ".rhiza" / "template.lock").write_text(body)


# --- lock_files --------------------------------------------------------------


def test_lock_files_reads_the_list(tmp_path):
    lock = tmp_path / "template.lock"
    lock.write_text('sha: "x"\nfiles:\n  - Makefile\n  - ruff.toml\n')
    assert st.lock_files(lock) == ["Makefile", "ruff.toml"]


def test_lock_files_missing_lock_is_empty(tmp_path):
    assert st.lock_files(tmp_path / "nope.lock") == []


def test_lock_files_without_a_files_key_is_empty(tmp_path):
    lock = tmp_path / "template.lock"
    lock.write_text('sha: "x"\nstrategy: merge\n')
    assert st.lock_files(lock) == []


def test_lock_files_ignores_a_non_list_files_value(tmp_path):
    lock = tmp_path / "template.lock"
    lock.write_text('files: "Makefile"\n')
    assert st.lock_files(lock) == []


# --- porcelain parsing -------------------------------------------------------


def test_unstaged_paths_picks_the_worktree_column():
    porcelain = [
        "M  staged_only.py",  # staged, nothing left
        " M unstaged.py",  # worktree modification
        "MM both.py",  # staged + further edits
        "?? untracked.py",
        "D  deleted_staged.py",
        "x",  # too short to parse
    ]
    assert st.unstaged_paths(porcelain) == ["both.py", "unstaged.py", "untracked.py"]


def test_deleted_paths_sees_either_column():
    porcelain = [" D gone.py", "D  staged_gone.py", " M kept.py", "?"]
    assert st.deleted_paths(porcelain) == {"gone.py", "staged_gone.py"}


# --- stage_synced() end to end ----------------------------------------------


def test_stages_only_template_files(repo):
    """The headline invariant: repo-owned edits are left behind."""
    (repo / "ruff.toml").write_text("# changed upstream\n")
    (repo / "src" / "app.py").write_text('"""Reformatted by make fmt."""\n')
    _write_lock(repo, ["ruff.toml"])

    summary = st.stage_synced(repo)

    assert summary["exit_code"] == st.EXIT_OK
    assert summary["staged"] == [".rhiza/template.lock", "ruff.toml"]
    assert summary["unstaged"] == ["src/app.py"]
    assert _staged(repo) == [".rhiza/template.lock", "ruff.toml"]
    assert any("left unstaged" in n for n in summary["notes"])


def test_stages_new_template_files_and_the_config(repo):
    (repo / "Makefile").write_text("include .rhiza/rhiza.mk\n")
    (repo / ".rhiza" / "template.yml").write_text('repository: "o/r"\nref: "v2"\n')
    _write_lock(repo, ["Makefile", "ruff.toml"])

    summary = st.stage_synced(repo)

    assert summary["staged"] == [".rhiza/template.lock", ".rhiza/template.yml", "Makefile"]
    assert summary["unstaged"] == []


def test_stages_an_upstream_deletion(repo):
    """A template file upstream removed is still a template-owned change."""
    (repo / "ruff.toml").unlink()
    _write_lock(repo, ["ruff.toml"])

    summary = st.stage_synced(repo)

    assert "ruff.toml" in summary["staged"]
    assert summary["unstaged"] == []


def test_tolerates_a_stale_lock_entry(repo):
    """A lock path that is neither on disk nor tracked must not fail the whole batch."""
    (repo / "ruff.toml").write_text("# changed\n")
    _write_lock(repo, ["ruff.toml", "docs/never-existed.md"])

    summary = st.stage_synced(repo)

    assert summary["exit_code"] == st.EXIT_OK
    assert "ruff.toml" in summary["staged"]


def test_deduplicates_lock_entries_against_the_config_paths(repo):
    """A lock that repeats a path, or lists template.yml itself, stages it once."""
    (repo / "ruff.toml").write_text("# changed\n")
    _write_lock(repo, ["ruff.toml", ".rhiza/template.yml", "ruff.toml"])

    summary = st.stage_synced(repo)

    assert summary["exit_code"] == st.EXIT_OK
    assert summary["staged"].count("ruff.toml") == 1


def test_nothing_to_stage_is_reported(repo):
    """A no-op sync stages nothing and says so."""
    _write_lock(repo, ["ruff.toml"])
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "lock")

    summary = st.stage_synced(repo)

    assert summary["staged"] == []
    assert any("nothing to stage" in n for n in summary["notes"])


def test_a_damaged_lock_still_stages_only_the_config(repo):
    """An unparseable lock degrades to the pointer, never to a blanket add."""
    (repo / ".rhiza" / "template.lock").write_text("\t: not: valid: yaml: [\n")
    (repo / "src" / "app.py").write_text('"""Edited."""\n')

    summary = st.stage_synced(repo)

    assert summary["staged"] == [".rhiza/template.lock"]
    assert summary["unstaged"] == ["src/app.py"]


def test_missing_lock_exits_1(repo):
    (repo / ".rhiza" / "template.lock").unlink(missing_ok=True)
    summary = st.stage_synced(repo)
    assert summary["exit_code"] == st.EXIT_NO_LOCK
    assert any("run the sync first" in n for n in summary["notes"])


def test_a_git_failure_exits_2(tmp_path):
    """Outside a git repo, git fails and the script reports it rather than crashing."""
    (tmp_path / ".rhiza").mkdir()
    _write_lock(tmp_path, ["ruff.toml"])
    summary = st.stage_synced(tmp_path)
    assert summary["exit_code"] == st.EXIT_GIT_ERROR
    assert any("git failed" in n for n in summary["notes"])


@pytest.mark.parametrize(
    ("failing_call", "label"),
    [(1, "git add"), (2, "git diff --cached"), (3, "the second git status")],
)
def test_a_failure_at_any_later_git_call_exits_2(repo, monkeypatch, failing_call, label):
    """Every git invocation after the first is checked, not just the status probe."""
    (repo / "ruff.toml").write_text("# changed\n")
    _write_lock(repo, ["ruff.toml"])

    real_git = st._git
    calls = {"n": 0}

    def flaky(target, args):
        calls["n"] += 1
        if calls["n"] == failing_call + 1:  # +1: call 1 is the initial status probe
            return subprocess.CompletedProcess(args, 1, "", f"boom in {label}")
        return real_git(target, args)

    monkeypatch.setattr(st, "_git", flaky)
    summary = st.stage_synced(repo)

    assert summary["exit_code"] == st.EXIT_GIT_ERROR
    assert any(f"boom in {label}" in n for n in summary["notes"])


def test_batches_large_lock_lists(repo):
    """More paths than the batch size still all get staged."""
    names = [f"f{i:03d}.txt" for i in range(st._BATCH + 5)]
    for name in names:
        (repo / name).write_text(f"{name}\n")
    _write_lock(repo, names)

    summary = st.stage_synced(repo)

    assert summary["exit_code"] == st.EXIT_OK
    for name in names:
        assert name in summary["staged"]


# --- main() / CLI -----------------------------------------------------------


def test_main_json_output(repo, capsys):
    (repo / "ruff.toml").write_text("# changed\n")
    _write_lock(repo, ["ruff.toml"])
    rc = st.main([str(repo), "--json"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert "ruff.toml" in payload["staged"]


def test_main_text_output(repo, capsys):
    (repo / "ruff.toml").write_text("# changed\n")
    (repo / "src" / "app.py").write_text('"""Edited."""\n')
    _write_lock(repo, ["ruff.toml"])
    rc = st.main([str(repo)])
    assert rc == 0
    captured = capsys.readouterr()
    assert "staged   ruff.toml" in captured.out
    assert "left     src/app.py" in captured.err
    assert "note" in captured.err


def test_main_returns_the_no_lock_exit_code(tmp_path, capsys):
    rc = st.main([str(tmp_path)])
    assert rc == st.EXIT_NO_LOCK
    assert "run the sync first" in capsys.readouterr().err


# --- end-to-end: /update's template-only guarantee, against a real sync --------


def test_e2e_update_stages_only_template_files(synced_repo_copy):
    """/update's core promise, measured on a genuinely synced repo.

    The fixture repos can't prove this: the lock has to be the one `sync.py` actually
    wrote, over the ~60 files the real template delivers. A repo-owned edit alongside
    them must be left behind — that is the bug where `git add --all` swept a `make fmt`
    reformat of `src/` into a template bump PR.
    """
    repo = synced_repo_copy
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "chore: apply sync")

    # Now: a template file changes upstream-style, and the repo's own source changes.
    (repo / "ruff.toml").write_text('target-version = "py312"\n')
    (repo / "src" / "widget" / "main.py").write_text(
        '"""Entry point for widget."""\n\n\ndef greeting() -> str:\n'
        '    """Reformatted locally."""\n    return "hello"\n'
    )

    summary = st.stage_synced(repo)

    assert summary["exit_code"] == st.EXIT_OK
    assert "ruff.toml" in summary["staged"], "a template file was not staged"
    assert "src/widget/main.py" in summary["unstaged"], "a repo-owned edit was staged"
    assert not any(p.startswith("src/") for p in summary["staged"])


def test_e2e_the_lock_covers_what_the_template_delivered(synced_repo_copy):
    """The staged set is the sync's own record, not a guess about which paths look shared."""
    lock = synced_repo_copy / ".rhiza" / "template.lock"
    files = st.lock_files(lock)
    assert len(files) > 20, f"expected the real template's file list, got {files}"
    # Files the template is known to own, and one it never does.
    assert "Makefile" in files
    assert ".rhiza/rhiza.mk" in files
    assert not any(f.startswith("src/") for f in files), "src/ is the repo's own"
