"""Tests for the test-layout checker (`scripts/check_test_layout.py`)."""

from __future__ import annotations

import check_test_layout as ctl


def _write(path, text=""):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def test_top_level_classes(tmp_path):
    f = tmp_path / "m.py"
    f.write_text("class A:\n    pass\n\n\ndef g():\n    pass\n")
    assert ctl._top_level_classes(f) == {"A"}


def test_discovery_ignores_dunder_and_conftest(tmp_path):
    src = tmp_path / "src"
    _write(src / "a.py")
    _write(src / "__init__.py")
    _write(src / "conftest.py")
    tests = tmp_path / "tests"
    _write(tests / "test_a.py")
    _write(tests / "conftest.py")
    assert [p.name for p in ctl._source_modules(src)] == ["a.py"]
    assert [p.name for p in ctl._test_files(tests)] == ["test_a.py"]


def test_clean_layout_has_no_errors(tmp_path):
    src, tests = tmp_path / "src", tmp_path / "tests"
    _write(src / "pkg" / "foo.py", "class Bar:\n    pass\n")  # nested mirroring
    _write(tests / "pkg" / "test_foo.py", "class TestBar:\n    pass\n")
    assert ctl.check(src, tests) == []


def test_missing_test_file(tmp_path):
    src, tests = tmp_path / "src", tmp_path / "tests"
    _write(src / "foo.py", "x = 1\n")
    tests.mkdir()
    assert any("missing test file" in e for e in ctl.check(src, tests))


def test_missing_test_class(tmp_path):
    src, tests = tmp_path / "src", tmp_path / "tests"
    _write(src / "foo.py", "class Bar:\n    pass\n")
    _write(tests / "test_foo.py", "def test_x():\n    pass\n")
    assert any("missing class TestBar" in e for e in ctl.check(src, tests))


def test_orphan_test_file(tmp_path):
    src, tests = tmp_path / "src", tmp_path / "tests"
    src.mkdir()
    _write(tests / "test_ghost.py", "def test_x():\n    pass\n")
    assert any("orphan test file" in e for e in ctl.check(src, tests))


def test_orphan_test_class(tmp_path):
    src, tests = tmp_path / "src", tmp_path / "tests"
    _write(src / "foo.py", "x = 1\n")
    _write(tests / "test_foo.py", "class TestBar:\n    pass\n")
    assert any("orphan test class TestBar" in e for e in ctl.check(src, tests))


def test_main_ok(tmp_path, capsys):
    src, tests = tmp_path / "src", tmp_path / "tests"
    _write(src / "foo.py", "class Bar:\n    pass\n")
    _write(tests / "test_foo.py", "class TestBar:\n    pass\n")
    assert ctl.main(["--src", str(src), "--tests", str(tests)]) == 0
    assert "Test layout OK" in capsys.readouterr().out


def test_main_reports_and_fails(tmp_path, capsys):
    src, tests = tmp_path / "src", tmp_path / "tests"
    _write(src / "foo.py", "x = 1\n")
    tests.mkdir()
    assert ctl.main(["--src", str(src), "--tests", str(tests)]) == 1
    assert "check failed" in capsys.readouterr().err
