#!/usr/bin/env python3
"""Finish an `init --lib` skeleton into a rhiza-shaped one — behind `/rhiza:skeleton`.

Three languages, one remit: close the gap between what the language's own initialiser
writes and what a rhiza-managed repo needs, so `/rhiza:update`'s synced gates have
something to pass. Running `uv init --lib` / `cargo init --lib` / `go mod init` is the
caller's job — this only finishes the result, and reports what's missing when there is
nothing to finish.

**This module is the dispatcher and the CLI, nothing else.** Each language's gap is
different in kind rather than in degree, so each has its own module and this one only
picks between them:

  `_skeleton_python`    uv's placeholder `hello()`, the empty README, and the four
                        `[project]` keys the template's pyproject gate requires
  `_skeleton_rust`      the `[package]` metadata crates.io wants, plus the doc comments
                        `-D missing_docs` denies — cargo's stub is added to, never replaced
  `_skeleton_go`        a `README.md` and a `doc.go`; `go.mod` holds no metadata to fill in
  `_skeleton_version`   `[tool.bumpversion]`, so `/rhiza:release` never guesses a version
  `_skeleton_common`    the README stub and git identity all three need
  `_rhiza_toml`         the shared "add a key, reformat nothing" TOML primitives, which
                        `set_license` and `set_python_version` use as well

Every edit is idempotent and additive: real code and hand-written metadata are never
overwritten, and each placeholder is only rewritten while it still *is* the initialiser's
placeholder. Stdlib-only, so `/skeleton` can run it with no install step.

Usage:
  uv run --python 3.12 --no-project python \
      scripts/init_skeleton.py [TARGET] --owner OWNER --repo NAME \
      [--host github|gitlab] [--language python|rust|go] [--description TEXT] [--json]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _skeleton_common as common  # noqa: E402
from _skeleton_go import finish_go  # noqa: E402
from _skeleton_python import finish_python  # noqa: E402
from _skeleton_rust import finish_rust  # noqa: E402
from _skeleton_version import note_bumpversion  # noqa: E402


def finish_skeleton(
    target: Path,
    *,
    owner: str,
    repo: str,
    host: str,
    description: str | None,
    language: str = "python",
) -> dict[str, Any]:
    """Finish the `uv init` / `cargo init` / `go mod init` skeleton; return a summary.

    The version location is declared last for every language, and only when the manifest
    work succeeded — it anchors to the version that manifest declares.
    """
    modified: list[str] = []
    notes: list[str] = []

    if language == "go":
        # Go takes no owner or host: `go.mod` has no field either one could fill.
        result = finish_go(
            target, repo=repo, description=description, modified=modified, notes=notes
        )
    else:
        finish = finish_rust if language == "rust" else finish_python
        result = finish(
            target,
            owner=owner,
            repo=repo,
            domain=common.host_domain(host),
            description=description,
            modified=modified,
            notes=notes,
        )

    note_bumpversion(target, language, result)
    return result


def main(argv: list[str] | None = None) -> int:
    """Entry point: parse args, finish the skeleton, return an exit code."""
    parser = argparse.ArgumentParser(
        description="Finish a `uv init` / `cargo init` skeleton into a rhiza-shaped one.",
    )
    parser.add_argument(
        "target", nargs="?", default=".", help="Repository root (default: current directory)."
    )
    parser.add_argument("--owner", required=True, help="GitHub/GitLab owner or org.")
    parser.add_argument("--repo", required=True, help="Repository name (for the project URLs).")
    parser.add_argument(
        "--host", choices=("github", "gitlab"), default="github", help="Git hosting platform."
    )
    parser.add_argument(
        "--language",
        choices=("python", "rust", "go"),
        default="python",
        help="Which skeleton to finish: uv's pyproject.toml, cargo's Cargo.toml, "
        "or go mod init's go.mod.",
    )
    parser.add_argument("--description", help="Project description (replaces uv's placeholder).")
    parser.add_argument(
        "--json", dest="json_output", action="store_true", help="Emit the summary as JSON."
    )
    args = parser.parse_args(argv)

    summary = finish_skeleton(
        Path(args.target).resolve(),
        owner=args.owner,
        repo=args.repo,
        host=args.host,
        description=args.description,
        language=args.language,
    )

    if args.json_output:
        print(json.dumps(summary, indent=2))
    else:
        for path in summary["modified"]:
            print(f"modified {path}")
        for note in summary["notes"]:
            print(f"note     {note}", file=sys.stderr)
    return 0 if summary["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
