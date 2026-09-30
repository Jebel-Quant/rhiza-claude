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


# --- pycon fences -------------------------------------------------------------


def test_check_pycon_compiles_each_example_without_running():
    """A transcript whose example would raise still passes the syntax-only pass."""
    fence = rdm.Fence("pycon", "", ">>> raise SystemExit(1)\n", 1)
    assert rdm.check_pycon(fence) == ("ok", "")


def test_check_pycon_reports_the_readme_line_of_a_syntax_error():
    """The detail points at the README line, not the line within the fence."""
    fence = rdm.Fence("pycon", "", ">>> x = 1\n>>> def f(:\n", 10)
    status, detail = rdm.check_pycon(fence)
    assert status == "failed"
    assert "README line 12" in detail


def test_check_pycon_reports_a_malformed_prompt():
    """A continuation line without its space is doctest's ValueError, reported as failed."""
    fence = rdm.Fence("pycon", "", ">>> if True:\n...pass\n", 1)
    status, detail = rdm.check_pycon(fence)
    assert status == "failed"
    assert detail


def test_check_pycon_skips_a_fence_without_a_prompt():
    """A `pycon` label on plain output has nothing a doctest could run."""
    assert rdm.check_pycon(rdm.Fence("pycon", "", "just output\n", 1))[0] == "skipped"


def test_run_pycon_fences_joins_fences_into_one_session(tmp_path: Path):
    """The second fence uses the first one's import — one doctest, in document order."""
    readme = readme_with(
        tmp_path,
        "```pycon\n>>> import math\n```\n\nprose\n\n```pycon\n>>> math.floor(2.5)\n2\n```\n",
    )
    execution = rdm.run_pycon_fences(readme, rdm.fences(readme.read_text(encoding="utf-8")))
    assert (execution["ran"], execution["failed"], execution["attempted"]) == (True, 0, 2)
    assert execution["violations"] == []


def test_run_pycon_fences_honours_ellipsis(tmp_path: Path):
    """`...` in expected output matches anything, as the template's doctest does."""
    readme = readme_with(tmp_path, "```pycon\n>>> print('a long line')\na ...\n```\n")
    execution = rdm.run_pycon_fences(readme, rdm.fences(readme.read_text(encoding="utf-8")))
    assert execution["failed"] == 0


def test_run_pycon_fences_runs_in_the_readmes_directory(tmp_path: Path):
    """Relative paths in an example resolve against the repo root the README sits in."""
    (tmp_path / "marker.txt").write_text("here", encoding="utf-8")
    readme = readme_with(
        tmp_path, "```pycon\n>>> open('marker.txt', encoding='utf-8').read()\n'here'\n```\n"
    )
    execution = rdm.run_pycon_fences(readme, rdm.fences(readme.read_text(encoding="utf-8")))
    assert execution["failed"] == 0


def test_run_pycon_fences_survives_output_written_behind_doctests_back(tmp_path: Path):
    """Bytes sent straight to fd 1 land before the verdict line, not inside it."""
    readme = readme_with(
        tmp_path, "```pycon\n>>> import os\n>>> _ = os.write(1, b'noise\\n')\n```\n"
    )
    execution = rdm.run_pycon_fences(readme, rdm.fences(readme.read_text(encoding="utf-8")))
    assert (execution["failed"], execution["violations"]) == (0, [])


def test_run_pycon_fences_names_the_first_failing_example(tmp_path: Path):
    """A mismatch names the example's source, which is what a reader searches for."""
    readme = readme_with(tmp_path, "```pycon\n>>> 1 + 1\n3\n>>> 2 + 2\n5\n```\n")
    execution = rdm.run_pycon_fences(readme, rdm.fences(readme.read_text(encoding="utf-8")))
    assert execution["failed"] == 2
    assert "2 of 2 example(s) failed, first: 1 + 1" in execution["violations"][0]


def test_run_pycon_fences_leaves_skipped_fences_out(tmp_path: Path):
    """A `+RHIZA_SKIP` fence is never executed, so nothing is left to run."""
    readme = readme_with(tmp_path, "```pycon +RHIZA_SKIP\n>>> raise SystemExit(1)\n```\n")
    execution = rdm.run_pycon_fences(readme, rdm.fences(readme.read_text(encoding="utf-8")))
    assert execution == {"ran": False, "violations": [], "notes": ["no executable pycon fence"]}


