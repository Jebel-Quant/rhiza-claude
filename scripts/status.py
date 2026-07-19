#!/usr/bin/env python3
"""Show the current rhiza sync status from `.rhiza/template.lock`.

A stdlib-only port of the `rhiza status` command, bundled with this plugin so
`/rhiza:status` works without the `rhiza` CLI (or PyYAML) installed. It reads
the authoritative lock written by the last sync and reports the template
repository, ref, SHA, sync timestamp, strategy, and included templates/paths.
With `--files` it also renders the managed files as a directory tree — the view
that used to live in the separate `/rhiza:tree` command.

Usage:
  uv run --python 3.12 --no-project python scripts/status.py [TARGET] [--json] [--files] [--check]

  TARGET    repository root to inspect (default: current directory)
  --json    emit a single JSON object on stdout instead of human-readable lines
  --files   append the managed files as a `tree`-style listing (human output)
  --check   compare the pinned ref to the latest upstream release (needs network)

When no lock is present the repo has never been synced; this prints a hint to
stderr and exits 0 (nothing to report is not an error). The `--json` payload
mirrors `rhiza status --json` field-for-field (including `files`), so tools like
stats.py can read either interchangeably. Where the CLI uses `rich` for the file
tree, this renders plain ASCII connectors so it stays dependency-free.

Everything is offline and deterministic except `--check`, which shells out to
`git ls-remote --tags` (no `gh`, no auth for public repos) to see whether a newer
release exists; a network or git failure there is reported, never fatal.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

_SEMVER_RE = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)$")

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _rhiza_yaml import load_yaml  # noqa: E402

LOCK_REL = Path(".rhiza") / "template.lock"


def _as_list(value: Any) -> list[str]:
    """Normalise a scalar/None/list lock field to a list of strings."""
    if value is None:
        return []
    if isinstance(value, list):
        return [str(x) for x in value]
    return [str(value)]


def _status_dict(lock: dict[str, Any]) -> dict[str, Any]:
    """Build the machine-readable status payload from a parsed lock.

    Mirrors the field set emitted by `rhiza status --json`.
    """
    host = str(lock.get("host", "github"))
    repo = str(lock.get("repo", ""))
    return {
        "repository": f"{host}/{repo}" if repo else host,
        "host": host,
        "repo": repo,
        "ref": str(lock.get("ref", "main")),
        "sha": str(lock.get("sha", "")),
        "synced_at": str(lock.get("synced_at", "")),
        "strategy": str(lock.get("strategy", "")),
        "templates": _as_list(lock.get("templates")),
        "include": _as_list(lock.get("include")),
        "files": _as_list(lock.get("files")),
    }


def _build_tree(paths: list[str]) -> dict[str, Any]:
    """Fold a flat path list into a nested {name: subtree} dict."""
    root: dict[str, Any] = {}
    for path in sorted(paths):
        node = root
        for part in Path(path).parts:
            node = node.setdefault(part, {})
    return root


def _render(node: dict[str, Any], prefix: str = "") -> list[str]:
    """Render a nested tree dict into Unix-`tree`-style lines."""
    lines: list[str] = []
    items = sorted(node.items())
    for i, (name, child) in enumerate(items):
        last = i == len(items) - 1
        lines.append(f"{prefix}{'└── ' if last else '├── '}{name}")
        if child:
            lines.extend(_render(child, prefix + ("    " if last else "│   ")))
    return lines


def _print_file_tree(files: list[str]) -> None:
    """Print the managed files as a `tree`-style listing plus a total count."""
    if not files:
        print("No files are tracked in template.lock", file=sys.stderr)
        return
    print("\nFiles managed by Rhiza:")
    print(".")
    for line in _render(_build_tree(files)):
        print(line)
    print(f"\n{len(files)} file{'s' if len(files) != 1 else ''} managed by Rhiza")


def _parse_semver(tag: str) -> tuple[int, int, int] | None:
    """Parse a `vX.Y.Z` tag into a (major, minor, patch) tuple, or None."""
    m = _SEMVER_RE.match(tag)
    return (int(m.group(1)), int(m.group(2)), int(m.group(3))) if m else None


def _remote_url(host: str, repo: str) -> str:
    """Build an HTTPS clone URL for the given host alias and owner/repo slug."""
    base = "gitlab.com" if "gitlab" in host else "github.com"
    return f"https://{base}/{repo}"


def _remote_tags(host: str, repo: str) -> list[str]:
    """Return the remote's tag names via `git ls-remote --tags`, or [] on failure."""
    try:
        proc = subprocess.run(  # nosec B603 B607
            ["git", "ls-remote", "--tags", _remote_url(host, repo)],
            capture_output=True,
            text=True,
            check=True,
            timeout=20,
        )
    except (OSError, subprocess.SubprocessError):
        return []
    tags: set[str] = set()
    for line in proc.stdout.splitlines():
        _, _, name = line.partition("refs/tags/")
        if name:
            tags.add(name.removesuffix("^{}"))
    return sorted(tags)


