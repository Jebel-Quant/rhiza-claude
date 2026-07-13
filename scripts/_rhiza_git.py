#!/usr/bin/env python3
"""Git subprocess engine for the stdlib-only `sync` port.

This is the private helper behind `scripts/sync.py`, mirroring the role
`_rhiza_yaml.py` plays for parsing: it owns every `git` invocation and the
diff/3-way-merge machinery, so the orchestration in `sync.py` stays free of
subprocess detail. Ported from the rhiza CLI's `rhiza.models._git` engine.

The engine shells out to `git` for everything hard — `git clone --sparse`,
`git diff --no-index`, `git apply -3`, and `git merge-file` — rather than
re-implementing merge in Python. Every call goes through the single
:func:`_run_git` seam, which keeps the module trivially testable (real git for
happy paths, a monkeypatched seam for error branches).

The functions here do not print: they return structured facts (clean/conflict
booleans, artifact lists) and leave user-facing output to `sync.py`.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess  # nosec B404
from dataclasses import dataclass, field
from pathlib import Path

_SRC_PREFIX = "upstream-template-old/"
_DST_PREFIX = "upstream-template-new/"


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


def get_diff(git: GitContext, repo0: Path, repo1: Path) -> str:
    """Compute the diff between two directory trees via ``git diff --no-index``.

    The custom ``upstream-template-old/``/``upstream-template-new/`` prefixes are
    stripped afterwards so the resulting headers carry clean relative paths that
    ``git apply`` can consume.

    Args:
        git: The git context.
        repo0: Base (old) directory tree.
        repo1: Upstream (new) directory tree.

    Returns:
        The rewritten unified diff text.
    """
    repo0_str = repo0.resolve().as_posix()
    repo1_str = repo1.resolve().as_posix()
    result = _run_git(
        git,
        [
            "-c",
            "diff.noprefix=",
            "diff",
            "--no-index",
            "--relative",
            "--binary",
            "--src-prefix=upstream-template-old/",
            "--dst-prefix=upstream-template-new/",
            "--no-ext-diff",
            "--no-color",
            repo0_str,
            repo1_str,
        ],
        cwd=repo0_str,
    )
    diff = result.stdout.decode()
    for repo in (repo0_str, repo1_str):
        repo_nix = re.sub("/[a-z]:", "", repo)
        diff = diff.replace(f"upstream-template-old{repo_nix}", "upstream-template-old").replace(
            f"upstream-template-new{repo_nix}", "upstream-template-new"
        )
    return diff.replace(repo0_str + "/", "").replace(repo1_str + "/", "")


def _path_after(line: str, marker: str, prefix: str) -> str | None:
    """Return the diff path on a ``---``/``+++`` header line, stripped of *prefix*."""
    raw = line[len(marker) :].strip().strip('"').split("\t")[0]
    if raw != "/dev/null" and raw.startswith(prefix):
        return raw[len(prefix) :]
    return None


@dataclass
class _DiffFileState:
    """Accumulates the per-file flags/paths seen while scanning one ``diff --git`` block."""

    is_new: bool = False
    is_deleted: bool = False
    src_path: str | None = None
    dst_path: str | None = None
    started: bool = False

    def reset(self) -> None:
        """Begin a new file block, clearing all accumulated state."""
        self.is_new = False
        self.is_deleted = False
        self.src_path = None
        self.dst_path = None
        self.started = True

    def update(self, line: str) -> None:
        """Update state from a single non-``diff --git`` header line."""
        if line.startswith("new file mode"):
            self.is_new = True
        elif line.startswith("deleted file mode"):
            self.is_deleted = True
        elif line.startswith("--- "):
            self.src_path = _path_after(line, "--- ", _SRC_PREFIX) or self.src_path
        elif line.startswith("+++ "):
            self.dst_path = _path_after(line, "+++ ", _DST_PREFIX) or self.dst_path

    def entry(self) -> tuple[str, bool, bool] | None:
        """Return this block's ``(rel_path, is_new, is_deleted)`` entry, if a path was captured."""
        rel = self.src_path if self.is_deleted else self.dst_path
        return (rel, self.is_new, self.is_deleted) if rel else None


def parse_diff_filenames(diff: str) -> list[tuple[str, bool, bool]]:
    """Parse a diff from :func:`get_diff` into ``(rel_path, is_new, is_deleted)`` entries."""
    results: list[tuple[str, bool, bool]] = []
    state = _DiffFileState()
    for line in diff.splitlines():
        if line.startswith("diff --git "):
            if state.started and (entry := state.entry()):
                results.append(entry)
            state.reset()
        else:
            state.update(line)
    if state.started and (entry := state.entry()):
        results.append(entry)
    return results


# ---------------------------------------------------------------------------
# Applying changes (3-way merge)
# ---------------------------------------------------------------------------


