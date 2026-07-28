"""Tests for the rhiza pointer writer (`scripts/init_scaffold.py`).

`/init` writes exactly one file itself, `.rhiza/template.yml`. The project skeleton
comes from `uv init --lib` (finished by the skeleton procedure), the
`Makefile`/CI/docs base from the template sync (`/update`), and the license, Python
version, and docs from the license, python-version, and `/rhiza:docs` steps.
"""

from __future__ import annotations

import json

import init_scaffold as scaf
from conftest import assert_ok, run_cmd

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


# --- end-to-end: the /init chain, against a real sync -------------------------
#
# The setup lives in conftest.py's `synced_repo` fixture, which walks the documented
# /init path and then runs the real sync. These assert the outcome. They always run —
# they were opt-in behind RHIZA_E2E=1, which is how /quality shipped unable to run.


def test_e2e_init_produces_the_pointer_and_nothing_else(synced_repo):
    """/init writes exactly one file itself; the rest comes from other steps."""
    pointer = synced_repo / ".rhiza" / "template.yml"
    assert pointer.is_file()
    body = pointer.read_text()
    assert 'repository: "jebel-quant/rhiza"' in body
    assert "  - github-project" in body


def test_e2e_the_sync_delivers_what_init_deliberately_does_not(synced_repo):
    """/init ships no Makefile or CI — the template does, and this proves it."""
    assert (synced_repo / "Makefile").is_file(), "sync delivered no Makefile"
    assert (synced_repo / ".rhiza" / "rhiza.mk").is_file(), "sync delivered no rhiza.mk"
    assert (synced_repo / "ruff.toml").is_file()
    assert list((synced_repo / ".github" / "workflows").glob("*.yml")), "no CI synced"


def test_e2e_the_skeleton_satisfies_the_templates_pyproject_gate(synced_repo):
    """The shape the synced .rhiza/tests/test_pyproject.py asserts.

    Without it /update's gates cannot run at all: `make test` depends on a `uv sync`
    that needs a pyproject, and the synced gate checks these specific fields.
    """
    body = (synced_repo / "pyproject.toml").read_text()
    assert "[project.urls]" in body
    assert "[dependency-groups]" in body
    assert 'license = "MIT"' in body
    assert "Programming Language :: Python :: 3.12" in body
    assert 'requires-python = ">=3.12"' in body
    # uv's undocumented placeholder must be gone, or interrogate and coverage both fail.
    assert (synced_repo / "src" / "widget" / "__init__.py").read_text() == (
        '"""widget package."""\n'
    )


def test_e2e_the_projects_own_tests_pass_under_the_coverage_gate(synced_repo):
    """`make test` is what /update runs, and it must pass on a freshly built repo."""
    assert_ok(run_cmd(["make", "test"], synced_repo), "make test")
