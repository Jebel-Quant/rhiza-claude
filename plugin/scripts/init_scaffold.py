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
      [--host github|gitlab] [--template-host github|gitlab] \
      [--language python|go|rust] \
      [--template-repo owner/repo] [--ref TAG] [--json]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

# All three languages share `jebel-quant/rhiza`: the template is multi-language, with a
# per-language toolchain bundle (`python-core` / `rust-core` / `go-core`) layered on a
# neutral `core`. There is no per-language template repository; an `owner/repo` override
# is for a fork of this one.
DEFAULT_TEMPLATE_REPO = {
    "python": "jebel-quant/rhiza",
    "go": "jebel-quant/rhiza",
    "rust": "jebel-quant/rhiza",
}

# Which profile a (language, host) pair resolves to. Python's names are unprefixed
# for backwards compatibility — renaming them would break the pointer of every repo
# already synced.
#
# Rust and Go map both hosts to their `-local` profile, because that is the only profile
# the template defines for either. Hosted-CI profiles are made almost entirely of
# workflows, and the template's `github`/`gitlab` bundles still ship Python ones (a
# release job running `uv build` against PyPI, Dependabot declaring the `uv` ecosystem),
# so they land together with each language's workflows. Writing a pointer at a
# `rust-github-project` that does not exist would fail the first sync with
# "Profile 'rust-github-project' was not found"; a Rust or Go repo gets working local
# tooling now and gains CI when it exists.
#
# `scripts/check_template_profile.py` is what keeps this table honest — `/rhiza:init`
# checks the profile against the ref it is about to pin, because every wrong entry here
# has cost a user their first `/rhiza:update` rather than failing at `/init`.
_PROFILES: dict[str, dict[str, str]] = {
    "python": {"github": "github-project", "gitlab": "gitlab-project"},
    "go": {"github": "go-local", "gitlab": "go-local"},
    "rust": {"github": "rust-local", "gitlab": "rust-local"},
}


def profile_for_host(host: str, language: str = "python") -> str:
    """Return the sync profile matching the git hosting platform and language."""
    platform = "gitlab" if host == "gitlab" else "github"
    return _PROFILES.get(language, _PROFILES["python"])[platform]


def render_template_yml(
    repo: str, ref: str, host: str, language: str, template_host: str | None = None
) -> str:
    """Render `.rhiza/template.yml` (mirrors template.yml.jinja2).

    Two independent facts, which must not be conflated:

    * *host* — where **this repo** lives. It selects the ``profiles:`` entry, so a
      GitLab repo gets ``gitlab-project`` and its CI, not GitHub's.
    * *template_host* — where the **template** lives. It becomes ``template-host:``,
      which `sync.py` turns into the clone URL.

    They are usually different: a GitLab-hosted project following ``jebel-quant/rhiza``
    is on GitLab, but the template is on GitHub. Deriving one from the other emitted
    ``template-host: gitlab`` for every GitLab repo, so the first sync tried to clone
    the template from gitlab.com and died with "could not read Username". Default
    *template_host* to GitHub — where the rhiza templates are — not to *host*.
    """
    lines = [f'repository: "{repo}"', f'ref: "{ref}"']
    if (template_host or "github") == "gitlab":
        lines.append("template-host: gitlab")
    if language != "python":
        lines.append(f"language: {language}")
    lines += ["", "profiles:", f"  - {profile_for_host(host, language)}", ""]
    return "\n".join(lines)


def scaffold(
    target: Path,
    *,
    host: str,
    language: str,
    template_repo: str,
    ref: str,
    template_host: str | None = None,
) -> dict[str, Any]:
    """Write `.rhiza/template.yml` if absent; return a summary dict."""
    path = target / ".rhiza" / "template.yml"
    created: list[str] = []
    skipped: list[str] = []

    if path.exists():
        skipped.append(".rhiza/template.yml")
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(render_template_yml(template_repo, ref, host, language, template_host))
        created.append(".rhiza/template.yml")

    return {
        "target": str(target),
        "language": language,
        "template_repository": template_repo,
        "ref": ref,
        "profile": profile_for_host(host, language),
        "template_host": template_host or "github",
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
        "--host",
        choices=("github", "gitlab"),
        default="github",
        help="Where THIS repo lives; selects the profile (and its CI).",
    )
    parser.add_argument(
        "--template-host",
        choices=("github", "gitlab"),
        default="github",
        help="Where the TEMPLATE lives; sets the clone URL. Usually github, even for "
        "a GitLab-hosted repo, because the rhiza templates are on GitHub.",
    )
    parser.add_argument(
        "--language",
        choices=tuple(DEFAULT_TEMPLATE_REPO),
        default="python",
        help="Project language; selects the default template repo and the profile prefix.",
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
        template_host=args.template_host,
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
