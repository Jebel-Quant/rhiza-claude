"""Tests for the docstring half of the example checker (`scripts/_doc_examples_source.py`).

The run-mode tests really write modules and really import them, because the failure this
guards against — a docstring claiming 7 where the code returns 6 — exists only at
execution time. The inventory tests deliberately do the opposite: they assert that
examples are *found* with no import at all, which is what lets the first pass work in an
interpreter that has none of the project's dependencies.

The third theme is the one that keeps a partial run honest: an unimportable module is
counted as unmeasured, never as a pass and never as a failure.
"""

from __future__ import annotations

import sys
from pathlib import Path

import _doc_examples_source as src
import pytest


def module_with(root: Path, name: str, body: str) -> Path:
    """Write a module under *root* and return its path."""
    path = root / f"{name}.py"
    path.write_text(body, encoding="utf-8")
    return path


# --- inventory ----------------------------------------------------------------


def test_docstring_examples_finds_them_without_importing(tmp_path: Path):
    """`ast` plus `DocTestParser`, so this pass works with the dependencies absent."""
    path = module_with(
        tmp_path,
        "mod",
        '"""Module.\n\n>>> 1 + 1\n2\n"""\n\n\ndef f():\n    """Doc.\n\n'
        '    >>> f()\n    1\n    """\n    return 1\n',
    )
    found, problems = src.docstring_examples(path)
    assert problems == []
    assert {(item["object"], item["examples"]) for item in found} == {("<module>", 1), ("f", 1)}


def test_docstring_examples_reports_a_malformed_example(tmp_path: Path):
    """A doctest that cannot even be parsed is broken before anything runs it."""
    path = module_with(tmp_path, "bad", '"""Doc.\n\n    >>> 1 + 1\n2\n    """\n')
    found, problems = src.docstring_examples(path)
    assert found == []
    assert "malformed doctest" in problems[0]


def test_docstring_examples_reports_a_file_that_does_not_parse(tmp_path: Path):
    """A source file that isn't Python is a violation, not a crash."""
    path = module_with(tmp_path, "broken", "def f(:\n")
    found, problems = src.docstring_examples(path)
    assert found == [] and "does not parse" in problems[0]


def test_docstring_examples_ignores_docstring_free_code(tmp_path: Path):
    """Undocumented code is `docs-coverage`'s business, not this checker's."""
    path = module_with(tmp_path, "plain", "x = 1\n\n\nclass A:\n    pass\n")
    assert src.docstring_examples(path) == ([], [])


def test_source_files_skips_vendored_and_test_trees(tmp_path: Path):
    """A source root of `.` reaches `.venv` and `tests`; importing either would be wrong."""
    module_with(tmp_path, "keep", "")
    for skipped in (".venv", "tests"):
        (tmp_path / skipped).mkdir()
        module_with(tmp_path / skipped, "drop", "")
    assert [p.name for p in src.source_files(tmp_path)] == ["keep.py"]


# --- execution ----------------------------------------------------------------


def test_run_doctests_passes_on_a_true_example(tmp_path: Path):
    """The happy path: the example evaluates to what the docstring claims."""
    path = module_with(tmp_path, "dt_true", '"""Doc.\n\n>>> 2 * 3\n6\n"""\n')
    result = src.run_doctests(tmp_path, [path])
    assert (result["attempted"], result["failed"]) == (1, 0)


def test_run_doctests_fails_on_a_stale_example(tmp_path: Path):
    """The whole point of the gate: a docstring that says 7 where the code says 6."""
    path = module_with(tmp_path, "dt_stale", '"""Doc.\n\n>>> 2 * 3\n7\n"""\n')
    result = src.run_doctests(tmp_path, [path])
    assert result["failed"] == 1
    assert "dt_stale" in result["failures"][0]


