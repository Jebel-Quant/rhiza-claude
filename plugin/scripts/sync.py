#!/usr/bin/env python3
"""Sync rhiza template files into this repo using a 3-way merge.

A stdlib-only port of the `rhiza sync` command, bundled with this plugin so
`/rhiza:sync` (and `/rhiza:update`) work without the `rhiza` CLI installed:
clone the upstream template, materialise the previously-synced snapshot beside
it, and three-way merge the two into the working tree — preserving local edits
and leaving conflict markers where both sides changed a region.

The merge itself lives in `_rhiza_merge.py`, which compares the two snapshot
directories directly. It used to render a `git diff --no-index` of one against
the other, apply it with `git apply -3`, then parse that diff text back into a
file list to merge each file with `git merge-file` anyway. Since nothing runs
`git apply` now, **`.rej` files are no longer produced**.

Usage:
  uv run --python 3.12 --no-project python scripts/sync.py [TARGET] [--branch BRANCH]

  TARGET     repository root to sync (default: current directory)
  --branch   template branch to use when template.yml has no `ref`
             (default: main)

Requires `git` on PATH and Python >= 3.11 (uses ``datetime.UTC``); run it under
``uv run --python 3.12`` since the system ``python3`` may be older (macOS ships
3.9). **Mutates the working tree.** Exit codes:
  0  synced cleanly (or already up to date)
  1  synced with conflicts — resolve the `<<<<<<<` markers, then commit (this is
     the expected outcome when local edits collide with upstream). Also returned
     when a locally-modified binary file could not be merged, which is reported
     by name since it leaves no marker behind.
  2  could not sync (dirty tree, invalid template.yml, or a git failure)
"""

from __future__ import annotations

import argparse
import datetime
import shutil
import subprocess  # nosec B404
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _rhiza_git as git  # noqa: E402
import _rhiza_merge as merge  # noqa: E402
from _rhiza_common import SyncError, log  # noqa: E402
from _rhiza_lock import (  # noqa: E402
    build_lock,
    clean_orphaned_files,
    previously_tracked,
    read_base_sha,
    write_lock,
)
from _rhiza_lock import (
    lock_path as resolve_lock_path,
)
from _rhiza_snapshot import (  # noqa: E402
    clone_template,
    copy_files,
    prepare_snapshot,
)
from _rhiza_template import Template, load_template, normalise_excludes  # noqa: E402

EXIT_OK = 0
EXIT_CONFLICTS = 1
EXIT_ERROR = 2


def _now() -> str:
    """Return the current UTC time as an ISO 8601 ``...Z`` timestamp (seam for tests)."""
    return datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------------------
# Template configuration
# ---------------------------------------------------------------------------


def _merge_with_base(
    ctx: git.GitContext,
    target: Path,
    upstream_snapshot: Path,
    base_sha: str,
    base_snapshot: Path,
    git_url: str,
    include_paths: list[str],
    excludes: set[str],
    path_map: dict[str, str],
) -> bool:
    """Materialise the base snapshot and three-way merge base->upstream into *target*."""
    base_clone = Path(tempfile.mkdtemp())
    try:
        git.clone(ctx, git_url, base_clone, include_paths, sha=base_sha)
        prepare_snapshot(base_clone, include_paths, excludes, base_snapshot, path_map)
    except (subprocess.CalledProcessError, OSError):
        log("Could not check out base commit — treating all files as new")
    finally:
        shutil.rmtree(base_clone, ignore_errors=True)

    outcome = merge.merge_trees(ctx, target, base_snapshot, upstream_snapshot)
    if not (outcome.merged or outcome.conflicted or outcome.unmergeable or outcome.deleted):
        log("Template unchanged since last sync — nothing to apply")
        return True

    log(
        f"Merged {len(outcome.merged)} file(s)"
        + (f", deleted {len(outcome.deleted)}" if outcome.deleted else "")
    )
    for path in outcome.conflicted:
        log(f"  conflict: {path} — `<<<<<<<` markers written")
    for path in outcome.unmergeable:
        # Named individually because there is no marker to find these by: the file was
        # left exactly as the user had it, which is the safe choice but an invisible one.
        log(f"  cannot merge: {path} — locally modified and not text; left untouched")
    return outcome.clean


