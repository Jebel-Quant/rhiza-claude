#!/usr/bin/env python3
"""Finish a `uv init --lib` skeleton into a rhiza-shaped one — behind `/rhiza:skeleton`.

`uv init --lib` gets a Python project 90% of the way there: `pyproject.toml`,
`src/<pkg>/__init__.py`, `README.md`, `.python-version`. This script closes the
gap between that and what a rhiza-managed repo needs, so `/rhiza:update`'s synced
gates have something to pass:

  src/<pkg>/__init__.py   replace uv's undocumented `hello()` placeholder with a
                          package docstring (interrogate + coverage both fail on it)
  README.md               uv creates it **empty**, and the template's
                          test_readme_validation.py asserts it is non-empty
  [project].description   fill in uv's "Add your description here" placeholder
  [project.urls]          Homepage + Repository — the template's .rhiza/tests/
                          test_pyproject.py requires both
  [dependency-groups]     `test` (incl. pytest) and `lint` groups — likewise required

It writes **no** ``classifiers`` — not a ``License ::`` trove classifier (PEP 639
replaced it with the SPDX ``license`` field, and `/rhiza:license` owns that), and
not the ``Programming Language :: Python :: X.Y`` entries either (`/rhiza:python-version`
owns those). This script never touches the ``classifiers`` key.

Every edit is idempotent and additive: real code and hand-written metadata are
never overwritten. The placeholder `__init__.py` is only rewritten while it still
*is* uv's placeholder. Stdlib-only, so `/skeleton` can run it without the `rhiza`
CLI. Running `uv init --lib` itself is the caller's job — this script only finishes
the result, and reports what's missing when there's nothing to finish.

Usage:
  uv run --python 3.12 --no-project python \
      scripts/init_skeleton.py [TARGET] --owner OWNER --repo NAME \
      [--host github|gitlab] [--description TEXT] [--json]
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

_HOSTS = {"github": "github.com", "gitlab": "gitlab.com"}

# uv seeds this into `[project].description`; it is not a real description.
_UV_DESCRIPTION_PLACEHOLDER = "Add your description here"

# Dependency groups the template's pyproject gate requires, with lower bounds.
_DEPENDENCY_GROUPS: dict[str, list[str]] = {
    "test": ["pytest>=8.0", "pytest-cov>=5.0"],
    "lint": ["ruff>=0.6"],
}


def _project_block(lines: list[str]) -> tuple[int, int]:
    """Return ``(header_idx, end_idx)`` bounding the ``[project]`` table body."""
    header = next((i for i, line in enumerate(lines) if line.strip() == "[project]"), None)
    if header is None:
        raise ValueError("pyproject.toml has no [project] table")
    end = len(lines)
    for i in range(header + 1, len(lines)):
        if lines[i].lstrip().startswith("["):
            end = i
            break
    return header, end


def is_uv_placeholder_init(text: str) -> bool:
    """Is *text* still `uv init --lib`'s untouched `hello()` placeholder?

    Conservative by design: anything the user has added (an import, a second
    function, a docstring of their own) makes this False, so real code is never
    rewritten.
    """
    body = [line for line in text.splitlines() if line.strip()]
    return bool(body) and all(
        re.match(r'^def hello\(\) -> str:$|^\s+return "Hello from .*!"$', line) for line in body
    )


def normalize_package_init(target: Path) -> list[str]:
    """Rewrite any placeholder `src/<pkg>/__init__.py` to a package docstring.

    Returns the relative paths modified (empty when there's nothing to normalise).
    """
    modified: list[str] = []
    src = target / "src"
    if not src.is_dir():
        return modified
    for init in sorted(src.glob("*/__init__.py")):
        if is_uv_placeholder_init(init.read_text()):
            init.write_text(f'"""{init.parent.name} package."""\n')
            modified.append(str(init.relative_to(target)))
    return modified


def seed_readme(target: Path, *, repo: str, description: str | None) -> bool:
    """Give an empty `README.md` a title and description; return whether it was written.

    `uv init --lib` creates `README.md` **empty** — zero bytes. The template's
    `.rhiza/tests/test_readme_validation.py` asserts ``len(content) > 0``, so a repo
    built by the documented `/init` chain failed `make rhiza-test` before it had done
    anything wrong. Closing that gap is exactly this script's remit.

    Only an empty (or whitespace-only) file is written. `/rhiza:docs` owns the real
    README and must never find its work overwritten — this is a stub to clear the gate,
    not a document. Nothing is created if `README.md` is absent, since its absence is a
    different failure the template reports separately.
    """
    readme = target / "README.md"
    if not readme.is_file() or readme.read_text().strip():
        return False
    body = f"# {repo}\n"
    if description:
        body += f"\n{description}\n"
    # No fenced code blocks: the same template test executes any it finds.
    body += "\nRun `/rhiza:docs` to write this properly.\n"
    readme.write_text(body)
    return True


def set_description(text: str, description: str) -> tuple[str, bool]:
    """Set ``[project].description``, replacing uv's placeholder or inserting it.

    A description the user has already written is left alone. Returns
    ``(new_text, changed)``.
    """
    lines = text.splitlines()
    header, end = _project_block(lines)
    pattern = re.compile(r"^\s*description\s*=\s*(.*)$")
    new_line = f'description = "{description}"'
    for i in range(header + 1, end):
        match = pattern.match(lines[i])
        if not match:
            continue
        if _UV_DESCRIPTION_PLACEHOLDER not in match.group(1):
            return text, False  # a real description — hands off
        lines[i] = new_line
        break
    else:
        lines.insert(header + 1, new_line)
    new_text = "\n".join(lines)
    if text.endswith("\n"):
        new_text += "\n"
    return new_text, True


def _table_span(lines: list[str], name: str) -> tuple[int, int] | None:
    """Return ``(header_idx, end_idx)`` of a top-level ``[name]`` table, or None."""
    header = next((i for i, line in enumerate(lines) if line.strip() == f"[{name}]"), None)
    if header is None:
        return None
    end = len(lines)
    for i in range(header + 1, len(lines)):
        if lines[i].lstrip().startswith("["):
            end = i
            break
    return header, end


def _append_table(lines: list[str], header: str, body: list[str]) -> None:
    """Append a ``[header]`` table with *body* lines to the end of the document."""
    while lines and not lines[-1].strip():
        lines.pop()
    lines.extend(["", header, *body])


def set_project_urls(text: str, homepage: str, repository: str) -> tuple[str, bool]:
    """Ensure ``[project.urls]`` declares Homepage and Repository.

    Existing entries win — only missing keys are added. Returns
    ``(new_text, changed)``.
    """
    lines = text.splitlines()
    wanted = {"Homepage": homepage, "Repository": repository}
    span = _table_span(lines, "project.urls")
    if span is None:
        _append_table(lines, "[project.urls]", [f'{k} = "{v}"' for k, v in wanted.items()])
        changed = True
    else:
        header, end = span
        present = {
            match.group(1)
            for line in lines[header + 1 : end]
            if (match := re.match(r"^\s*([A-Za-z-]+)\s*=", line))
        }
        missing = [f'{k} = "{v}"' for k, v in wanted.items() if k not in present]
        lines[end:end] = missing
        changed = bool(missing)
    new_text = "\n".join(lines)
    if text.endswith("\n"):
        new_text += "\n"
    return new_text, changed


def set_dependency_groups(text: str) -> tuple[str, bool]:
    """Ensure ``[dependency-groups]`` declares the required ``test`` and ``lint`` groups.

    Existing groups are left exactly as they are — this only adds absent ones, each
    with lower-bounded requirements. Returns ``(new_text, changed)``.
    """
    lines = text.splitlines()
    span = _table_span(lines, "dependency-groups")
    if span is None:
        body = [f"{name} = {json.dumps(deps)}" for name, deps in _DEPENDENCY_GROUPS.items()]
        _append_table(lines, "[dependency-groups]", body)
        changed = True
    else:
        header, end = span
        present = {
            match.group(1)
            for line in lines[header + 1 : end]
            if (match := re.match(r"^\s*([A-Za-z0-9_-]+)\s*=", line))
        }
        missing = [
            f"{name} = {json.dumps(deps)}"
            for name, deps in _DEPENDENCY_GROUPS.items()
            if name not in present
        ]
        lines[end:end] = missing
        changed = bool(missing)
    new_text = "\n".join(lines)
    if text.endswith("\n"):
        new_text += "\n"
    return new_text, changed


def finish_skeleton(
    target: Path,
    *,
    owner: str,
    repo: str,
    host: str,
    description: str | None,
) -> dict[str, Any]:
    """Finish the `uv init --lib` skeleton at *target*; return a summary dict."""
    modified: list[str] = []
    notes: list[str] = []
    changes: list[str] = []

    modified.extend(normalize_package_init(target))
    if modified:
        notes.append("normalised uv's placeholder hello() to a package docstring")

    if seed_readme(target, repo=repo, description=description):
        modified.append("README.md")
        notes.append("seeded the empty README.md uv left behind — /rhiza:docs owns the real one")

    pyproject = target / "pyproject.toml"
    if not pyproject.exists():
        notes.append("pyproject.toml absent — run `uv init --lib` first")
        return {"modified": modified, "changes": changes, "notes": notes, "ok": False}

    host_domain = _HOSTS.get(host, _HOSTS["github"])
    text = original = pyproject.read_text()
    try:
        if description:
            text, changed = set_description(text, description)
            if changed:
                changes.append("description")
        text, changed = set_project_urls(
            text,
            homepage=f"https://{host_domain}/{owner}/{repo}",
            repository=f"https://{host_domain}/{owner}/{repo}",
        )
        if changed:
            changes.append("project.urls")
        text, changed = set_dependency_groups(text)
        if changed:
            changes.append("dependency-groups")
    except ValueError as exc:
        notes.append(f"pyproject.toml: {exc}")
        return {"modified": modified, "changes": changes, "notes": notes, "ok": False}

    if text != original:
        pyproject.write_text(text)
        modified.append("pyproject.toml")
        notes.append("pyproject.toml: " + ", ".join(changes))
    else:
        notes.append("pyproject.toml already rhiza-shaped")

    if not re.search(r"^\s*authors\s*=", original, re.MULTILINE):
        notes.append("[project].authors is absent — the template's pyproject gate wants one")
    notes.append("license + classifiers are /rhiza:license and /rhiza:python-version's job")

    return {"modified": modified, "changes": changes, "notes": notes, "ok": True}


def main(argv: list[str] | None = None) -> int:
    """Entry point: parse args, finish the skeleton, return an exit code."""
    parser = argparse.ArgumentParser(
        description="Finish a `uv init --lib` skeleton into a rhiza-shaped one.",
    )
    parser.add_argument(
        "target", nargs="?", default=".", help="Repository root (default: current directory)."
    )
    parser.add_argument("--owner", required=True, help="GitHub/GitLab owner or org.")
    parser.add_argument("--repo", required=True, help="Repository name (for the project URLs).")
    parser.add_argument(
        "--host", choices=("github", "gitlab"), default="github", help="Git hosting platform."
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
