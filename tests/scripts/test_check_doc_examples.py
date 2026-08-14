"""Tests for the example checker's dispatcher and CLI (`scripts/check_doc_examples.py`).

The halves are covered by their own mirrored files; what is left here is the verdict, and
the verdict has three states rather than two. Exit 1 means an example is broken. Exit 2
means there was nothing to check — no source root, no README — which `/quality` scores
out-of-scope, exactly as it scores an unavailable `make` target. Collapsing those two into
"non-zero" is how a repo with no README would come to be reported as having a broken one.
"""

from __future__ import annotations

import json
from pathlib import Path

import check_doc_examples as cde
import pytest


def readme_with(tmp_path: Path, body: str) -> Path:
    """Write a README under *tmp_path* and return its path."""
    path = tmp_path / "README.md"
    path.write_text(body, encoding="utf-8")
    return path


# --- the combined verdict -----------------------------------------------------


def test_report_exits_two_when_there_is_nothing_to_check(tmp_path: Path):
    """No source root and no README: unscoreable, which is not the same as failing."""
    assert cde.report(tmp_path, "src", "README.md", run=False)["exit_code"] == cde.EXIT_NOTHING


def test_report_exits_zero_when_the_examples_hold(tmp_path: Path):
    """A README that parses is a pass even with no doctests anywhere."""
    readme_with(tmp_path, "```bash\nmake test\n```\n")
    assert cde.report(tmp_path, "src", "README.md", run=False)["exit_code"] == cde.EXIT_OK


def test_report_exits_one_on_a_broken_example(tmp_path: Path):
    """A violation in either half fails the check."""
    readme_with(tmp_path, "```python\ndef f(:\n```\n")
    assert cde.report(tmp_path, "src", "README.md", run=False)["exit_code"] == cde.EXIT_VIOLATION


def test_report_merges_both_halves(tmp_path: Path):
    """One summary, so the caller never has to run the two halves separately."""
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "dt_merge.py").write_text('"""Doc.\n\n>>> 1\n1\n"""\n', encoding="utf-8")
    readme_with(tmp_path, "```bash\nmake test\n```\n")
    summary = cde.report(tmp_path, "src", "README.md", run=False)
    assert summary["docstrings"]["examples"] == 1
    assert summary["readme"]["blocks"][0]["status"] == "ok"


# --- the CLI ------------------------------------------------------------------


def test_main_prints_a_readable_report(tmp_path: Path, capsys: pytest.CaptureFixture[str]):
    """Text mode is what a model reads back out of the tool result."""
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "dt_cli.py").write_text('"""Doc.\n\n>>> 1\n1\n"""\n', encoding="utf-8")
    readme_with(tmp_path, "```bash\nmake test\n```\n\n```\nuntagged\n```\n")
    code = cde.main(["--target-dir", str(tmp_path), "--run"])
    out, err = capsys.readouterr()
    assert code == cde.EXIT_OK
    assert "docstrings" in out and "readme" in out and "example" in out
    assert "note" in err


def test_main_prints_violations_to_stderr(tmp_path: Path, capsys: pytest.CaptureFixture[str]):
    """A failing example has to be visible without `--json`."""
    readme_with(tmp_path, "```bash\nfor i in 1 2; do\n```\n")
    code = cde.main(["--target-dir", str(tmp_path)])
    assert code == cde.EXIT_VIOLATION
    assert "violation" in capsys.readouterr().err


def test_main_reports_absent_halves_in_text_mode(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
):
    """Both "unavailable" lines, which are the degraded-mode default."""
    code = cde.main(["--target-dir", str(tmp_path)])
    out, _ = capsys.readouterr()
    assert code == cde.EXIT_NOTHING
    assert out.count("unavailable") == 2


def test_main_emits_json_with_both_halves(tmp_path: Path, capsys: pytest.CaptureFixture[str]):
    """`--json` is the shape the command feeds into the scorecard."""
    readme_with(tmp_path, "```bash\nfor i in 1 2; do\n```\n")
    code = cde.main(["--target-dir", str(tmp_path), "--json"])
    summary = json.loads(capsys.readouterr().out)
    assert code == cde.EXIT_VIOLATION
    assert summary["violations"] and set(summary) >= {"docstrings", "readme", "notes"}


def test_main_honours_a_custom_source_root_and_readme(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
):
    """The flags the prose passes are the flags that work."""
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "dt_custom.py").write_text(
        '"""Doc.\n\n>>> 1 + 1\n2\n"""\n', encoding="utf-8"
    )
    (tmp_path / "docs.md").write_text("```python\nprint(1)\n```\n", encoding="utf-8")
    code = cde.main(
        ["--target-dir", str(tmp_path), "--source-root", "pkg", "--readme", "docs.md", "--json"]
    )
    summary = json.loads(capsys.readouterr().out)
    assert code == cde.EXIT_OK
    assert summary["docstrings"]["examples"] == 1
    assert summary["readme"]["present"] is True
