#!/usr/bin/env python3
"""Sync rhiza template files into this repo using a cruft-style 3-way merge.

A stdlib-only port of the `rhiza sync` command, bundled with this plugin so
`/rhiza:sync` (and `/rhiza:update`) work without the `rhiza` CLI installed. It
reproduces the CLI's behaviour: clone the upstream template, diff the
previously-synced snapshot against the new one, and apply that diff onto the
working tree via `git apply -3` (falling back to `git merge-file`), preserving
local edits and leaving conflict markers where both sides changed a region.

Usage:
  python3 scripts/sync.py [TARGET] [--branch BRANCH]

  TARGET     repository root to sync (default: current directory)
  --branch   template branch to use when template.yml has no `ref`
             (default: main)

Requires `git` on PATH. **Mutates the working tree.** Exit codes:
  0  synced cleanly (or already up to date)
  1  synced with conflicts — resolve `<<<<<<<` markers and `*.rej` files, then
     commit (this is the expected outcome when local edits collide with upstream)
  2  could not sync (dirty tree, invalid template.yml, or a git failure)
"""

from __future__ import annotations

import argparse
import datetime
import os
import shutil
import subprocess  # nosec B404
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _rhiza_git as git  # noqa: E402
from _rhiza_yaml import dump_yaml, load_yaml  # noqa: E402

_DEFAULT_BUNDLES_PATH = ".rhiza/template-bundles.yml"
_PROTECTED = frozenset({Path(".rhiza/template.yml")})

EXIT_OK = 0
EXIT_CONFLICTS = 1
EXIT_ERROR = 2


class SyncError(Exception):
    """A fatal, non-conflict sync failure (bad config, dirty tree, git error)."""


def _log(message: str) -> None:
    """Emit a progress/diagnostic line to stderr."""
    print(message, file=sys.stderr)


def _now() -> str:
    """Return the current UTC time as an ISO 8601 ``...Z`` timestamp (seam for tests)."""
    return datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _as_list(value: Any) -> list[str]:
    """Normalise a scalar/None/list config field into a list of strings."""
    if value is None:
        return []
    if isinstance(value, list):
        return [str(x) for x in value]
    if isinstance(value, str):
        parts = value.split("\\n") if "\\n" in value and "\n" not in value else value.split("\n")
        return [p.strip() for p in parts if p.strip()]
    return [str(value)]


# ---------------------------------------------------------------------------
# Template configuration
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Template:
    """The parsed `.rhiza/template.yml` fields sync needs."""

    repository: str
    ref: str
    host: str = "github"
    include: list[str] = field(default_factory=list)
    exclude: list[str] = field(default_factory=list)
    templates: list[str] = field(default_factory=list)
    profiles: list[str] = field(default_factory=list)
    bundles_path: str = _DEFAULT_BUNDLES_PATH

    @classmethod
    def from_config(cls, config: dict[str, Any]) -> Template:
        """Build a :class:`Template` from a parsed template.yml dict, honouring key aliases."""
        repository = config.get("repository") or config.get("template-repository") or ""
        ref = config.get("ref") or config.get("template-branch") or ""
        return cls(
            repository=str(repository),
            ref=str(ref),
            host=str(config.get("template-host", "github")),
            include=_as_list(config.get("include")),
            exclude=_as_list(config.get("exclude")),
            templates=_as_list(config.get("templates")),
            profiles=_as_list(config.get("profiles")),
            bundles_path=str(config.get("template-bundles-path", _DEFAULT_BUNDLES_PATH)),
        )

    @property
    def git_url(self) -> str:
        """Return the HTTPS clone URL for the configured repository and host.

        Raises:
            SyncError: If the repository is unset or the host is unsupported.
        """
        if not self.repository:
            raise SyncError("template-repository is not configured in template.yml")
        # A full URL or local/file path (self-hosted or under test) is used verbatim.
        if "://" in self.repository or self.repository.startswith(("/", "./", "../")):
            return self.repository
        if self.host == "github":
            return f"https://github.com/{self.repository}.git"
        if self.host == "gitlab":
            return f"https://gitlab.com/{self.repository}.git"
        raise SyncError(f"Unsupported template-host: {self.host}. Must be 'github' or 'gitlab'.")


def _load_template(target: Path, template_file: Path) -> Template:
    """Load and validate the template config, raising :class:`SyncError` on any problem."""
    if not template_file.exists():
        raise SyncError(f"No template.yml found at {template_file}")
    try:
        config = load_yaml(template_file)
    except (OSError, ValueError) as exc:
        raise SyncError(f"Could not read {template_file}: {exc}") from exc

    template = Template.from_config(config)
    if not template.repository:
        raise SyncError("template-repository is required in template.yml")
    if not template.templates and not template.include and not template.profiles:
        raise SyncError("template.yml must set at least one of: templates, profiles, include")
    return template


