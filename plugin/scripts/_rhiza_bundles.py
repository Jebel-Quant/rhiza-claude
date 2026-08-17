"""Resolve profiles and bundles to the file paths a sync should copy.

The largest single job in the sync and the one with no I/O at all: `profiles` expand to
bundle names, bundle names expand to `(source, dest)` file entries, and the result is an
ordered, de-duplicated path list plus a remap table.

It also owns the path-safety check. `template-bundles.yml` comes from the template repo,
so a `dest` is untrusted input that gets joined onto the target directory — an absolute
path, a drive letter or a `..` component would write outside the project.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _rhiza_common import SyncError, has_drive_letter  # noqa: E402
from _rhiza_template import Template  # noqa: E402
from _rhiza_yaml import as_list  # noqa: E402


def _ensure_safe_bundle_path(value: str) -> None:
    r"""Reject a bundle path that could escape the project directory.

    ``template-bundles.yml`` is untrusted (fetched from the template repo) and a
    remapped ``dest`` is joined onto the target directory, so an absolute path, a
    Windows drive letter, or a ``..`` component could write outside the project.

    The three rejected shapes, against the ordinary relative paths that must keep
    working — and note the fourth line, where a Windows separator is normalised *before*
    the check, so a backslash cannot smuggle a traversal past it:

    >>> for value in ("Makefile", ".github/workflows/ci.yml", "/etc/passwd",
    ...               "..\\secrets.env", "C:/Windows/system32"):
    ...     try:
    ...         _ensure_safe_bundle_path(value)
    ...         print(f"accepted  {value}")
    ...     except SyncError:
    ...         print(f"rejected  {value}")
    accepted  Makefile
    accepted  .github/workflows/ci.yml
    rejected  /etc/passwd
    rejected  ..\secrets.env
    rejected  C:/Windows/system32

    Raises:
        SyncError: If *value* is absolute, uses a drive letter, or traverses up.
    """
    normalized = value.replace("\\", "/")
    pure = PurePosixPath(normalized)
    if pure.is_absolute() or has_drive_letter(normalized) or ".." in pure.parts:
        raise SyncError(
            f"Unsafe bundle path {value!r}: paths must be relative to the project root "
            "(no absolute paths, drive letters, or '..' traversal)."
        )


def _bundle_file_entries(raw_files: Any) -> list[tuple[str, str]]:
    """Coerce a bundle's ``files`` field into validated ``(source, dest)`` pairs."""
    entries: list[tuple[str, str]] = []
    for entry in as_list(raw_files) if isinstance(raw_files, str) else (raw_files or []):
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
            requires[name] = as_list(data.get("requires"))
            files[name] = _bundle_file_entries(data.get("files"))
        profiles = {
            name: as_list((data or {}).get("bundles")) for name, data in raw_profiles.items()
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


def resolve_bundle_names(template: Template, bundles: Bundles) -> list[str]:
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
