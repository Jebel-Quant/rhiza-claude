"""End-to-end retirement sign-off for `/rhiza:init`'s scaffolder.

Proves that a freshly-scaffolded repo — `scripts/init_scaffold.py` → a real
`rhiza sync` → the template's own gates — comes up **green**, which is the bar
for retiring `rhiza init`:

  * `make rhiza-test` runs the template's shipped contracts
    (`.rhiza/tests/test_pyproject.py`, `test_readme_validation.py`,
    `test_docstrings.py`) against our scaffold;
  * `make test` runs the scaffolded `tests/test_main.py` under the coverage gate.

This is **slow and needs the network** (`uvx rhiza sync` fetches the template,
`uv` builds a venv), so it is opt-in and skipped by default. Run it with:

    RHIZA_E2E=1 uvx pytest tests/test_init_e2e.py -v

It also skips automatically when `git`, `make`, `uv`, or `uvx` are missing.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

# The template ref to sync. Pinned for determinism; bump when validating a newer
# rhiza release (any release whose bundled tests the scaffold must still pass).
TEMPLATE_REF = "v1.1.3"

SCAFFOLD = Path(__file__).resolve().parents[1] / "scripts" / "init_scaffold.py"

_REQUIRED_TOOLS = ("git", "make", "uv", "uvx")

pytestmark = [
    pytest.mark.skipif(
        os.environ.get("RHIZA_E2E") != "1",
        reason="slow/network end-to-end; set RHIZA_E2E=1 to run",
    ),
    *[
        pytest.mark.skipif(shutil.which(tool) is None, reason=f"{tool} not available")
        for tool in _REQUIRED_TOOLS
    ],
]


def _run(cmd: list[str], cwd: Path, timeout: int = 600) -> subprocess.CompletedProcess:
    """Run a command, returning the completed process (stdout+stderr captured)."""
    return subprocess.run(
        cmd,
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def _git(cwd: Path, *args: str) -> None:
    """Run a git command, raising on failure."""
    result = _run(["git", *args], cwd)
    assert result.returncode == 0, f"git {' '.join(args)} failed:\n{result.stderr}"


def _assert_ok(result: subprocess.CompletedProcess, label: str) -> None:
    """Assert a command exited 0, surfacing its output on failure."""
    assert result.returncode == 0, f"{label} failed:\n{result.stdout}\n{result.stderr}"


def test_init_scaffold_survives_sync_and_gates(tmp_path: Path) -> None:
    """A scaffolded repo passes the template gates after a real sync."""
    repo = tmp_path / "e2e-init"
    repo.mkdir()

    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", "e2e@example.com")
    _git(repo, "config", "user.name", "E2E Test")

    # 1. Scaffold via the bundled script (the same call commands/init.md makes).
    scaffold = _run(
        [
            "python3",
            str(SCAFFOLD),
            str(repo),
            "--project-name",
            "e2e-init",
            "--owner",
            "jebel-quant",
            "--host",
            "github",
            "--language",
            "python",
            "--template-repo",
            "jebel-quant/rhiza",
            "--ref",
            TEMPLATE_REF,
            "--components",
            "package,mkdocs,readme",
        ],
        repo,
    )
    assert scaffold.returncode == 0, f"scaffold failed:\n{scaffold.stderr}"
    for expected in ("pyproject.toml", "Makefile", "README.md", ".rhiza/template.yml"):
        assert (repo / expected).exists(), f"scaffolder did not create {expected}"

    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "chore: scaffold rhiza-managed project")

    # 2. First sync via the bootstrap Makefile (→ uvx rhiza sync .).
    sync = _run(["make", "sync"], repo)
    _assert_ok(sync, "make sync")
    assert (repo / ".rhiza" / "rhiza.mk").exists(), "sync did not deliver .rhiza/rhiza.mk"
    template_tests = repo / ".rhiza" / "tests" / "test_pyproject.py"
    assert template_tests.exists(), "sync did not deliver the template tests"

    # 3. The template's own contract tests must pass against our scaffold.
    rhiza_test = _run(["make", "rhiza-test"], repo)
    _assert_ok(rhiza_test, "make rhiza-test")
    assert "failed" not in rhiza_test.stdout.lower(), rhiza_test.stdout

    # 4. The scaffolded project's own tests must pass under the coverage gate.
    project_test = _run(["make", "test"], repo)
    _assert_ok(project_test, "make test")
    assert "passed" in project_test.stdout.lower(), project_test.stdout
