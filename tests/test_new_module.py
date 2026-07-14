"""Tests for the `/rhiza:new` module scaffolder (`scripts/new_module.py`)."""

from __future__ import annotations

import ast
import json

import new_module
import pytest


def _pkg(tmp_path, name="mypkg"):
    """Create a src-layout package under tmp_path and return the repo root."""
    (tmp_path / "src" / name).mkdir(parents=True)
    (tmp_path / "src" / name / "__init__.py").write_text("")
    (tmp_path / "tests").mkdir()
    return tmp_path


class TestNewModuleError:
    """Tests for the NewModuleError sentinel (also satisfies layout parity)."""

    def test_is_exception(self):
        """It is a plain Exception subclass carrying a message."""
        err = new_module.NewModuleError("boom")
        assert isinstance(err, Exception)
        assert str(err) == "boom"


def test_valid_identifier():
    assert new_module._valid_identifier("foo")
    assert not new_module._valid_identifier("1foo")
    assert not new_module._valid_identifier("class")  # keyword
    assert not new_module._valid_identifier("a-b")


def test_split_name_variants():
    assert new_module.split_name("parsing") == ["parsing"]
    assert new_module.split_name("utils.parsing") == ["utils", "parsing"]
    assert new_module.split_name("utils/parsing") == ["utils", "parsing"]


def test_split_name_rejects_empty():
    with pytest.raises(new_module.NewModuleError):
        new_module.split_name("...")


def test_split_name_rejects_bad_identifier():
    with pytest.raises(new_module.NewModuleError, match="not a valid Python identifier"):
        new_module.split_name("utils.1bad")


def test_find_package_single(tmp_path):
    repo = _pkg(tmp_path, "solo")
    assert new_module.find_package(repo / "src").name == "solo"


def test_find_package_missing_src(tmp_path):
    with pytest.raises(new_module.NewModuleError, match="does not exist"):
        new_module.find_package(tmp_path / "src")


def test_find_package_empty(tmp_path):
    (tmp_path / "src").mkdir()
    with pytest.raises(new_module.NewModuleError, match="no package directory"):
        new_module.find_package(tmp_path / "src")


def test_find_package_ignores_dunder_and_hidden(tmp_path):
    (tmp_path / "src" / "real").mkdir(parents=True)
    (tmp_path / "src" / "__pycache__").mkdir()
    (tmp_path / "src" / ".hidden").mkdir()
    assert new_module.find_package(tmp_path / "src").name == "real"


def test_find_package_multiple(tmp_path):
    (tmp_path / "src" / "a").mkdir(parents=True)
    (tmp_path / "src" / "b").mkdir(parents=True)
    with pytest.raises(new_module.NewModuleError, match="multiple packages"):
        new_module.find_package(tmp_path / "src")


def test_render_module_with_function():
    body = new_module.render_module("thing module.", ["thing"], [])
    assert body.startswith('"""thing module."""')
    assert "def thing() -> None:" in body
    ast.parse(body)  # must be valid Python


def test_render_module_with_class():
    body = new_module.render_module("thing module.", [], ["Widget"])
    assert "class Widget:" in body
    ast.parse(body)


def test_render_test_with_class_and_func():
    body = new_module.render_test("mypkg.thing", ["thing"], ["Widget"])
    assert "import mypkg.thing" in body
    assert "class TestWidget:" in body
    assert "def test_thing_placeholder():" in body
    ast.parse(body)


def test_new_module_basic(tmp_path):
    repo = _pkg(tmp_path)
    report = new_module.new_module("parsing", repo)
    module = repo / "src" / "mypkg" / "parsing.py"
    # Test path mirrors the module relative to src — including the package dir.
    test = repo / "tests" / "mypkg" / "test_parsing.py"
    assert module.exists() and test.exists()
    assert str(module) in report["created"]
    assert str(test) in report["created"]
    # A class-less module still defines a docstringed placeholder function.
    assert "def parsing() -> None:" in module.read_text()
    assert "import mypkg.parsing" in test.read_text()


def test_new_module_with_class(tmp_path):
    repo = _pkg(tmp_path)
    new_module.new_module("shapes", repo, classes=["Circle"])
    module = (repo / "src" / "mypkg" / "shapes.py").read_text()
    test = (repo / "tests" / "mypkg" / "test_shapes.py").read_text()
    assert "class Circle:" in module
    assert "def parsing" not in module  # no placeholder func when a class is given
    assert "class TestCircle:" in test


def test_new_module_nested_creates_init_files(tmp_path):
    repo = _pkg(tmp_path)
    new_module.new_module("utils.parsing", repo)
    assert (repo / "src" / "mypkg" / "utils" / "__init__.py").exists()
    assert (repo / "src" / "mypkg" / "utils" / "parsing.py").exists()
    assert (repo / "tests" / "mypkg" / "utils" / "test_parsing.py").exists()


def test_new_module_skips_existing(tmp_path):
    repo = _pkg(tmp_path)
    new_module.new_module("parsing", repo)
    report = new_module.new_module("parsing", repo)  # second run
    assert report["created"] == []
    assert any("parsing.py" in p for p in report["skipped"])


def test_new_module_rejects_bad_class(tmp_path):
    repo = _pkg(tmp_path)
    with pytest.raises(new_module.NewModuleError, match="not a valid class name"):
        new_module.new_module("shapes", repo, classes=["1Bad"])


def test_main_human_output(tmp_path, capsys):
    repo = _pkg(tmp_path)
    rc = new_module.main(["parsing", str(repo)])
    out = capsys.readouterr().out
    assert rc == 0
    assert "Created for 'parsing':" in out
    assert "parsing.py" in out


def test_main_json_output(tmp_path, capsys):
    repo = _pkg(tmp_path)
    rc = new_module.main(["parsing", str(repo), "--json", "--class", "Widget"])
    payload = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert any("shapes" not in p and "parsing.py" in p for p in payload["created"])


def test_main_nothing_to_create(tmp_path, capsys):
    repo = _pkg(tmp_path)
    new_module.main(["parsing", str(repo)])
    capsys.readouterr()  # discard first run
    new_module.main(["parsing", str(repo)])
    assert "Nothing to create" in capsys.readouterr().out


def test_main_skipped_reported(tmp_path, capsys):
    repo = _pkg(tmp_path)
    # Pre-create the test file so the second target is skipped but the module is created.
    (repo / "tests" / "mypkg").mkdir()
    (repo / "tests" / "mypkg" / "test_parsing.py").write_text("x = 1\n")
    new_module.main(["parsing", str(repo)])
    out = capsys.readouterr().out
    assert "Skipped (already present):" in out


def test_main_usage_error_returns_one(tmp_path, capsys):
    (tmp_path / "src").mkdir()  # no package under src
    rc = new_module.main(["parsing", str(tmp_path)])
    assert rc == 1
    assert "error:" in capsys.readouterr().err
