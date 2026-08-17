"""Materialise a template ref as a flat snapshot directory.

Clone the template (sparse, to the included paths only), then copy the included,
non-excluded files into a snapshot directory *at their destination paths*. The result is
a plain tree that mirrors what the target repo should contain.

`_rhiza_merge.py` consumes two of these — one at the previously-synced ref, one at the
new one — which is what makes the merge a three-way merge over ordinary directories.
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _rhiza_git as git  # noqa: E402
from _rhiza_bundles import Bundles, resolve_bundle_names  # noqa: E402
from _rhiza_common import log  # noqa: E402
from _rhiza_template import Template, is_excluded  # noqa: E402
from _rhiza_yaml import load_yaml  # noqa: E402


def clone_template(
    ctx: git.GitContext, template: Template, branch: str
) -> tuple[Path, str, list[str], dict[str, str]]:
    """Clone the upstream template and resolve the include paths + path map.

    Returns ``(upstream_dir, upstream_sha, include_paths, path_map)``; the caller
    owns *upstream_dir* and must remove it.
    """
    rhiza_branch = template.ref or branch
    include_paths = list(template.include)
    upstream_dir = Path(tempfile.mkdtemp())
    path_map: dict[str, str] = {}

    if template.profiles or template.templates:
        git.clone(ctx, template.git_url, upstream_dir, [template.bundles_path], branch=rhiza_branch)
        bundles = Bundles.from_config(load_yaml(upstream_dir / template.bundles_path))
        names = resolve_bundle_names(template, bundles)
        resolved = bundles.resolve_to_paths(names)
        path_map = bundles.resolve_to_path_map(names)
        include_paths = list(dict.fromkeys(resolved + include_paths))
        git.update_sparse_checkout(ctx, upstream_dir, include_paths)
    else:
        git.clone(ctx, template.git_url, upstream_dir, include_paths, branch=rhiza_branch)

    upstream_sha = git.get_head_sha(ctx, upstream_dir)
    log(f"Upstream HEAD: {upstream_sha[:12]}")
    return upstream_dir, upstream_sha, include_paths, path_map


def _expand_paths(base_dir: Path, paths: list[str]) -> list[Path]:
    """Expand file/directory *paths* under *base_dir* into a flat list of files."""
    all_files: list[Path] = []
    for rel in paths:
        full = base_dir / rel
        if full.is_file():
            all_files.append(full)
        elif full.is_dir():
            all_files.extend(
                Path(dirpath) / fname
                for dirpath, _, filenames in os.walk(full, followlinks=True)
                for fname in filenames
            )
    return all_files


def _remap_path(source: str, path_map: dict[str, str]) -> str:
    """Translate *source* to its destination via *path_map* (exact or directory-prefix)."""
    if source in path_map:
        return path_map[source]
    for src, dest in path_map.items():
        src_prefix = src.rstrip("/") + "/"
        if source.startswith(src_prefix):
            suffix = source[len(src_prefix) :]
            return dest.rstrip("/") + "/" + suffix if dest.rstrip("/") else suffix
    return source


def prepare_snapshot(
    clone_dir: Path,
    include_paths: list[str],
    excludes: set[str],
    snapshot_dir: Path,
    path_map: dict[str, str],
) -> list[Path]:
    """Copy included, non-excluded files from *clone_dir* into *snapshot_dir* at dest paths.

    The remap happens **before** the exclusion test, and the order is the whole point:
    `exclude:` is declared in destination paths, so testing the source path meant a
    bundle-sourced file was never matched. `bundles/python-core/.pre-commit-config.yaml`
    is not `.pre-commit-config.yaml`, so the file was copied, listed in the lock, and
    staged into the PR by `stage_synced.py` — all against an explicit exclusion.
    """
    template_files: list[Path] = []
    for f in _expand_paths(clone_dir, include_paths):
        rel_source = f.relative_to(clone_dir).as_posix()
        rel_dest = _remap_path(rel_source, path_map)
        if is_excluded(rel_dest, excludes):
            continue
        dst = snapshot_dir / rel_dest
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(f, dst)
        template_files.append(Path(rel_dest))
    return template_files


def copy_files(snapshot_dir: Path, target: Path, files: list[Path]) -> None:
    """Copy each of *files* from *snapshot_dir* into *target*, creating parents."""
    for rel in sorted(files):
        dst = target / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(snapshot_dir / rel, dst)


# ---------------------------------------------------------------------------
# Lock file + orphan cleanup
# ---------------------------------------------------------------------------
