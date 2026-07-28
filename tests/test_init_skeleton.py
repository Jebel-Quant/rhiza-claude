"""Tests for the skeleton finisher (`scripts/init_skeleton.py`) behind `/rhiza:skeleton`.

`uv init --lib` creates the project; this script closes the gap between that and the
`[project]` shape the rhiza template's synced pyproject gate requires. It must be
idempotent, additive, and must never write a `classifiers` key.
"""

from __future__ import annotations

import json

import init_skeleton as sk
import pytest

# `pyproject.toml` exactly as `uv init --lib --python 3.12` leaves it.
_UV_PYPROJECT = """\
[project]
name = "acme-tool"
version = "0.1.0"
description = "Add your description here"
readme = "README.md"
authors = [
    { name = "A Dev", email = "dev@example.com" }
]
requires-python = ">=3.12"
dependencies = []

[build-system]
requires = ["uv_build>=0.11.28,<0.12.0"]
build-backend = "uv_build"
"""

# `src/<pkg>/__init__.py` exactly as `uv init --lib` leaves it.
_UV_INIT = 'def hello() -> str:\n    return "Hello from acme-tool!"\n'


# --- is_uv_placeholder_init --------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (_UV_INIT, True),
        ('def hello() -> str:\n\n    return "Hello from x!"\n', True),  # blank lines ignored
        ('"""acme_tool package."""\n', False),  # already normalised
        ("", False),  # empty file is not the placeholder
        (_UV_INIT + "\nimport os\n", False),  # user added something
        ('def hello() -> str:\n    return "Hello!"\n\ndef other() -> None:\n    pass\n', False),
    ],
)
def test_is_uv_placeholder_init(text, expected):
    assert sk.is_uv_placeholder_init(text) is expected


# --- normalize_package_init --------------------------------------------------


def test_normalize_package_init_rewrites_placeholder(tmp_path):
    pkg = tmp_path / "src" / "acme_tool"
    pkg.mkdir(parents=True)
    (pkg / "__init__.py").write_text(_UV_INIT)
    assert sk.normalize_package_init(tmp_path) == ["src/acme_tool/__init__.py"]
    assert (pkg / "__init__.py").read_text() == '"""acme_tool package."""\n'


def test_normalize_package_init_leaves_real_code_alone(tmp_path):
    pkg = tmp_path / "src" / "acme_tool"
    pkg.mkdir(parents=True)
    real = '"""My own docstring."""\n\nVERSION = "1"\n'
    (pkg / "__init__.py").write_text(real)
    assert sk.normalize_package_init(tmp_path) == []
    assert (pkg / "__init__.py").read_text() == real


def test_normalize_package_init_without_src(tmp_path):
    assert sk.normalize_package_init(tmp_path) == []


# --- set_description ---------------------------------------------------------


def test_set_description_replaces_uv_placeholder():
    out, changed = sk.set_description(_UV_PYPROJECT, "Does acme things.")
    assert changed
    assert 'description = "Does acme things."' in out
    assert "Add your description here" not in out


def test_set_description_keeps_a_real_description():
    written = _UV_PYPROJECT.replace("Add your description here", "Hand-written.")
    out, changed = sk.set_description(written, "Something else.")
    assert not changed
    assert out == written


def test_set_description_inserts_when_absent():
    without = _UV_PYPROJECT.replace('description = "Add your description here"\n', "")
    out, changed = sk.set_description(without, "Freshly added.")
    assert changed
    assert 'description = "Freshly added."' in out


def test_set_description_preserves_missing_trailing_newline():
    out, changed = sk.set_description(_UV_PYPROJECT.rstrip("\n"), "No newline.")
    assert changed
    assert not out.endswith("\n")


def test_set_description_requires_project_table():
    with pytest.raises(ValueError):
        sk.set_description("[build-system]\nrequires = []\n", "x")


# --- set_project_urls --------------------------------------------------------