def _run_merge(
    ctx: git.GitContext,
    target: Path,
    template: Template,
    upstream_snapshot: Path,
    upstream_sha: str,
    base_sha: str | None,
    template_files: list[Path],
    include_paths: list[str],
    excludes: set[str],
    path_map: dict[str, str],
    lock_path: Path,
) -> bool:
    """Apply the upstream snapshot to *target*, clean orphans, write the lock; return clean-ness."""
    tracked_before = previously_tracked(lock_path)
    base_snapshot = Path(tempfile.mkdtemp())
    try:
        if base_sha:
            clean = _merge_with_base(
                ctx,
                target,
                upstream_snapshot,
                base_sha,
                base_snapshot,
                template.git_url,
                include_paths,
                excludes,
                path_map,
            )
        else:
            log("First sync — copying all template files")
            copy_files(upstream_snapshot, target, template_files)
            clean = True

        missing = [p for p in template_files if not (target / p).exists()]
        if missing:
            log(f"Restoring {len(missing)} template file(s) missing from target")
            copy_files(upstream_snapshot, target, missing)

        clean_orphaned_files(target, template_files, excludes, tracked_before)
        lock = build_lock(upstream_sha, template, [str(p) for p in template_files], _now())
        write_lock(target, lock, lock_path)
    finally:
        shutil.rmtree(base_snapshot, ignore_errors=True)
    return clean


def sync(target: Path, branch: str) -> int:
    """Run the sync and return a process exit code (see the module docstring)."""
    target = target.resolve()
    ctx = git.GitContext.default()

    dirty = git.status_porcelain(ctx, target)
    if dirty:
        log("Working tree is not clean — commit or stash your changes before syncing:")
        for line in dirty:
            log(f"  {line}")
        return EXIT_ERROR

    template = load_template(target, target / ".rhiza" / "template.yml")
    lock_path = resolve_lock_path(target, None)
    base_sha = read_base_sha(lock_path)

    log(f"Cloning {template.repository}@{template.ref or branch}")
    upstream_dir, upstream_sha, include_paths, path_map = clone_template(ctx, template, branch)
    upstream_snapshot = Path(tempfile.mkdtemp())
    try:
        excludes = normalise_excludes(template.exclude)
        template_files = prepare_snapshot(
            upstream_dir, include_paths, excludes, upstream_snapshot, path_map
        )
        log(f"Upstream: {len(template_files)} file(s) to consider")
        clean = _run_merge(
            ctx,
            target,
            template,
            upstream_snapshot,
            upstream_sha,
            base_sha,
            template_files,
            include_paths,
            excludes,
            path_map,
            lock_path,
        )
    finally:
        shutil.rmtree(upstream_snapshot, ignore_errors=True)
        shutil.rmtree(upstream_dir, ignore_errors=True)

    if not clean:
        log("Conflicts remain — resolve `<<<<<<<` markers, then commit.")
        return EXIT_CONFLICTS
    log(f"Sync complete — {len(template_files)} file(s) processed")
    return EXIT_OK


def main(argv: list[str] | None = None) -> int:
    """Entry point: parse args, run the sync, and translate failures to exit codes."""
    parser = argparse.ArgumentParser(
        description="Sync rhiza template files into this repo (3-way merge)."
    )
    parser.add_argument(
        "target",
        nargs="?",
        default=".",
        help="Repository root to sync (default: current directory).",
    )
    parser.add_argument(
        "--branch",
        "-b",
        default="main",
        help="Template branch to use when template.yml has no `ref` (default: main).",
    )
    args = parser.parse_args(argv)
    try:
        return sync(Path(args.target), args.branch)
    except SyncError as exc:
        log(f"error: {exc}")
        return EXIT_ERROR
    except subprocess.CalledProcessError as exc:
        stderr = exc.stderr.decode() if isinstance(exc.stderr, bytes) else (exc.stderr or "")
        log(f"error: git failed: {stderr.strip() or exc}")
        return EXIT_ERROR
    except RuntimeError as exc:
        log(f"error: {exc}")
        return EXIT_ERROR


if __name__ == "__main__":
    raise SystemExit(main())
