#!/usr/bin/env python3
"""Show the current rhiza sync status from `.rhiza/template.lock`.

A stdlib-only port of the `rhiza status` command, bundled with this plugin so
`/rhiza:status` works without the `rhiza` CLI (or PyYAML) installed. It reads
the authoritative lock written by the last sync and reports the template
repository, ref, SHA, sync timestamp, strategy, and included templates/paths.

Usage:
  python3 scripts/status.py [TARGET] [--json]

  TARGET   repository root to inspect (default: current directory)
  --json   emit a single JSON object on stdout instead of human-readable lines

When no lock is present the repo has never been synced; this prints a hint to
stderr and exits 0 (nothing to report is not an error). The `--json` payload
mirrors `rhiza status --json` field-for-field, so tools like stats.py can read
either interchangeably.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

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


def status(target: Path, *, json_output: bool = False) -> int:
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
    return 0


def main(argv: list[str] | None = None) -> int:
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
    args = parser.parse_args(argv)
    return status(Path(args.target), json_output=args.json_output)


if __name__ == "__main__":
    raise SystemExit(main())