def test_set_project_urls_appends_the_table():
    out, changed = sk.set_project_urls(_UV_PYPROJECT, "https://h/o/r", "https://r/o/r")
    assert changed
    assert "[project.urls]" in out
    assert 'Homepage = "https://h/o/r"' in out
    assert 'Repository = "https://r/o/r"' in out


def test_set_project_urls_adds_only_missing_keys():
    partial = _UV_PYPROJECT + '\n[project.urls]\nHomepage = "https://kept"\n'
    out, changed = sk.set_project_urls(partial, "https://new", "https://repo")
    assert changed
    assert 'Homepage = "https://kept"' in out  # existing entry wins
    assert "https://new" not in out
    assert 'Repository = "https://repo"' in out


def test_set_project_urls_is_idempotent():
    once, _ = sk.set_project_urls(_UV_PYPROJECT, "https://h", "https://r")
    twice, changed = sk.set_project_urls(once, "https://h", "https://r")
    assert not changed
    assert twice == once


def test_set_project_urls_collapses_trailing_blank_lines():
    """An appended table gets exactly one blank line before it, not a pile of them."""
    out, changed = sk.set_project_urls(_UV_PYPROJECT + "\n\n\n", "https://h", "https://r")
    assert changed
    assert 'build-backend = "uv_build"\n\n[project.urls]' in out


def test_set_project_urls_preserves_missing_trailing_newline():
    out, changed = sk.set_project_urls(_UV_PYPROJECT.rstrip("\n"), "https://h", "https://r")
    assert changed
    assert not out.endswith("\n")


# --- set_dependency_groups ---------------------------------------------------


def test_set_dependency_groups_appends_the_table():
    out, changed = sk.set_dependency_groups(_UV_PYPROJECT)
    assert changed
    assert "[dependency-groups]" in out
    assert "pytest>=8.0" in out
    assert "ruff>=0.6" in out


def test_set_dependency_groups_adds_only_missing_groups():
    partial = _UV_PYPROJECT + '\n[dependency-groups]\ntest = ["pytest>=7.0"]\n'
    out, changed = sk.set_dependency_groups(partial)
    assert changed
    assert 'test = ["pytest>=7.0"]' in out  # existing group untouched
    assert out.count("test = ") == 1
    assert "ruff>=0.6" in out


def test_set_dependency_groups_is_idempotent():
    once, _ = sk.set_dependency_groups(_UV_PYPROJECT)
    twice, changed = sk.set_dependency_groups(once)
    assert not changed
    assert twice == once


def test_set_dependency_groups_preserves_missing_trailing_newline():
    out, changed = sk.set_dependency_groups(_UV_PYPROJECT.rstrip("\n"))
    assert changed
    assert not out.endswith("\n")


def test_dependency_group_requirements_are_lower_bounded():
    for deps in sk._DEPENDENCY_GROUPS.values():
        for dep in deps:
            assert ">=" in dep, f"{dep} must carry a lower bound"


# --- no classifiers, ever ----------------------------------------------------


def test_finish_skeleton_never_writes_classifiers(tmp_path):
    """Classifiers belong to /python-version (Python) and nobody (License ::).

    PEP 639 replaced `License :: …` with the SPDX `license` field, so neither this
    script nor /rhiza:license may write one — even though the template's pyproject
    gate still asserts it.
    """
    (tmp_path / "pyproject.toml").write_text(_UV_PYPROJECT)
    sk.finish_skeleton(tmp_path, owner="o", repo="r", host="github", description="d")
    text = (tmp_path / "pyproject.toml").read_text()
    assert "classifiers" not in text
    assert "License ::" not in text


# --- finish_skeleton() end to end -------------------------------------------


