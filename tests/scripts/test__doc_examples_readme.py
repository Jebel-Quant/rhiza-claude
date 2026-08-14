"""Tests for the README half of the example checker (`scripts/_doc_examples_readme.py`).

The interesting assertions are about what this refuses to call a failure: a fence with no
language is *untagged*, an illustrative one is *skipped*, and a README that isn't there is
*out of scope*. Each is a place where reporting FAIL would describe the document's genre
rather than a defect in it — the same mistake `check_make_targets.py` exists to prevent one
level up.

Shell is only ever parsed here, so the tests assert on `bash -n`'s verdict and never on a
side effect: a test that proved a README fence *ran* would be proving the thing this module
promises not to do.
"""

from __future__ import annotations

from pathlib import Path

import _doc_examples_readme as rdm
import pytest


def readme_with(tmp_path: Path, body: str) -> Path:
    """Write a README under *tmp_path* and return its path."""
    path = tmp_path / "README.md"
    path.write_text(body, encoding="utf-8")
    return path


# --- fences -------------------------------------------------------------------


class TestFence:
    """The parsed shape of one fenced block."""

    def test_carries_language_flags_body_and_line(self):
        """Every field is populated from the fence itself."""
        text = "intro\n\n```python +RHIZA_SKIP\nx = 1\n```\n"
        (fence,) = rdm.fences(text)
        assert fence == rdm.Fence("python", "+RHIZA_SKIP", "x = 1\n", 3)

    def test_language_is_lowercased_and_flags_default_to_empty(self):
        """A bare ```BASH fence still classifies as shell."""
        (fence,) = rdm.fences("```BASH\ntrue\n```\n")
        assert (fence.language, fence.flags) == ("bash", "")


def test_fences_returns_blocks_in_document_order():
    """Order matters: the report is read against the file."""
    text = "```bash\ntrue\n```\n\ntext\n\n```python\nx = 1\n```\n"
    assert [f.language for f in rdm.fences(text)] == ["bash", "python"]


def test_fences_ignores_an_indented_inner_fence():
    """A closing fence has to start a line, or a nested example truncates the block."""
    text = "```markdown\n    ```\n    inner\n    ```\n```\n"
    (fence,) = rdm.fences(text)
    assert "inner" in fence.body


def test_should_skip_matches_the_templates_flag():
    """`+RHIZA_SKIP` is spelled exactly as the synced tests spell it."""
    assert rdm.should_skip(" +RHIZA_SKIP other") is True
    assert rdm.should_skip("other") is False


# --- shell fences -------------------------------------------------------------


def test_shell_skip_reason_names_a_directory_tree():
    """Box-drawing characters mean the fence is a tree wearing a bash label."""
    assert rdm.shell_skip_reason("repo/\n├── src\n") == "directory tree, not shell"


def test_shell_skip_reason_names_a_comment_only_block():
    """Nothing to parse means nothing that can be wrong."""
    assert rdm.shell_skip_reason("# just a note\n\n# and another\n") == "comments only"


def test_shell_skip_reason_is_none_for_real_shell():
    """Real shell is checked rather than skipped."""
    assert rdm.shell_skip_reason("make test\n") is None


def test_check_shell_accepts_valid_shell():
    """`bash -n` parses it, so the fence is ok."""
    fence = rdm.Fence("bash", "", "for i in 1 2; do echo $i; done\n", 1)
    assert rdm.check_shell(fence) == ("ok", "")


def test_check_shell_reports_a_syntax_error_in_bashs_own_wording():
    """The detail is the last line bash printed, not a paraphrase of it."""
    status, detail = rdm.check_shell(rdm.Fence("bash", "", "for i in 1 2; do\n", 1))
    assert status == "failed"
    assert detail


def test_last_line_falls_back_when_there_is_no_output():
    """A silent failure still gets a detail string."""
    assert rdm.last_line("  \n ", "fallback") == "fallback"


# --- python fences ------------------------------------------------------------


def test_check_python_compiles_without_running():
    """A fence that would raise at runtime still compiles — this pass is syntax only."""
    assert rdm.check_python(rdm.Fence("python", "", "raise SystemExit(1)\n", 1)) == ("ok", "")


def test_check_python_reports_the_syntax_error():
    """A broken example is a documentation bug, reported with its line."""
    status, detail = rdm.check_python(rdm.Fence("python", "", "def f(:\n", 1))
    assert status == "failed"
    assert "line" in detail


# --- classification -----------------------------------------------------------


