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


def test_template_yml_gitlab_repo_still_clones_the_template_from_github():
    """`--host gitlab` is about *this* repo, not about where the template lives.

    Deriving `template-host` from it made every GitLab repo try to clone
    jebel-quant/rhiza from gitlab.com, so the first sync died with "could not read
    Username". The profile must switch; the clone URL must not.
    """
    out = scaf.render_template_yml("jebel-quant/rhiza-go", "v2.0.0", "gitlab", "go")
    assert "  - gitlab-project" in out
    assert "language: go" in out
    assert "template-host" not in out, "the template is on GitHub, not GitLab"


def test_template_yml_template_host_is_opt_in():
    """A genuinely GitLab-hosted template still works — it just has to be asked for."""
    out = scaf.render_template_yml("grp/tmpl", "v1.0.0", "gitlab", "python", template_host="gitlab")
    assert "template-host: gitlab" in out
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


def test_scaffold_rust_uses_the_shared_template_and_a_rust_profile(tmp_path):
    """Rust rides on jebel-quant/rhiza — only the profile is namespaced."""
    summary = scaf.scaffold(
        tmp_path,
        host="github",
        language="rust",
        template_repo=scaf.DEFAULT_TEMPLATE_REPO["rust"],
        ref="main",
    )
    assert summary["profile"] == "rust-local"
    tpl = (tmp_path / ".rhiza" / "template.yml").read_text()
    assert "jebel-quant/rhiza" in tpl
    assert "language: rust" in tpl
    assert "  - rust-local" in tpl


def test_rust_resolves_to_a_profile_the_template_actually_defines(tmp_path):
    """Both hosts map to rust-local: hosted Rust profiles arrive with the workflows.

    A pointer at a `rust-github-project` that does not exist fails the very first
    sync, which is a worse first experience than local-only tooling that works.
    """
    assert scaf.profile_for_host("github", "rust") == "rust-local"
    assert scaf.profile_for_host("gitlab", "rust") == "rust-local"


def test_an_unknown_language_still_gets_a_profile(tmp_path):
    """`--language` is validated by argparse, but the mapping must not KeyError."""
    assert scaf.profile_for_host("github", "cobol") == "github-project"


def test_python_profiles_stay_unprefixed():
    """Renaming python's profiles would break the pointer of every synced repo."""
    assert scaf.profile_for_host("github", "python") == "github-project"
    assert scaf.profile_for_host("gitlab") == "gitlab-project"


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


# --- end-to-end: the gitlab-project profile -----------------------------------
#
# GitLab had no command-level coverage at all, which is how /update shipped with no
# `glab mr create` path. The profile side is testable from here: `gitlab-project` is a
# bundle selection inside a template hosted on GitHub, so no GitLab account is needed.


def test_e2e_gitlab_profile_is_written_without_redirecting_the_template(gitlab_synced_repo):
    """The pointer selects GitLab's CI while still cloning the template from GitHub.

    This fixture is what caught the conflation: with `template-host: gitlab` emitted
    for every GitLab repo, the sync below tried gitlab.com and died with "could not
    read Username for 'https://gitlab.com'". A GitLab repo on a GitHub-hosted template
    must have no `template-host` at all.
    """
    body = (gitlab_synced_repo / ".rhiza" / "template.yml").read_text()
    assert "  - gitlab-project" in body
    assert "template-host" not in body


def test_e2e_gitlab_sync_materialises_gitlab_ci_and_not_github(gitlab_synced_repo):
    """The platform bundles are the only difference between the two profiles.

    Getting this wrong ships a repo with the other platform's CI — inert at best,
    and confusing at worst.
    """
    assert (gitlab_synced_repo / ".gitlab-ci.yml").is_file(), "no .gitlab-ci.yml synced"
    assert (gitlab_synced_repo / ".gitlab").is_dir(), "no .gitlab/ synced"
    workflows = gitlab_synced_repo / ".github" / "workflows"
    assert not workflows.exists() or not list(workflows.glob("*.yml")), (
        "the gitlab profile must not materialise GitHub workflows"
    )


def test_e2e_gitlab_and_github_profiles_share_the_core_api(gitlab_synced_repo, synced_repo):
    """Both profiles include `core`, so the make API must be identical across them."""
    for path in ("Makefile", ".rhiza/rhiza.mk", "ruff.toml"):
        assert (gitlab_synced_repo / path).is_file(), f"gitlab profile lacks {path}"
        assert (synced_repo / path).is_file(), f"github profile lacks {path}"


# --- end-to-end: the Rust axis ------------------------------------------------


def test_e2e_the_rust_pointer_names_the_language_and_its_profile(rust_crate):
    """The pointer is the whole of /init's own output, and Rust's differs in two ways.

    `language: rust` is what everything downstream reads (`language_profile.detect`
    prefers it over sniffing the manifest), and the profile is the Rust one rather than
    the Python default.
    """
    from conftest import rust_profile

    body = (rust_crate / ".rhiza" / "template.yml").read_text()
    assert 'repository: "jebel-quant/rhiza"' in body, "Rust shares the Python template"
    assert "language: rust" in body
    assert f"  - {rust_profile('github')}" in body
    assert "template-host" not in body, "the template is GitHub-hosted; nothing to redirect"


def test_e2e_the_rust_sync_writes_a_lock_recording_the_profile(rust_synced_repo):
    """The sync is what /update runs; the lock is the record of what it did."""
    import _rhiza_yaml
    from conftest import rust_profile

    lock = _rhiza_yaml.load_yaml(rust_synced_repo / ".rhiza" / "template.lock")
    assert lock["profiles"] == [rust_profile("github")]
    assert lock["sha"], "the lock records no upstream SHA"
    assert lock["files"], "the lock records no files"


def test_e2e_the_rust_sync_delivers_the_rust_toolchain_layer(rust_synced_repo):
    """What `rust-core` ships, asserted as *what the lock says arrived* — not a wish list.

    The template owns which files a profile carries. Hardcoding them here would fail the
    day upstream reorganises its bundles, which is a template change, not a plugin bug.
    So: every file the lock records exists, and the Rust make include is among them.
    """
    import _rhiza_yaml

    lock = _rhiza_yaml.load_yaml(rust_synced_repo / ".rhiza" / "template.lock")
    missing = [f for f in lock["files"] if not (rust_synced_repo / f).exists()]
    assert missing == [], f"the lock records files the sync did not deliver: {missing}"
    assert (rust_synced_repo / "Makefile").is_file(), "sync delivered no Makefile"
    assert (rust_synced_repo / ".rhiza" / "rhiza.mk").is_file(), "sync delivered no rhiza.mk"
    rust_mk = [f for f in lock["files"] if f.startswith(".rhiza/make.d/") and "rust" in f]
    assert rust_mk, f"no Rust make include in the synced files: {lock['files']}"


def test_e2e_the_rust_profile_ships_no_hosted_ci_and_that_is_deliberate(rust_synced_repo):
    """`rust-local` is local tooling only — asserting CI here would demand a wrong thing.

    The template's `github`/`gitlab` bundles still ship *Python* workflows (a release job
    running `uv build` against PyPI), so a Rust profile including them would deliver CI
    that fails on its first run. The absence is the design, and a test that expected
    workflows would be the thing that's wrong.
    """
    workflows = rust_synced_repo / ".github" / "workflows"
    assert not workflows.exists() or not list(workflows.glob("*.yml")), (
        "the Rust profile is local-only; hosted CI arrives with the Rust workflows"
    )