def test_finish_skeleton_completes_a_uv_project(tmp_path):
    (tmp_path / "pyproject.toml").write_text(_UV_PYPROJECT)
    pkg = tmp_path / "src" / "acme_tool"
    pkg.mkdir(parents=True)
    (pkg / "__init__.py").write_text(_UV_INIT)

    summary = sk.finish_skeleton(
        tmp_path, owner="jebel-quant", repo="acme-tool", host="github", description="Acme things."
    )

    assert summary["ok"]
    assert set(summary["modified"]) == {"src/acme_tool/__init__.py", "pyproject.toml"}
    assert summary["changes"] == ["description", "project.urls", "dependency-groups"]
    text = (tmp_path / "pyproject.toml").read_text()
    assert 'description = "Acme things."' in text
    assert 'Homepage = "https://github.com/jebel-quant/acme-tool"' in text
    assert "[dependency-groups]" in text
    assert (pkg / "__init__.py").read_text() == '"""acme_tool package."""\n'


def test_finish_skeleton_is_idempotent(tmp_path):
    (tmp_path / "pyproject.toml").write_text(_UV_PYPROJECT)
    kwargs = {"owner": "o", "repo": "r", "host": "github", "description": "d"}
    sk.finish_skeleton(tmp_path, **kwargs)
    first = (tmp_path / "pyproject.toml").read_text()

    second_summary = sk.finish_skeleton(tmp_path, **kwargs)
    assert second_summary["modified"] == []
    assert second_summary["changes"] == []
    assert any("already rhiza-shaped" in n for n in second_summary["notes"])
    assert (tmp_path / "pyproject.toml").read_text() == first


def test_finish_skeleton_uses_the_gitlab_host(tmp_path):
    (tmp_path / "pyproject.toml").write_text(_UV_PYPROJECT)
    sk.finish_skeleton(tmp_path, owner="grp", repo="proj", host="gitlab", description=None)
    assert "https://gitlab.com/grp/proj" in (tmp_path / "pyproject.toml").read_text()


def test_finish_skeleton_without_pyproject_reports_not_ok(tmp_path):
    summary = sk.finish_skeleton(tmp_path, owner="o", repo="r", host="github", description="d")
    assert not summary["ok"]
    assert any("uv init --lib" in n for n in summary["notes"])


def test_finish_skeleton_without_project_table_reports_not_ok(tmp_path):
    (tmp_path / "pyproject.toml").write_text("[build-system]\nrequires = []\n")
    summary = sk.finish_skeleton(tmp_path, owner="o", repo="r", host="github", description="d")
    assert not summary["ok"]
    assert any("no [project] table" in n for n in summary["notes"])


def test_finish_skeleton_flags_absent_authors(tmp_path):
    without = _UV_PYPROJECT.replace(
        'authors = [\n    { name = "A Dev", email = "dev@example.com" }\n]\n', ""
    )
    (tmp_path / "pyproject.toml").write_text(without)
    summary = sk.finish_skeleton(tmp_path, owner="o", repo="r", host="github", description=None)
    assert summary["ok"]
    assert any("authors" in n for n in summary["notes"])


def test_finish_skeleton_does_not_flag_present_authors(tmp_path):
    (tmp_path / "pyproject.toml").write_text(_UV_PYPROJECT)
    summary = sk.finish_skeleton(tmp_path, owner="o", repo="r", host="github", description=None)
    assert not any("authors" in n for n in summary["notes"])


# --- main() / CLI -----------------------------------------------------------


def test_main_json_output(tmp_path, capsys):
    (tmp_path / "pyproject.toml").write_text(_UV_PYPROJECT)
    rc = sk.main([str(tmp_path), "--owner", "o", "--repo", "r", "--json"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"]
    assert "project.urls" in payload["changes"]


def test_main_text_output(tmp_path, capsys):
    (tmp_path / "pyproject.toml").write_text(_UV_PYPROJECT)
    rc = sk.main([str(tmp_path), "--owner", "o", "--repo", "r", "--description", "Text mode."])
    assert rc == 0
    captured = capsys.readouterr()
    assert "modified pyproject.toml" in captured.out
    assert "note" in captured.err


def test_main_exits_1_without_a_pyproject(tmp_path, capsys):
    rc = sk.main([str(tmp_path), "--owner", "o", "--repo", "r"])
    assert rc == 1
    assert "uv init --lib" in capsys.readouterr().err
