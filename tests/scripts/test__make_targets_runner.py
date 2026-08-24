"""Tests for `_make_targets_runner` — the pin, the catalogue, and the advice.

Everything here is checked without a makefile and, apart from the monkeypatched calls,
without a subprocess: this module's job is to be the half of `check_make_targets` that
does not read the repo, so its tests should not need one either. The chain walk, the seam
and the CLI live in `test_check_make_targets.py`.

Flat functions rather than grouping classes on purpose — `check_test_layout` mirrors a
`Test<Class>` onto a source *class*, and this module has none.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import _make_targets_runner as runner

# Captured `rhiza-task list` output. The indentation is the fixture: `book` and `fmt` wrap
# into continuation lines whose name column is blank, which is the case the parse exists
# for. Re-indenting this is the way to make these tests pass while measuring nothing.
_LIST_OUTPUT = (
    " task                section         needs                 does\n"
    " book                Book            test benchmark        build the companion\n"
    "                                     stress                book\n"
    " fmt                 Quality                               run the pre-commit\n"
    "                                                           hooks over all files\n"
    " deps                Python          install               run deptry over the\n"
    "                                                           contributed folders\n"
)


# --- pin_from: reading RHIZA_TASK out of a chain the caller supplies ---------------


def test_pin_from_reads_the_first_file_in_the_chain_that_pins(tmp_path: Path) -> None:
    """The chain, not the root file: a repo may pin from an include."""
    root, included = tmp_path / "Makefile", tmp_path / "local.mk"
    root.write_text("-include local.mk\n", encoding="utf-8")
    included.write_text("RHIZA_TASK ?= rhiza-task@1.3.1\n", encoding="utf-8")
    assert runner.pin_from([root, included]) == "rhiza-task@1.3.1"


def test_pin_from_is_none_when_nothing_in_the_chain_pins(tmp_path: Path) -> None:
    """No pin is "this repo does not delegate", which is not an error."""
    mk = tmp_path / "Makefile"
    mk.write_text("test: ; @pytest\n", encoding="utf-8")
    assert runner.pin_from([mk]) is None


def test_pin_from_is_none_for_an_empty_chain() -> None:
    """A repo with no makefile at all reaches here with nothing to read."""
    assert runner.pin_from([]) is None


def test_pin_from_accepts_a_plain_assignment_as_well_as_a_conditional_one(
    tmp_path: Path,
) -> None:
    """`RHIZA_TASK = x` pins as much as `?=` does; a repo may harden either way."""
    mk = tmp_path / "Makefile"
    mk.write_text("RHIZA_TASK = rhiza-task@2.0.0\n", encoding="utf-8")
    assert runner.pin_from([mk]) == "rhiza-task@2.0.0"


# --- parse_task_list: the table, and what could break reading it ------------------


def test_parse_task_list_reads_the_name_column_and_ignores_wrapped_rows() -> None:
    """Captured output: three tasks, and the continuation lines are not tasks."""
    assert runner.parse_task_list(_LIST_OUTPUT) == ["book", "fmt", "deps"]


def test_parse_task_list_returns_nothing_without_a_header_row() -> None:
    """No header means the name column is unknown, so no row can be read.

    Returning `[]` rather than guessing at column 0 is the point: an error banner printed
    where a table was expected must yield "no tasks", which `tasks` turns into None —
    never a list of misparsed words a caller would go on to treat as gates.
    """
    assert runner.parse_task_list("error: could not resolve rhiza-task\n") == []


def test_parse_task_list_deduplicates_a_repeated_name() -> None:
    """`--all` lists one task under two layers; the caller wants each name once."""
    doubled = " task  section\n fmt   Quality\n fmt   Python\n"
    assert runner.parse_task_list(doubled) == ["fmt"]


def test_parse_task_list_skips_lines_that_cannot_hold_a_name() -> None:
    """A blank line, and text left of the name column, are both not tasks.

    Both halves are real: the runner emits trailing blank lines, and indexing past the end
    of one would raise rather than skip it.
    """
    assert runner.parse_task_list(" task  section\n fmt   Quality\n\nx\n") == ["fmt"]


def test_parse_task_list_rejects_a_name_that_is_not_task_shaped() -> None:
    """Task names are lowercase and hyphenated; anything else is table furniture."""
    assert runner.parse_task_list(" task  section\n Not-A-Task  x\n fmt  Quality\n") == ["fmt"]


# --- tasks: invoking the pinned runner, and the three ways it cannot be asked -----


def test_tasks_is_none_without_a_pin(tmp_path: Path) -> None:
    """Nothing to invoke, so nothing to report."""
    assert runner.tasks(None, tmp_path) is None


def test_tasks_is_none_without_uvx(tmp_path: Path, monkeypatch) -> None:
    """The runner is reached through uvx; without it there is nothing to ask."""
    monkeypatch.setattr(runner.shutil, "which", lambda _name: None)
    assert runner.tasks("rhiza-task@1.1.0", tmp_path) is None


def test_tasks_is_none_when_the_runner_exits_non_zero(tmp_path: Path, monkeypatch) -> None:
    """A failed runner is unmeasured, never an empty gate set.

    This distinction is the whole reason None exists: `/quality` must not read a failed
    enumeration as "this repo has no gates" and score every concern out-of-scope.
    """
    monkeypatch.setattr(runner.shutil, "which", lambda _name: "/usr/bin/uvx")
    monkeypatch.setattr(
        runner.subprocess,
        "run",
        lambda *a, **k: subprocess.CompletedProcess(a[0], 1, "", "boom"),
    )
    assert runner.tasks("rhiza-task@1.1.0", tmp_path) is None


def test_tasks_runs_the_pinned_runner_inside_the_repo(tmp_path: Path, monkeypatch) -> None:
    """Both the pin and the working directory are load-bearing.

    A bare `uvx rhiza-task list` answers for whatever release is current, and running it
    outside the repo answers for the wrong language layer — the runner resolves the layer
    from the files around it.
    """
    seen: dict[str, object] = {}

    def fake_run(argv, **kwargs):
        seen["argv"] = argv
        seen["cwd"] = kwargs["cwd"]
        return subprocess.CompletedProcess(argv, 0, _LIST_OUTPUT, "")

    monkeypatch.setattr(runner.shutil, "which", lambda _name: "/usr/bin/uvx")
    monkeypatch.setattr(runner.subprocess, "run", fake_run)

    assert runner.tasks("rhiza-task@9.9.9", tmp_path) == ["book", "fmt", "deps"]
    assert seen["argv"] == ["/usr/bin/uvx", "rhiza-task@9.9.9", "list"]
    assert seen["cwd"] == tmp_path


# --- delegating_notes: three notes, each stopping a scoring mistake ---------------


def test_delegating_notes_names_the_gate_count_the_place_and_the_pin() -> None:
    """Everything a reader needs to resolve the gates themselves."""
    notes = runner.delegating_notes(7, "a catch-all rule in Makefile", "rhiza-task@1.1.0")
    assert len(notes) == 3
    assert "all 7 named gate(s)" in notes[0]
    assert "a catch-all rule in Makefile" in notes[0]
    assert "uvx rhiza-task@1.1.0 list" in notes[1]
    assert "pin this makefile carries" in notes[1]


def test_delegating_notes_still_names_a_runner_without_a_pin() -> None:
    """A shim delegates either way; it just cannot say which release."""
    notes = runner.delegating_notes(1, "a catch-all rule", None)
    assert "uvx rhiza-task list" in notes[1]
    assert "runner a shim delegates to" in notes[1]


def test_delegating_notes_says_an_unknown_task_was_never_a_gate() -> None:
    """The note that stops the FAIL: a gate never provided is out-of-scope."""
    assert "out-of-scope, never FAIL" in runner.delegating_notes(1, "x", None)[2]


# --- catch_all_source: naming the file the delegation lives in --------------------


def test_catch_all_source_finds_the_shims_pattern_rule(tmp_path: Path) -> None:
    """`%:` is the shim's delegation, and the note names the file it is in."""
    mk = tmp_path / "Makefile"
    mk.write_text("%: ; @uvx rhiza-task $@\n", encoding="utf-8")
    found = runner.catch_all_source([mk])
    assert found is not None and found.name == "Makefile"


