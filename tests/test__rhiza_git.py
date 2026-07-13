"""Unit tests for `scripts/_rhiza_git.py`.

Happy paths run in `test_sync.py` against real git; here we cover the error and
edge branches deterministically by faulting the single `_run_git` seam.
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


# --- diff parsing -------------------------------------------------------------


def test_path_after_dev_null_and_unprefixed() -> None:
    assert git._path_after("--- /dev/null", "--- ", git._SRC_PREFIX) is None
    assert git._path_after("--- other/x", "--- ", git._SRC_PREFIX) is None
    assert git._path_after("--- upstream-template-old/x", "--- ", git._SRC_PREFIX) == "x"


def test_parse_diff_filenames_new_deleted_modified() -> None:
    diff = (
        "diff --git upstream-template-old/n.txt upstream-template-new/n.txt\n"
        "new file mode 100644\n--- /dev/null\n+++ upstream-template-new/n.txt\n"
        "diff --git upstream-template-old/d.txt upstream-template-new/d.txt\n"
        "deleted file mode 100644\n--- upstream-template-old/d.txt\n+++ /dev/null\n"
        "diff --git upstream-template-old/m.txt upstream-template-new/m.txt\n"
        "--- upstream-template-old/m.txt\n+++ upstream-template-new/m.txt\n"
    )
    assert git.parse_diff_filenames(diff) == [
        ("n.txt", True, False),
        ("d.txt", False, True),
        ("m.txt", False, False),
    ]


def test_parse_diff_filenames_block_without_path_is_skipped() -> None:
    assert git.parse_diff_filenames("diff --git a b\nsome noise\n") == []


# --- apply_diff branches ------------------------------------------------------


def test_apply_diff_empty_is_clean(ctx: git.GitContext, tmp_path: Path) -> None:
    assert git.apply_diff(ctx, "   \n", tmp_path) is True


def test_apply_diff_clean(
    ctx: git.GitContext, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(git, "_run_git", lambda *a, **k: _completed(0))
    assert git.apply_diff(ctx, "diff\n", tmp_path) is True


def test_apply_diff_blob_absent_uses_merge_file(
    ctx: git.GitContext, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fake(_ctx: Any, args: list[str], **_kw: Any) -> Any:
        raise subprocess.CalledProcessError(1, args, b"", b"error: lacks the necessary blob\n")

    monkeypatch.setattr(git, "_run_git", fake)
    called: dict[str, bool] = {}
    monkeypatch.setattr(git, "merge_file_fallback", lambda *a: called.setdefault("hit", True))
    git.apply_diff(ctx, "diff\n", tmp_path, tmp_path, tmp_path)
    assert called["hit"]


def test_apply_diff_other_error_uses_reject(
    ctx: git.GitContext, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fake(_ctx: Any, args: list[str], **_kw: Any) -> Any:
        raise subprocess.CalledProcessError(1, args, b"", b"error: some other failure\n")

    monkeypatch.setattr(git, "_run_git", fake)
    # base/upstream given but the stderr is not a blob error -> apply --reject path.
    assert git.apply_diff(ctx, "diff\n", tmp_path, tmp_path, tmp_path) is False


def test_apply_reject_success_still_returns_false(
    ctx: git.GitContext, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(git, "_run_git", lambda *a, **k: _completed(0))
    assert git._apply_reject(ctx, "diff\n", tmp_path) is False


def test_apply_reject_tolerates_failure(
    ctx: git.GitContext, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fake(_ctx: Any, args: list[str], **_kw: Any) -> Any:
        raise subprocess.CalledProcessError(1, args, b"", b"nope")

    monkeypatch.setattr(git, "_run_git", fake)
    assert git._apply_reject(ctx, "diff\n", tmp_path) is False


# --- merge helpers ------------------------------------------------------------


def test_merge_one_file_new_copies(ctx: git.GitContext, tmp_path: Path) -> None:
    up = tmp_path / "up"
    up.mkdir()
    (up / "n.txt").write_text("new\n")
    assert git.merge_one_file(ctx, "n.txt", tmp_path, tmp_path, up, True, False) is True
    assert (tmp_path / "n.txt").read_text() == "new\n"


def test_merge_one_file_delete_removes(ctx: git.GitContext, tmp_path: Path) -> None:
    (tmp_path / "d.txt").write_text("x\n")
    empty = tmp_path / "e"
    empty.mkdir()
    assert git.merge_one_file(ctx, "d.txt", tmp_path, empty, empty, False, True) is True
    assert not (tmp_path / "d.txt").exists()


def test_apply_non_merge_delete_absent_is_noop(tmp_path: Path) -> None:
    git._apply_non_merge(tmp_path / "gone.txt", tmp_path / "up.txt", is_deleted=True)  # no error


def test_apply_non_merge_upstream_absent_is_noop(tmp_path: Path) -> None:
    git._apply_non_merge(tmp_path / "t.txt", tmp_path / "missing.txt", is_deleted=False)
    assert not (tmp_path / "t.txt").exists()


def test_merge_file_fallback_reports_conflict(
    ctx: git.GitContext, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    for name in ("target", "base", "up"):
        (tmp_path / name).mkdir()
        (tmp_path / name / "f.txt").write_text(f"{name}\n")
    diff = (
        "diff --git upstream-template-old/f.txt upstream-template-new/f.txt\n"
        "--- upstream-template-old/f.txt\n+++ upstream-template-new/f.txt\n"
    )
    monkeypatch.setattr(git, "git_merge_file", lambda *a: False)  # force conflict
    assert (
        git.merge_file_fallback(ctx, diff, tmp_path / "target", tmp_path / "base", tmp_path / "up")
        is False
    )


def test_git_merge_file_returncode(
    ctx: git.GitContext, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(git, "_run_git", lambda *a, **k: _completed(0))
    assert git.git_merge_file(ctx, tmp_path / "t", tmp_path / "b", tmp_path / "u") is True
    monkeypatch.setattr(git, "_run_git", lambda *a, **k: _completed(1))
    assert git.git_merge_file(ctx, tmp_path / "t", tmp_path / "b", tmp_path / "u") is False


# --- conflict artifact scanning -----------------------------------------------


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


class Test_DiffFileState:
    def test_new_file_entry(self) -> None:
        state = git._DiffFileState()
        state.reset()
        assert state.started and not state.is_new and state.entry() is None
        state.update("new file mode 100644")
        state.update("+++ upstream-template-new/x.txt")
        assert state.entry() == ("x.txt", True, False)

    def test_deleted_file_entry(self) -> None:
        state = git._DiffFileState()
        state.reset()
        state.update("deleted file mode 100644")
        state.update("--- upstream-template-old/gone.txt")
        assert state.entry() == ("gone.txt", False, True)
