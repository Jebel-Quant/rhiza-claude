"""Tests for the `rhiza validate` port (`scripts/validate.py`)."""

from __future__ import annotations

import pytest
import validate
import validate as v
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
    write_template(git_repo, 'repository: "o/r"\nlanguage: cobol\ntemplates:\n  - core\n')
    ok, log = _run(git_repo)
    # cobol has no structure validator, so structure is skipped (pass with warning)
    assert ok is True
    assert any("cobol" in w for w in log.warnings)


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


def log():
    return v.Log(verbose=True)


def test_python_structure(tmp_path):
    lg = log()
    assert v._validate_python_structure(lg, tmp_path) is False  # no pyproject
    (tmp_path / "pyproject.toml").write_text("[project]\n")
    (tmp_path / "src").mkdir()
    (tmp_path / "tests").mkdir()
    lg2 = log()
    assert v._validate_python_structure(lg2, tmp_path) is True
    assert not lg2.warnings  # src + tests present → no warnings


def test_go_structure(tmp_path):
    lg = log()
    assert v._validate_go_structure(lg, tmp_path) is False  # no go.mod, warns on cmd/pkg
    (tmp_path / "go.mod").write_text("module x\n")
    (tmp_path / "cmd").mkdir()
    (tmp_path / "pkg").mkdir()
    (tmp_path / "internal").mkdir()
    lg2 = log()
    assert v._validate_go_structure(lg2, tmp_path) is True


def test_rust_structure(tmp_path):
    lg = log()
    assert v._validate_rust_structure(lg, tmp_path) is False  # no Cargo.toml
    (tmp_path / "Cargo.toml").write_text("[package]\nname = 'x'\n")
    lg2 = log()
    assert v._validate_rust_structure(lg2, tmp_path) is True  # manifest is enough to pass
    assert any("lib.rs" in w for w in lg2.warnings)  # ...but the missing crate root warns

    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "lib.rs").write_text("//! x\n")
    lg3 = log()
    assert v._validate_rust_structure(lg3, tmp_path) is True
    assert not lg3.warnings


def test_rust_workspace_root_needs_no_crate_root(tmp_path):
    """A virtual workspace has a Cargo.toml and deliberately no src/ — not a warning."""
    (tmp_path / "Cargo.toml").write_text('[workspace]\nmembers = ["crates/*"]\n')
    lg = log()
    assert v._validate_rust_structure(lg, tmp_path) is True
    assert not lg.warnings


def test_check_project_structure_unknown_language(tmp_path):
    lg = log()
    assert v._check_project_structure(lg, tmp_path, "cobol") is True
    assert lg.warnings


def test_check_git_repository(tmp_path):
    assert v._check_git_repository(log(), tmp_path) is False
    (tmp_path / ".git").mkdir()
    assert v._check_git_repository(log(), tmp_path) is True


def test_template_file_exists(tmp_path):
    lg = log()
    ok, path = v._check_template_file_exists(lg, tmp_path, None)
    assert ok is False and path == tmp_path / ".rhiza" / "template.yml"
    # outside the target → relative_to ValueError branch, then missing
    outside = tmp_path.parent / "elsewhere.yml"
    ok2, _ = v._check_template_file_exists(log(), tmp_path, outside)
    assert ok2 is False
    # present
    tf = tmp_path / "t.yml"
    tf.write_text("x: 1\n")
    ok3, _ = v._check_template_file_exists(log(), tmp_path, tf)
    assert ok3 is True


def test_parse_template_file(tmp_path, monkeypatch):
    tf = tmp_path / "t.yml"
    tf.write_text('repository: "a/b"\n')
    ok, cfg = v._parse_template_file(log(), tf)
    assert ok and cfg["repository"] == "a/b"

    monkeypatch.setattr(v, "load_yaml", lambda p: (_ for _ in ()).throw(ValueError("bad")))
    ok2, cfg2 = v._parse_template_file(log(), tf)
    assert ok2 is False and cfg2 is None

    monkeypatch.setattr(v, "load_yaml", lambda p: (_ for _ in ()).throw(OSError("io")))
    ok3, _ = v._parse_template_file(log(), tf)
    assert ok3 is False

    monkeypatch.setattr(v, "load_yaml", lambda p: {})
    ok4, _ = v._parse_template_file(log(), tf)
    assert ok4 is False  # empty


