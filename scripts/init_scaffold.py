#!/usr/bin/env python3
"""Write a rhiza-managed repo's one non-synced file: `.rhiza/template.yml`.

Bundled with this plugin so `/rhiza:init` can point a repo at a template without
the `rhiza` CLI. That pointer is the only file `/init` writes itself — everything
else is another step's job:

  project skeleton      the skeleton procedure (scripts/init_skeleton.py)
  Makefile, CI, docs    the template sync, via `/rhiza:update`
  license               the license procedure (scripts/set_license.py)
  Python version        the python-version procedure (scripts/set_python_version.py)
  README / mkdocs.yml   `/rhiza:docs`
  first module + test   the user's own

The file is created **only if absent** — an existing `template.yml` is left
untouched (bumping one is `/rhiza:update`'s job).

Usage:
  uv run --python 3.12 --no-project python \
      scripts/init_scaffold.py [TARGET] \
      [--host github|gitlab] [--language python|go] \
      [--template-repo owner/repo] [--ref TAG] [--json]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

DEFAULT_TEMPLATE_REPO = {"python": "jebel-quant/rhiza", "go": "jebel-quant/rhiza-go"}


def profile_for_host(host: str) -> str:
    """Return the sync profile matching the git hosting platform."""
    return "gitlab-project" if host == "gitlab" else "github-project"


def render_template_yml(repo: str, ref: str, host: str, language: str) -> str:
    """Render `.rhiza/template.yml` (mirrors template.yml.jinja2)."""
    lines = [f'repository: "{repo}"', f'ref: "{ref}"']
    if host == "gitlab":
        lines.append("template-host: gitlab")
    if language != "python":
        lines.append(f"language: {language}")
    lines += ["", "profiles:", f"  - {profile_for_host(host)}", ""]
    return "\n".join(lines)


def scaffold(
    target: Path,
    *,
    host: str,
    language: str,
    template_repo: str,
    ref: str,
) -> dict[str, Any]:
    """Write `.rhiza/template.yml` if absent; return a summary dict."""
    path = target / ".rhiza" / "template.yml"
    created: list[str] = []
    skipped: list[str] = []

    if path.exists():
        skipped.append(".rhiza/template.yml")
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(render_template_yml(template_repo, ref, host, language))
        created.append(".rhiza/template.yml")

    return {
        "target": str(target),
        "language": language,
        "template_repository": template_repo,
        "ref": ref,
        "profile": profile_for_host(host),
        "created": created,
        "skipped": skipped,
    }


def main(argv: list[str] | None = None) -> int:
    """Entry point: parse args, write the pointer, and return an exit code."""
    parser = argparse.ArgumentParser(
        description="Write a rhiza-managed repo's .rhiza/template.yml pointer.",
    )
    parser.add_argument(
        "target", nargs="?", default=".", help="Repository root (default: current directory)."
    )
    parser.add_argument(
        "--host", choices=("github", "gitlab"), default="github", help="Git hosting platform."
    )
    parser.add_argument(
        "--language", choices=("python", "go"), default="python", help="Project language."
    )
    parser.add_argument(
        "--template-repo", help="Template repository owner/repo (default: by language)."
    )
    parser.add_argument("--ref", default="main", help="Template branch/tag (default: main).")
    parser.add_argument(
        "--json", dest="json_output", action="store_true", help="Emit the summary as JSON."
    )
    args = parser.parse_args(argv)

    summary = scaffold(
        Path(args.target).resolve(),
        host=args.host,
        language=args.language,
        template_repo=args.template_repo or DEFAULT_TEMPLATE_REPO[args.language],
        ref=args.ref,
    )

    if args.json_output:
        print(json.dumps(summary, indent=2))
    else:
        for path in summary["created"]:
            print(f"created  {path}")
        for path in summary["skipped"]:
            print(f"skipped  {path} (already exists)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
