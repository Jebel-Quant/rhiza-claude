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

# What one badge group contributes: the badges it emits, and the reasons it skipped
# any it couldn't back with a fact. Either list may be empty.
Section = tuple[list[str], list[str]]


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


def _template_section(template_ref: str | None) -> Section:
    """The rhiza template-version badge."""
    if not template_ref:
        return [], ["template version: no ref in .rhiza/template.yml"]
    return [
        _md(
            f"rhiza {template_ref}",
            f"{_SHIELDS}/badge/rhiza-{template_ref}-blue",
            f"https://github.com/jebel-quant/rhiza/releases/tag/{template_ref}",
        )
    ], []


def _license_section(license_id: str | None) -> Section:
    """The license badge, pointing at the repo's own LICENSE file."""
    if not license_id:
        return [], ["license: no LICENSE file detected"]
    return [
        _md(
            f"License: {license_id}",
            f"{_SHIELDS}/badge/License-{license_id}-green.svg",
            "LICENSE",
        )
    ], []


def _python_section(python_versions: list[str]) -> Section:
    """The supported-Python-versions badge."""
    if not python_versions:
        return [], ["python versions: not a Python project"]
    joined = " • ".join(python_versions)
    return [
        _md(
            "Python versions",
            f"{_SHIELDS}/badge/Python-{joined}-blue?logo=python",
            "https://www.python.org/",
        )
    ], []


def _ci_section(*, gitlab: bool, slug: str, branch: str, ci_workflow: str | None) -> Section:
    """The CI badge — a GitLab pipeline, or a named GitHub Actions workflow."""
    if gitlab:
        return [
            _md(
                "pipeline",
                f"https://gitlab.com/{slug}/badges/{branch}/pipeline.svg",
                f"https://gitlab.com/{slug}/-/pipelines",
            )
        ], []
    if not ci_workflow:
        return [], ["CI: no workflow file found in .github/workflows"]
    base = f"https://github.com/{slug}/actions/workflows/{ci_workflow}"
    return [_md("CI", f"{base}/badge.svg?event=push", base)], []


def _coverage_section(*, coverage: str | None, slug: str, branch: str) -> Section:
    """The coverage badge for whichever service was detected."""
    if coverage == "codecov":
        return [
            _md(
                "codecov",
                f"https://codecov.io/gh/{slug}/branch/{branch}/graph/badge.svg",
                f"https://codecov.io/gh/{slug}",
            )
        ], []
    if coverage == "gitlab":
        return [
            _md(
                "coverage",
                f"https://gitlab.com/{slug}/badges/{branch}/coverage.svg",
                f"https://gitlab.com/{slug}/-/commits/{branch}",
            )
        ], []
    return [], ["coverage: no coverage service detected"]


def _tooling_section(*, uses_ruff: bool, uses_uv: bool) -> Section:
    """Badges for the tooling the repo uses. Optional extras — nothing is ever skipped."""
    badges: list[str] = []
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
    return badges, []


def _github_services_section(*, gitlab: bool, slug: str, public: bool, codespaces: bool) -> Section:
    """Badges for the GitHub-only services — all of them omitted on GitLab."""
    if gitlab:
        return [], ["CodeFactor, OpenSSF Scorecard, Codespaces: GitHub-only"]

    badges = [
        _md(
            "CodeFactor",
            f"https://www.codefactor.io/repository/github/{slug}/badge",
            f"https://www.codefactor.io/repository/github/{slug}",
        )
    ]
    skipped: list[str] = []

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
    return badges, skipped


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
    """Build the ordered badge list plus the reasons any standard badge was skipped.

    Each section decides for itself whether its fact was detected, so the **omit,
    don't fake** rule lives next to the badge it governs; the order they appear in
    below is the order they appear in the README.
    """
    gitlab = host == "gitlab"
    slug = f"{owner}/{repo}"
    sections: list[Section] = [
        ([release_badge(host, owner, repo)], []),
        _template_section(template_ref),
        _license_section(license_id),
        _python_section(python_versions),
        _ci_section(gitlab=gitlab, slug=slug, branch=branch, ci_workflow=ci_workflow),
        _coverage_section(coverage=coverage, slug=slug, branch=branch),
        _tooling_section(uses_ruff=uses_ruff, uses_uv=uses_uv),
        _github_services_section(gitlab=gitlab, slug=slug, public=public, codespaces=codespaces),
    ]

    badges = [badge for section, _ in sections for badge in section]
    skipped = [reason for _, reasons in sections for reason in reasons]
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
