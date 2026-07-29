"""Unit tests for `scripts/_rhiza_git.py`.

The error paths real git will not produce on demand are reached by faulting the single
`_run_git` seam. Happy paths at the repo level live in `test_sync.py`.

The diff machinery that used to dominate this file — `get_diff`, `apply_diff`,
`_apply_reject`, `merge_file_fallback`, `parse_diff_filenames`, `_DiffFileState` — is
gone along with the code it tested. The merge, and the property tests that hold it to
its invariants, are in `test__rhiza_merge.py`.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import _rhiza_git as git
import pytest


def _completed(
    returncode: int = 0, stdout: bytes = b"", stderr: bytes = b""
) -> subprocess.CompletedProcess[bytes]:
    """Build a fake CompletedProcess for a stubbed git call."""
    return subprocess.CompletedProcess(
        args=["git"], returncode=returncode, stdout=stdout, stderr=stderr
    )


@pytest.fixture
def ctx() -> git.GitContext:
    """A GitContext with a placeholder executable (real git is never run here)."""
    return git.GitContext(executable="git", env={})


# --- executable discovery + context -------------------------------------------


def test_get_git_executable_found(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(git.shutil, "which", lambda _: "/usr/bin/git")
    assert git.get_git_executable() == "/usr/bin/git"


def test_get_git_executable_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(git.shutil, "which", lambda _: None)
    with pytest.raises(RuntimeError, match="git executable not found"):
        git.get_git_executable()


def test_scan_conflict_artifacts_rej_and_markers(tmp_path: Path) -> None:
    (tmp_path / "a.rej").write_text("hunk\n")
    (tmp_path / "b.txt").write_text("x\n<<<<<<< HEAD\n")
    (tmp_path / "clean.txt").write_text("fine\n")
    (tmp_path / "sub").mkdir()
    rej, markers = git.scan_conflict_artifacts(tmp_path)
    assert rej == ["a.rej"]
    assert markers == ["b.txt"]


def test_scan_conflict_artifacts_tolerates_unreadable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "x.txt").write_text("data\n")
    orig = Path.read_bytes

    def boom(self: Path, *a: Any, **k: Any) -> bytes:
        if self.name == "x.txt":
            raise OSError("unreadable")
        return orig(self, *a, **k)

    monkeypatch.setattr(Path, "read_bytes", boom)
    rej, markers = git.scan_conflict_artifacts(tmp_path)
    assert rej == [] and markers == []


class TestGitContext:
    def test_default_sets_prompt_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(git.shutil, "which", lambda _: "/usr/bin/git")
        ctx = git.GitContext.default()
        assert ctx.executable == "/usr/bin/git"
        assert ctx.env["GIT_TERMINAL_PROMPT"] == "0"
