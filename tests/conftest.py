"""Shared test fixtures for the rhiza-config plugin scripts.

The scripts under `scripts/` are standalone (run as `python3 scripts/<x>.py`),
not an installed package, so put that directory on `sys.path` to import them.
"""

from __future__ import annotations

import subprocess
import sys
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))


@pytest.fixture
def git_repo(tmp_path: Path) -> Path:
    """A minimal git repo skeleton: a `.git` dir and a `pyproject.toml`."""
    (tmp_path / ".git").mkdir()
    (tmp_path / "pyproject.toml").write_text("[project]\nname='x'\n")
    (tmp_path / "src").mkdir()
    (tmp_path / "tests").mkdir()
    return tmp_path


def write_template(repo: Path, body: str) -> Path:
    """Write `.rhiza/template.yml` under `repo` and return its path."""
    rhiza = repo / ".rhiza"
    rhiza.mkdir(exist_ok=True)
    tmpl = rhiza / "template.yml"
    tmpl.write_text(body)
    return tmpl


# ---------------------------------------------------------------------------
# Real-git fixtures for the sync port (test_sync*.py)
# ---------------------------------------------------------------------------

_HERMETIC_ENV = {
    "GIT_CONFIG_GLOBAL": "/dev/null",
    "GIT_CONFIG_SYSTEM": "/dev/null",
    "GIT_TERMINAL_PROMPT": "0",
    "GIT_AUTHOR_NAME": "Test",
    "GIT_AUTHOR_EMAIL": "test@example.com",
    "GIT_COMMITTER_NAME": "Test",
    "GIT_COMMITTER_EMAIL": "test@example.com",
    "GIT_AUTHOR_DATE": "2026-01-01T00:00:00 +0000",
    "GIT_COMMITTER_DATE": "2026-01-01T00:00:00 +0000",
}


@pytest.fixture
def hermetic_git(monkeypatch: pytest.MonkeyPatch) -> None:
    """Set a hermetic git environment (no user/global config, fixed identity)."""
    for key, value in _HERMETIC_ENV.items():
        monkeypatch.setenv(key, value)


class Repo:
    """A tiny helper around a real git working tree used to build sync scenarios."""

    def __init__(self, path: Path) -> None:
        """Wrap the working tree rooted at *path*."""
        self.path = path

    def git(self, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
        """Run a git command in this repo, returning the completed process."""
        return subprocess.run(  # noqa: S603
            ["git", *args], cwd=str(self.path), check=check, capture_output=True, text=True
        )

    def write(self, rel: str, content: str) -> Path:
        """Write *content* to *rel* (creating parents) and return the path."""
        target = self.path / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)
        return target

    def read(self, rel: str) -> str:
        """Return the text of *rel*."""
        return (self.path / rel).read_text()

    def exists(self, rel: str) -> bool:
        """Return whether *rel* exists in the working tree."""
        return (self.path / rel).exists()

    def commit(self, message: str = "commit") -> str:
        """Stage everything and commit; return the new HEAD SHA."""
        self.git("add", "-A")
        self.git("commit", "-q", "--no-gpg-sign", "-m", message)
        return self.git("rev-parse", "HEAD").stdout.strip()


@pytest.fixture
def make_repo(tmp_path: Path, hermetic_git: None) -> Iterator[Callable[[str], Repo]]:
    """Return a factory that creates initialised git repos under the temp dir."""
    counter = {"n": 0}

    def _make(name: str = "repo") -> Repo:
        counter["n"] += 1
        path = tmp_path / f"{name}{counter['n']}"
        path.mkdir()
        repo = Repo(path)
        repo.git("init", "-q", "-b", "main", ".")
        return repo

    yield _make