@pytest.mark.parametrize(
    ("config", "expected"),
    [
        ({}, None),
        ({"profiles": "x"}, False),
        ({"profiles": []}, False),
        ({"profiles": [""]}, False),
        ({"profiles": ["github-project"]}, True),
    ],
)
def test_profiles_field(config, expected):
    assert v._validate_profiles_field(log(), config) is expected


def test_config_mode_profiles_invalid():
    assert v._validate_configuration_mode(log(), {"profiles": "x"}) is False


def test_config_mode_bundles_renamed():
    assert v._validate_configuration_mode(log(), {"bundles": ["x"], "profiles": ["p"]}) is False


def test_config_mode_nothing_specified():
    assert v._validate_configuration_mode(log(), {"ref": "main"}) is False


def test_config_mode_variants():
    assert v._validate_configuration_mode(log(), {"profiles": ["p"]}) is True
    assert v._validate_configuration_mode(log(), {"templates": ["a"], "include": ["b"]}) is True
    assert v._validate_configuration_mode(log(), {"templates": ["a"]}) is True
    assert v._validate_configuration_mode(log(), {"include": ["b"]}) is True


def test_required_fields():
    assert v._validate_required_fields(log(), {}) is False
    assert v._validate_required_fields(log(), {"repository": 5}) is False
    assert v._validate_required_fields(log(), {"repository": "a/b"}) is True
    assert v._validate_required_fields(log(), {"template-repository": "a/b"}) is True


def test_repository_format():
    assert v._validate_repository_format(log(), {}) is True  # absent → caught elsewhere
    assert v._validate_repository_format(log(), {"repository": 5}) is False
    assert v._validate_repository_format(log(), {"repository": "noslash"}) is False
    assert v._validate_repository_format(log(), {"repository": "a/b"}) is True


def test_string_list():
    assert v._validate_string_list(log(), {}, "templates", "ex") is True  # absent
    assert v._validate_string_list(log(), {"templates": "x"}, "templates", "ex") is False
    assert v._validate_string_list(log(), {"templates": []}, "templates", "ex") is False
    lg = log()
    assert v._validate_string_list(lg, {"templates": ["a", 5]}, "templates", "ex") is True
    assert lg.warnings  # non-string entry warned


def test_branch_field():
    v._validate_branch_field(log(), {})  # absent → no-op
    lg = log()
    v._validate_branch_field(lg, {"ref": 5})
    assert lg.warnings
    lg2 = log()
    v._validate_branch_field(lg2, {"template-branch": "main"})
    assert not lg2.warnings


def test_host_field():
    v._validate_host_field(log(), {})  # absent
    lg = log()
    v._validate_host_field(lg, {"template-host": 5})
    assert lg.warnings
    lg2 = log()
    v._validate_host_field(lg2, {"template-host": "bitbucket"})
    assert lg2.warnings
    lg3 = log()
    v._validate_host_field(lg3, {"template-host": "github"})
    assert not lg3.warnings


def test_language_field():
    v._validate_language_field(log(), {})
    lg = log()
    v._validate_language_field(lg, {"language": 5})
    assert lg.warnings
    lg2 = log()
    v._validate_language_field(lg2, {"language": "cobol"})
    assert lg2.warnings
    lg3 = log()
    v._validate_language_field(lg3, {"language": "python"})
    assert not lg3.warnings


def test_exclude_field():
    v._validate_exclude_field(log(), {})
    lg = log()
    v._validate_exclude_field(lg, {"exclude": "x"})
    assert lg.warnings
    lg2 = log()
    v._validate_exclude_field(lg2, {"exclude": ["ok", 5]})
    assert lg2.warnings  # non-string path


def test_config_fields_templates_include_invalid():
    lg = log()
    assert v._validate_config_fields(lg, {"repository": "a/b", "templates": "x"}) is False
    lg2 = log()
    assert v._validate_config_fields(lg2, {"repository": "a/b", "include": "x"}) is False