def _outdated_message(ref: str, tags: list[str]) -> str:
    """Compose a one-line 'update available?' summary for *ref* against *tags*."""
    releases = [(t, v) for t in tags if (v := _parse_semver(t)) is not None]
    if not releases:
        return "Update     : could not determine the latest release"
    latest_tag, latest_ver = max(releases, key=lambda tv: tv[1])
    current = _parse_semver(ref)
    if current is None:
        return (
            f"Update     : latest release is {latest_tag} "
            f"(current ref '{ref}' is not a release tag) — run /update"
        )
    behind = sum(1 for _, v in releases if v > current)
    if behind == 0:
        return f"Update     : up to date ({latest_tag} is the latest release)"
    plural = "s" if behind != 1 else ""
    return f"Update     : {ref} → {latest_tag} ({behind} release{plural} behind) — run /update"


def _print_outdated(payload: dict[str, Any]) -> None:
    """Print the outdated-check line for a status payload (network via git)."""
    if not payload["repo"]:
        print("Update     : no template repository recorded in the lock")
        return
    tags = _remote_tags(payload["host"], payload["repo"])
    print(_outdated_message(payload["ref"], tags))


def status(
    target: Path,
    *,
    json_output: bool = False,
    show_files: bool = False,
    check: bool = False,
) -> int:
    """Print the sync status; return a process exit code."""
    lock_path = (target / LOCK_REL).resolve()
    if not lock_path.exists():
        print("No template.lock found — run `rhiza sync` first", file=sys.stderr)
        return 0

    try:
        lock = load_yaml(lock_path)
    except (OSError, ValueError) as exc:
        print(f"Could not read {lock_path}: {exc}", file=sys.stderr)
        return 1

    payload = _status_dict(lock)
    if json_output:
        print(json.dumps(payload, indent=2))
        return 0

    print(f"Repository : {payload['repository']}")
    print(f"Ref        : {payload['ref']}")
    sha = payload["sha"]
    print(f"SHA        : {sha[:12]}" if sha else "SHA        : (unknown)")
    print(f"Synced at  : {payload['synced_at'] or '(unknown)'}")
    print(f"Strategy   : {payload['strategy'] or '(unknown)'}")
    if payload["templates"]:
        print(f"Templates  : {', '.join(payload['templates'])}")
    elif payload["include"]:
        print(f"Include    : {', '.join(payload['include'])}")
    if check:
        _print_outdated(payload)
    if show_files:
        _print_file_tree(payload["files"])
    return 0


def main(argv: list[str] | None = None) -> int:
    """Entry point: print status; return an exit code."""
    parser = argparse.ArgumentParser(
        description="Show the current rhiza sync status from .rhiza/template.lock.",
    )
    parser.add_argument(
        "target",
        nargs="?",
        default=".",
        help="Repository root to inspect (default: current directory).",
    )
    parser.add_argument(
        "--json",
        dest="json_output",
        action="store_true",
        help="Emit the status as a single JSON object on stdout.",
    )
    parser.add_argument(
        "--files",
        "--tree",
        dest="show_files",
        action="store_true",
        help="Append the managed files as a tree-style listing (human output).",
    )
    parser.add_argument(
        "--check",
        dest="check",
        action="store_true",
        help="Compare the pinned ref to the latest upstream release (needs network).",
    )
    args = parser.parse_args(argv)
    return status(
        Path(args.target),
        json_output=args.json_output,
        show_files=args.show_files,
        check=args.check,
    )


if __name__ == "__main__":
    raise SystemExit(main())
