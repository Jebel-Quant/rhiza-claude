"""Read and write `.rhiza/template.lock`, and remove files that left the template.

The lock records the synced SHA and the exact file list, which two other things depend
on: the next sync reads the SHA to find its merge base, and `stage_synced.py` reads the
file list so `/update` can stage template-owned paths only.

Orphan cleanup lives here because it is the lock's inverse — a file the previous lock
tracked but the current file set no longer contains is one this sync must delete.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _rhiza_common import escapes_root, log  # noqa: E402
from _rhiza_yaml import as_list  # noqa: E402

# Never removed by orphan cleanup: without it the repo stops being rhiza-managed.
_PROTECTED = frozenset({Path(".rhiza/template.yml")})
from _rhiza_template import Template, is_excluded  # noqa: E402
from _rhiza_yaml import dump_yaml, load_yaml  # noqa: E402


def lock_path(target: Path, lock_file: Path | None) -> Path:
    """Return the lock-file path (explicit override or the default under .rhiza)."""
    return lock_file if lock_file is not None else target / ".rhiza" / "template.lock"


def previously_tracked(lock_path: Path) -> set[Path]:
    """Return the file set recorded in an existing lock's ``files`` field.

    Entries that would resolve outside the target root are dropped, loudly. This is the
    first place a lock's paths are read, and the one where they are later **unlinked** —
    `clean_orphaned_files` joins each onto *target* and deletes it — so a `..` entry here
    would be a delete outside the repository rather than the read-only join `stage_synced`
    guards. Nothing upstream produces one today; the containment was implicit, exactly as
    `_PROTECTED` was before mutation testing found that any string would do.
    """
    if not lock_path.exists():
        return set()
    try:
        lock = load_yaml(lock_path)
    except (OSError, ValueError):
        return set()
    tracked: set[Path] = set()
    for entry in as_list(lock.get("files")):
        if escapes_root(str(entry)):
            log(f"Ignoring lock entry outside the repository: {entry}")
            continue
        tracked.add(Path(entry))
    return tracked


def clean_orphaned_files(
    target: Path, template_files: list[Path], excludes: set[str], previously_tracked: set[Path]
) -> None:
    """Delete files tracked by the previous sync that the template no longer provides.

    An excluded path is never an orphan. Matching goes through :func:`is_excluded` rather
    than comparing against *excludes* directly, so that a directory entry protects the
    files under it: `excludes` now holds the configured destination paths verbatim, and a
    set membership test would read `docs` and `docs/guide.md` as unrelated. Locks written
    before the exclusion fix list excluded files in `files:`, which makes them look like
    orphans on the next sync — this is what stops that from deleting them.
    """
    orphaned = previously_tracked - set(template_files) - set(_PROTECTED)
    for rel in sorted(orphaned):
        if is_excluded(rel.as_posix(), excludes):
            continue
        full = target / rel
        if full.exists():
            try:
                full.unlink()
                log(f"[DEL] {rel}")
            except OSError as exc:
                log(f"Failed to delete {rel}: {exc}")


def _lock_identity(lock: dict[str, Any]) -> tuple[Any, ...]:
    """Return the content-comparison key for a lock dict, excluding ``synced_at``."""
    return (
        str(lock.get("sha", "")),
        str(lock.get("repo", "")),
        str(lock.get("host", "")),
        str(lock.get("ref", "")),
        as_list(lock.get("include")),
        as_list(lock.get("exclude")),
        as_list(lock.get("templates")),
        as_list(lock.get("files")),
        str(lock.get("strategy", "")),
    )


def build_lock(sha: str, template: Template, files: list[str], synced_at: str) -> dict[str, Any]:
    """Assemble the ordered lock dict (matching the CLI's field order) for serialisation."""
    lock: dict[str, Any] = {
        "sha": sha,
        "repo": template.repository,
        "host": template.host,
        "ref": template.ref,
        "include": template.include,
        "exclude": template.exclude,
        "templates": template.templates,
    }
    if template.profiles:
        lock["profiles"] = template.profiles
    lock["files"] = files
    lock["synced_at"] = synced_at
    lock["strategy"] = "merge"
    return lock


def write_lock(target: Path, lock: dict[str, Any], lock_path: Path) -> None:
    """Write the lock atomically; filter ``files`` to on-disk paths and skip no-op rewrites."""
    lock = dict(lock)
    lock["files"] = sorted(f for f in as_list(lock.get("files")) if (target / f).exists())

    if lock_path.exists():
        try:
            existing = load_yaml(lock_path)
        except (OSError, ValueError):
            existing = None
        if existing is not None and _lock_identity(existing) == _lock_identity(lock):
            log(f"{lock_path.name} is already up to date — skipping write")
            return

    lock_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = Path(str(lock_path) + ".tmp")
    dump_yaml(lock, tmp_path)
    os.replace(tmp_path, lock_path)
    log(f"Updated {lock_path.name} -> {str(lock['sha'])[:12]}")


# ---------------------------------------------------------------------------
# Merge orchestration
# ---------------------------------------------------------------------------


def read_base_sha(lock_path: Path) -> str | None:
    """Return the previously-synced SHA from the lock, or ``None`` for a first sync."""
    if not lock_path.exists():
        return None
    try:
        return str(load_yaml(lock_path).get("sha") or "") or None
    except (OSError, ValueError):
        return None