def _repo(tmp_path, body, language_files=None):
    (tmp_path / ".git").mkdir()
    (tmp_path / ".rhiza").mkdir()
    (tmp_path / ".rhiza" / "template.yml").write_text(body)
    for rel in language_files or []:
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("x")


def test_validate_go_end_to_end(tmp_path):
    _repo(
        tmp_path,
        'repository: "a/b"\nlanguage: go\nprofiles:\n  - github-project\nref: main\n',
        ["go.mod"],
    )
    assert v.validate(log(), tmp_path) is True


def test_validate_rust_end_to_end(tmp_path):
    _repo(
        tmp_path,
        'repository: "a/b"\nlanguage: rust\nprofiles:\n  - rust-github-project\nref: main\n',
        ["Cargo.toml", "src/lib.rs"],
    )
    assert v.validate(log(), tmp_path) is True


def test_validate_fails_on_bad_config(tmp_path):
    _repo(tmp_path, "language: go\nprofiles:\n  - github-project\n", ["go.mod"])  # no repository
    assert v.validate(log(), tmp_path) is False


def test_main_json_and_path_to_template(tmp_path, capsys):
    (tmp_path / ".git").mkdir()
    (tmp_path / "pyproject.toml").write_text("[project]\n")
    (tmp_path / "template.yml").write_text('repository: "a/b"\nprofiles: [github-project]\n')
    rc = v.main([str(tmp_path), "--path-to-template", str(tmp_path), "--json", "--verbose"])
    assert rc == 0
    import json

    payload = json.loads(capsys.readouterr().out)
    assert payload["valid"] is True


def test_main_returns_one_on_failure(tmp_path):
    assert v.main([str(tmp_path)]) == 1  # not a git repo


class TestLog:
    def test_error_and_warning_recorded(self):
        lg = v.Log()
        lg.error("boom")
        lg.warning("careful")
        assert lg.errors == ["boom"]
        assert lg.warnings == ["careful"]

    def test_levels_and_verbose_gating(self, capsys):
        quiet = v.Log(verbose=False)
        quiet.debug("hidden")
        assert capsys.readouterr().err == ""
        loud = v.Log(verbose=True)
        loud.success("ok")
        loud.info("fyi")
        loud.debug("shown")
        err = capsys.readouterr().err
        assert "ok" in err and "fyi" in err and "shown" in err


# --- branch coverage: the arms line coverage could not see ---------------------


@pytest.mark.parametrize("present", ["pkg", "internal"])
def test_go_structure_accepts_either_package_folder_alone(tmp_path, present):
    """`pkg` or `internal` — either satisfies the layout; both were always present before.

    The rule is "not neither", so each folder's success path has to be reachable on its
    own, not only when the other is there too.
    """
    (tmp_path / "go.mod").write_text("module x\n")
    (tmp_path / present).mkdir()
    lg = log()
    assert v._validate_go_structure(lg, tmp_path) is True


# --- end-to-end: a real crate and a real workspace ----------------------------


def test_e2e_a_real_crate_validates(rust_crate):
    """`validate.py` against a crate built by the /init chain, not by a fixture writer.

    `/rhiza:status` runs this first, so a Rust repo that fails here is reported as
    misconfigured before anything else is even looked at.
    """
    ok, log = _run(rust_crate)
    assert ok, log.errors


def test_e2e_a_virtual_workspace_validates_too(rust_crate, tmp_path):
    """`[workspace]` with no `src/` is a legitimate Rust repo, and the commoner shape.

    The distinction is already coded; neither half had ever been run against a real tree.
    A workspace root reported as a malformed crate is the "confidently wrong" failure the
    language axis exists to prevent.
    """
    import shutil

    workspace = tmp_path / "widget"
    shutil.copytree(rust_crate, workspace)
    shutil.rmtree(workspace / "src")
    (workspace / "Cargo.toml").write_text('[workspace]\nmembers = ["crates/*"]\nresolver = "3"\n')

    ok, log = _run(workspace)
    assert ok, log.errors
    assert not (workspace / "src").exists()
