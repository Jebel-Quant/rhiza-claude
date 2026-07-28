#!/usr/bin/env python3
"""Render a repo's README badge block — the engine behind `/rhiza:docs`.

Badges are *generated*, not hand-authored: every URL follows from facts about the
repo (platform, owner/repo, default branch, language, license, CI workflow, coverage
service). Keeping the templates here rather than in prose means the set is
deterministic, ordered, and testable — and that the **omit, don't fake** rule is
enforced by code: a badge whose backing fact is absent is never emitted, so a README
never advertises a workflow, license, or coverage service that isn't there.

Detection is the caller's job (it has the repo in front of it); this script takes the
facts as flags and renders the block. Pass `--json` for the badge list plus the
reasons anything was skipped, so the command can report them.

Usage:
  uv run --python 3.12 --no-project python \
      scripts/render_badges.py --owner OWNER --repo REPO \
      [--host github|gitlab] [--branch main] [--license MIT] \
      [--python-versions 3.12,3.13] [--ci-workflow rhiza_ci.yml] \
      [--template-ref v1.1.3] [--coverage codecov|gitlab] \
      [--uses-ruff] [--uses-uv] [--public] [--codespaces] [--json]
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

_SHIELDS = "https://img.shields.io"


def _md(label: str, image: str, link: str) -> str:
    """Render one markdown badge (an image wrapped in a link)."""
    return f"[![{label}]({image})]({link})"


def release_badge(host: str, owner: str, repo: str) -> str:
    """The repo's own latest-release badge."""
    if host == "gitlab":
        return _md(
            "Release",
            f"{_SHIELDS}/gitlab/v/release/{owner}%2F{repo}",
            f"https://gitlab.com/{owner}/{repo}/-/releases",
        )
    return _md(
        "Release",
        f"{_SHIELDS}/github/v/release/{owner}/{repo}?sort=semver",
        f"https://github.com/{owner}/{repo}/releases",
    )


def build_badges(
    *,
    host: str,
    owner: str,
    repo: str,
    branch: str,
    license_id: str | None,
    python_versions: list[str],
    ci_workflow: str | None,
    template_ref: str | None,
    coverage: str | None,
    uses_ruff: bool,
    uses_uv: bool,
    public: bool,
    codespaces: bool,
) -> dict[str, Any]:
    """Build the ordered badge list plus the reasons any standard badge was skipped."""
    gitlab = host == "gitlab"
    slug = f"{owner}/{repo}"
    badges: list[str] = [release_badge(host, owner, repo)]
    skipped: list[str] = []

    if template_ref:
        badges.append(
            _md(
                f"rhiza {template_ref}",
                f"{_SHIELDS}/badge/rhiza-{template_ref}-blue",
                f"https://github.com/jebel-quant/rhiza/releases/tag/{template_ref}",
            )
        )
    else:
        skipped.append("template version: no ref in .rhiza/template.yml")

    if license_id:
        badges.append(
            _md(
                f"License: {license_id}",
                f"{_SHIELDS}/badge/License-{license_id}-green.svg",
                "LICENSE",
            )
        )
    else:
        skipped.append("license: no LICENSE file detected")

    if python_versions:
        joined = " • ".join(python_versions)
        badges.append(
            _md(
                "Python versions",
                f"{_SHIELDS}/badge/Python-{joined}-blue?logo=python",
                "https://www.python.org/",
            )
        )
    else:
        skipped.append("python versions: not a Python project")

    if gitlab:
        badges.append(
            _md(
                "pipeline",
                f"https://gitlab.com/{slug}/badges/{branch}/pipeline.svg",
                f"https://gitlab.com/{slug}/-/pipelines",
            )
        )
    elif ci_workflow:
        base = f"https://github.com/{slug}/actions/workflows/{ci_workflow}"
        badges.append(_md("CI", f"{base}/badge.svg?event=push", base))
    else:
        skipped.append("CI: no workflow file found in .github/workflows")

    if coverage == "codecov":
        badges.append(
            _md(
                "codecov",
                f"https://codecov.io/gh/{slug}/branch/{branch}/graph/badge.svg",
                f"https://codecov.io/gh/{slug}",
            )
        )
    elif coverage == "gitlab":
        badges.append(
            _md(
                "coverage",
                f"https://gitlab.com/{slug}/badges/{branch}/coverage.svg",
                f"https://gitlab.com/{slug}/-/commits/{branch}",
            )
        )
    else:
        skipped.append("coverage: no coverage service detected")

    if uses_ruff:
        badges.append(
            _md(
                "Code style: ruff",
                f"{_SHIELDS}/badge/code%20style-ruff-000000.svg?logo=ruff",
                "https://github.com/astral-sh/ruff",
            )
        )
    if uses_uv:
        badges.append(
            _md(
                "uv",
                f"{_SHIELDS}/endpoint?url=https://raw.githubusercontent.com/"
                "astral-sh/uv/main/assets/badge/v0.json",
                "https://github.com/astral-sh/uv",
            )
        )

    # GitHub-only services.
    if gitlab:
        skipped.append("CodeFactor, OpenSSF Scorecard, Codespaces: GitHub-only")
    else:
        badges.append(
            _md(
                "CodeFactor",
                f"https://www.codefactor.io/repository/github/{slug}/badge",
                f"https://www.codefactor.io/repository/github/{slug}",
            )
        )
        if public:
            badges.append(
                _md(
                    "OpenSSF Scorecard",
                    f"https://api.scorecard.dev/projects/github.com/{slug}/badge",
                    f"https://scorecard.dev/viewer/?uri=github.com/{slug}",
                )
            )
        else:
            skipped.append("OpenSSF Scorecard: only meaningful for a public repo")
        if codespaces:
            badges.append(
                _md(
                    "Open in GitHub Codespaces",
                    "https://github.com/codespaces/badge.svg",
                    f"https://codespaces.new/{slug}",
                )
            )

    return {"badges": badges, "skipped": skipped, "block": render_block(badges)}


