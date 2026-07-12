"""Tests for the `rhiza init` scaffolding port (`scripts/init_scaffold.py`).

Beyond the unit checks, several tests re-assert the same contracts the
template's own bundled tests enforce (`.rhiza/tests/test_pyproject.py`,
`test_readme_validation.py`, `test_docstrings.py`) so the scaffold is proven to
pass them — that parity is the whole point of retiring `rhiza init`.
"""

from __future__ import annotations

import ast
import json
import re
import tomllib

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


# --- pyproject.toml: mirror the template's test_pyproject.py contract --------


@pytest.fixture
def pyproject() -> dict:
    text = scaf.render_pyproject("my-proj", "my_proj", "acme", "github.com", "A thing.")
    return tomllib.loads(text)


def test_pyproject_is_valid_toml_with_required_fields(pyproject):
    project = pyproject["project"]
    for field in (
        "name",
        "version",
        "description",
        "readme",
        "requires-python",
        "license",
        "authors",
    ):
        assert field in project, f"missing [project].{field}"


def test_pyproject_version_is_semver(pyproject):
    assert re.match(r"^\d+\.\d+\.\d+", str(pyproject["project"]["version"]))


def test_pyproject_authors_have_names(pyproject):
    authors = pyproject["project"]["authors"]
    assert any(a.get("name", "").strip() for a in authors)


def test_pyproject_urls_present(pyproject):
    urls = pyproject["project"]["urls"]
    assert urls["Homepage"].strip() and urls["Repository"].strip()
    assert "acme/my-proj" in urls["Repository"]


def test_pyproject_classifiers(pyproject):
    cl = pyproject["project"]["classifiers"]
    assert any(re.match(r"Programming Language :: Python :: 3\.\d+", c) for c in cl)
    assert any(c.startswith("License ::") for c in cl)


def test_pyproject_dependency_groups(pyproject):
    dg = pyproject["dependency-groups"]
    assert "test" in dg and any("pytest" in str(d).lower() for d in dg["test"])
    assert "lint" in dg


def test_pyproject_wheel_packages_use_package_name(pyproject):
    assert pyproject["tool"]["hatch"]["build"]["targets"]["wheel"]["packages"] == ["src/my_proj"]


def test_pyproject_urls_host_aware_for_gitlab():
    data = tomllib.loads(scaf.render_pyproject("p", "p", "org", "gitlab.com", "d"))
    assert "gitlab.com/org/p" in data["project"]["urls"]["Homepage"]


# --- generated Python is valid + docstringed (test_docstrings contract) -----


def test_main_and_test_modules_parse_and_have_docstrings():
    main_src = scaf._fill(scaf._MAIN_PY, PROJECT_NAME="demo")
    tree = ast.parse(main_src)
    funcs = [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)]
    assert {f.name for f in funcs} == {"say_hello", "main"}
    assert all(ast.get_docstring(f) for f in funcs), "every function must have a docstring"
    # test module imports the *package* name and parses
    test_src = scaf._fill(scaf._TEST_MAIN_PY, PACKAGE_NAME="demo_pkg")
    assert "from demo_pkg.main import" in test_src
    ast.parse(test_src)


# --- README: satisfies test_readme_validation.py ----------------------------


def test_readme_is_real_and_validates():
    readme = scaf.render_readme("cool-proj", "cool_proj", "Neat.")
    assert readme.startswith("# cool-proj")
    assert "Neat." in readme
    # The only python block is tagged +RHIZA_SKIP, so the validator excludes it:
    code_block = re.compile(r"```python([^\n]*)\n(.*?)```", re.DOTALL)
    blocks = code_block.findall(readme)
    assert blocks, "expected a python usage block"
    assert all("+RHIZA_SKIP" in flags for flags, _ in blocks)
    # ...and the non-skipped python that would actually run is therefore empty,
    # which is exactly what makes an example-only README pass validation.
    runnable = "".join(code for flags, code in blocks if "+RHIZA_SKIP" not in flags)
    assert runnable == ""


# --- scaffold() end to end --------------------------------------------------


def test_scaffold_python_creates_expected_files(tmp_path):
    summary = scaf.scaffold(
        tmp_path,
        project_name="acme-tool",
        package_name="acme_tool",
        owner="acme",
        host="github",
        language="python",
        template_repo="jebel-quant/rhiza",
        ref="v1.1.3",
        components=["package", "mkdocs", "readme"],
    )
    created = set(summary["created"])
    assert ".rhiza/template.yml" in created
    assert "Makefile" in created
    assert "pyproject.toml" in created
    assert "src/acme_tool/__init__.py" in created
    assert "src/acme_tool/main.py" in created
    assert "tests/test_main.py" in created
    assert "mkdocs.yml" in created
    assert "README.md" in created
    assert (tmp_path / "Makefile").read_text().startswith("## Makefile (repo-owned)")


def test_scaffold_skips_existing_files(tmp_path):
    (tmp_path / "README.md").write_text("hand-written\n")
    summary = scaf.scaffold(
        tmp_path,
        project_name="p",
        package_name="p",
        owner="o",
        host="github",
        language="python",
        template_repo="jebel-quant/rhiza",
        ref="main",
        components=["readme"],
    )
    assert "README.md" in summary["skipped"]
    assert "README.md" not in summary["created"]
    assert (tmp_path / "README.md").read_text() == "hand-written\n"  # untouched


def test_scaffold_go_only_readme_and_config(tmp_path):
    summary = scaf.scaffold(
        tmp_path,
        project_name="gotool",
        package_name="gotool",
        owner="acme",
        host="github",
        language="go",
        template_repo="jebel-quant/rhiza-go",
        ref="main",
        components=["package", "mkdocs", "readme"],
    )
    created = set(summary["created"])
    assert created == {".rhiza/template.yml", "Makefile", "README.md"}
    assert not (tmp_path / "pyproject.toml").exists()
    assert not (tmp_path / "src").exists()
    assert any("go mod init" in n for n in summary["notes"])
    # template.yml records the go language + go template repo
    tpl = (tmp_path / ".rhiza" / "template.yml").read_text()
    assert "language: go" in tpl
    assert "jebel-quant/rhiza-go" in tpl


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


# --- main() / CLI -----------------------------------------------------------


def test_main_json_output(tmp_path, capsys, monkeypatch):
    # keep uv lock from running against the real environment
    monkeypatch.setattr(scaf, "_run_uv_lock", lambda target, notes: notes.append("uv lock stubbed"))
    rc = scaf.main([str(tmp_path), "--project-name", "widget", "--owner", "acme", "--json"])
    assert rc == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["project_name"] == "widget"
    assert payload["package_name"] == "widget"
    assert payload["template_repository"] == "jebel-quant/rhiza"
    assert ".rhiza/template.yml" in payload["created"]


def test_main_defaults_project_name_to_dir(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(scaf, "_run_uv_lock", lambda target, notes: None)
    rc = scaf.main([str(tmp_path), "--json"])
    assert rc == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["project_name"] == tmp_path.name


def test_main_rejects_unknown_component(tmp_path):
    with pytest.raises(SystemExit):
        scaf.main([str(tmp_path), "--components", "bogus"])
