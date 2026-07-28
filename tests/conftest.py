"""Shared test fixtures for the rhiza-config plugin scripts.

The scripts under `scripts/` are standalone (run as
`uv run --python 3.12 --no-project python scripts/<x>.py`), not an installed
package, so put that directory on `sys.path` to import them.
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


# ---------------------------------------------------------------------------
# Fixture repos for the command-outcome tests (test_check_make_targets.py)
#
# The commands are prose a model executes, so their *outcomes* can only be tested
# against a realistic tree. These build the three states a rhiza command actually
# meets, which is what the contract tests can't reach: they verify a command refers
# to things that exist, not that running it does the right thing.
# ---------------------------------------------------------------------------

# A stand-in for the make API the template sync delivers as .rhiza/rhiza.mk. Only the
# target names matter for probing — the recipes are never run (`make -n`).
SYNCED_MAKEFILE = """\
.PHONY: fmt typecheck docs-coverage deptry security validate test help
help: ; @echo help
fmt: ; @echo fmt
typecheck: ; @echo typecheck
docs-coverage: ; @echo docs-coverage
deptry: ; @echo deptry
security: ; @echo security
validate: ; @echo validate
test: ; @echo test
"""

# A reduced profile: `core` only, so the tests-bundle gates are legitimately absent.
PARTIAL_MAKEFILE = """\
.PHONY: fmt deptry help
help: ; @echo help
fmt: ; @echo fmt
deptry: ; @echo deptry
"""


@pytest.fixture
def unmanaged_repo(tmp_path: Path) -> Path:
    """A repo that was never rhiza-managed: no `.rhiza/` at all.

    `/quality` and `/update` must refuse this rather than score or sync it.
    """
    (tmp_path / "src").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "x"\nversion = "0.1.0"\n')
    return tmp_path


@pytest.fixture
def managed_unsynced_repo(unmanaged_repo: Path) -> Path:
    """Rhiza-managed but never synced — the state `/init` deliberately leaves behind.

    There is a `template.yml` but no `rhiza.mk` and no makefile, so every gate is
    unavailable. Scoring this repo as broken was the bug the probe exists to prevent.
    """
    write_template(unmanaged_repo, 'repository: "jebel-quant/rhiza"\nref: "v1.1.3"\n')
    return unmanaged_repo


@pytest.fixture
def managed_synced_repo(managed_unsynced_repo: Path) -> Path:
    """Rhiza-managed *and* synced: the makefile and lock the sync delivers are present."""
    rhiza = managed_unsynced_repo / ".rhiza"
    (rhiza / "rhiza.mk").write_text(SYNCED_MAKEFILE)
    (rhiza / "template.lock").write_text(
        'sha: "abc123"\nstrategy: merge\nfiles:\n  - ruff.toml\n  - Makefile\n'
    )
    (managed_unsynced_repo / "Makefile").write_text("include .rhiza/rhiza.mk\n")
    (managed_unsynced_repo / "ruff.toml").write_text('target-version = "py311"\n')
    return managed_unsynced_repo


@pytest.fixture
def partial_profile_repo(managed_unsynced_repo: Path) -> Path:
    """A synced repo on a reduced profile, missing the tests-bundle gates."""
    (managed_unsynced_repo / ".rhiza" / "rhiza.mk").write_text(PARTIAL_MAKEFILE)
    (managed_unsynced_repo / "Makefile").write_text("include .rhiza/rhiza.mk\n")
    return managed_unsynced_repo


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
