#!/usr/bin/env python3
"""Git subprocess engine for the stdlib-only `sync` port.

This is the private helper behind `scripts/sync.py`, mirroring the role
`_rhiza_yaml.py` plays for parsing: it owns every `git` invocation, so the
orchestration in `sync.py` stays free of subprocess detail. Ported from the rhiza
CLI's `rhiza.models._git` engine.

The engine shells out to `git` for everything hard — `git clone --sparse` and
`git merge-file` — rather than re-implementing it in Python. Every call goes
through the single :func:`_run_git` seam, which keeps the module trivially
testable (real git for happy paths, a monkeypatched seam for error branches).

The diff machinery this module used to carry — `git diff --no-index`,
`git apply -3`, `git apply --reject` and the diff-text parser that recovered a
file list from their output — is gone. `_rhiza_merge.py` reads that list off the
two snapshot directories instead, which is where it was always available. Nothing
runs `git apply` any more, so `.rej` files are no longer produced at all.

The functions here do not print: they return structured facts and leave
user-facing output to `sync.py`.
"""

from __future__ import annotations

import os
import shutil
import subprocess  # nosec B404
from dataclasses import dataclass, field
from pathlib import Path


def get_git_executable() -> str:
    """Return the absolute path to the git binary.

    Raises:
        RuntimeError: If git is not found on ``PATH``.
    """
    git_path = shutil.which("git")
    if git_path is None:
        msg = "git executable not found in PATH. Please ensure git is installed and available."
        raise RuntimeError(msg)
    return git_path


@dataclass
class GitContext:
    """The git executable path and environment shared across subprocess calls.

    Attributes:
        executable: Absolute path to the git binary.
        env: Environment variables passed to every git subprocess.
    """

    executable: str
    env: dict[str, str] = field(default_factory=dict)

    @classmethod
    def default(cls) -> GitContext:
        """Build a context from the system git and a prompt-disabled environment."""
        env = os.environ.copy()
        env["GIT_TERMINAL_PROMPT"] = "0"
        return cls(executable=get_git_executable(), env=env)


def _run_git(
    git: GitContext,
    args: list[str],
    *,
    cwd: Path | str | None = None,
    check: bool = False,
    stdin: bytes | None = None,
) -> subprocess.CompletedProcess[bytes]:
    """Run one git command through the single subprocess seam.

    Args:
        git: The git context (executable + environment).
        args: Arguments following the git executable.
        cwd: Working directory for the command, if any.
        check: When True, raise ``CalledProcessError`` on a non-zero exit.
        stdin: Optional bytes fed to the process on standard input.

    Returns:
        The completed process with captured (bytes) stdout/stderr.
    """
    return subprocess.run(  # nosec B603
        [git.executable, *args],
        cwd=str(cwd) if cwd is not None else None,
        input=stdin,
        capture_output=True,
        check=check,
        env=git.env,
    )


# ---------------------------------------------------------------------------
# Working-tree and remote operations
# ---------------------------------------------------------------------------


def status_porcelain(git: GitContext, target: Path) -> list[str]:
    """Return the non-empty ``git status --porcelain`` lines for *target*."""
    result = _run_git(git, ["status", "--porcelain"], cwd=target)
    return [line for line in result.stdout.decode().splitlines() if line.strip()]


def get_head_sha(git: GitContext, repo_dir: Path) -> str:
    """Return the full HEAD commit SHA of the repository at *repo_dir*."""
    result = _run_git(git, ["rev-parse", "HEAD"], cwd=repo_dir, check=True)
    return result.stdout.decode().strip()


def _sparse_set(git: GitContext, work_dir: Path, include_paths: list[str]) -> None:
    """Set the sparse-checkout cone of the clone at *work_dir* to *include_paths*."""
    _run_git(
        git, ["sparse-checkout", "set", "--skip-checks", *include_paths], cwd=work_dir, check=True
    )


def clone(
    git: GitContext,
    git_url: str,
    dest: Path,
    include_paths: list[str],
    *,
    branch: str | None = None,
    sha: str | None = None,
) -> None:
    """Sparse-clone *git_url* into *dest* and set its cone to *include_paths*.

    Pass *branch* for a shallow clone at a branch tip, or *sha* for a full-history
    clone checked out at that commit.
    """
    if branch is not None:
        head = ["clone", "--depth", "1", "--filter=blob:none", "--sparse", "--branch", branch]
    else:
        head = ["clone", "--filter=blob:none", "--sparse", "--no-checkout"]
    _run_git(git, [*head, git_url, str(dest)], check=True)
    _run_git(git, ["sparse-checkout", "init", "--cone"], cwd=dest, check=True)
    _sparse_set(git, dest, include_paths)
    if sha is not None:
        _run_git(git, ["checkout", sha], cwd=dest, check=True)


def update_sparse_checkout(git: GitContext, tmp_dir: Path, include_paths: list[str]) -> None:
    """Reset the sparse-checkout cone of the clone at *tmp_dir* to *include_paths*."""
    _sparse_set(git, tmp_dir, include_paths)


# ---------------------------------------------------------------------------
# Diff computation and parsing
# ---------------------------------------------------------------------------


def merge_file(git: GitContext, target_path: Path, base_path: Path, upstream_path: Path) -> int:
    """Three-way merge one file in place; return ``git merge-file``'s exit status.

    The status is returned rather than flattened to a boolean because its values mean
    genuinely different things, and the caller acts differently on each: **0** merged
    cleanly, a small **positive** number is that many conflicted regions (markers have
    been written into *target_path*), and **255** is a refusal — in practice a binary
    file, where nothing was written and nothing can be.
    """
    result = _run_git(
        git,
        [
            "merge-file",
            "-L",
            "HEAD",
            "-L",
            "base",
            "-L",
            "rhiza-template",
            str(target_path),
            str(base_path),
            str(upstream_path),
        ],
    )
    return result.returncode


def scan_conflict_artifacts(target: Path) -> tuple[list[str], list[str]]:
    """Scan *target* for merge artifacts, returning ``(rej_files, marker_files)``.

    Looks for ``*.rej`` files and text files containing a ``<<<<<<<`` conflict marker.
    The merge no longer produces rejects — `git apply --reject` was the only thing that
    ever did, and it is gone — but the scan still reports them, because a repo can carry
    one from a hand-run `git apply` or an interrupted older sync, and silently ignoring
    it would be worse than naming it.
    """
    rej_files: list[str] = []
    marker_files: list[str] = []
    for path in sorted(target.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(target).as_posix()
        if path.suffix == ".rej":
            rej_files.append(rel)
        else:
            try:
                if b"<<<<<<<" in path.read_bytes()[:1_048_576]:
                    marker_files.append(rel)
            except OSError:
                pass
    return rej_files, marker_files
