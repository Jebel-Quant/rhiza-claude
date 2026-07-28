"""Tests for the rhiza pointer writer (`scripts/init_scaffold.py`).

`/init` writes exactly one file itself, `.rhiza/template.yml`. The project skeleton
comes from `uv init --lib` (finished by the skeleton procedure), the
`Makefile`/CI/docs base from the template sync (`/update`), and the license, Python
version, and docs from the license, python-version, and `/rhiza:docs` steps.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import init_scaffold as scaf
import pytest

# --- profile helper ----------------------------------------------------------


def test_profile_for_host():
    assert scaf.profile_for_host("github") == "github-project"
    assert scaf.profile_for_host("gitlab") == "gitlab-project"


# --- template.yml -----------------------------------------------------------


def test_template_yml_github():
    out = scaf.render_template_yml("jebel-quant/rhiza", "v1.1.3", "github", "python")
    assert 'repository: "jebel-quant/rhiza"' in out
    assert 'ref: "v1.1.3"' in out
    assert "template-host" not in out  # github is the default, not emitted
    assert "language:" not in out  # python is the default, not emitted
    assert "  - github-project" in out


def test_template_yml_gitlab_and_go():
    out = scaf.render_template_yml("jebel-quant/rhiza-go", "v2.0.0", "gitlab", "go")
    assert "template-host: gitlab" in out
    assert "language: go" in out
    assert "  - gitlab-project" in out


# --- scaffold() end to end --------------------------------------------------


def test_scaffold_writes_only_the_pointer(tmp_path):
    summary = scaf.scaffold(
        tmp_path,
        host="github",
        language="python",
        template_repo="jebel-quant/rhiza",
        ref="v1.1.3",
    )
    assert summary["created"] == [".rhiza/template.yml"]
    # Everything else belongs to uv init / the sync / the focused commands.
    assert set(p.name for p in tmp_path.iterdir()) == {".rhiza"}
    assert (tmp_path / ".rhiza" / "template.yml").read_text().startswith("repository:")


def test_scaffold_skips_an_existing_pointer(tmp_path):
    (tmp_path / ".rhiza").mkdir()
    (tmp_path / ".rhiza" / "template.yml").write_text("hand-written\n")
    summary = scaf.scaffold(
        tmp_path,
        host="github",
        language="python",
        template_repo="jebel-quant/rhiza",
        ref="main",
    )
    assert summary["created"] == []
    assert summary["skipped"] == [".rhiza/template.yml"]
    assert (tmp_path / ".rhiza" / "template.yml").read_text() == "hand-written\n"  # untouched


def test_scaffold_go_defaults(tmp_path):
    summary = scaf.scaffold(
        tmp_path,
        host="github",
        language="go",
        template_repo="jebel-quant/rhiza-go",
        ref="main",
    )
    assert summary["created"] == [".rhiza/template.yml"]
    tpl = (tmp_path / ".rhiza" / "template.yml").read_text()
    assert "language: go" in tpl
    assert "jebel-quant/rhiza-go" in tpl


# --- main() / CLI -----------------------------------------------------------


def test_main_json_output(tmp_path, capsys):
    rc = scaf.main([str(tmp_path), "--json"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["template_repository"] == "jebel-quant/rhiza"
    assert payload["profile"] == "github-project"
    assert payload["ref"] == "main"
    assert payload["created"] == [".rhiza/template.yml"]


def test_main_language_selects_default_template_repo(tmp_path, capsys):
    rc = scaf.main([str(tmp_path), "--language", "go", "--json"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["template_repository"] == "jebel-quant/rhiza-go"


def test_main_text_output(tmp_path, capsys):
    rc = scaf.main([str(tmp_path)])
    assert rc == 0
    assert "created  .rhiza/template.yml" in capsys.readouterr().out


def test_main_text_output_skipped(tmp_path, capsys):
    (tmp_path / ".rhiza").mkdir()
    (tmp_path / ".rhiza" / "template.yml").write_text("x\n")
    rc = scaf.main([str(tmp_path)])
    assert rc == 0
    assert "skipped" in capsys.readouterr().err


# --- end-to-end: the /init pointer survives a real sync + the template gates --

# The template ref to sync. Pinned for determinism; bump when validating a newer
# rhiza release (any release whose bundled tests the scaffold must still pass).
TEMPLATE_REF = "v1.1.3"

_SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
SCAFFOLD = _SCRIPTS / "init_scaffold.py"
SKELETON = _SCRIPTS / "init_skeleton.py"
SYNC = _SCRIPTS / "sync.py"
SET_LICENSE = _SCRIPTS / "set_license.py"
SET_PYVER = _SCRIPTS / "set_python_version.py"
MAKE_TARGETS = _SCRIPTS / "check_make_targets.py"

# Invoke the bundled scripts the way the commands do — under a pinned modern
# interpreter via uv — so they never run under a stale system python3 (macOS
# ships 3.9, where sync.py's datetime.UTC would crash). uv is a guaranteed E2E
# dependency (see _E2E_MISSING below).
PY = ["uv", "run", "--python", "3.12", "--no-project", "python"]

_E2E_MISSING = [t for t in ("git", "make", "uv", "uvx") if shutil.which(t) is None]


def _run_cmd(cmd: list[str], cwd: Path, timeout: int = 600) -> subprocess.CompletedProcess:
    """Run a command, returning the completed process (stdout+stderr captured)."""
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout)


def _git(cwd: Path, *args: str) -> None:
    """Run a git command, raising on failure."""
    result = _run_cmd(["git", *args], cwd)
    assert result.returncode == 0, f"git {' '.join(args)} failed:\n{result.stderr}"


def _assert_ok(result: subprocess.CompletedProcess, label: str) -> None:
    """Assert a command exited 0, surfacing its output on failure."""
    assert result.returncode == 0, f"{label} failed:\n{result.stdout}\n{result.stderr}"


@pytest.mark.skipif(os.environ.get("RHIZA_E2E") != "1", reason="slow/network; set RHIZA_E2E=1")
@pytest.mark.skipif(bool(_E2E_MISSING), reason="git/make/uv/uvx not all available")
def test_pointer_survives_sync_and_gates(tmp_path: Path) -> None:
    """A repo built from the bundled scripts survives a real sync + the gates.

    Walks the whole path `/rhiza:init` drives — `uv init`, the skeleton finisher,
    the pointer, python-version, license — then `/update`'s sync, so the combination
    stays green against the real template.
    """
    repo = tmp_path / "e2e-init"
    repo.mkdir()

    # 1. Skeleton via uv init (the skeleton procedure's step 2).
    _assert_ok(
        _run_cmd(["uv", "init", "--lib", "--name", "e2e_init", "--python", "3.12"], repo),
        "uv init",
    )
    _git(repo, "config", "user.email", "e2e@example.com")
    _git(repo, "config", "user.name", "E2E Test")

    # 2. Finish it into a rhiza shape (the skeleton procedure's step 3): normalises
    #    uv's undocumented hello() placeholder and adds the [project] entries the
    #    template's pyproject gate asserts.
    _assert_ok(
        _run_cmd(
            [*PY, str(SKELETON), str(repo), "--owner", "jebel-quant", "--repo", "e2e-init",
             "--description", "End-to-end fixture for the rhiza plugin."],
            repo,
        ),
        "init_skeleton",
    )  # fmt: skip
    assert (repo / "src" / "e2e_init" / "__init__.py").read_text() == '"""e2e_init package."""\n'

    # 3. A module + its mirrored test — the user's first module, which `/init`
    #    deliberately does not scaffold. Kept trivial and fully covered so the
    #    template's coverage gate has something real to measure.
    (repo / "src" / "e2e_init" / "main.py").write_text(
        '"""Entry point for e2e_init."""\n\n\ndef greeting() -> str:\n'
        '    """Return the module\'s greeting."""\n    return "hello"\n'
    )
    (repo / "tests" / "e2e_init").mkdir(parents=True)
    (repo / "tests" / "e2e_init" / "test_main.py").write_text(
        '"""Tests for e2e_init.main."""\n\nfrom e2e_init.main import greeting\n\n\n'
        'def test_greeting() -> None:\n    """The greeting is returned."""\n'
        '    assert greeting() == "hello"\n'
    )

    # 4. The pointer — the one file /init writes itself (its step 5).
    scaffold = _run_cmd(
        [
            *PY, str(SCAFFOLD), str(repo),
            "--host", "github", "--language", "python",
            "--template-repo", "jebel-quant/rhiza", "--ref", TEMPLATE_REF,
        ],
        repo,
    )  # fmt: skip
    _assert_ok(scaffold, "scaffold")
    assert (repo / ".rhiza" / "template.yml").exists()
    assert not (repo / "Makefile").exists(), "/init must not write a Makefile"

    # 5. Packaging metadata: the python-version and license procedures.
    _assert_ok(
        _run_cmd([*PY, str(SET_PYVER), str(repo), "--python-version", "3.12"], repo),
        "set_python_version",
    )
    _assert_ok(
        _run_cmd(
            [*PY, str(SET_LICENSE), str(repo), "--license", "MIT", "--owner", "jebel-quant"],
            repo,
        ),
        "set_license",
    )
    assert (repo / "LICENSE").exists()
    pyproject_text = (repo / "pyproject.toml").read_text()
    assert 'license = "MIT"' in pyproject_text
    assert "Programming Language :: Python :: 3.12" in pyproject_text
    # The skeleton finisher's entries survive the metadata steps.
    assert "[project.urls]" in pyproject_text
    assert "[dependency-groups]" in pyproject_text

    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "chore: scaffold rhiza-managed project")

    # 6. First sync via the bundled stdlib porter — this is what delivers the
    #    Makefile, CI, and .rhiza/rhiza.mk.
    sync = _run_cmd([*PY, str(SYNC), "."], repo)
    _assert_ok(sync, "scripts/sync.py")
    assert (repo / ".rhiza" / "rhiza.mk").exists(), "sync did not deliver .rhiza/rhiza.mk"
    assert (repo / "Makefile").exists(), "sync did not deliver a Makefile"

    # 7. Every gate /quality names must exist in the synced repo.
    #
    #    This is the assertion that would have caught /quality being unrunnable: it
    #    named seven `make` targets and probed none of them. The target list is read
    #    out of commands/quality.md, so adding a gate to the prose without the template
    #    providing it fails here rather than in front of a user.
    probe = _run_cmd([*PY, str(MAKE_TARGETS), "--target-dir", str(repo), "--require"], repo)
    _assert_ok(probe, f"check_make_targets --require\n{probe.stdout}")

    # 8. The scaffolded project's own tests pass under the coverage gate.
    project_test = _run_cmd(["make", "test"], repo)
    _assert_ok(project_test, "make test")
