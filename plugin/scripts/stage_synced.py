#!/usr/bin/env python3
"""Stage only the template-owned files after a sync — the engine behind `/rhiza:update`.

`/rhiza:update` must open a PR containing **nothing but files that came from the
template repository**. `scripts/sync.py` already records exactly which paths it
materialized, in ``.rhiza/template.lock``'s ``files`` list, so this script stages
that list — plus ``.rhiza/template.yml`` and the lock itself — and nothing else.

That makes the guarantee mechanical rather than a rule prose has to honour: a
blanket ``git add --all`` would sweep in the repo's own source, a ``make fmt``
reformat, or an unrelated edit, and quietly turn a template bump into a PR that
touches everything. Whatever is left unstaged is reported so the caller can pass it
on to the user, who decides what to do with it.

Usage:
  uv run --python 3.12 --no-project python \
      scripts/stage_synced.py [TARGET] [--json]

Exit codes:
  0  staged cleanly (possibly with nothing to stage)
  1  no ``.rhiza/template.lock`` — run the sync first
  2  a git failure
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess  # nosec B404
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _rhiza_yaml import load_yaml  # noqa: E402

# Always staged alongside the lock's `files`: the pointer and the lock itself.
_CONFIG_PATHS = (".rhiza/template.yml", ".rhiza/template.lock")

EXIT_OK = 0
EXIT_NO_LOCK = 1
EXIT_GIT_ERROR = 2

# `git add` takes many pathspecs, but keep batches bounded so a first sync of
# several hundred files cannot overflow the command line.
_BATCH = 100


class GitFailed(Exception):
    """A git invocation exited non-zero, carrying the stderr to report.

    Every git call here is a step in one sequence, and any failure has the same outcome:
    stage nothing further and report EXIT_GIT_ERROR. Raising lets :func:`stage_synced`
    say that once instead of guarding each call — the four hand-written guards it
    replaced were most of that function's branching.
    """

    def __init__(self, stderr: str) -> None:
        """Record the *stderr* git wrote."""
        super().__init__(stderr)
        self.stderr = stderr


def _git(target: Path, args: list[str]) -> subprocess.CompletedProcess[str]:
    """Run one git command in *target*, capturing text output."""
    env = os.environ.copy()
    env["GIT_TERMINAL_PROMPT"] = "0"
    return subprocess.run(  # nosec B603
        [shutil.which("git") or "git", *args],
        cwd=str(target),
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )


def _git_output(target: Path, args: list[str]) -> str:
    """Run one git command in *target* and return its stdout, or raise :class:`GitFailed`."""
    result = _git(target, args)
    if result.returncode != 0:
        raise GitFailed(result.stderr)
    return result.stdout


def _porcelain(target: Path) -> list[str]:
    """Return the non-blank lines of ``git status --porcelain`` in *target*."""
    return [
        line for line in _git_output(target, ["status", "--porcelain"]).splitlines() if line.strip()
    ]


def lock_files(lock_path: Path) -> list[str]:
    """Return the ``files`` list recorded in ``.rhiza/template.lock``.

    Returns an empty list when the lock is unreadable or records no files — the
    caller still stages the config paths, so a damaged lock degrades to "stage the
    pointer only" rather than to a blanket add.
    """
    try:
        raw = load_yaml(lock_path).get("files")
    except (OSError, ValueError):
        return []
    if not isinstance(raw, list):
        return []
    return [str(entry) for entry in raw if str(entry).strip()]


def unstaged_paths(porcelain: list[str]) -> list[str]:
    """Return paths from ``git status --porcelain`` that are not fully staged.

    Porcelain v1 gives two status columns — index, then worktree. Any worktree
    column other than a space means changes remain outside the index (``??`` for
    untracked, ``M`` for a modification we did not stage, and so on).
    """
    remainder = [line[3:].strip() for line in porcelain if len(line) >= 4 and line[1] != " "]
    return sorted(set(remainder))


def deleted_paths(porcelain: list[str]) -> set[str]:
    """Return tracked paths git reports as deleted, in either status column.

    A template file upstream removed is a template-owned change, so it must still be
    stageable even though it is no longer on disk.
    """
    return {line[3:].strip() for line in porcelain if len(line) >= 4 and "D" in line[:2]}


def wanted_paths(target: Path, lock_path: Path, deleted: set[str]) -> list[str]:
    """Return the paths to stage: the config paths plus the lock's ``files``.

    Deduped, order-stable, and limited to paths git can actually match — on disk, or
    tracked-and-deleted. A stale lock entry that is neither would make ``git add`` fail on
    the whole batch, so one dead entry must not cost the entire sync.
    """
    wanted: list[str] = []
    for path in (*_CONFIG_PATHS, *lock_files(lock_path)):
        if path in wanted:
            continue
        if (target / path).exists() or path in deleted:
            wanted.append(path)
    return wanted


def _add_in_batches(target: Path, wanted: list[str]) -> None:
    """Stage *wanted* in bounded batches, raising :class:`GitFailed` on any failure.

    ``--all`` so upstream deletions stage as deletions, not just adds and modifications.
    """
    for start in range(0, len(wanted), _BATCH):
        _git_output(target, ["add", "--all", "--", *wanted[start : start + _BATCH]])


def _notes_for(staged: list[str], left: list[str]) -> list[str]:
    """Return the human-readable notes for a completed staging run."""
    notes: list[str] = []
    if left:
        notes.append(
            f"{len(left)} path(s) left unstaged — not template-owned, "
            "so they stay in the working tree"
        )
    if not staged:
        notes.append("nothing to stage — the sync changed no template files")
    return notes


def stage_synced(target: Path) -> dict[str, Any]:
    """Stage the template-owned paths at *target*; return a summary dict."""
    lock_path = target / ".rhiza" / "template.lock"
    if not lock_path.exists():
        return {
            "staged": [],
            "unstaged": [],
            "notes": ["no .rhiza/template.lock — run the sync first"],
            "exit_code": EXIT_NO_LOCK,
        }

    try:
        deleted = deleted_paths(_porcelain(target))
        _add_in_batches(target, wanted_paths(target, lock_path, deleted))
        staged_out = _git_output(target, ["diff", "--cached", "--name-only"])
        staged_paths = sorted(p for p in staged_out.splitlines() if p.strip())
        left = unstaged_paths(_porcelain(target))
    except GitFailed as exc:
        return _git_error(exc.stderr)

    return {
        "staged": staged_paths,
        "unstaged": left,
        "notes": _notes_for(staged_paths, left),
        "exit_code": EXIT_OK,
    }


def _git_error(stderr: str) -> dict[str, Any]:
    """Build the summary for a failed git invocation."""
    return {
        "staged": [],
        "unstaged": [],
        "notes": [f"git failed: {stderr.strip()}"],
        "exit_code": EXIT_GIT_ERROR,
    }


def main(argv: list[str] | None = None) -> int:
    """Entry point: stage the template-owned paths and return an exit code."""
    parser = argparse.ArgumentParser(
        description="Stage only the files the last rhiza sync materialized.",
    )
    parser.add_argument(
        "target", nargs="?", default=".", help="Repository root (default: current directory)."
    )
    parser.add_argument(
        "--json", dest="json_output", action="store_true", help="Emit the summary as JSON."
    )
    args = parser.parse_args(argv)

    summary = stage_synced(Path(args.target).resolve())

    if args.json_output:
        print(json.dumps(summary, indent=2))
    else:
        for path in summary["staged"]:
            print(f"staged   {path}")
        for path in summary["unstaged"]:
            print(f"left     {path}", file=sys.stderr)
        for note in summary["notes"]:
            print(f"note     {note}", file=sys.stderr)
    return int(summary["exit_code"])


if __name__ == "__main__":
    raise SystemExit(main())