def test_run_doctests_reports_an_unimportable_module_as_unmeasured(tmp_path: Path):
    """A missing dependency is a fact about the environment, never a doc defect."""
    path = module_with(tmp_path, "dt_import", "import definitely_not_a_real_package\n")
    result = src.run_doctests(tmp_path, [path])
    assert result["failures"] == []
    assert "dt_import" in result["unimportable"][0]


def test_run_doctests_leaves_sys_path_as_it_found_it(tmp_path: Path):
    """The import path is borrowed for the run, not kept."""
    before = list(sys.path)
    src.run_doctests(tmp_path, [])
    assert sys.path == before


# --- the report ---------------------------------------------------------------


def test_docstring_report_marks_a_missing_source_root_out_of_scope(tmp_path: Path):
    """No source root is not a failure — say so and score it out of scope."""
    report = src.docstring_report(tmp_path / "src", run=False)
    assert report["present"] is False and report["violations"] == []


def test_docstring_report_names_the_silence_when_there_are_no_examples(tmp_path: Path):
    """Zero examples reads as a pass unless something says otherwise."""
    module_with(tmp_path, "plain", '"""Doc, no example."""\n')
    report = src.docstring_report(tmp_path, run=False)
    assert report["examples"] == 0
    assert "no doctest examples found" in report["notes"][0]


def test_docstring_report_says_when_examples_were_found_but_not_run(tmp_path: Path):
    """Parsed is not passed, and the note keeps the two apart."""
    module_with(tmp_path, "dt_notrun", '"""Doc.\n\n>>> 1\n1\n"""\n')
    report = src.docstring_report(tmp_path, run=False)
    assert "not run" in report["notes"][0]
    assert "execution" not in report


def test_docstring_report_runs_them_under_run(tmp_path: Path):
    """With --run the examples execute and their failures become violations."""
    module_with(tmp_path, "dt_run_bad", '"""Doc.\n\n>>> 1 + 1\n3\n"""\n')
    report = src.docstring_report(tmp_path, run=True)
    assert report["execution"]["failed"] == 1
    assert report["violations"]


def test_docstring_report_notes_unimportable_modules_after_a_run(tmp_path: Path):
    """The unmeasured half is stated, so a partial run cannot read as a full one."""
    module_with(tmp_path, "dt_ok", '"""Doc.\n\n>>> 1\n1\n"""\n')
    module_with(tmp_path, "dt_missing_dep", "import definitely_not_a_real_package\n")
    report = src.docstring_report(tmp_path, run=True)
    assert report["violations"] == []
    assert "unmeasured" in report["notes"][0]


def test_docstring_report_is_quiet_when_a_run_is_clean(tmp_path: Path):
    """Nothing to say when every example ran and held."""
    module_with(tmp_path, "dt_clean", '"""Doc.\n\n>>> 1\n1\n"""\n')
    assert src.docstring_report(tmp_path, run=True)["notes"] == []


# --- printing -----------------------------------------------------------------


def test_print_report_says_unavailable_for_a_missing_source_root(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
):
    """Unavailable, not empty — the word the scorecard reads as out-of-scope."""
    src.print_report(src.docstring_report(tmp_path / "src", run=False))
    assert "unavailable" in capsys.readouterr().out


def test_print_report_omits_the_run_line_when_nothing_ran(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
):
    """Without --run there is no run to report, and claiming one would be the lie."""
    module_with(tmp_path, "dt_unrun", '"""Doc.\n\n>>> 1\n1\n"""\n')
    src.print_report(src.docstring_report(tmp_path, run=False))
    out = capsys.readouterr().out
    assert "1 example(s)" in out
    assert "failed" not in out


def test_print_report_lists_each_example_and_the_run(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
):
    """Where the examples are is the half of the report a reviewer acts on."""
    module_with(tmp_path, "dt_print", '"""Doc.\n\n>>> 1\n1\n"""\n')
    src.print_report(src.docstring_report(tmp_path, run=True))
    out = capsys.readouterr().out
    assert "1 example(s)" in out
    assert "dt_print.py:1 <module>" in out
    assert "0 failed" in out