def test_run_pycon_fences_reports_a_child_that_produced_no_verdict(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """A child that dies before printing its JSON is a failure with stderr's last line."""
    readme = readme_with(tmp_path, "```pycon\n>>> 1\n1\n```\n")
    monkeypatch.setattr(rdm, "_DOCTEST_CHILD", "import sys; sys.exit('child broke')")
    execution = rdm.run_pycon_fences(readme, rdm.fences(readme.read_text(encoding="utf-8")))
    assert execution["failed"] is None
    assert "exited 1 — child broke" in execution["violations"][0]


def test_first_failed_example_falls_back_to_the_last_line():
    """A report with no `Failed example:` header still yields a detail."""
    assert rdm._first_failed_example("odd\nreport\n") == "report"


# --- classification -----------------------------------------------------------


@pytest.mark.parametrize(
    ("language", "flags", "body", "expected"),
    [
        ("python", "+RHIZA_SKIP", "boom(\n", "skipped"),
        ("bash", "", "├── src\n", "skipped"),
        ("bash", "", "make test\n", "ok"),
        ("python", "", "x = 1\n", "ok"),
        ("result", "", "hello\n", "skipped"),
        ("pycon", "", ">>> 1 + 1\n2\n", "ok"),
        ("pycon", "+RHIZA_SKIP", ">>> boom(\n", "skipped"),
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


def test_readme_report_runs_only_the_doctest_for_a_pycon_readme(tmp_path: Path):
    """A migrated README gets no legacy `python` execution and no note about it."""
    readme = readme_with(tmp_path, "```pycon\n>>> print('hi')\nhi\n```\n")
    report = rdm.readme_report(readme, run=True)
    assert report["doctest"]["failed"] == 0
    assert "execution" not in report
    assert report["violations"] == [] and report["notes"] == []


def test_readme_report_runs_both_conventions_in_a_mixed_readme(tmp_path: Path):
    """Half-migrated READMEs are checked under both conventions, failures from each."""
    readme = readme_with(
        tmp_path, "```pycon\n>>> 1\n2\n```\n\n```python\nprint('hi')\n```\n\n```result\nbye\n```\n"
    )
    report = rdm.readme_report(readme, run=True)
    assert len(report["violations"]) == 2


def test_readme_report_never_executes_pycon_without_run(tmp_path: Path):
    """Execution is opt-in: without `run`, a failing transcript is only compiled."""
    readme = readme_with(tmp_path, "```pycon\n>>> 1\n2\n```\n")
    report = rdm.readme_report(readme, run=False)
    assert "doctest" not in report
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
    execution = rdm.run_python_fences(readme, rdm.fences(readme.read_text(encoding="utf-8")))
    assert "exited 1" in execution["violations"][0]


def test_run_python_fences_only_asserts_the_exit_status_without_a_result_block(tmp_path: Path):
    """Undocumented output is a note: most READMEs never adopted the result-block convention."""
    readme = readme_with(tmp_path, "```python\nprint('undocumented')\n```\n")
    execution = rdm.run_python_fences(readme, rdm.fences(readme.read_text(encoding="utf-8")))
    assert execution["violations"] == []
    assert "no ```result``` block" in execution["notes"][0]


def test_run_python_fences_skips_a_readme_with_nothing_to_run(tmp_path: Path):
    """A skipped fence is not executed, so no program is left to run."""
    readme = readme_with(tmp_path, "```python +RHIZA_SKIP\nraise SystemExit(1)\n```\n")
    execution = rdm.run_python_fences(readme, rdm.fences(readme.read_text(encoding="utf-8")))
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


def test_print_report_tallies_the_doctest_run(tmp_path: Path, capsys: pytest.CaptureFixture[str]):
    """The pycon run gets its own line: examples attempted and failed."""
    readme = readme_with(tmp_path, "```pycon\n>>> 1\n1\n```\n")
    rdm.print_report(rdm.readme_report(readme, run=True))
    assert "pycon fences as one doctest: 1 example(s), 0 failed" in capsys.readouterr().out
