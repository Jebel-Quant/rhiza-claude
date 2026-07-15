#!/usr/bin/env python3
"""Scaffold a rhiza-managed project's non-synced, rhiza-only starter files.

Bundled with this plugin so `/rhiza:init` can wire up a repo without the `rhiza`
CLI. The project *skeleton* (`pyproject.toml`, `src/<pkg>/`, `README.md`) now
comes from `uv init --lib`, and `rhiza sync` delivers the shared infrastructure
(CI, `.rhiza/rhiza.mk`, `docs/mkdocs-base.yml`, `ruff.toml`, `pytest.ini`, …).
This script writes only the rhiza-specific files neither of those provides:

  .rhiza/template.yml   the sync config (repository/ref/profile)
  Makefile              a small repo-owned Makefile that includes .rhiza/rhiza.mk
                        once the first sync delivers it
  mkdocs.yml            (optional) INHERITs docs/mkdocs-base.yml (delivered by sync)

Every file is created **only if absent** — existing files are left untouched.

Usage:
  python3 scripts/init_scaffold.py [TARGET] --project-name NAME --owner OWNER \
      [--host github|gitlab] [--language python|go] \
      [--template-repo owner/repo] [--ref TAG] \
      [--components mkdocs] [--json]

`.rhiza/template.yml` and `Makefile` are always written; `--components` selects
from the optional set {mkdocs} (Python only). Go projects get `template.yml` +
`Makefile` and a `go mod init` hint.
"""

from __future__ import annotations

import argparse
import json
import keyword
import re
import sys
from pathlib import Path
from typing import Any

DEFAULT_TEMPLATE_REPO = {"python": "jebel-quant/rhiza", "go": "jebel-quant/rhiza-go"}
OPTIONAL_COMPONENTS = ("mkdocs",)
DEFAULT_DESCRIPTION = "Add your description here."

_HOSTS = {
    "github": ("github.com", "github.io"),
    "gitlab": ("gitlab.com", "gitlab.io"),
}

# --- string templates -------------------------------------------------------

_MKDOCS = """\
INHERIT: docs/mkdocs-base.yml

site_name: __PROJECT_NAME__
site_description: __DESCRIPTION__
site_url: https://__OWNER__.__PAGES_HOST__/__PROJECT_NAME__/
repo_url: https://__REPO_HOST__/__OWNER__/__PROJECT_NAME__
repo_name: __OWNER__/__PROJECT_NAME__
edit_uri: edit/main/

docs_dir: docs

nav:
  - Home: index.md
  - Reports:
      - Test Report: reports/html-report/report.html
      - Coverage Report: reports/html-coverage/index.html
"""

# A small repo-owned Makefile. Before the first sync there is no `.rhiza/rhiza.mk`
# yet, so `sync` prints guidance instead of shelling out to the (retired) `rhiza`
# CLI — the first sync is performed by `/rhiza:init` (bundled scripts/sync.py),
# and afterwards the template's own `.rhiza/rhiza.mk` provides the real targets.
_MAKEFILE = """\
## Makefile (repo-owned)
# Keep this file small. It can be edited without breaking template sync.

# Before the first sync there is no .rhiza/rhiza.mk yet.
ifeq ($(wildcard .rhiza/rhiza.mk),)
.PHONY: sync
sync: ## Not rhiza-managed yet
\t@echo "Not synced yet — run /rhiza:init (first sync) or /rhiza:update."
\t@exit 1
endif

# Include the Rhiza API — delivered by the first template sync.
-include .rhiza/rhiza.mk

# Optional: developer-local extensions (not committed)
-include local.mk
"""


def normalize_package_name(name: str) -> str:
    """Normalise a string into a valid Python package identifier."""
    name = re.sub(r"[^a-zA-Z0-9_]", "_", name)
    if name and name[0].isdigit():
        name = f"_{name}"
    if keyword.iskeyword(name):
        name = f"{name}_"
    return name


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


def _fill(template: str, **subs: str) -> str:
    """Replace __TOKEN__ placeholders in a template body."""
    out = template
    for key, value in subs.items():
        out = out.replace(f"__{key}__", value)
    return out


def render_mkdocs(
    project_name: str, owner: str, repo_host: str, pages_host: str, description: str
) -> str:
    """Render mkdocs.yml for the given project."""
    return _fill(
        _MKDOCS,
        PROJECT_NAME=project_name,
        OWNER=owner,
        REPO_HOST=repo_host,
        PAGES_HOST=pages_host,
        DESCRIPTION=description,
    )


