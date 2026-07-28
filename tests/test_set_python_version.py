"""Tests for the Python-version engine (`scripts/set_python_version.py`).

Behind `/rhiza:python-version`. Enforces the supported floor: only 3.11–3.14 are
valid; 3.9/3.10 (and a bare `:: 3`) are rejected or scrubbed.
"""

from __future__ import annotations

import json

import pytest
import set_python_version as sp

_PYPROJECT = """\
[project]
name = "widget"
version = "0.1.0"
requires-python = ">=3.9"
dependencies = []

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"
"""

# A pyproject already carrying stale + non-Python classifiers.
_WITH_CLASSIFIERS = """\
[project]
name = "widget"
requires-python = ">=3.9"
classifiers = [
    "Programming Language :: Python :: 3",
    "Programming Language :: Python :: 3.9",
    "Programming Language :: Python :: 3.11",
    "Typing :: Typed",
]
dependencies = []
"""


# --- classifiers ------------------------------------------------------------


def test_classifiers_list_from_version_upward_never_bare_3():
    assert sp.python_version_classifiers("3.12") == [
        "Programming Language :: Python :: 3.12",
        "Programming Language :: Python :: 3.13",
        "Programming Language :: Python :: 3.14",
    ]
    assert "Programming Language :: Python :: 3" not in sp.python_version_classifiers("3.11")


@pytest.mark.parametrize("bad", ["3.9", "3.10", "3", "4.0"])
def test_classifiers_reject_unsupported(bad):
    with pytest.raises(ValueError):
        sp.python_version_classifiers(bad)


# --- apply_python_metadata --------------------------------------------------


def test_apply_inserts_when_absent():
    out, changes = sp.apply_python_metadata(_PYPROJECT, "3.12")
    assert 'requires-python = ">=3.12"' in out
    assert ">=3.9" not in out  # legacy floor corrected
    assert "Programming Language :: Python :: 3.12" in out
    assert set(changes) == {"requires-python", "classifiers"}


def test_apply_retargets_and_scrubs_stale(tmp_path):
    out, changes = sp.apply_python_metadata(_WITH_CLASSIFIERS, "3.13")
    assert 'requires-python = ">=3.13"' in out
    # stale + unsupported Python classifiers scrubbed
    assert "Python :: 3.9" not in out
    assert '"Programming Language :: Python :: 3"' not in out
    assert "Python :: 3.11" not in out
    # supported range added, non-Python classifier preserved
    assert "Python :: 3.13" in out
    assert "Python :: 3.14" in out
    assert "Typing :: Typed" in out
    assert "classifiers" in changes


def test_apply_is_idempotent():
    once, _ = sp.apply_python_metadata(_PYPROJECT, "3.12")
    twice, changes = sp.apply_python_metadata(once, "3.12")
    assert twice == once
    assert changes == []


def test_apply_rejects_unsupported_version():
    with pytest.raises(ValueError):
        sp.apply_python_metadata(_PYPROJECT, "3.10")


def test_apply_requires_a_project_table():
    with pytest.raises(ValueError, match=r"no \[project\] table"):
        sp.apply_python_metadata("[build-system]\nrequires = []\n", "3.12")


def test_apply_inserts_requires_python_when_the_key_is_absent():
    without = _PYPROJECT.replace('requires-python = ">=3.9"\n', "")
    out, changes = sp.apply_python_metadata(without, "3.12")
    assert 'requires-python = ">=3.12"' in out
    assert "requires-python" in changes


def test_apply_handles_a_single_line_classifiers_array():
    """`classifiers = ["a", "b"]` on one line must be rewritten, not duplicated."""
    single = _PYPROJECT.replace(
        "dependencies = []",
        'classifiers = ["Typing :: Typed", "Programming Language :: Python :: 3.9"]\n'
        "dependencies = []",
    )
    out, changes = sp.apply_python_metadata(single, "3.13")
    assert out.count("classifiers = [") == 1
    assert "Typing :: Typed" in out  # non-Python entry preserved
    assert "Python :: 3.9" not in out  # stale entry scrubbed
    assert "Python :: 3.13" in out
    assert "classifiers" in changes


def test_apply_tolerates_an_unterminated_classifiers_array():
    """A malformed array with no closing `]` must not hang or crash."""
    broken = _PYPROJECT.replace(
        "dependencies = []", 'classifiers = [\n    "Typing :: Typed",\ndependencies = []'
    )
    out, changes = sp.apply_python_metadata(broken, "3.12")
    assert "Python :: 3.12" in out
    assert "classifiers" in changes


# --- set_python_version() end to end ----------------------------------------


def test_set_python_version_writes_pyproject(tmp_path):
    (tmp_path / "pyproject.toml").write_text(_PYPROJECT)
    summary = sp.set_python_version(tmp_path, python_version="3.12")
    assert "pyproject.toml" in summary["modified"]
    assert 'requires-python = ">=3.12"' in (tmp_path / "pyproject.toml").read_text()


def test_set_python_version_no_pyproject_notes(tmp_path):
    summary = sp.set_python_version(tmp_path, python_version="3.12")
    assert summary["modified"] == []
    assert any("absent" in n for n in summary["notes"])


def test_set_python_version_notes_a_malformed_pyproject(tmp_path):
    """No `[project]` table is reported, not raised — nothing is written."""
    (tmp_path / "pyproject.toml").write_text("[build-system]\nrequires = []\n")
    summary = sp.set_python_version(tmp_path, python_version="3.12")
    assert summary["modified"] == []
    assert any("no [project] table" in n for n in summary["notes"])


def test_set_python_version_is_idempotent(tmp_path):
    """A second run reports 'already up to date' and rewrites nothing."""
    (tmp_path / "pyproject.toml").write_text(_PYPROJECT)
    sp.set_python_version(tmp_path, python_version="3.12")
    first = (tmp_path / "pyproject.toml").read_text()

    summary = sp.set_python_version(tmp_path, python_version="3.12")
    assert summary["modified"] == []
    assert any("already up to date" in n for n in summary["notes"])
    assert (tmp_path / "pyproject.toml").read_text() == first


# --- main() / CLI -----------------------------------------------------------


def test_main_rejects_unsupported_version(tmp_path):
    with pytest.raises(SystemExit):
        sp.main([str(tmp_path), "--python-version", "3.10"])


def test_main_json(tmp_path, capsys):
    (tmp_path / "pyproject.toml").write_text(_PYPROJECT)
    rc = sp.main([str(tmp_path), "--python-version", "3.13", "--json"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["python_version"] == "3.13"
    assert "pyproject.toml" in payload["modified"]


def test_main_text_output(tmp_path, capsys):
    """Text mode prints the modified paths on stdout and notes on stderr."""
    (tmp_path / "pyproject.toml").write_text(_PYPROJECT)
    rc = sp.main([str(tmp_path), "--python-version", "3.12"])
    assert rc == 0
    captured = capsys.readouterr()
    assert "modified pyproject.toml" in captured.out
    assert "note" in captured.err
