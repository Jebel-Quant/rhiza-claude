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


def test_benchmarks_and_stress_are_exempt(tmp_path):
    src, tests = tmp_path / "src", tmp_path / "tests"
    src.mkdir()
    # Free-standing test files with no mirrored source — normally orphans.
    _write(tests / "benchmarks" / "test_speed.py", "def test_x():\n    pass\n")
    _write(tests / "stress" / "test_load.py", "class TestGhost:\n    pass\n")
    assert ctl.check(src, tests) == []


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


# --- configuration & opt-out --------------------------------------------------


def test_coerce_scalar():
    assert ctl._coerce_scalar('"hello"') == "hello"
    assert ctl._coerce_scalar("'hello'") == "hello"
    assert ctl._coerce_scalar('"tail # not a comment"') == "tail # not a comment"
    assert ctl._coerce_scalar("true") is True
    assert ctl._coerce_scalar("false  # inline comment") is False
    assert ctl._coerce_scalar("bare") == "bare"
    assert ctl._coerce_scalar('[ "a", "b" ]') == ["a", "b"]
    assert ctl._coerce_scalar("[]") == []
    assert ctl._coerce_scalar('"unterminated') == "unterminated"
    assert ctl._coerce_scalar('["unterminated') == ["unterminated"]


def test_parse_flat_section():
    text = (
        "# comment\n"
        "[project]\n"
        'name = "x"\n'
        "\n"
        "[tool.check_test_layout]\n"
        "enforce = false\n"
        "# a comment line\n"
        'reason = "grouped by behaviour"\n'
        'exempt_dirs = ["integration"]\n'
        "\n"
        "[tool.other]\n"
        "ignored = true\n"
    )
    section = ctl._parse_flat_section(text, "tool.check_test_layout")
    assert section == {
        "enforce": False,
        "reason": "grouped by behaviour",
        "exempt_dirs": ["integration"],
    }


def test_read_config_absent(tmp_path):
    assert ctl._read_config(tmp_path / "pyproject.toml") == {}


def test_read_config_via_tomllib(tmp_path):
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(
        '[tool.check_test_layout]\nenforce = false\nreason = "behaviour-grouped"\n'
    )
    assert ctl._read_config(pyproject) == {"enforce": False, "reason": "behaviour-grouped"}


def test_read_config_no_section(tmp_path):
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text('[project]\nname = "x"\n')
    assert ctl._read_config(pyproject) == {}


def test_read_config_section_not_a_table(tmp_path):
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text('[tool]\ncheck_test_layout = "oops"\n')
    assert ctl._read_config(pyproject) == {}


def test_read_config_malformed_toml(tmp_path):
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text("this is = = not toml [\n")
    assert ctl._read_config(pyproject) == {}


def test_read_config_fallback_without_tomllib(tmp_path, monkeypatch):
    monkeypatch.setattr(ctl, "tomllib", None)
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(
        '[tool.check_test_layout]\nenforce = false\nreason = "behaviour-grouped"\n'
    )
    assert ctl._read_config(pyproject) == {"enforce": False, "reason": "behaviour-grouped"}


def test_exempt_dirs_extends_defaults():
    assert ctl._exempt_dirs({}) == {"benchmarks", "stress"}
    assert ctl._exempt_dirs({"exempt_dirs": ["integration"]}) == {
        "benchmarks",
        "stress",
        "integration",
    }
    # Non-list values are ignored rather than raising.
    assert ctl._exempt_dirs({"exempt_dirs": "nope"}) == {"benchmarks", "stress"}


def test_check_respects_config_exempt_dirs(tmp_path):
    src, tests = tmp_path / "src", tmp_path / "tests"
    src.mkdir()
    _write(tests / "integration" / "test_flow.py", "def test_x():\n    pass\n")
    # Without config the free-standing test is an orphan; the exemption clears it.
    assert any("orphan test file" in e for e in ctl.check(src, tests))
    assert ctl.check(src, tests, {"exempt_dirs": ["integration"]}) == []


# --- template-owned tests (jebel-quant/rhiza#1489) ----------------------------


def _synced(tmp_path, *files):
    """Write a `.rhiza/template.lock` tracking *files* and return its path."""
    lock = tmp_path / ".rhiza" / "template.lock"
    listing = "".join(f"- {f}\n" for f in files)
    _write(
        lock,
        "sha: abc123\nrepo: jebel-quant/rhiza\nexclude: []\n"
        f"files:\n{listing}"
        'synced_at: "2026-08-04"\nstrategy: merge\n',
    )
    return lock


def test_lock_files_reads_the_block_sequence(tmp_path):
    lock = _synced(tmp_path, ".bandit", "tests/test_rhiza_packaging.py")
    assert ctl._lock_files(lock) == [".bandit", "tests/test_rhiza_packaging.py"]


