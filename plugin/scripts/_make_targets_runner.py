#!/usr/bin/env python3
"""The delegation half of `check_make_targets.py`: the shim, its pin, and its catalogue.

**Why this is a module and not four more functions in the probe.** Through template v1.3 a
repo's gates were `make` targets, so `check_make_targets.py` answered "what gates are
there?" by reading the makefile chain — one instrument, one file. Template v1.4 moved the
gates into a *pinned CLI* behind a shim whose ``%:`` rule answers every target name, which
splits the question in two: reading makefiles now finds only the shim and its pin, and the
catalogue has to be asked of the runner. Those are different instruments with different
failure modes — a missing pin is not a failed subprocess — and keeping them in one file put
it 20% over this repo's 500-line bar.

The split is by *concern*: everything about a repo that **delegates** is here — whether its
makefile is a shim at all, what it pins, what the runner then offers, and what to advise a
caller who finds one. Probing ordinary make targets stays behind.

This module never walks the include chain. The caller passes in the chain it already has,
so nothing here imports its own orchestrator — the rule `_rhiza_common`'s docstring spells
out, and the reason that one exists.
"""

from __future__ import annotations

import re
import shutil
import subprocess  # nosec B404
from collections.abc import Iterable
from pathlib import Path

# A catch-all rule: `%:` (the shim's delegation to its task runner) or `.DEFAULT:`. Both
# require the colon to follow the name immediately, which is what keeps `%.o: %.c` — an
# ordinary pattern rule — and `.DEFAULT_GOAL := help` out. Used only to *name* the file
# in the notes; whether probing works at all is decided by asking make, which is
# `check_make_targets.resolves_everything`.
_CATCH_ALL = re.compile(r"^(?:%|\.DEFAULT)[ \t]*::?[^=]", re.MULTILINE)
# The task runner a v1.4 shim pins: `RHIZA_TASK ?= rhiza-task@1.1.0`. The pin is the whole
# point of reading it — `uvx rhiza-task list` answers for whatever release is current,
# which is not necessarily the one this repo's gates run under.
_TASK_RUNNER_PIN = re.compile(r"^RHIZA_TASK\s*\??=\s*(\S+)", re.MULTILINE)
# A plausible task name in `rhiza-task list` output. Deliberately the same shape as a make
# target: the names carried over from the make layer unchanged.
_TASK_NAME = re.compile(r"[a-z][a-z0-9-]*")


def catch_all_source(makefiles: Iterable[Path]) -> Path | None:
    """Return the first of *makefiles* that defines a catch-all rule, or None.

    Explanatory only — it names a file for the notes. Whether probing can be trusted at
    all is `check_make_targets.resolves_everything`'s question, which asks make instead of
    reading text, and so catches a catch-all built from variables that this cannot see.

    >>> import tempfile, pathlib
    >>> d = pathlib.Path(tempfile.mkdtemp())
    >>> mk = d / "Makefile"
    >>> _ = mk.write_text(".DEFAULT_GOAL := help")
    >>> catch_all_source([mk]) is None
    True
    >>> _ = mk.write_text("%: ; @uvx rhiza-task $@")
    >>> catch_all_source([mk]).name
    'Makefile'
    """
    return next(
        (
            makefile
            for makefile in makefiles
            if _CATCH_ALL.search(makefile.read_text(encoding="utf-8", errors="ignore"))
        ),
        None,
    )


def pin_from(makefiles: Iterable[Path]) -> str | None:
    """Return the `rhiza-task` pin *makefiles* carry, or None.

    A v1.4 shim is a delegation to a *pinned* CLI, and that pin is the only thing on disk
    saying which task catalogue this repo's gates actually come from. Reading it is what
    turns "ask the runner" into a command a caller can run verbatim.

    >>> import tempfile, pathlib
    >>> d = pathlib.Path(tempfile.mkdtemp())
    >>> mk = d / "Makefile"
    >>> _ = mk.write_text("RHIZA_TASK ?= rhiza-task@1.1.0")
    >>> pin_from([mk])
    'rhiza-task@1.1.0'

    A makefile that defines its targets outright pins nothing, and that is the signal
    "this repo does not delegate" rather than an error:

    >>> _ = mk.write_text("test: ; @pytest")
    >>> pin_from([mk]) is None
    True
    """
    for makefile in makefiles:
        found = _TASK_RUNNER_PIN.search(makefile.read_text(encoding="utf-8", errors="ignore"))
        if found:
            return found.group(1)
    return None


