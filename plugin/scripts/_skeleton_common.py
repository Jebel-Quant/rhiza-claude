#!/usr/bin/env python3
"""The two things all three skeleton finishers need: a README stub and a git identity.

Small on purpose. What lives here is what genuinely does not vary by language — `uv`,
`cargo` and `go mod` differ on almost everything about a manifest, but a repo needs a
non-empty `README.md` either way, and the author metadata comes from the same
`git config` in all three cases.

`host_url` is here for the same reason: the owner/repo URL goes into `[project.urls]`,
into `[package].repository`, and nowhere at all on the Go side, so the mapping from
`--host` to a domain belongs to none of them individually.
"""

from __future__ import annotations

import shutil
import subprocess  # nosec B404
from pathlib import Path

HOSTS = {"github": "github.com", "gitlab": "gitlab.com"}


def host_domain(host: str) -> str:
    """Return the domain for *host*, falling back to GitHub's for an unknown name."""
    return HOSTS.get(host, HOSTS["github"])


def host_url(domain: str, owner: str, repo: str) -> str:
    """Return the canonical project URL for *owner*/*repo* on *domain*."""
    return f"https://{domain}/{owner}/{repo}"


def seed_readme(target: Path, *, repo: str, description: str | None, create: bool = False) -> bool:
    """Give an empty `README.md` a title and description; return whether it was written.

    `uv init --lib` creates `README.md` **empty** — zero bytes. The template's
    `.rhiza/tests/test_readme_validation.py` asserts ``len(content) > 0``, so a repo
    built by the documented `/init` chain failed `make rhiza-test` before it had done
    anything wrong. Closing that gap is exactly the skeleton's remit.

    Only an empty (or whitespace-only) file is written. `/rhiza:docs` owns the real
    README and must never find its work overwritten — this is a stub to clear the gate,
    not a document. Nothing is created if `README.md` is absent, since for uv its
    absence is a different failure the template reports separately — pass *create* for
    an initialiser that writes no README at all (`cargo init`, `go mod init`), where the
    file being missing is the normal case rather than a signal.
    """
    readme = target / "README.md"
    if readme.is_file():
        if readme.read_text().strip():
            return False
    elif not create:
        return False
    body = f"# {repo}\n"
    if description:
        body += f"\n{description}\n"
    # No fenced code blocks: the same template test executes any it finds.
    body += "\nRun `/rhiza:docs` to write this properly.\n"
    readme.write_text(body)
    return True


def git_identity(target: Path) -> tuple[str | None, str | None]:
    """Return ``(name, email)`` from git config in *target*, or ``(None, None)``.

    This is where `uv init` gets the authors entry it writes — and when git has no
    identity configured it writes **no `authors` key at all**, which the template's
    pyproject gate requires. So the same source is consulted here to fill the gap.
    """
    git = shutil.which("git")
    if git is None:  # pragma: no cover - git is present everywhere this runs
        return None, None

    def read(key: str) -> str | None:
        """Return the value git config reports for *key*, or None when it is unset.

        `git config --get` exits **1** for a key that is simply unset, which is the
        commonest case here and not a failure — the empty stdout *is* the answer. Any
        other non-zero exit (no repo, unreadable config) also yields empty stdout, and
        "no identity available" is the same outcome for all of them.
        """
        # rc-ignored: `git config --get` exits 1 on an unset key; empty stdout is the answer.
        result = subprocess.run(  # nosec B603
            [git, "config", "--get", key], cwd=str(target), capture_output=True, text=True,
            check=False,
        )  # fmt: skip
        value = result.stdout.strip()
        return value or None

    return read("user.name"), read("user.email")


def author_entry(owner: str, name: str | None, email: str | None) -> str:
    """Render a single ``Name <email>`` author string for a Cargo `authors` array.

    Falls back to *owner* when git reports no name: the gate needs a non-empty author,
    and the repo owner is the best fact available on a machine with no git identity.
    """
    author = name or owner
    return f"{author} <{email}>" if email else author
