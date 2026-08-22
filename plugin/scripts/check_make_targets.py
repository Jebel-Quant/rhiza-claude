#!/usr/bin/env python3
"""Probe the `make` targets a command names — behind `/rhiza:quality`'s step 0.

Seven of `/quality`'s gates are `make` targets that the template sync delivers, and those
seven are what this probes. It used to run them without checking they existed, and the
result was the worst kind of failure: in an unsynced repo all seven returned "No rule to
make target", were scored FAIL, and the repo was reported as broken when the truth was
that it was unsynced. Six of the seven are absent in this plugin's own repo.

Two things make that hard to catch by hand, and this script addresses both:

* **The target list is derived from the command's prose**, not duplicated here. It is
  parsed out of the numbered gate list in `skills/quality/SKILL.md`, so the probe and the
  command cannot drift — add a `make` gate to the prose and it gets probed automatically.
  The gate list is longer than the target list: the entries backed by a bundled checker
  rather than a `make` target (test-layout parity, the example checker) are shipped with
  the plugin and resolve without a sync, so there is nothing to probe and the regex passes
  over them.
* **Availability varies by profile.** `typecheck`, `security` and `docs-coverage` come
  from the template's *tests* bundle and `fmt`/`deps` from *core*, so a repo on a
  reduced profile legitimately lacks some. An absent target is reported as
  **unavailable**, which `/quality` scores as out-of-scope — never as a failure.
* **Some makefiles answer everything, and then probing proves nothing.** Template v1.4
  retired the make layer for a task runner behind a shim whose `%:` rule forwards any
  unknown target, so `make -n <anything>` exits 0. That turned this script's one
  instrument into a tautology and produced the *inverse* of the bug above: every gate
  reported available, the retired `deptry` alias included, on a repo whose task is
  called `deps` — so
  `/quality` ran a gate that does not exist and scored the runner's "unknown task"
  error as a FAIL. Such a repo's gates are reported **undetermined**, which is neither
  available nor a failure, with the notes saying how to resolve them.

It also **discovers** what the repo documents beyond that list. The prose names the
Python profile's gates; a Go or Rust repo synced from a sibling template has different
ones, and hard-coding those would mean asserting targets for templates this plugin has
never seen. Instead every `target: ## description` in the makefile is read, and the
ones the prose didn't name come back as `undeclared` — so a non-Python repo yields real
gates to run rather than a report that nothing is available.

Probing uses `make -n`, which resolves the target without running any recipe.

Usage:
  uv run --python 3.12 --no-project python \
      scripts/check_make_targets.py [--target-dir DIR] [--from FILE] \
      [--require] [--json]

Exit codes:
  0  probed successfully (targets may be unavailable or undetermined — neither is an error)
  1  no makefile to probe — either an unsynced repo or a v1.4 one that kept no shim,
     which the notes tell apart — or --require was given and a target is missing or
     undetermined
  2  no gate list could be parsed from the command prose
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess  # nosec B404
import sys
from pathlib import Path
from typing import Any

# The numbered gate list in skills/quality/SKILL.md: "1. `make fmt` — …".
_GATE = re.compile(r"^\s*\d+\.\s+`make ([a-z][a-z0-9-]*)`", re.MULTILINE)
_MAKEFILES = ("Makefile", "makefile", "GNUmakefile")
# A self-documenting target — `test:  ## Run the suite` — the convention every rhiza
# Makefile uses for `make help`. Undocumented internal targets are deliberately not
# matched: they are not gates anyone meant to expose. `test::` (a double-colon rule,
# which rust.mk uses) counts too.
_DOCUMENTED = re.compile(r"^([a-z][a-z0-9_-]*)::?.*?##\s*(.+)$", re.MULTILINE)
# An `include`/`-include` line, with its (possibly glob) operands.
_INCLUDE = re.compile(r"^\s*-?include\s+(.+?)\s*$", re.MULTILINE)
# How deep to follow includes. Makefile -> .rhiza/rhiza.mk -> .rhiza/make.d/*.mk is two,
# so three leaves room without risking a pathological chain.
_INCLUDE_DEPTH = 3
# A catch-all rule: `%:` (the shim's delegation to its task runner) or `.DEFAULT:`. Both
# require the colon to follow the name immediately, which is what keeps `%.o: %.c` — an
# ordinary pattern rule — and `.DEFAULT_GOAL := help` out. Used only to *name* the file
# in the notes; whether probing works at all is decided by asking make (see
# :func:`resolves_everything`).
_CATCH_ALL = re.compile(r"^(?:%|\.DEFAULT)[ \t]*::?[^=]", re.MULTILINE)
# A target no repository would define, used to ask make whether it answers anything.
_SENTINEL_TARGET = "rhiza-probe-no-such-target"
# The task runner a v1.4 shim pins: `RHIZA_TASK ?= rhiza-task@1.1.0`. The pin is the
# whole point of reading it — `uvx rhiza-task list` answers for whatever release is
# current, which is not necessarily the one this repo's gates run under.
_TASK_RUNNER_PIN = re.compile(r"^RHIZA_TASK\s*\??=\s*(\S+)", re.MULTILINE)
# The one artefact every sync writes, at every template version. `.rhiza/rhiza.mk` used
# to stand in for it and stopped being written at template v1.4, so it now answers "was
# this repo ever synced?" wrongly for every repo on the current template.
_LOCK_REL = Path(".rhiza") / "template.lock"

EXIT_OK = 0
EXIT_UNAVAILABLE = 1
EXIT_NO_GATES = 2


def gate_targets(command_file: Path) -> list[str]:
    """Return the `make` targets named in *command_file*'s numbered gate list.

    Parsed rather than hardcoded so the probe follows the prose. Order is preserved,
    because `/quality` runs the gates cheapest-first and the report should match.
    """
    if not command_file.is_file():
        return []
    seen: list[str] = []
    for target in _GATE.findall(command_file.read_text(encoding="utf-8")):
        if target not in seen:
            seen.append(target)
    return seen


def find_makefile(target_dir: Path) -> Path | None:
    """Return the repo's makefile, or None when there isn't one."""
    return next((target_dir / n for n in _MAKEFILES if (target_dir / n).is_file()), None)


def makefile_chain(target_dir: Path, *, depth: int = _INCLUDE_DEPTH) -> list[Path]:
    """Return the repo's makefile plus the files it ``include``s, in reading order.

    **Reading only the root makefile finds nothing on a real repo.** A rhiza-synced
    repo's `Makefile` is a stub — a few variables and `include .rhiza/rhiza.mk` — which
    in turn ends with `-include .rhiza/make.d/*.mk`, and *that* is where every gate
    lives. Probing was unaffected (``make -n`` follows includes itself), but discovery
    read one file where make reads a dozen, so a synced Rust repo reported zero
    discovered targets while `.rhiza/make.d/rust.mk` was sitting there defining `deps`,
    `license` and `coverage`. The mechanism that exists to stop `/quality` reporting
    "nothing could be checked" was doing exactly that.

    Globs are expanded and each file is visited once. An operand containing `$` is
    skipped: it is a make variable this parser cannot resolve, and guessing is worse
    than omitting.
    """
    root = find_makefile(target_dir)
    if root is None:
        return []
    chain: list[Path] = []
    seen: set[Path] = set()

    def _walk(path: Path, remaining: int) -> None:
        resolved = path.resolve()
        if resolved in seen or not path.is_file():
            return
        seen.add(resolved)
        chain.append(path)
        if remaining <= 0:
            return
        for operands in _INCLUDE.findall(path.read_text(encoding="utf-8", errors="ignore")):
            for operand in operands.split():
                if "$" in operand:
                    continue
                for included in sorted(target_dir.glob(operand)):
                    _walk(included, remaining - 1)

    _walk(root, depth)
    return chain


def documented_targets(target_dir: Path) -> dict[str, str]:
    """Return the repo's self-documenting `make` targets, mapped to their descriptions.

    The gate list in the prose is the **Python** profile. A Go or Rust repo synced from
    a sibling template offers a different set, and naming those from a table here would
    mean asserting targets for templates this plugin has never seen — the failure mode
    that had `/quality` scoring repos against gates that did not exist.

    So they are discovered instead, from the ``target: ## description`` convention every
    rhiza Makefile uses to build ``make help`` — across the whole include chain, because
    that is where make itself looks (see :func:`makefile_chain`). What comes back is what
    the repo really offers, whatever language it is.
    """
    found: dict[str, str] = {}
    for makefile in makefile_chain(target_dir):
        for name, description in _DOCUMENTED.findall(
            makefile.read_text(encoding="utf-8", errors="ignore")
        ):
            found.setdefault(name, description.strip())
    return found


def target_exists(target_dir: Path, target: str) -> bool:
    """Is *target* resolvable by make in *target_dir*?

    ``make -n`` expands the recipe without executing it, so this stays side-effect
    free even for targets that would build or install something.
    """
    make = shutil.which("make")
    if make is None:  # pragma: no cover - make is present everywhere this runs
        return False
    env = os.environ.copy()
    env["NO_COLOR"] = "1"
    result = subprocess.run(  # nosec B603
        [make, "-n", target],
        cwd=str(target_dir),
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    return result.returncode == 0


def catch_all_source(target_dir: Path) -> Path | None:
    """Return the makefile in the chain that defines a catch-all rule, or None.

    Explanatory only — it names a file for the notes. The question of whether probing
    can be trusted is :func:`resolves_everything`'s.

    >>> import tempfile, pathlib
    >>> d = pathlib.Path(tempfile.mkdtemp())
    >>> _ = (d / "Makefile").write_text(".DEFAULT_GOAL := help")
    >>> catch_all_source(d) is None
    True
    >>> _ = (d / "Makefile").write_text("%: ; @uvx rhiza-task $@")
    >>> catch_all_source(d).name
    'Makefile'
    """
    return next(
        (
            makefile
            for makefile in makefile_chain(target_dir)
            if _CATCH_ALL.search(makefile.read_text(encoding="utf-8", errors="ignore"))
        ),
        None,
    )


def pinned_task_runner(target_dir: Path) -> str | None:
    """Return the `rhiza-task` pin the makefile chain carries, or None.

    A v1.4 shim is a delegation to a *pinned* CLI, and that pin is the only thing on
    disk that says which task catalogue this repo's gates actually come from. Reading it
    is what turns "ask the runner" into a command a caller can run verbatim.

    >>> import tempfile, pathlib
    >>> d = pathlib.Path(tempfile.mkdtemp())
    >>> _ = (d / "Makefile").write_text("RHIZA_TASK ?= rhiza-task@1.1.0\\n%: ; @uvx $@")
    >>> pinned_task_runner(d)
    'rhiza-task@1.1.0'
    >>> _ = (d / "Makefile").write_text("test: ; @pytest")
    >>> pinned_task_runner(d) is None
    True
    """
    for makefile in makefile_chain(target_dir):
        found = _TASK_RUNNER_PIN.search(makefile.read_text(encoding="utf-8", errors="ignore"))
        if found:
            return found.group(1)
    return None


def resolves_everything(target_dir: Path) -> bool:
    """Does this repo's make answer a target that cannot exist?

    Behavioural rather than textual, and that is the point. Template v1.4's `Makefile`
    is a shim: `%:` forwards every unresolved target to `uvx rhiza-task`, so
    :func:`target_exists` returns True for anything at all and the whole probe becomes a
    tautology. Asking about a target no repo would define is the one question whose
    answer separates the two cases — and it catches a catch-all this parser cannot see,
    whether it arrives through an `include` past the depth limit or is built from make
    variables.
    """
    return target_exists(target_dir, _SENTINEL_TARGET)


def _delegating_notes(target_dir: Path, targets: list[str]) -> list[str]:
    """Guidance for a repo whose makefile answers every target."""
    source = catch_all_source(target_dir)
    where = f"a catch-all rule in {source.name}" if source else "a catch-all rule"
    pin = pinned_task_runner(target_dir)
    runner = pin if pin else "rhiza-task"
    return [
        f"this makefile resolves *every* target ({where}), so `make -n` cannot tell a "
        f"real gate from a typo — all {len(targets)} named gate(s) are reported "
        "undetermined rather than available, which is what they are.",
        f"enumerate the repo's real tasks with `uvx {runner} list`, which is the "
        + ("pin this makefile carries" if pin else "runner a shim delegates to")
        + " and the authority on what exists; `make help` shows the same catalogue plus "
        "any `local.mk` targets. Match each named gate to a task before running it.",
        "a gate that fails with an unknown-task error was never provided: score it "
        "out-of-scope, never FAIL.",
    ]


def _probe_notes(available: list[str], unavailable: list[str], undeclared: list[str]) -> list[str]:
    """Build the guidance notes for a completed probe.

    Every note here exists to stop a *scoring* mistake rather than to describe the repo:
    an absent target is out-of-scope, never a FAIL, and a repo whose real gates sit under
    other names must not be reported as unscoreable.
    """
    notes: list[str] = []
    if unavailable:
        notes.append(
            f"{len(unavailable)} target(s) not defined for this profile — score them "
            "out-of-scope, never FAIL: " + ", ".join(unavailable)
        )
    if not available:
        notes.append("no gate is available — check that the template sync completed")

    if not (undeclared and unavailable):
        return notes

    # Deliberately "most missing" rather than "all missing": a Go or Rust template will
    # almost certainly define `test`, so requiring zero matches would keep the hint
    # hidden from exactly the repos it exists for.
    if len(unavailable) > len(available):
        notes.append(
            f"most named gates are absent, but this repo documents {len(undeclared)} "
            "other target(s). If this is a Go, Rust or non-standard template, those are "
            "its real gates — run the relevant ones from `undeclared` and score them, "
            "rather than reporting that nothing could be checked."
        )
    else:
        # The milder case: most named gates resolve (`fmt`, `test`, `typecheck` are named
        # the same in every language layer) while the one that doesn't has a
        # differently-named analogue sitting in `undeclared`. `deptry`/`deps` used to be
        # the example and no longer is — the prose names `deps`, which every language layer
        # agrees on — but the shape recurs whenever a template renames a target, and scoring
        # the absent one out-of-scope would silently skip a gate the repo does provide.
        notes.append(
            f"{len(unavailable)} named gate(s) are absent while this repo documents "
            f"{len(undeclared)} other target(s) — check `undeclared` for the equivalent "
            "under a different name and score that instead of skipping the concern."
        )
    return notes


def _delegating_probe(target_dir: Path, targets: list[str]) -> dict[str, Any]:
    """The summary for a repo whose makefile answers every target.

    Nothing is `available`, and reporting otherwise is the worse error of the two: a
    shim says yes to every probe, so trusting it is how the retired `deptry` alias came
    back available on a repo whose only task is `deps`. What survives is `undeclared` —
    the `##` convention still reads, and on a shim the repo-owned targets at the foot of
    the file are the only ones anything on disk can vouch for.
    """
    documented = documented_targets(target_dir)
    return {
        "targets": targets,
        "available": [],
        "unavailable": [],
        "undetermined": targets,
        "undeclared": sorted(name for name in documented if name not in targets),
        "documented": documented,
        "notes": _delegating_notes(target_dir, targets),
        "exit_code": EXIT_OK,
    }


def _no_makefile_probe(target_dir: Path, targets: list[str]) -> dict[str, Any]:
    """The summary for a repo with no makefile at all — which is now two repos.

    Until template v1.4 there was only one: an unsynced repo, whose gates genuinely do
    not exist anywhere and whose fix is `/rhiza:update`. v1.4 retired the make layer for
    a pinned task runner and stopped shipping a `Makefile`, so a repo that is fully
    synced and up to date reaches this branch too — and telling *that* repo to sync is
    both wrong and unactionable. `.rhiza/template.lock` separates them, because a sync
    writes it at every version.

    The gates of a synced repo are reported **undetermined** rather than unavailable, for
    the same reason a shim's are: nothing here can see the task runner's catalogue, so
    "absent" is a claim this probe cannot make. What it can do is say where to look.
    """
    if not (target_dir / _LOCK_REL).is_file():
        return {
            "targets": targets,
            "available": [],
            "unavailable": targets,
            "undetermined": [],
            "undeclared": [],
            "documented": {},
            "notes": [
                "no makefile and no `.rhiza/template.lock` — the repo is not synced, so "
                "every gate is unavailable. Run /rhiza:update before scoring."
            ],
            "exit_code": EXIT_UNAVAILABLE,
        }
    return {
        "targets": targets,
        "available": [],
        "unavailable": [],
        "undetermined": targets,
        "undeclared": [],
        "documented": {},
        "notes": [
            "no makefile, but `.rhiza/template.lock` is present: this repo *is* synced. "
            "Template v1.4 retired the make layer for a pinned task runner and this repo "
            "kept no shim `Makefile`, so all "
            f"{len(targets)} named gate(s) are undetermined rather than unavailable — "
            "they moved, they are not missing. Do not run /rhiza:update over this.",
            "enumerate the real tasks with `uvx rhiza-task list` and run each gate as "
            "`uvx rhiza-task <task>`, matching it to a task first. There is no makefile "
            "to read a pin out of, so that resolves to the current release.",
            "a gate with no matching task was never provided: score it out-of-scope, never FAIL.",
        ],
        "exit_code": EXIT_UNAVAILABLE,
    }


def probe(target_dir: Path, command_file: Path) -> dict[str, Any]:
    """Probe every gate target named in *command_file*; return a summary dict."""
    targets = gate_targets(command_file)
    if not targets:
        return {
            "targets": [],
            "available": [],
            "unavailable": [],
            "undetermined": [],
            "undeclared": [],
            "documented": {},
            "notes": [f"no `make <target>` gate list found in {command_file.name}"],
            "exit_code": EXIT_NO_GATES,
        }

    if find_makefile(target_dir) is None:
        return _no_makefile_probe(target_dir, targets)

    if resolves_everything(target_dir):
        return _delegating_probe(target_dir, targets)

    documented = documented_targets(target_dir)
    available = [t for t in targets if target_exists(target_dir, t)]
    unavailable = [t for t in targets if t not in available]
    # Targets the repo documents that the prose never named. On a Python repo this is
    # usually noise (`book`, `clean`); on a Go or Rust one it is where the real gates
    # are, because the prose list describes a template this repo isn't using.
    undeclared = sorted(name for name in documented if name not in targets)

    return {
        "targets": targets,
        "available": available,
        "unavailable": unavailable,
        "undetermined": [],
        "undeclared": undeclared,
        "documented": documented,
        "notes": _probe_notes(available, unavailable, undeclared),
        "exit_code": EXIT_OK,
    }


def _state(target: str, summary: dict[str, Any]) -> str:
    """How *target* is labelled in the text report."""
    if target in summary["undetermined"]:
        return "undetermined"
    return "available" if target in summary["available"] else "unavailable"


def main(argv: list[str] | None = None) -> int:
    """Entry point: probe the gate targets and return an exit code."""
    parser = argparse.ArgumentParser(
        description="Probe the make targets a rhiza command names as its gates.",
    )
    parser.add_argument("--target-dir", default=".", help="Repository root (default: cwd).")
    parser.add_argument(
        "--from",
        dest="command_file",
        default=None,
        help="Command file to read the gate list from (default: the bundled quality.md).",
    )
    parser.add_argument(
        "--require",
        action="store_true",
        help="Exit non-zero unless every target was confirmed present.",
    )
    parser.add_argument(
        "--json", dest="json_output", action="store_true", help="Emit the summary as JSON."
    )
    args = parser.parse_args(argv)

    command_file = (
        Path(args.command_file)
        if args.command_file
        else Path(__file__).resolve().parent.parent / "skills" / "quality" / "SKILL.md"
    )
    summary = probe(Path(args.target_dir).resolve(), command_file)
    # `undetermined` fails `--require` too. The flag asks whether every gate is there,
    # and a makefile that answers everything cannot say — treating "could not tell" as
    # "yes" is the whole defect this reports.
    if args.require and (summary["unavailable"] or summary["undetermined"]):
        summary["exit_code"] = EXIT_UNAVAILABLE

    if args.json_output:
        print(json.dumps(summary, indent=2))
    else:
        for target in summary["targets"]:
            print(f"{_state(target, summary):<12} make {target}")
        for target in summary["undeclared"]:
            print(f"{'discovered':<12} make {target}  # {summary['documented'][target]}")
        for note in summary["notes"]:
            print(f"note         {note}", file=sys.stderr)
    return int(summary["exit_code"])


if __name__ == "__main__":
    raise SystemExit(main())
