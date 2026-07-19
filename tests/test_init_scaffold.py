"""Tests for the rhiza-only scaffolding port (`scripts/init_scaffold.py`).

The project skeleton (`pyproject.toml`, `src/`, `README.md`) comes from
`uv init --lib`; this script writes only the rhiza-only files (`template.yml`, a
repo-owned `Makefile`, and optionally `mkdocs.yml`).
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import init_scaffold as scaf
import pytest

# --- naming / profile helpers -----------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("my-project", "my_project"),
        ("weird.name!", "weird_name_"),
        ("123start", "_123start"),
        ("class", "class_"),
        ("already_ok", "already_ok"),
    ],
)
def test_normalize_package_name(raw, expected):
    assert scaf.normalize_package_name(raw) == expected


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


# --- mkdocs.yml -------------------------------------------------------------


def test_render_mkdocs_is_host_aware():
    out = scaf.render_mkdocs("my-proj", "acme", "github.com", "github.io", "A thing.")
    assert out.startswith("INHERIT: docs/mkdocs-base.yml")
    assert "site_name: my-proj" in out
    assert "site_description: A thing." in out
    assert "https://acme.github.io/my-proj/" in out
    assert "repo_url: https://github.com/acme/my-proj" in out


# --- Makefile ---------------------------------------------------------------


def test_makefile_has_no_rhiza_cli_dependency():
    # The repo-owned Makefile must not shell out to the (retired) rhiza CLI.
    assert "uvx rhiza" not in scaf._MAKEFILE
    assert "rhiza sync" not in scaf._MAKEFILE
    assert "-include .rhiza/rhiza.mk" in scaf._MAKEFILE


# --- scaffold() end to end --------------------------------------------------


def test_scaffold_python_writes_rhiza_only_files(tmp_path):
    summary = scaf.scaffold(
        tmp_path,
        project_name="acme-tool",
        package_name="acme_tool",
        owner="acme",
        host="github",
        language="python",
        template_repo="jebel-quant/rhiza",
        ref="v1.1.3",
        components=["mkdocs"],
    )
    created = set(summary["created"])
    assert created == {".rhiza/template.yml", "Makefile", "mkdocs.yml"}
    # The skeleton is uv init's job — the scaffolder never writes it.
    assert not (tmp_path / "pyproject.toml").exists()
    assert not (tmp_path / "src").exists()
    assert not (tmp_path / "README.md").exists()
    assert (tmp_path / "Makefile").read_text().startswith("## Makefile (repo-owned)")


def test_scaffold_empty_components_writes_only_config_and_makefile(tmp_path):
    summary = scaf.scaffold(
        tmp_path,
        project_name="p",
        package_name="p",
        owner="o",
        host="github",
        language="python",
        template_repo="jebel-quant/rhiza",
        ref="main",
        components=[],
    )
    assert set(summary["created"]) == {".rhiza/template.yml", "Makefile"}
    assert not (tmp_path / "mkdocs.yml").exists()


def test_scaffold_skips_existing_files(tmp_path):
    (tmp_path / "Makefile").write_text("hand-written\n")
    summary = scaf.scaffold(
        tmp_path,
        project_name="p",
        package_name="p",
        owner="o",
        host="github",
        language="python",
        template_repo="jebel-quant/rhiza",
        ref="main",
        components=["mkdocs"],
    )
    assert "Makefile" in summary["skipped"]
    assert "Makefile" not in summary["created"]
    assert (tmp_path / "Makefile").read_text() == "hand-written\n"  # untouched


def test_scaffold_go_gets_config_and_hint_no_mkdocs(tmp_path):
    summary = scaf.scaffold(
        tmp_path,
        project_name="gotool",
        package_name="gotool",
        owner="acme",
        host="github",
        language="go",
        template_repo="jebel-quant/rhiza-go",
        ref="main",
        components=["mkdocs"],  # mkdocs is Python-only → skipped for Go
    )
    created = set(summary["created"])
    assert created == {".rhiza/template.yml", "Makefile"}
    assert not (tmp_path / "mkdocs.yml").exists()
    assert any("go mod init" in n for n in summary["notes"])
    tpl = (tmp_path / ".rhiza" / "template.yml").read_text()
    assert "language: go" in tpl
    assert "jebel-quant/rhiza-go" in tpl


# --- main() / CLI -----------------------------------------------------------


def test_main_json_output(tmp_path, capsys):
    rc = scaf.main([str(tmp_path), "--project-name", "widget", "--owner", "acme", "--json"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["project_name"] == "widget"
    assert payload["package_name"] == "widget"
    assert payload["template_repository"] == "jebel-quant/rhiza"
    assert ".rhiza/template.yml" in payload["created"]


def test_main_defaults_project_name_to_dir(tmp_path, capsys):
    rc = scaf.main([str(tmp_path), "--json"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["project_name"] == tmp_path.name


def test_main_rejects_unknown_component(tmp_path):
    with pytest.raises(SystemExit):
        scaf.main([str(tmp_path), "--components", "package"])  # retired component


def test_parse_components_rejects_unknown():
    with pytest.raises(ValueError):
        scaf._parse_components("bogus", "python")


def test_main_text_output(tmp_path, capsys):
    rc = scaf.main([str(tmp_path), "--project-name", "x", "--components", "mkdocs"])
    assert rc == 0
    assert "created" in capsys.readouterr().out


def test_main_text_output_with_note(tmp_path, capsys):
    # a Go project emits a `go mod init` note → covers the notes loop
    rc = scaf.main([str(tmp_path), "--language", "go", "--components", ""])
    assert rc == 0
    assert "note" in capsys.readouterr().err


def test_main_nothing_to_create(tmp_path, capsys):
    (tmp_path / ".rhiza").mkdir()
    (tmp_path / ".rhiza" / "template.yml").write_text("x\n")
    (tmp_path / "Makefile").write_text("x\n")
    rc = scaf.main([str(tmp_path), "--project-name", "x", "--components", ""])
    assert rc == 0
    assert "nothing to create" in capsys.readouterr().err


# --- end-to-end: the /init flow survives a real sync + the template gates ----

# The template ref to sync. Pinned for determinism; bump when validating a newer
# rhiza release (any release whose bundled tests the scaffold must still pass).
TEMPLATE_REF = "v1.1.3"

_SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
SCAFFOLD = _SCRIPTS / "init_scaffold.py"
SYNC = _SCRIPTS / "sync.py"
NEW_MODULE = _SCRIPTS / "new_module.py"

# Invoke the bundled scripts the way /init does — under a pinned modern
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
def test_init_flow_survives_sync_and_gates(tmp_path: Path) -> None:
    """The full /init flow (uv init → scaffold → seed → sync) passes the gates."""
    repo = tmp_path / "e2e-init"
    repo.mkdir()

    # 1. Skeleton via uv init (step 2 of /init).
    _assert_ok(_run_cmd(["uv", "init", "--lib", "--name", "e2e_init"], repo), "uv init")
    _git(repo, "config", "user.email", "e2e@example.com")
    _git(repo, "config", "user.name", "E2E Test")

    # 2. Seed a starter module + test (what /init delegates to /new).
    _assert_ok(_run_cmd([*PY, str(NEW_MODULE), "main", str(repo)], repo), "new main")

    # 3. Scaffold the rhiza-only files (step 8).
    scaffold = _run_cmd(
        [
            *PY, str(SCAFFOLD), str(repo),
            "--project-name", "e2e-init", "--owner", "jebel-quant",
            "--host", "github", "--language", "python",
            "--template-repo", "jebel-quant/rhiza", "--ref", TEMPLATE_REF,
            "--components", "mkdocs",
        ],
        repo,
    )  # fmt: skip
    _assert_ok(scaffold, "scaffold")
    for expected in ("pyproject.toml", "Makefile", ".rhiza/template.yml"):
        assert (repo / expected).exists(), f"missing {expected}"
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "chore: scaffold rhiza-managed project")

    # 4. First sync via the bundled stdlib porter (NOT uvx rhiza).
    sync = _run_cmd([*PY, str(SYNC), "."], repo)
    _assert_ok(sync, "scripts/sync.py")
    assert (repo / ".rhiza" / "rhiza.mk").exists(), "sync did not deliver .rhiza/rhiza.mk"

    # 5. The scaffolded project's own tests pass under the coverage gate.
    project_test = _run_cmd(["make", "test"], repo)
    _assert_ok(project_test, "make test")
