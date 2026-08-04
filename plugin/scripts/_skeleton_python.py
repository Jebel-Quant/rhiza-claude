#!/usr/bin/env python3
"""Finish what `uv init --lib` leaves out of a Python package.

`uv init --lib` gets a project 90% of the way there: `pyproject.toml`,
`src/<pkg>/__init__.py`, `README.md`, `.python-version`. This module closes the gap
between that and what a rhiza-managed repo needs, so `/rhiza:update`'s synced gates have
something to pass:

  src/<pkg>/__init__.py   replace uv's undocumented `hello()` placeholder with a
                          package docstring (interrogate + coverage both fail on it)
  README.md               uv creates it **empty**, and the template's
                          test_readme_validation.py asserts it is non-empty
  [project].authors       uv omits it entirely when git has no configured identity,
                          and the template's pyproject gate requires a named author
  [project].description   fill in uv's "Add your description here" placeholder
  [project.urls]          Homepage + Repository — the template's .rhiza/tests/
                          test_pyproject.py requires both
  [dependency-groups]     a `test` group (incl. pytest) — likewise required

It writes **no** ``classifiers`` — not a ``License ::`` trove classifier (PEP 639
replaced it with the SPDX ``license`` field, and `/rhiza:license` owns that), and not the
``Programming Language :: Python :: X.Y`` entries either (`/rhiza:python-version` owns
those). Nothing here touches the ``classifiers`` key.

The version location — `[tool.bumpversion]` — is `_skeleton_version`'s, since the same
question has a different answer in each language.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _skeleton_common as common  # noqa: E402
from _rhiza_toml import merge_table, set_key  # noqa: E402

_PYPROJECT = "pyproject.toml"

# uv seeds this into `[project].description`; it is not a real description.
_UV_DESCRIPTION_PLACEHOLDER = "Add your description here"

# Dependency groups the template's pyproject gate requires, with lower bounds. `lint`
# was here until the gate dropped its required-group check (rhiza #1484): the template
# provisions every linter through prek/uvx, so nothing ever resolved that group.
_DEPENDENCY_GROUPS: dict[str, list[str]] = {
    "test": ["pytest>=8.0", "pytest-cov>=5.0"],
}


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


def set_description(text: str, description: str) -> tuple[str, bool]:
    """Set ``[project].description``, replacing uv's placeholder or inserting it.

    A description the user has already written is left alone. Returns
    ``(new_text, changed)``.
    """
    return set_key(
        text,
        "project",
        "description",
        json.dumps(description),
        filename=_PYPROJECT,
        replaceable=lambda value: _UV_DESCRIPTION_PLACEHOLDER in value,
    )


def set_authors(text: str, *, name: str, email: str | None) -> tuple[str, bool]:
    """Ensure ``[project].authors`` names at least one author; return ``(text, changed)``.

    `uv init --lib` omits the key entirely when git has no configured identity, and an
    author already written by hand is never touched. Two of the template's
    `.rhiza/tests/test_pyproject.py` assertions depend on this — the key existing, and
    its first entry having a non-empty ``name``.
    """
    entry = f'{{ name = "{name}"' + (f', email = "{email}"' if email else "") + " }"
    return set_key(
        text,
        "project",
        "authors",
        f"[{entry}]",
        filename=_PYPROJECT,
        # An empty inline list is uv's placeholder; anything else — including the `[` that
        # opens uv's own multi-line array — is the user's.
        replaceable=lambda value: re.fullmatch(r"\[\s*\]", value.strip()) is not None,
    )


def set_project_urls(text: str, homepage: str, repository: str) -> tuple[str, bool]:
    """Ensure ``[project.urls]`` declares Homepage and Repository.

    Existing entries win — only missing keys are added. Returns ``(new_text, changed)``.
    """
    new_text, added = merge_table(
        text,
        "project.urls",
        {"Homepage": json.dumps(homepage), "Repository": json.dumps(repository)},
        filename=_PYPROJECT,
    )
    return new_text, bool(added)


def set_dependency_groups(text: str) -> tuple[str, bool]:
    """Ensure ``[dependency-groups]`` declares the required ``test`` group.

    Existing groups are left exactly as they are — this only adds absent ones, each
    with lower-bounded requirements. Returns ``(new_text, changed)``.
    """
    new_text, added = merge_table(
        text,
        "dependency-groups",
        {name: json.dumps(deps) for name, deps in _DEPENDENCY_GROUPS.items()},
        filename=_PYPROJECT,
    )
    return new_text, bool(added)


def apply_pyproject(
    text: str,
    changes: list[str],
    *,
    url: str,
    description: str | None,
    author_name: str,
    author_email: str | None,
) -> str:
    """Apply every `[project]` edit to *text*, recording each in *changes*.

    *changes* is appended to in place rather than returned, so that a
    :class:`ValueError` from a later edit still leaves the caller holding the keys the
    earlier ones wrote. Reporting "we changed nothing" after a partial edit would be a
    lie about the file on disk.
    """
    if description:
        text, changed = set_description(text, description)
        if changed:
            changes.append("description")
    text, changed = set_project_urls(text, url, url)
    if changed:
        changes.append("project.urls")
    text, changed = set_dependency_groups(text)
    if changed:
        changes.append("dependency-groups")
    text, changed = set_authors(text, name=author_name, email=author_email)
    if changed:
        changes.append("authors")
    return text


def finish_python(
    target: Path,
    *,
    owner: str,
    repo: str,
    domain: str,
    description: str | None,
    modified: list[str],
    notes: list[str],
) -> dict[str, Any]:
    """Finish a `uv init --lib` skeleton; return a summary dict."""
    modified.extend(normalize_package_init(target))
    if modified:
        notes.append("normalised uv's placeholder hello() to a package docstring")

    if common.seed_readme(target, repo=repo, description=description):
        modified.append("README.md")
        notes.append("seeded the empty README.md uv left behind — /rhiza:docs owns the real one")

    manifest = target / _PYPROJECT
    # `is_file`, not `exists`: a directory named pyproject.toml would pass the gate here
    # and then be read as an absent manifest by every helper downstream.
    if not manifest.is_file():
        notes.append("pyproject.toml absent — run `uv init --lib` first")
        return {"modified": modified, "changes": [], "notes": notes, "ok": False}

    changes: list[str] = []
    original = manifest.read_text()
    identity_name, identity_email = common.git_identity(target)
    try:
        text = apply_pyproject(
            original,
            changes,
            url=common.host_url(domain, owner, repo),
            description=description,
            # Falls back to the owner: the gate needs a non-empty name, and the owner is
            # the best fact available when the machine has no git identity at all.
            author_name=identity_name or owner,
            author_email=identity_email,
        )
    except ValueError as exc:
        notes.append(f"pyproject.toml: {exc}")
        return {"modified": modified, "changes": changes, "notes": notes, "ok": False}

    if text != original:
        manifest.write_text(text)
        modified.append(_PYPROJECT)
        notes.append("pyproject.toml: " + ", ".join(changes))
    else:
        notes.append("pyproject.toml already rhiza-shaped")

    notes.append("license + classifiers are /rhiza:license and /rhiza:python-version's job")
    return {"modified": modified, "changes": changes, "notes": notes, "ok": True}