# ---------------------------------------------------------------------------
# Bundle resolution (profiles/templates -> file paths)
# ---------------------------------------------------------------------------


def _ensure_safe_bundle_path(value: str) -> None:
    """Reject a bundle path that could escape the project directory.

    ``template-bundles.yml`` is untrusted (fetched from the template repo) and a
    remapped ``dest`` is joined onto the target directory, so an absolute path, a
    Windows drive letter, or a ``..`` component could write outside the project.

    Raises:
        SyncError: If *value* is absolute, uses a drive letter, or traverses up.
    """
    normalized = value.replace("\\", "/")
    pure = PurePosixPath(normalized)
    has_drive = len(normalized) >= 2 and normalized[0].isalpha() and normalized[1] == ":"
    if pure.is_absolute() or has_drive or ".." in pure.parts:
        raise SyncError(
            f"Unsafe bundle path {value!r}: paths must be relative to the project root "
            "(no absolute paths, drive letters, or '..' traversal)."
        )


def _bundle_file_entries(raw_files: Any) -> list[tuple[str, str]]:
    """Coerce a bundle's ``files`` field into validated ``(source, dest)`` pairs."""
    entries: list[tuple[str, str]] = []
    for entry in _as_list(raw_files) if isinstance(raw_files, str) else (raw_files or []):
        if isinstance(entry, str):
            source = dest = entry
        elif isinstance(entry, dict) and "source" in entry:
            source = str(entry["source"])
            dest = str(entry.get("dest", source))
        else:
            raise SyncError(
                f"Bundle file entry must be a string or a {{source, dest}} map, got: {entry!r}"
            )
        _ensure_safe_bundle_path(source)
        _ensure_safe_bundle_path(dest)
        entries.append((source, dest))
    return entries


@dataclass(frozen=True)
class Bundles:
    """The bundle/profile definitions from `template-bundles.yml` that sync needs."""

    requires: dict[str, list[str]]
    files: dict[str, list[tuple[str, str]]]
    profiles: dict[str, list[str]]

    @classmethod
    def from_config(cls, config: dict[str, Any]) -> Bundles:
        """Parse a `template-bundles.yml` dict into requires/files/profiles maps."""
        raw_bundles = config.get("bundles") or {}
        raw_profiles = config.get("profiles") or {}
        requires: dict[str, list[str]] = {}
        files: dict[str, list[tuple[str, str]]] = {}
        for name, data in raw_bundles.items():
            data = data or {}
            requires[name] = _as_list(data.get("requires"))
            files[name] = _bundle_file_entries(data.get("files"))
        profiles = {
            name: _as_list((data or {}).get("bundles")) for name, data in raw_profiles.items()
        }
        return cls(requires=requires, files=files, profiles=profiles)

    def _order(self, names: list[str], *, strict: bool) -> list[str]:
        """Return *names* plus their ``requires`` dependencies in dependency-first order."""
        order: list[str] = []
        resolved: set[str] = set()
        resolving: set[str] = set()

        def _collect(name: str) -> None:
            if name not in self.requires:
                if strict:
                    raise SyncError(f"Bundle '{name}' does not exist")
                return
            if name in resolving:
                if strict:
                    raise SyncError(f"Circular dependency detected for bundle '{name}'")
                return
            if name in resolved:
                return
            resolving.add(name)
            for dependency in self.requires[name]:
                _collect(dependency)
            resolving.discard(name)
            resolved.add(name)
            order.append(name)

        for name in names:
            _collect(name)
        return order

    def resolve_to_paths(self, names: list[str]) -> list[str]:
        """Resolve bundle *names* (and dependencies) to a deduplicated source-path list."""
        paths: list[str] = []
        seen: set[str] = set()
        for name in self._order(names, strict=True):
            entries = self.files[name]
            sources = [source for source, _ in entries] if entries else [f"bundles/{name}/"]
            for source in sources:
                if source not in seen:
                    seen.add(source)
                    paths.append(source)
        return paths

    def resolve_to_path_map(self, names: list[str]) -> dict[str, str]:
        """Return a source->dest map for remapped entries (and dir bundles map to '')."""
        resolved = set(self.resolve_to_paths(names))
        path_map: dict[str, str] = {}
        for name in self._order(names, strict=False):
            entries = self.files[name]
            if entries:
                for source, dest in entries:
                    if source in resolved and source != dest:
                        path_map[source] = dest
            else:
                path_map[f"bundles/{name}/"] = ""
        return path_map