def _write_if_absent(
    path: Path, content: str, created: list[str], skipped: list[str], target: Path
) -> None:
    """Write *content* to *path* only when it does not already exist."""
    rel = str(path.relative_to(target)) if path.is_relative_to(target) else str(path)
    if path.exists():
        skipped.append(rel)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    created.append(rel)


def scaffold(
    target: Path,
    *,
    project_name: str,
    package_name: str,
    owner: str,
    host: str,
    language: str,
    template_repo: str,
    ref: str,
    components: list[str],
    description: str = DEFAULT_DESCRIPTION,
) -> dict[str, Any]:
    """Write the rhiza-only starter files; return a summary dict."""
    repo_host, pages_host = _HOSTS.get(host, _HOSTS["github"])
    created: list[str] = []
    skipped: list[str] = []
    notes: list[str] = []

    # Always: template.yml + repo-owned Makefile.
    _write_if_absent(
        target / ".rhiza" / "template.yml",
        render_template_yml(template_repo, ref, host, language),
        created,
        skipped,
        target,
    )
    _write_if_absent(target / "Makefile", _MAKEFILE, created, skipped, target)

    if language == "go":
        # The Go module is the user's to create; leave a hint.
        notes.append(
            f"go: run `go mod init {repo_host}/{owner}/{project_name}` to start the module"
        )

    # Optional mkdocs.yml (Python only; Go docs are out of scope here).
    if "mkdocs" in set(components) and language == "python":
        _write_if_absent(
            target / "mkdocs.yml",
            render_mkdocs(project_name, owner, repo_host, pages_host, description),
            created,
            skipped,
            target,
        )

    return {
        "target": str(target),
        "project_name": project_name,
        "package_name": package_name,
        "language": language,
        "template_repository": template_repo,
        "ref": ref,
        "profile": profile_for_host(host),
        "created": created,
        "skipped": skipped,
        "notes": notes,
    }


def _parse_components(raw: str | None, language: str) -> list[str]:
    """Resolve the --components value to a validated list."""
    if raw is None:
        return list(OPTIONAL_COMPONENTS)
    items = [c.strip() for c in raw.split(",") if c.strip()]
    unknown = [c for c in items if c not in OPTIONAL_COMPONENTS]
    if unknown:
        choices = ", ".join(OPTIONAL_COMPONENTS)
        raise ValueError(f"unknown component(s): {', '.join(unknown)}; choose from {choices}")
    return items


def main(argv: list[str] | None = None) -> int:
    """Entry point: parse args, scaffold, and return an exit code."""
    parser = argparse.ArgumentParser(
        description="Scaffold a rhiza-managed project's rhiza-only starter files.",
    )
    parser.add_argument(
        "target", nargs="?", default=".", help="Repository root (default: current directory)."
    )
    parser.add_argument("--project-name", help="Project name (default: target directory name).")
    parser.add_argument(
        "--package-name", help="Python package name (default: normalized project name)."
    )
    parser.add_argument(
        "--owner", default="your-org", help="GitHub/GitLab owner or org (default: your-org)."
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
        "--description", default=DEFAULT_DESCRIPTION, help="Short project description."
    )
    parser.add_argument(
        "--components",
        help=f"Comma list from {{{', '.join(OPTIONAL_COMPONENTS)}}}; default: all applicable.",
    )
    parser.add_argument(
        "--json", dest="json_output", action="store_true", help="Emit the summary as JSON."
    )
    args = parser.parse_args(argv)

    target = Path(args.target).resolve()
    project_name = args.project_name or target.name
    package_name = args.package_name or normalize_package_name(project_name)
    template_repo = args.template_repo or DEFAULT_TEMPLATE_REPO[args.language]
    try:
        components = _parse_components(args.components, args.language)
    except ValueError as exc:
        parser.error(str(exc))

    summary = scaffold(
        target,
        project_name=project_name,
        package_name=package_name,
        owner=args.owner,
        host=args.host,
        language=args.language,
        template_repo=template_repo,
        ref=args.ref,
        components=components,
        description=args.description,
    )

    if args.json_output:
        print(json.dumps(summary, indent=2))
    else:
        for path in summary["created"]:
            print(f"created  {path}")
        for path in summary["skipped"]:
            print(f"skipped  {path} (already exists)", file=sys.stderr)
        for note in summary["notes"]:
            print(f"note     {note}", file=sys.stderr)
        if not summary["created"]:
            print("nothing to create — all target files already exist", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