def test_catch_all_source_finds_a_default_rule_too(tmp_path: Path) -> None:
    """`.DEFAULT:` delegates the same way an unnamed pattern rule does."""
    mk = tmp_path / "local.mk"
    mk.write_text(".DEFAULT: ; @echo no\n", encoding="utf-8")
    assert runner.catch_all_source([mk]) is not None


def test_catch_all_source_ignores_an_ordinary_pattern_rule(tmp_path: Path) -> None:
    """`%.o: %.c` is a normal rule; treating it as delegation would void every probe."""
    mk = tmp_path / "Makefile"
    mk.write_text("%.o: %.c\n\t$(CC) -c $<\n", encoding="utf-8")
    assert runner.catch_all_source([mk]) is None


def test_catch_all_source_ignores_the_default_goal_assignment(tmp_path: Path) -> None:
    """`.DEFAULT_GOAL := help` names a target; it does not answer for every one."""
    mk = tmp_path / "Makefile"
    mk.write_text(".DEFAULT_GOAL := help\n", encoding="utf-8")
    assert runner.catch_all_source([mk]) is None


def test_catch_all_source_returns_the_first_match_in_the_chain(tmp_path: Path) -> None:
    """Reading order is the caller's; this reports the first file that delegates."""
    root, included = tmp_path / "Makefile", tmp_path / "local.mk"
    root.write_text("-include local.mk\n", encoding="utf-8")
    included.write_text("%: ; @uvx rhiza-task $@\n", encoding="utf-8")
    found = runner.catch_all_source([root, included])
    assert found is not None and found.name == "local.mk"


def test_catch_all_source_is_none_for_an_empty_chain() -> None:
    """A repo with no makefile reaches here with nothing to read."""
    assert runner.catch_all_source([]) is None