def test_lock_files_tolerates_quotes_comments_and_other_keys(tmp_path):
    lock = tmp_path / "template.lock"
    _write(
        lock,
        "# a comment\n"
        "exclude:\n- bundles/github/x.yml\n"
        "files:\n"
        '- "quoted.py"\n'
        "# mid-block comment\n"
        "- 'single.py'\n"
        "synced_at: now\n"
        "- not-a-file\n",  # after the block closed: not ours
    )
    assert ctl._lock_files(lock) == ["quoted.py", "single.py"]


def test_lock_files_empty_when_absent_inline_or_unreadable(tmp_path):
    assert ctl._lock_files(tmp_path / "nope.lock") == []
    assert ctl._lock_files(tmp_path) == []  # a directory: OSError, not a crash
    inline = tmp_path / "inline.lock"
    _write(inline, "files: []\nsynced_at: now\n")
    assert ctl._lock_files(inline) == []
    no_key = tmp_path / "nokey.lock"
    _write(no_key, "sha: abc\n")
    assert ctl._lock_files(no_key) == []


def test_template_owned_resolves_against_the_repo_root(tmp_path):
    lock = _synced(tmp_path, "tests/test_rhiza_packaging.py")
    # `.rhiza/template.lock` -> the repo root is the lock's grandparent.
    assert ctl._template_owned(lock) == {(tmp_path / "tests/test_rhiza_packaging.py").resolve()}
    # An explicit --lock elsewhere resolves against its own directory instead.
    loose = tmp_path / "elsewhere" / "template.lock"
    _write(loose, "files:\n- tests/test_x.py\n")
    assert ctl._template_owned(loose) == {(loose.parent / "tests/test_x.py").resolve()}


def test_template_owned_test_file_is_not_an_orphan(tmp_path):
    src, tests = tmp_path / "src", tmp_path / "tests"
    src.mkdir()
    # Exactly rhiza v1.3.2's synced starter test: no src/rhiza_packaging.py exists,
    # and none ever will — it tests packaging metadata, not a source module.
    _write(tests / "test_rhiza_packaging.py", "def test_version():\n    pass\n")
    assert any("orphan test file" in e for e in ctl.check(src, tests))
    owned = ctl._template_owned(_synced(tmp_path, "tests/test_rhiza_packaging.py"))
    assert ctl.check(src, tests, None, owned) == []


def test_the_exemption_does_not_cover_the_repos_own_tests(tmp_path):
    src, tests = tmp_path / "src", tmp_path / "tests"
    src.mkdir()
    _write(tests / "test_rhiza_packaging.py", "def test_version():\n    pass\n")
    _write(tests / "test_ghost.py", "class TestGone:\n    pass\n")
    owned = ctl._template_owned(_synced(tmp_path, "tests/test_rhiza_packaging.py"))
    errors = ctl.check(src, tests, None, owned)
    assert [e for e in errors if "test_ghost.py" in e]
    assert not [e for e in errors if "test_rhiza_packaging.py" in e]


def test_main_exempts_template_owned_tests(tmp_path, capsys):
    src, tests = tmp_path / "src", tmp_path / "tests"
    src.mkdir()
    _write(tests / "test_rhiza_packaging.py", "def test_version():\n    pass\n")
    lock = _synced(tmp_path, "tests/test_rhiza_packaging.py")
    argv = ["--src", str(src), "--tests", str(tests), "--config", str(tmp_path / "pyproject.toml")]
    assert ctl.main([*argv, "--lock", str(tmp_path / "missing.lock")]) == 1
    assert ctl.main([*argv, "--lock", str(lock)]) == 0
    assert "Test layout OK" in capsys.readouterr().out


def test_main_without_a_lock_is_unchanged(tmp_path, capsys):
    """The default --lock points at a file most repos do not have; that must be fine."""
    src, tests = tmp_path / "src", tmp_path / "tests"
    _write(src / "foo.py", "class Bar:\n    pass\n")
    _write(tests / "test_foo.py", "class TestBar:\n    pass\n")
    assert ctl.main(["--src", str(src), "--tests", str(tests)]) == 0
    assert "tests mirror sources 1:1" in capsys.readouterr().out


def test_unquote():
    assert ctl._unquote(' "a.py" ') == "a.py"
    assert ctl._unquote("'a.py'") == "a.py"
    assert ctl._unquote("a.py") == "a.py"
    assert ctl._unquote('"') == '"'  # a lone quote is not a matching pair


def test_main_enforce_false_ok(tmp_path, capsys):
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(
        '[tool.check_test_layout]\nenforce = false\nreason = "behaviour-grouped suite"\n'
    )
    assert ctl.main(["--src", str(tmp_path / "src"), "--config", str(pyproject)]) == 0
    out = capsys.readouterr().out
    assert "parity not enforced" in out
    assert "behaviour-grouped suite" in out


def test_main_enforce_false_requires_reason(tmp_path, capsys):
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text("[tool.check_test_layout]\nenforce = false\n")
    assert ctl.main(["--config", str(pyproject)]) == 1
    assert "requires a non-empty 'reason'" in capsys.readouterr().err