def render_block(badges: list[str]) -> str:
    """Render the badge block: the release badge alone, then the rest together."""
    if not badges:
        return ""
    head, *rest = badges
    if not rest:
        return head + "\n"
    return head + "\n" + "\n".join(rest) + "\n"


def _split_csv(raw: str | None) -> list[str]:
    """Split a comma-separated flag value into a clean list."""
    return [part.strip() for part in (raw or "").split(",") if part.strip()]


def main(argv: list[str] | None = None) -> int:
    """Entry point: render the badge block and return an exit code."""
    parser = argparse.ArgumentParser(description="Render a README badge block.")
    parser.add_argument("--owner", required=True, help="Repository owner / namespace.")
    parser.add_argument("--repo", required=True, help="Repository name.")
    parser.add_argument(
        "--host", choices=("github", "gitlab"), default="github", help="Hosting platform."
    )
    parser.add_argument("--branch", default="main", help="Default branch (default: main).")
    parser.add_argument("--license", dest="license_id", help="SPDX id; omit if unlicensed.")
    parser.add_argument("--python-versions", help="Comma-separated, e.g. 3.12,3.13.")
    parser.add_argument("--ci-workflow", help="CI workflow filename, e.g. rhiza_ci.yml.")
    parser.add_argument("--template-ref", help="Template ref from .rhiza/template.yml.")
    parser.add_argument(
        "--coverage", choices=("codecov", "gitlab"), help="Detected coverage service."
    )
    parser.add_argument("--uses-ruff", action="store_true", help="Repo lints with ruff.")
    parser.add_argument("--uses-uv", action="store_true", help="Repo uses uv.")
    parser.add_argument("--public", action="store_true", help="Repo is public.")
    parser.add_argument("--codespaces", action="store_true", help="Offer a Codespaces badge.")
    parser.add_argument(
        "--json", dest="json_output", action="store_true", help="Emit the summary as JSON."
    )
    args = parser.parse_args(argv)

    summary = build_badges(
        host=args.host,
        owner=args.owner,
        repo=args.repo,
        branch=args.branch,
        license_id=args.license_id,
        python_versions=_split_csv(args.python_versions),
        ci_workflow=args.ci_workflow,
        template_ref=args.template_ref,
        coverage=args.coverage,
        uses_ruff=args.uses_ruff,
        uses_uv=args.uses_uv,
        public=args.public,
        codespaces=args.codespaces,
    )

    if args.json_output:
        print(json.dumps(summary, indent=2))
    else:
        print(summary["block"], end="")
        for reason in summary["skipped"]:
            print(f"omitted  {reason}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
