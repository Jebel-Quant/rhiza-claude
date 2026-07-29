#!/usr/bin/env python3
"""Three-way merge of a template snapshot into the working tree — `sync.py`'s merge.

`sync.py` holds three trees on disk by the time it merges: the **base** snapshot (the
template as it was at the previously-synced SHA), the **upstream** snapshot (the template
now), and the **target** working tree. A three-way merge is exactly what those three
inputs are for.

It used to reach that merge the long way round: render a unified diff of base→upstream
with ``git diff --no-index``, apply it with ``git apply -3``, and — when the target repo
lacked the template's blob objects, which it always does — parse the diff text back into
a file list and merge each file with ``git merge-file`` after all. `git apply --reject`
was the last resort, scattering ``.rej`` files.

The diff was pure overhead. It was generated from two directories we already had, only to
be parsed again to recover the file list those same directories state directly. Removing
it deletes ``get_diff``, ``apply_diff``, ``_apply_reject``, ``merge_file_fallback``,
``parse_diff_filenames``, ``_DiffFileState`` and ``_path_after`` — the diff plumbing, not
the merge — and takes ``.rej`` files with it, since nothing runs ``git apply`` any more.

`git merge-file` is the merge, and it is a subprocess, so nothing about this module's
licence changes. (The one library that would have replaced it, `merge3`, is
GPL-2.0-or-later against this plugin's MIT — a real incompatibility, and unnecessary
given git is already a hard requirement.)

What the merge decides, per file, from the three trees:

  in upstream, not in base      new upstream file      -> copy it in
  in base, not in upstream      upstream deleted it    -> delete it
  identical in base + upstream  template never changed -> **leave the local file alone**
  absent from the target        nothing to merge into  -> copy upstream in
  otherwise                     both sides moved       -> `git merge-file`

That third rule is the important one: a file the template did not change is never
rewritten, whatever the user did to it.

`git merge-file` exit codes are no longer flattened to a boolean. 0 is clean, a small
positive number is that many conflicted regions (markers written), and 255 is a refusal —
in practice a binary file, which cannot be three-way merged at all. A refusal leaves the
target **untouched** and is reported: silently overwriting a locally-modified binary
would be data loss with nothing to show the user.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from pathlib import Path

import _rhiza_git as git

# `git merge-file` returns 255 for "I will not merge this" (binary, unreadable). Any
# other non-zero value is a conflict count.
_MERGE_REFUSED = 255

# How much of a file to sniff for NUL before calling it binary.
_SNIFF_BYTES = 8192


@dataclass
class MergeOutcome:
    """What the merge did, path by path."""

    merged: list[str] = field(default_factory=list)
    conflicted: list[str] = field(default_factory=list)
    unmergeable: list[str] = field(default_factory=list)
    deleted: list[str] = field(default_factory=list)

    @property
    def clean(self) -> bool:
        """True when every file landed without a conflict or a refusal."""
        return not self.conflicted and not self.unmergeable


@dataclass(frozen=True)
class Change:
    """One template file that differs between the base and upstream snapshots."""

    path: str
    is_new: bool
    is_deleted: bool


def _relative_files(root: Path) -> set[str]:
    """Return every file under *root*, as POSIX-relative paths."""
    return {p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file()}


def _same_content(left: Path, right: Path) -> bool:
    """Are these two files byte-identical?"""
    try:
        return left.read_bytes() == right.read_bytes()
    except OSError:  # pragma: no cover - unreadable snapshot files
        return False


def is_binary(path: Path) -> bool:
    """Does *path* look binary — i.e. contain a NUL in its first few KiB?

    The same heuristic git uses. `git merge-file` refuses binary input, so this lets the
    refusal be predicted and reported as such rather than surfacing as a bare error.
    """
    try:
        return b"\x00" in path.read_bytes()[:_SNIFF_BYTES]
    except OSError:  # pragma: no cover - unreadable target files
        return False


def changed_files(base_snapshot: Path, upstream_snapshot: Path) -> list[Change]:
    """Return the template files that differ between the two snapshots.

    Read straight off the two trees. This is the list the old code recovered by parsing
    the text of a diff it had generated from these very directories.

    Files identical in both are **omitted**, which is what guarantees that an unchanged
    template file is never touched in the target.
    """
    base_files = _relative_files(base_snapshot)
    upstream_files = _relative_files(upstream_snapshot)

    changes: list[Change] = []
    for path in sorted(base_files | upstream_files):
        in_base, in_upstream = path in base_files, path in upstream_files
        if in_base and in_upstream:
            if _same_content(base_snapshot / path, upstream_snapshot / path):
                continue
            changes.append(Change(path, is_new=False, is_deleted=False))
        elif in_upstream:
            changes.append(Change(path, is_new=True, is_deleted=False))
        else:
            changes.append(Change(path, is_new=False, is_deleted=True))
    return changes


def _delete(target_path: Path) -> None:
    """Remove a file the template no longer ships."""
    if target_path.exists():
        target_path.unlink()


def _copy(upstream_path: Path, target_path: Path) -> None:
    """Install an upstream file wholesale, creating parent directories."""
    target_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(upstream_path, target_path)


def merge_one(
    ctx: git.GitContext,
    change: Change,
    target: Path,
    base_snapshot: Path,
    upstream_snapshot: Path,
    outcome: MergeOutcome,
) -> None:
    """Apply a single *change* to *target*, recording what happened in *outcome*."""
    target_path = target / change.path
    base_path = base_snapshot / change.path
    upstream_path = upstream_snapshot / change.path

    if change.is_deleted:
        _delete(target_path)
        outcome.deleted.append(change.path)
        return

    # Nothing local to preserve, or no base to merge against: take upstream whole.
    if change.is_new or not target_path.exists():
        _copy(upstream_path, target_path)
        outcome.merged.append(change.path)
        return

    # The user has not touched it — upstream wins without a merge, and without any
    # chance of `git merge-file` mangling an unchanged file.
    if _same_content(target_path, base_path):
        _copy(upstream_path, target_path)
        outcome.merged.append(change.path)
        return

    if is_binary(target_path) or is_binary(upstream_path) or is_binary(base_path):
        # Locally modified *and* binary. Leave it alone and say so: there is no merge to
        # perform and no marker to leave, so overwriting would lose work invisibly.
        outcome.unmergeable.append(change.path)
        return

    status = git.merge_file(ctx, target_path, base_path, upstream_path)
    if status == 0:
        outcome.merged.append(change.path)
    elif status == _MERGE_REFUSED:
        outcome.unmergeable.append(change.path)
    else:
        outcome.conflicted.append(change.path)


def merge_trees(
    ctx: git.GitContext, target: Path, base_snapshot: Path, upstream_snapshot: Path
) -> MergeOutcome:
    """Merge *upstream_snapshot* into *target*, using *base_snapshot* as the merge base."""
    outcome = MergeOutcome()
    for change in changed_files(base_snapshot, upstream_snapshot):
        merge_one(ctx, change, target, base_snapshot, upstream_snapshot, outcome)
    return outcome