@pytest.mark.parametrize(
    ("language", "flags", "body", "expected"),
    [
        ("python", "+RHIZA_SKIP", "boom(\n", "skipped"),
        ("bash", "", "├── src\n", "skipped"),
        ("bash", "", "make test\n", "ok"),
        ("python", "", "x = 1\n", "ok"),
        ("result", "", "hello\n", "skipped"),
        ("", "", "some text\n", "untagged"),
        ("json", "", "{}\n", "skipped"),
    ],
)
def test_check_fence_classifies_every_language(language, flags, body, expected):
    """One dispatch table, exercised through every arm."""
    status, _ = rdm.check_fence(rdm.Fence(language, flags, body, 1))
    assert status == expected


# --- the report ---------------------------------------------------------------


def test_readme_report_marks_a_missing_readme_out_of_scope(tmp_path: Path):
    """Absent is not failing — the same rule as an unavailable make target."""
    report = rdm.readme_report(tmp_path / "README.md", run=False)
    assert report["present"] is False
    assert report["violations"] == []
    assert "out of scope" in report["notes"][0]


def test_readme_report_flags_a_broken_shell_fence_with_its_line(tmp_path: Path):
    """The violation names the file and the line, so it is actionable."""
    report = rdm.readme_report(readme_with(tmp_path, "```bash\nfor i in 1 2; do\n```\n"), run=False)
    assert report["violations"] and "README.md:1" in report["violations"][0]


def test_readme_report_notes_untagged_fences_without_failing(tmp_path: Path):
    """Nothing can check them, and pretending otherwise would be the lie."""
    report = rdm.readme_report(readme_with(tmp_path, "```\nwho knows\n```\n"), run=False)
    assert report["violations"] == []
    assert "no language" in report["notes"][0]


def test_readme_report_runs_python_fences_and_matches_the_result_block(tmp_path: Path):
    """The documented output is the assertion, exactly as the template does it."""
    readme = readme_with(tmp_path, "```python\nprint('hi')\n```\n\n```result\nhi\n```\n")
    report = rdm.readme_report(readme, run=True)
    assert report["execution"]["matched"] is True
    assert report["violations"] == []


def test_readme_report_reports_a_mismatch_against_the_result_block(tmp_path: Path):
    """A README whose output drifted is exactly what this catches."""
    readme = readme_with(tmp_path, "```python\nprint('hi')\n```\n\n```result\nbye\n```\n")
    report = rdm.readme_report(readme, run=True)
    assert report["execution"]["matched"] is False
    assert "does not match" in report["violations"][0]


def test_run_python_fences_reports_a_non_zero_exit(tmp_path: Path):
    """A fence that raises is a broken example, whatever the result block says."""
    readme = readme_with(tmp_path, "```python\nraise ValueError('nope')\n```\n")
    execution = rdm.run_python_fences(readme, rdm.fences(readme.read_text()))
    assert "exited 1" in execution["violations"][0]


def test_run_python_fences_only_asserts_the_exit_status_without_a_result_block(tmp_path: Path):
    """Undocumented output is a note: most READMEs never adopted the result-block convention."""
    readme = readme_with(tmp_path, "```python\nprint('undocumented')\n```\n")
    execution = rdm.run_python_fences(readme, rdm.fences(readme.read_text()))
    assert execution["violations"] == []
    assert "no ```result``` block" in execution["notes"][0]


def test_run_python_fences_skips_a_readme_with_nothing_to_run(tmp_path: Path):
    """A skipped fence is not executed, so no program is left to run."""
    readme = readme_with(tmp_path, "```python +RHIZA_SKIP\nraise SystemExit(1)\n```\n")
    execution = rdm.run_python_fences(readme, rdm.fences(readme.read_text()))
    assert execution == {"ran": False, "violations": [], "notes": ["no executable python fence"]}


# --- printing -----------------------------------------------------------------


def test_print_report_says_unavailable_for_a_missing_readme(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
):
    """Unavailable, not empty — the word the scorecard reads as out-of-scope."""
    rdm.print_report(rdm.readme_report(tmp_path / "README.md", run=False))
    assert "unavailable" in capsys.readouterr().out


def test_print_report_tallies_the_fences_and_the_run(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
):
    """Every line a model reads back: the tally, each fence, and the execution result."""
    readme = readme_with(
        tmp_path, "```bash\nmake test\n```\n\n```python\nprint('hi')\n```\n\n```result\nhi\n```\n"
    )
    rdm.print_report(rdm.readme_report(readme, run=True))
    out = capsys.readouterr().out
    assert "3 fence(s)" in out
    assert "README.md:1 bash" in out
    assert "output matched: True" in out