def _resolve_bundle_names(template: Template, bundles: Bundles) -> list[str]:
    """Expand configured profiles to bundle names and merge with explicit templates."""
    if not template.profiles:
        return template.templates
    names: list[str] = []
    for profile in template.profiles:
        if profile not in bundles.profiles:
            available = ", ".join(sorted(bundles.profiles)) or "none"
            raise SyncError(f"Profile '{profile}' was not found. Available profiles: {available}")
        for bundle in bundles.profiles[profile]:
            if bundle not in names:
                names.append(bundle)
    return list(dict.fromkeys(names + template.templates))


# ---------------------------------------------------------------------------
# Cloning + snapshot preparation
# ---------------------------------------------------------------------------


def _clone_template(
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
        names = _resolve_bundle_names(template, bundles)
        resolved = bundles.resolve_to_paths(names)
        path_map = bundles.resolve_to_path_map(names)
        include_paths = list(dict.fromkeys(resolved + include_paths))
        git.update_sparse_checkout(ctx, upstream_dir, include_paths)
    else:
        git.clone(ctx, template.git_url, upstream_dir, include_paths, branch=rhiza_branch)

    upstream_sha = git.get_head_sha(ctx, upstream_dir)
    _log(f"Upstream HEAD: {upstream_sha[:12]}")
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


def _excluded_set(base_dir: Path, excluded_paths: list[str]) -> set[str]:
    """Return excluded relative-path strings for *base_dir* (always includes template.yml)."""
    result = {str(f.relative_to(base_dir)) for f in _expand_paths(base_dir, excluded_paths)}
    result.add(".rhiza/template.yml")
    return result


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


def _prepare_snapshot(
    clone_dir: Path,
    include_paths: list[str],
    excludes: set[str],
    snapshot_dir: Path,
    path_map: dict[str, str],
) -> list[Path]:
    """Copy included, non-excluded files from *clone_dir* into *snapshot_dir* at dest paths."""
    template_files: list[Path] = []
    for f in _expand_paths(clone_dir, include_paths):
        rel_source = str(f.relative_to(clone_dir))
        if rel_source in excludes:
            continue
        rel_dest = _remap_path(rel_source, path_map)
        dst = snapshot_dir / rel_dest
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(f, dst)
        template_files.append(Path(rel_dest))
    return template_files


def _copy_files(snapshot_dir: Path, target: Path, files: list[Path]) -> None:
    """Copy each of *files* from *snapshot_dir* into *target*, creating parents."""
    for rel in sorted(files):
        dst = target / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(snapshot_dir / rel, dst)


# ---------------------------------------------------------------------------
# Lock file + orphan cleanup
# ---------------------------------------------------------------------------


def _lock_path(target: Path, lock_file: Path | None) -> Path:
    """Return the lock-file path (explicit override or the default under .rhiza)."""
    return lock_file if lock_file is not None else target / ".rhiza" / "template.lock"


def _previously_tracked(lock_path: Path) -> set[Path]:
    """Return the file set recorded in an existing lock's ``files`` field."""
    if not lock_path.exists():
        return set()
    try:
        lock = load_yaml(lock_path)
    except (OSError, ValueError):
        return set()
    return {Path(f) for f in _as_list(lock.get("files"))}


def _clean_orphaned_files(
    target: Path, template_files: list[Path], excludes: set[str], previously_tracked: set[Path]
) -> None:
    """Delete files tracked by the previous sync that the template no longer provides."""
    orphaned = (
        previously_tracked - set(template_files) - {Path(e) for e in excludes} - set(_PROTECTED)
    )
    for rel in sorted(orphaned):
        full = target / rel
        if full.exists():
            try:
                full.unlink()
                _log(f"[DEL] {rel}")
            except OSError as exc:
                _log(f"Failed to delete {rel}: {exc}")


def _lock_identity(lock: dict[str, Any]) -> tuple[Any, ...]:
    """Return the content-comparison key for a lock dict, excluding ``synced_at``."""
    return (
        str(lock.get("sha", "")),
        str(lock.get("repo", "")),
        str(lock.get("host", "")),
        str(lock.get("ref", "")),
        _as_list(lock.get("include")),
        _as_list(lock.get("exclude")),
        _as_list(lock.get("templates")),
        _as_list(lock.get("files")),
        str(lock.get("strategy", "")),
    )


def _build_lock(sha: str, template: Template, files: list[str], synced_at: str) -> dict[str, Any]:
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


def _write_lock(target: Path, lock: dict[str, Any], lock_path: Path) -> None:
    """Write the lock atomically; filter ``files`` to on-disk paths and skip no-op rewrites."""
    lock = dict(lock)
    lock["files"] = sorted(f for f in _as_list(lock.get("files")) if (target / f).exists())

    if lock_path.exists():
        try:
            existing = load_yaml(lock_path)
        except (OSError, ValueError):
            existing = None
        if existing is not None and _lock_identity(existing) == _lock_identity(lock):
            _log(f"{lock_path.name} is already up to date — skipping write")
            return

    lock_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = Path(str(lock_path) + ".tmp")
    dump_yaml(lock, tmp_path)
    os.replace(tmp_path, lock_path)
    _log(f"Updated {lock_path.name} -> {str(lock['sha'])[:12]}")


# ---------------------------------------------------------------------------
# Merge orchestration
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
    """Clone the base snapshot, diff base->upstream, and apply it; return True if clean."""
    base_clone = Path(tempfile.mkdtemp())
    try:
        git.clone(ctx, git_url, base_clone, include_paths, sha=base_sha)
        _prepare_snapshot(base_clone, include_paths, excludes, base_snapshot, path_map)
    except (subprocess.CalledProcessError, OSError):
        _log("Could not check out base commit — treating all files as new")
    finally:
        shutil.rmtree(base_clone, ignore_errors=True)

    diff = git.get_diff(ctx, base_snapshot, upstream_snapshot)
    if not diff.strip():
        _log("Template unchanged since last sync — nothing to apply")
        return True
    return git.apply_diff(ctx, diff, target, base_snapshot, upstream_snapshot)


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
    previously_tracked = _previously_tracked(lock_path)
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
            _log("First sync — copying all template files")
            _copy_files(upstream_snapshot, target, template_files)
            clean = True

        missing = [p for p in template_files if not (target / p).exists()]
        if missing:
            _log(f"Restoring {len(missing)} template file(s) missing from target")
            _copy_files(upstream_snapshot, target, missing)

        _clean_orphaned_files(target, template_files, excludes, previously_tracked)
        lock = _build_lock(upstream_sha, template, [str(p) for p in template_files], _now())
        _write_lock(target, lock, lock_path)
    finally:
        shutil.rmtree(base_snapshot, ignore_errors=True)
    return clean


def sync(target: Path, branch: str) -> int:
    """Run the sync and return a process exit code (see the module docstring)."""
    target = target.resolve()
    ctx = git.GitContext.default()

    dirty = git.status_porcelain(ctx, target)
    if dirty:
        _log("Working tree is not clean — commit or stash your changes before syncing:")
        for line in dirty:
            _log(f"  {line}")
        return EXIT_ERROR

    template = _load_template(target, target / ".rhiza" / "template.yml")
    lock_path = _lock_path(target, None)
    base_sha = _read_base_sha(lock_path)

    _log(f"Cloning {template.repository}@{template.ref or branch}")
    upstream_dir, upstream_sha, include_paths, path_map = _clone_template(ctx, template, branch)
    upstream_snapshot = Path(tempfile.mkdtemp())
    try:
        excludes = _excluded_set(upstream_dir, template.exclude)
        template_files = _prepare_snapshot(
            upstream_dir, include_paths, excludes, upstream_snapshot, path_map
        )
        _log(f"Upstream: {len(template_files)} file(s) to consider")
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
        _log("Conflicts remain — resolve `<<<<<<<` markers and `.rej` files, then commit.")
        return EXIT_CONFLICTS
    _log(f"Sync complete — {len(template_files)} file(s) processed")
    return EXIT_OK


def _read_base_sha(lock_path: Path) -> str | None:
    """Return the previously-synced SHA from the lock, or ``None`` for a first sync."""
    if not lock_path.exists():
        return None
    try:
        return str(load_yaml(lock_path).get("sha") or "") or None
    except (OSError, ValueError):
        return None


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
        _log(f"error: {exc}")
        return EXIT_ERROR
    except subprocess.CalledProcessError as exc:
        stderr = exc.stderr.decode() if isinstance(exc.stderr, bytes) else (exc.stderr or "")
        _log(f"error: git failed: {stderr.strip() or exc}")
        return EXIT_ERROR
    except RuntimeError as exc:
        _log(f"error: {exc}")
        return EXIT_ERROR


if __name__ == "__main__":
    raise SystemExit(main())
