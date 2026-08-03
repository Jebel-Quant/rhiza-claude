#!/usr/bin/env python3
"""Probe the `make` targets a command names — behind `/rhiza:quality`'s step 0.

`/quality` runs seven gates, all of them `make` targets that the template sync
delivers. It used to run them without checking they existed, and the result was the
worst kind of failure: in an unsynced repo all seven returned "No rule to make
target", were scored FAIL, and the repo was reported as broken when the truth was
that it was unsynced. Six of the seven are absent in this plugin's own repo.

Two things make that hard to catch by hand, and this script addresses both:

* **The target list is derived from the command's prose**, not duplicated here. It is
  parsed out of the numbered gate list in `commands/quality.md`, so the probe and the
  command cannot drift — add a gate to the prose and it gets probed automatically.
* **Availability varies by profile.** `typecheck`, `security` and `docs-coverage` come
  from the template's *tests* bundle and `fmt`/`deptry` from *core*, so a repo on a
  reduced profile legitimately lacks some. An absent target is reported as
  **unavailable**, which `/quality` scores as out-of-scope — never as a failure.

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
  0  probed successfully (some targets may be unavailable — that is not an error)
  1  no makefile to probe, or --require was given and a target is missing
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

# The numbered gate list in commands/quality.md: "1. `make fmt` — …".
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
    for target in _GATE.findall(command_file.read_text()):
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
        for operands in _INCLUDE.findall(path.read_text(errors="ignore")):
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
        for name, description in _DOCUMENTED.findall(makefile.read_text(errors="ignore")):
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


def probe(target_dir: Path, command_file: Path) -> dict[str, Any]:
    """Probe every gate target named in *command_file*; return a summary dict."""
    targets = gate_targets(command_file)
    if not targets:
        return {
            "targets": [],
            "available": [],
            "unavailable": [],
            "undeclared": [],
            "documented": {},
            "notes": [f"no `make <target>` gate list found in {command_file.name}"],
            "exit_code": EXIT_NO_GATES,
        }

    if find_makefile(target_dir) is None:
        return {
            "targets": targets,
            "available": [],
            "unavailable": targets,
            "undeclared": [],
            "documented": {},
            "notes": [
                "no makefile — the repo is not synced, so every gate is unavailable. "
                "Run /rhiza:update before scoring."
            ],
            "exit_code": EXIT_UNAVAILABLE,
        }

    available = [t for t in targets if target_exists(target_dir, t)]
    unavailable = [t for t in targets if t not in available]
    documented = documented_targets(target_dir)
    # Targets the repo documents that the prose never named. On a Python repo this is
    # usually noise (`book`, `clean`); on a Go or Rust one it is where the real gates
    # are, because the prose list describes a template this repo isn't using.
    undeclared = sorted(name for name in documented if name not in targets)
    notes: list[str] = []
    if unavailable:
        notes.append(
            f"{len(unavailable)} target(s) not defined for this profile — score them "
            "out-of-scope, never FAIL: " + ", ".join(unavailable)
        )
    if not available:
        notes.append("no gate is available — check that the template sync completed")
    # Deliberately "most missing" rather than "all missing": a Go or Rust template will
    # almost certainly define `test`, so requiring zero matches would keep the hint
    # hidden from exactly the repos it exists for.
    if undeclared and len(unavailable) > len(available):
        notes.append(
            f"most named gates are absent, but this repo documents {len(undeclared)} "
            "other target(s). If this is a Go, Rust or non-standard template, those are "
            "its real gates — run the relevant ones from `undeclared` and score them, "
            "rather than reporting that nothing could be checked."
        )
    # The milder case, which a synced Rust repo really hits: most named gates resolve
    # (`fmt`, `test`, `typecheck` are named the same in every language layer) while the
    # one that doesn't has a differently-named analogue sitting in `undeclared` —
    # `deptry` is absent and `deps` is right there. Scoring the absent one out-of-scope
    # and stopping would silently skip a gate the repo does provide.
    elif undeclared and unavailable:
        notes.append(
            f"{len(unavailable)} named gate(s) are absent while this repo documents "
            f"{len(undeclared)} other target(s) — check `undeclared` for the equivalent "
            "under a different name (a Rust repo's `deps` is the `deptry` analogue) and "
            "score that instead of skipping the concern."
        )

    return {
        "targets": targets,
        "available": available,
        "unavailable": unavailable,
        "undeclared": undeclared,
        "documented": documented,
        "notes": notes,
        "exit_code": EXIT_OK,
    }


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
        help="Exit non-zero when any target is unavailable (for a repo that expects all).",
    )
    parser.add_argument(
        "--json", dest="json_output", action="store_true", help="Emit the summary as JSON."
    )
    args = parser.parse_args(argv)

    command_file = (
        Path(args.command_file)
        if args.command_file
        else Path(__file__).resolve().parent.parent / "commands" / "quality.md"
    )
    summary = probe(Path(args.target_dir).resolve(), command_file)
    if args.require and summary["unavailable"]:
        summary["exit_code"] = EXIT_UNAVAILABLE

    if args.json_output:
        print(json.dumps(summary, indent=2))
    else:
        for target in summary["targets"]:
            state = "available" if target in summary["available"] else "unavailable"
            print(f"{state:<12} make {target}")
        for target in summary["undeclared"]:
            print(f"{'discovered':<12} make {target}  # {summary['documented'][target]}")
        for note in summary["notes"]:
            print(f"note         {note}", file=sys.stderr)
    return int(summary["exit_code"])


if __name__ == "__main__":
    raise SystemExit(main())
