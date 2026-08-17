"""Tests for the uv/pyproject finisher (`scripts/_skeleton_python.py`).

`uv init --lib` creates the project; this module closes the gap between that and the
`[project]` shape the rhiza template's synced pyproject gate requires. It must be
idempotent, additive, and must never write a `classifiers` key.
"""

from __future__ import annotations

import _skeleton_python as py
import pytest

# `pyproject.toml` exactly as `uv init --lib --python 3.12` leaves it.
UV_PYPROJECT = """\
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
UV_INIT = 'def hello() -> str:\n    return "Hello from acme-tool!"\n'

_WITHOUT_AUTHORS = UV_PYPROJECT.replace(
    'authors = [\n    { name = "A Dev", email = "dev@example.com" }\n]\n', ""
)


# --- is_uv_placeholder_init --------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (UV_INIT, True),
        ('def hello() -> str:\n\n    return "Hello from x!"\n', True),  # blank lines ignored
        ('"""acme_tool package."""\n', False),  # already normalised
        ("", False),  # empty file is not the placeholder
        (UV_INIT + "\nimport os\n", False),  # user added something
        ('def hello() -> str:\n    return "Hello!"\n\ndef other() -> None:\n    pass\n', False),
    ],
)
def test_is_uv_placeholder_init(text, expected):
    assert py.is_uv_placeholder_init(text) is expected


# --- normalize_package_init --------------------------------------------------


def test_normalize_package_init_rewrites_placeholder(tmp_path):
    pkg = tmp_path / "src" / "acme_tool"
    pkg.mkdir(parents=True)
    (pkg / "__init__.py").write_text(UV_INIT, encoding="utf-8")
    assert py.normalize_package_init(tmp_path) == ["src/acme_tool/__init__.py"]
    assert (pkg / "__init__.py").read_text(encoding="utf-8") == '"""acme_tool package."""\n'


def test_normalize_package_init_leaves_real_code_alone(tmp_path):
    pkg = tmp_path / "src" / "acme_tool"
    pkg.mkdir(parents=True)
    real = '"""My own docstring."""\n\nVERSION = "1"\n'
    (pkg / "__init__.py").write_text(real, encoding="utf-8")
    assert py.normalize_package_init(tmp_path) == []
    assert (pkg / "__init__.py").read_text(encoding="utf-8") == real


def test_normalize_package_init_without_src(tmp_path):
    assert py.normalize_package_init(tmp_path) == []


# --- set_authors -------------------------------------------------------------


def test_set_authors_inserts_when_uv_omitted_the_key():
    """`uv init` writes no `authors` at all when git has no configured identity."""
    out, changed = py.set_authors(_WITHOUT_AUTHORS, name="Ada", email="ada@example.com")
    assert changed
    assert 'authors = [{ name = "Ada", email = "ada@example.com" }]' in out


def test_set_authors_replaces_uvs_empty_list():
    empty = UV_PYPROJECT.replace(
        'authors = [\n    { name = "A Dev", email = "dev@example.com" }\n]', "authors = []"
    )
    out, changed = py.set_authors(empty, name="Ada", email=None)
    assert changed
    assert 'authors = [{ name = "Ada" }]' in out
    assert "authors = []" not in out


def test_set_authors_leaves_a_real_author_alone():
    """A hand-written author is the user's; the gate only needs one to exist.

    uv writes it as a multi-line array, so the line the scan matches is `authors = [` —
    which must read as "the user's", not as an empty list to replace.
    """
    out, changed = py.set_authors(UV_PYPROJECT, name="Ada", email="ada@example.com")
    assert not changed
    assert out == UV_PYPROJECT
    assert "Ada" not in out


def test_set_authors_omits_an_absent_email():
    out, _ = py.set_authors(_WITHOUT_AUTHORS, name="jebel-quant", email=None)
    assert 'authors = [{ name = "jebel-quant" }]' in out
    assert "email" not in out.split("authors")[1].split("]")[0]


def test_set_authors_preserves_missing_trailing_newline():
    out, changed = py.set_authors(_WITHOUT_AUTHORS.rstrip("\n"), name="Ada", email=None)
    assert changed
    assert not out.endswith("\n")


# --- set_description ---------------------------------------------------------


def test_set_description_replaces_uv_placeholder():
    out, changed = py.set_description(UV_PYPROJECT, "Does acme things.")
    assert changed
    assert 'description = "Does acme things."' in out
    assert "Add your description here" not in out


def test_set_description_keeps_a_real_description():
    written = UV_PYPROJECT.replace("Add your description here", "Hand-written.")
    out, changed = py.set_description(written, "Something else.")
    assert not changed
    assert out == written


def test_set_description_inserts_when_absent():
    without = UV_PYPROJECT.replace('description = "Add your description here"\n', "")
    out, changed = py.set_description(without, "Freshly added.")
    assert changed
    assert 'description = "Freshly added."' in out


def test_set_description_preserves_missing_trailing_newline():
    out, changed = py.set_description(UV_PYPROJECT.rstrip("\n"), "No newline.")
    assert changed
    assert not out.endswith("\n")


def test_set_description_requires_project_table():
    with pytest.raises(ValueError):
        py.set_description("[build-system]\nrequires = []\n", "x")


def test_set_description_escapes_a_value_that_would_break_the_toml():
    """A quote in the description must not terminate the string early."""
    out, changed = py.set_description(UV_PYPROJECT, 'A "quoted" thing.')
    assert changed
    assert r'description = "A \"quoted\" thing."' in out


# --- set_project_urls --------------------------------------------------------


def test_set_project_urls_appends_the_table():
    out, changed = py.set_project_urls(UV_PYPROJECT, "https://h/o/r", "https://r/o/r")
    assert changed
    assert "[project.urls]" in out
    assert 'Homepage = "https://h/o/r"' in out
    assert 'Repository = "https://r/o/r"' in out


def test_set_project_urls_adds_only_missing_keys():
    partial = UV_PYPROJECT + '\n[project.urls]\nHomepage = "https://kept"\n'
    out, changed = py.set_project_urls(partial, "https://new", "https://repo")
    assert changed
    assert 'Homepage = "https://kept"' in out  # existing entry wins
    assert "https://new" not in out
    assert 'Repository = "https://repo"' in out


def test_set_project_urls_is_idempotent():
    once, _ = py.set_project_urls(UV_PYPROJECT, "https://h", "https://r")
    twice, changed = py.set_project_urls(once, "https://h", "https://r")
    assert not changed
    assert twice == once


def test_set_project_urls_collapses_trailing_blank_lines():
    """An appended table gets exactly one blank line before it, not a pile of them."""
    out, changed = py.set_project_urls(UV_PYPROJECT + "\n\n\n", "https://h", "https://r")
    assert changed
    assert 'build-backend = "uv_build"\n\n[project.urls]' in out


def test_set_project_urls_preserves_missing_trailing_newline():
    out, changed = py.set_project_urls(UV_PYPROJECT.rstrip("\n"), "https://h", "https://r")
    assert changed
    assert not out.endswith("\n")


# --- set_dependency_groups ---------------------------------------------------


def test_set_dependency_groups_appends_the_table():
    out, changed = py.set_dependency_groups(UV_PYPROJECT)
    assert changed
    assert "[dependency-groups]" in out
    assert "pytest>=8.0" in out
    assert "pytest-cov>=5.0" in out


def test_set_dependency_groups_leaves_an_existing_group_untouched():
    partial = UV_PYPROJECT + '\n[dependency-groups]\ntest = ["pytest>=7.0"]\n'
    out, changed = py.set_dependency_groups(partial)
    assert not changed
    assert 'test = ["pytest>=7.0"]' in out  # existing group untouched
    assert out.count("test = ") == 1


def test_set_dependency_groups_fills_test_into_an_existing_table():
    # The table exists but declares something else entirely, so `test` has to be added
    # *into* it rather than appended with a fresh header.
    other = UV_PYPROJECT + '\n[dependency-groups]\ndocs = ["mkdocs>=1.6"]\n'
    out, changed = py.set_dependency_groups(other)
    assert changed
    assert out.count("[dependency-groups]") == 1
    assert 'docs = ["mkdocs>=1.6"]' in out  # unrelated group untouched
    assert "pytest>=8.0" in out


def test_set_dependency_groups_is_idempotent():
    once, _ = py.set_dependency_groups(UV_PYPROJECT)
    twice, changed = py.set_dependency_groups(once)
    assert not changed
    assert twice == once


def test_set_dependency_groups_preserves_missing_trailing_newline():
    out, changed = py.set_dependency_groups(UV_PYPROJECT.rstrip("\n"))
    assert changed
    assert not out.endswith("\n")


def test_dependency_group_requirements_are_lower_bounded():
    for deps in py._DEPENDENCY_GROUPS.values():
        for dep in deps:
            assert ">=" in dep, f"{dep} must carry a lower bound"


# --- apply_pyproject ---------------------------------------------------------


def test_apply_pyproject_records_every_edit_in_order():
    changes: list[str] = []
    py.apply_pyproject(
        UV_PYPROJECT, changes, url="https://h/o/r", description="d",
        author_name="Ada", author_email=None,
    )  # fmt: skip
    # `authors` is absent: uv's manifest already names one.
    assert changes == ["description", "project.urls", "dependency-groups"]


def test_apply_pyproject_keeps_the_keys_it_wrote_before_a_later_edit_raised():
    """Reporting "nothing changed" after a partial edit would misdescribe the file.

    With no `[project]` table, the url and dependency-group edits still append their own
    tables, and only `set_authors` raises. Those two writes happened.
    """
    changes: list[str] = []
    with pytest.raises(ValueError):
        py.apply_pyproject(
            "[build-system]\nrequires = []\n", changes, url="https://h", description=None,
            author_name="Ada", author_email=None,
        )  # fmt: skip
    assert changes == ["project.urls", "dependency-groups"]


# --- finish_python -----------------------------------------------------------


def test_finish_python_reports_an_absent_manifest(tmp_path):
    result = py.finish_python(
        tmp_path, owner="o", repo="r", domain="github.com", description="d",
        modified=[], notes=[],
    )  # fmt: skip
    assert result["ok"] is False
    assert any("uv init --lib" in note for note in result["notes"])


def test_finish_python_never_writes_classifiers(tmp_path):
    """Classifiers belong to /python-version (Python) and nobody (License ::).

    PEP 639 replaced `License :: …` with the SPDX `license` field, so neither this
    module nor /rhiza:license may write one — even though the template's pyproject
    gate still asserts it.
    """
    (tmp_path / "pyproject.toml").write_text(UV_PYPROJECT, encoding="utf-8")
    py.finish_python(
        tmp_path, owner="o", repo="r", domain="github.com", description="d",
        modified=[], notes=[],
    )  # fmt: skip
    text = (tmp_path / "pyproject.toml").read_text(encoding="utf-8")
    assert "classifiers" not in text
    assert "License ::" not in text