def apply_diff(
    git: GitContext,
    diff: str,
    target: Path,
    base_snapshot: Path | None = None,
    upstream_snapshot: Path | None = None,
) -> bool:
    """Apply *diff* to *target* via ``git apply -3``, with fallbacks on failure.

    When ``git apply -3`` fails because the template's blob objects are absent
    from the target repository *and* both snapshot directories are provided,
    falls back to :func:`merge_file_fallback` (which uses ``git merge-file`` on
    the on-disk snapshots). Otherwise falls back to ``git apply --reject``.

    Args:
        git: The git context.
        diff: Unified diff text.
        target: The target repository.
        base_snapshot: Optional tree at the base (previously-synced) SHA.
        upstream_snapshot: Optional tree at the new upstream SHA.

    Returns:
        True when everything applied cleanly, False when conflicts remain.
    """
    if not diff.strip():
        return True
    try:
        _run_git(git, ["apply", "-3"], cwd=target, stdin=diff.encode(), check=True)
    except subprocess.CalledProcessError as exc:
        stderr = exc.stderr.decode() if isinstance(exc.stderr, bytes) else (exc.stderr or "")
        if (
            base_snapshot is not None
            and upstream_snapshot is not None
            and "lacks the necessary blob" in stderr
        ):
            return merge_file_fallback(git, diff, target, base_snapshot, upstream_snapshot)
        return _apply_reject(git, diff, target)
    return True


def _apply_reject(git: GitContext, diff: str, target: Path) -> bool:
    """Apply *diff* with ``git apply --reject`` (leaving ``.rej`` files); always return False."""
    try:
        _run_git(git, ["apply", "--reject"], cwd=target, stdin=diff.encode(), check=True)
    except subprocess.CalledProcessError:
        pass  # partial application is expected; artifacts are scanned by the caller
    return False


def merge_file_fallback(
    git: GitContext,
    diff: str,
    target: Path,
    base_snapshot: Path,
    upstream_snapshot: Path,
) -> bool:
    """Apply *diff* file-by-file with ``git merge-file``, returning True if all merged cleanly.

    Unlike ``git apply -3`` this operates directly on the snapshot file contents,
    so it needs no shared git history. Conflict markers are left in place.
    """
    all_clean = True
    for rel_path, is_new, is_deleted in parse_diff_filenames(diff):
        if not merge_one_file(
            git, rel_path, target, base_snapshot, upstream_snapshot, is_new, is_deleted
        ):
            all_clean = False
    return all_clean


def merge_one_file(
    git: GitContext,
    rel_path: str,
    target: Path,
    base_snapshot: Path,
    upstream_snapshot: Path,
    is_new: bool,
    is_deleted: bool,
) -> bool:
    """Merge one file, returning True when clean (no conflict/error).

    Added, deleted, target-absent, or base/upstream-absent files cannot be
    three-way merged and are applied wholesale; everything else goes through
    ``git merge-file``.
    """
    target_path = target / rel_path
    base_path = base_snapshot / rel_path
    upstream_path = upstream_snapshot / rel_path
    if (
        is_new
        or is_deleted
        or not target_path.exists()
        or not (base_path.exists() and upstream_path.exists())
    ):
        _apply_non_merge(target_path, upstream_path, is_deleted=is_deleted)
        return True
    return git_merge_file(git, target_path, base_path, upstream_path)


def _apply_non_merge(target_path: Path, upstream_path: Path, *, is_deleted: bool) -> None:
    """Handle the non-3-way cases: delete on removal, else copy upstream wholesale."""
    if is_deleted:
        if target_path.exists():
            target_path.unlink()
        return
    if upstream_path.exists():
        target_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(upstream_path, target_path)


def git_merge_file(
    git: GitContext, target_path: Path, base_path: Path, upstream_path: Path
) -> bool:
    """Run ``git merge-file`` for one file; return True only on a clean (rc 0) merge."""
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
    return result.returncode == 0


def scan_conflict_artifacts(target: Path) -> tuple[list[str], list[str]]:
    """Scan *target* for merge artifacts, returning ``(rej_files, marker_files)``.

    Looks for ``*.rej`` files (from ``git apply --reject``) and text files
    containing a ``<<<<<<<`` conflict marker (from ``git apply -3`` or
    ``git merge-file``). Each list is sorted and relative to *target*.
    """
    rej_files: list[str] = []
    marker_files: list[str] = []
    for path in sorted(target.rglob("*")):
        if not path.is_file():
            continue
        rel = str(path.relative_to(target))
        if path.suffix == ".rej":
            rej_files.append(rel)
        else:
            try:
                if b"<<<<<<<" in path.read_bytes()[:1_048_576]:
                    marker_files.append(rel)
            except OSError:
                pass
    return rej_files, marker_files