def parse_task_list(output: str) -> list[str]:
    r"""Return the task names in ``rhiza-task list`` output, in order.

    The runner renders a table whose first column is the task name and whose longer rows
    wrap into continuation lines with that column blank. There is no machine-readable
    mode, so the column is located once from the header and every row is read at that
    offset — stable under the width changes that reflow the *other* columns, which is why
    this reads a fixed offset instead of splitting on whitespace.

    >>> parse_task_list(" task     section\n book     Book\n          more text\n test  Python")
    ['book', 'test']

    A blank line, a row whose name column is empty, and anything that is not a plausible
    task name are all skipped rather than guessed at:

    >>> parse_task_list(" task  section\n\n          orphan\n Not-A-Task  x\n fmt  Quality")
    ['fmt']

    With no header the column is unknown, so nothing is read: an error banner printed where
    a table was expected yields no tasks rather than a list of misparsed words.

    >>> parse_task_list("error: could not resolve rhiza-task\n")
    []
    """
    rows = iter(output.splitlines())
    column = next(
        (line.index("task") for line in rows if line.strip().split()[:1] == ["task"]),
        None,
    )
    if column is None:
        return []
    names: list[str] = []
    for line in rows:  # `rows` is an iterator, so this resumes after the header
        if len(line) <= column or line[column] == " ":
            continue
        name = line[column:].split()[0]
        if _TASK_NAME.fullmatch(name) and name not in names:
            names.append(name)
    return names


def tasks(pin: str | None, cwd: Path) -> list[str] | None:
    """Return the task names *pin* provides when run in *cwd*, or None.

    Run **in the repo**, because the runner resolves which language layer applies from the
    files around it: the same pin lists a different catalogue beside a `Cargo.toml` than
    beside a `pyproject.toml`. Asking from anywhere else answers for the wrong layer.

    None — never an empty list — whenever the question cannot be asked: no pin (so not a
    delegating repo), no ``uvx`` on PATH, or a runner that failed. That is the probe's
    "undetermined, not unavailable" distinction, and it matters at the call site: a caller
    must not read a failed enumeration as a repo with no gates and score every concern
    out-of-scope.
    """
    if pin is None:
        return None
    uvx = shutil.which("uvx")
    if uvx is None:
        return None
    result = subprocess.run(  # nosec B603
        [uvx, pin, "list"],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return None
    return parse_task_list(result.stdout)


def delegating_notes(gate_count: int, where: str, pin: str | None) -> list[str]:
    """The guidance a delegating repo's probe carries, as three notes.

    Pure text over three facts, so it lives beside the runner it talks about rather than
    beside the makefile reader that discovered them. Every note exists to stop a *scoring*
    mistake rather than to describe the repo: "undetermined" is not availability, the
    runner is the authority on what exists, and an unknown task was never a gate.

    >>> notes = delegating_notes(7, "a catch-all rule in Makefile", "rhiza-task@1.1.0")
    >>> len(notes)
    3
    >>> "all 7 named gate(s)" in notes[0]
    True
    >>> "uvx rhiza-task@1.1.0 list" in notes[1]
    True

    With no pin the advice still names a runner, because the shim delegates to one either
    way — it just cannot say which release:

    >>> "uvx rhiza-task list" in delegating_notes(1, "a catch-all rule", None)[1]
    True
    """
    runner = pin if pin else "rhiza-task"
    return [
        f"this makefile resolves *every* target ({where}), so `make -n` cannot tell a "
        f"real gate from a typo — all {gate_count} named gate(s) are reported "
        "undetermined rather than available, which is what they are.",
        f"enumerate the repo's real tasks with `uvx {runner} list`, which is the "
        + ("pin this makefile carries" if pin else "runner a shim delegates to")
        + " and the authority on what exists; `make help` shows the same catalogue plus "
        "any `local.mk` targets. Match each named gate to a task before running it.",
        "a gate that fails with an unknown-task error was never provided: score it "
        "out-of-scope, never FAIL.",
    ]
