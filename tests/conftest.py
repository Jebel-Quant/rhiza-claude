"""Shared test fixtures for the rhiza-config plugin scripts.

The scripts under `scripts/` are standalone (run as `python3 scripts/<x>.py`),
not an installed package, so put that directory on `sys.path` to import them.
"""

from __future__ import annotations

import sys
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
