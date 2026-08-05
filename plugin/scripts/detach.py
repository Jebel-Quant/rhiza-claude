#!/usr/bin/env python3
"""Detach the repo from rhiza by removing every rhiza-managed file.

A stdlib-only port of the `rhiza uninstall` command, bundled with this plugin so
`/rhiza:detach` works without the `rhiza` CLI (or PyYAML) installed. It reads
the `files` recorded in `.rhiza/template.lock`, deletes each one, prunes the
now-empty directories, and finally removes the lock file itself.

This detaches the repo from its template; it does not uninstall the plugin.

Usage:
  uv run --python 3.12 --no-project python scripts/detach.py [TARGET] [--force|-y]

  TARGET       repository root to clean (default: current directory)
  --force, -y  skip the confirmation prompt and proceed with deletion

This is destructive. Without --force it prompts for confirmation; if stdin is
not a TTY (no way to answer) it treats that as "no" and cancels. Exits 0 on
success or a clean no-op, 1 if any deletion failed or the lock is unreadable.
"""

from __future__ import annotations

import argparse
import stat
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _rhiza_yaml import load_yaml  # noqa: E402

LOCK_REL = Path(".rhiza") / "template.lock"


def _info(message: str) -> None:
    """Print an informational line to stderr."""
    print(message, file=sys.stderr)


def _error(message: str) -> None:
    """Print an error line to stderr."""
    print(f"error: {message}", file=sys.stderr)


def _confirm(files_to_remove: list[Path], target: Path) -> bool:
    """Show the deletion list and ask for confirmation; False cancels."""
    _info("This will remove the following files from your repository:")
    for file_path in sorted(files_to_remove):
        if (target / file_path).exists():
            _info(f"  - {file_path}")
    try:
        response = input("\nAre you sure you want to proceed? [y/N]: ").strip().lower()
    except (KeyboardInterrupt, EOFError):
        _info("\nDetach cancelled")
        return False
    if response not in ("y", "yes"):
        _info("Detach cancelled by user")
        return False
    return True


def _remove_files(files_to_remove: list[Path], target: Path) -> tuple[int, int, int]:
    """Delete the listed files; return (removed, skipped, errors)."""
    _info("Removing files...")
    removed = skipped = errors = 0
    for file_path in sorted(files_to_remove):
        full_path = target / file_path
        if not full_path.exists():
            skipped += 1
            continue
        try:
            full_path.unlink()
            _info(f"[DEL] {file_path}")
            removed += 1
        except PermissionError:
            # A read-only file must be made writable before it can be deleted.
            try:
                full_path.chmod(full_path.stat().st_mode | stat.S_IWRITE)
                full_path.unlink()
                _info(f"[DEL] {file_path}")
                removed += 1
            except OSError as exc:
                _error(f"Failed to delete {file_path}: {exc}")
                errors += 1
        except OSError as exc:
            _error(f"Failed to delete {file_path}: {exc}")
            errors += 1
    return removed, skipped, errors


def _cleanup_empty_directories(files_to_remove: list[Path], target: Path) -> int:
    """Remove directories left empty by the deletions; return the count."""
    removed = 0
    for file_path in sorted(files_to_remove, reverse=True):
        parent = (target / file_path).parent
        while parent != target and parent.exists():
            try:
                if parent.is_dir() and not any(parent.iterdir()):
                    parent.rmdir()
                    removed += 1
                    parent = parent.parent
                else:
                    break
            except OSError:
                break
    return removed


def _print_summary(removed: int, skipped: int, empty_dirs: int, errors: int) -> None:
    """Print the deletion summary counts."""
    _info("\nDetach summary:")
    _info(f"  Files removed: {removed}")
    if skipped:
        _info(f"  Files skipped (already deleted): {skipped}")
    if empty_dirs:
        _info(f"  Empty directories removed: {empty_dirs}")
    if errors:
        _error(f"  Errors encountered: {errors}")


def _drop_lock(lock_file: Path) -> tuple[int, int]:
    """Delete the lock so the repo is no longer rhiza-managed; return ``(removed, errors)``.

    Last, and deliberately so: while the lock is present the detach is resumable, because
    it is the only record of which files were managed.
    """
    if not lock_file.exists():
        return 0, 0
    try:
        lock_file.unlink()
    except OSError as exc:
        _error(f"Failed to delete {LOCK_REL}: {exc}")
        return 0, 1
    _info(f"[DEL] {LOCK_REL}")
    return 1, 0


def _report_outcome(errors: int) -> int:
    """Print the closing guidance and return the process exit code."""
    if errors:
        _error(f"Detach completed with {errors} error(s)")
        return 1
    _info("Repository detached from rhiza successfully")
    _info(
        "\nNext steps:\n"
        "  Review changes:  git status && git diff\n"
        '  Commit:          git add . && git commit -m "chore: remove rhiza templates"'
    )
    return 0


def detach(target: Path, *, force: bool) -> int:
    """Remove all rhiza-managed files; return a process exit code."""
    target = target.resolve()
    _info(f"Target repository: {target}")

    lock_file = target / LOCK_REL
    if not lock_file.exists():
        _info(f"No lock file found at: {LOCK_REL}")
        _info("Nothing to detach. This repository may not have Rhiza templates synced.")
        return 0

    try:
        lock = load_yaml(lock_file)
    except (OSError, ValueError) as exc:
        _error(f"Failed to read template.lock: {exc}")
        return 1

    files_to_remove = [Path(str(f)) for f in (lock.get("files") or [])]
    if not files_to_remove:
        _info("No files found to detach. Nothing to do.")
        return 0

    _info(f"Found {len(files_to_remove)} file(s) to remove")

    if not force and not _confirm(files_to_remove, target):
        return 0

    removed, skipped, errors = _remove_files(files_to_remove, target)
    empty_dirs = _cleanup_empty_directories(files_to_remove, target)
    lock_removed, lock_errors = _drop_lock(lock_file)

    _print_summary(removed + lock_removed, skipped, empty_dirs, errors + lock_errors)
    return _report_outcome(errors + lock_errors)


def main(argv: list[str] | None = None) -> int:
    """Entry point: parse args and run the detach."""
    parser = argparse.ArgumentParser(
        description="Detach the repo from rhiza, removing every file .rhiza/template.lock records.",
    )
    parser.add_argument(
        "target",
        nargs="?",
        default=".",
        help="Repository root to clean (default: current directory).",
    )
    parser.add_argument(
        "--force",
        "-y",
        action="store_true",
        help="Skip the confirmation prompt and proceed with deletion.",
    )
    args = parser.parse_args(argv)
    return detach(Path(args.target), force=args.force)


if __name__ == "__main__":
    raise SystemExit(main())
