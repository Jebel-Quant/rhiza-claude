"""Tests for the `rhiza validate` port (`scripts/validate.py`)."""

from __future__ import annotations

import validate
from conftest import write_template

VALID_TEMPLATE = 'repository: "owner/repo"\nref: main\ntemplates:\n  - core\n'


def _run(repo, template_file=None):
    """Run validation with a fresh Log; return (verdict, log)."""
    log = validate.Log()
    ok = validate.validate(log, repo, template_file=template_file)
    return ok, log


def test_valid_config_passes(git_repo):
    write_template(git_repo, VALID_TEMPLATE)
    ok, log = _run(git_repo)
    assert ok is True
    assert log.errors == []


def test_not_a_git_repo_fails(tmp_path):
    ok, log = _run(tmp_path)
    assert ok is False
    assert any("not a git repository" in e for e in log.errors)


def test_missing_template_fails(git_repo):
    ok, log = _run(git_repo)
    assert ok is False
    assert any("No template file found" in e for e in log.errors)


def test_empty_template_fails(git_repo):
    write_template(git_repo, "# nothing here\n")
    ok, log = _run(git_repo)
    assert ok is False
    assert any("empty" in e for e in log.errors)


def test_renamed_bundles_field_fails(git_repo):
    write_template(git_repo, 'repository: "o/r"\nbundles:\n  - core\n')
    ok, log = _run(git_repo)
    assert ok is False
    assert any("bundles" in e for e in log.errors)


def test_missing_repository_fails(git_repo):
    write_template(git_repo, "templates:\n  - core\n")
    ok, log = _run(git_repo)
    assert ok is False
    assert any("template-repository" in e or "repository" in e for e in log.errors)


def test_bad_repository_format_fails(git_repo):
    write_template(git_repo, 'repository: "noslash"\ntemplates:\n  - core\n')
    ok, log = _run(git_repo)
    assert ok is False
    assert any("owner/repo" in e for e in log.errors)


def test_no_configuration_mode_fails(git_repo):
    write_template(git_repo, 'repository: "o/r"\n')
    ok, log = _run(git_repo)
    assert ok is False
    assert any("at least one of" in e for e in log.errors)


def test_profiles_mode_passes(git_repo):
    write_template(git_repo, 'repository: "o/r"\nprofiles:\n  - github-project\n')
    ok, log = _run(git_repo)
    assert ok is True


def test_unknown_language_warns_but_passes(git_repo):
    write_template(git_repo, 'repository: "o/r"\nlanguage: rust\ntemplates:\n  - core\n')
    ok, log = _run(git_repo)
    # rust has no structure validator, so structure is skipped (pass with warning)
    assert ok is True
    assert any("rust" in w for w in log.warnings)


def test_go_language_requires_go_mod(tmp_path):
    (tmp_path / ".git").mkdir()
    write_template(tmp_path, 'repository: "o/r"\nlanguage: go\ntemplates:\n  - core\n')
    ok, log = _run(tmp_path)
    assert ok is False
    assert any("go.mod" in e for e in log.errors)


def test_path_to_template_override(git_repo):
    # place template.yml in the repo root instead of .rhiza/
    (git_repo / "template.yml").write_text(VALID_TEMPLATE)
    ok, log = _run(git_repo, template_file=git_repo / "template.yml")
    assert ok is True


def test_main_exit_codes_and_json(git_repo, capsys):
    write_template(git_repo, VALID_TEMPLATE)
    assert validate.main([str(git_repo)]) == 0

    write_template(git_repo, 'repository: "noslash"\ntemplates:\n  - core\n')
    rc = validate.main([str(git_repo), "--json"])
    assert rc == 1
    import json

    payload = json.loads(capsys.readouterr().out)
    assert payload["valid"] is False
    assert payload["errors"]
