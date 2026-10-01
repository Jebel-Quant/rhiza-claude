#!/usr/bin/env python3
"""The README half of `check_doc_examples.py`: fenced blocks, checked by language.

`markdownlint` checks that a fence is well-formed *markdown* and says nothing about
whether the shell inside it parses or the Python inside it runs. A README's examples are
the first thing a newcomer executes and the last thing anyone re-reads, so they rot
silently — which is why the rhiza template ships `test_readme.py` and
`test_readme_validation.py` into every managed repo. This module is that pair, minus the
`.rhiza/` directory, so an unmanaged repo gets the same check.

The conventions are the template's, deliberately: the `+RHIZA_SKIP` fence flag is spelled
the same, directory trees and comment-only blocks are skipped the same way, and `pycon`
fences are doctest transcripts — `>>>`/`...` prompts with the expected output inline,
every unskipped one in the file joined in document order and run as one doctest under
`ELLIPSIS`. A repo that adopts rhiza later keeps whatever verdict it had here.

The older convention — a `python` fence diffed against the ```result``` block after it —
is still understood, so a README that hasn't migrated keeps its verdict. New examples
should be `pycon`: the output sits next to the line that produced it, and a mismatch
names the example rather than the whole program.

**Shell fences are parsed, never executed** — under any flag. A README's shell is
routinely destructive-adjacent (`make clean`, `git push`, `rm -rf`), and a fence that
cannot parse is a documentation bug whether or not anyone runs it.
"""

from __future__ import annotations

import doctest
import json
import re
import shutil
import subprocess  # nosec B404
import sys
from pathlib import Path
from typing import Any, NamedTuple

# A fenced block: the info string (language plus any flags) and the body. The closing
# fence has to start a line, so an indented fence inside a block doesn't end it early.
_FENCE = re.compile(r"^```([^\n`]*)\n(.*?)^```", re.S | re.M)

# The template's own marker for a fence that is illustrative rather than runnable, spelled
# exactly as `.rhiza/tests/test_readme.py` spells it. Sharing the spelling is the point: a
# fence a repo opted out of upstream is opted out here too.
SKIP_FLAG = "+RHIZA_SKIP"

# Box-drawing characters mean the fence is a directory tree wearing a `bash` label.
_TREE_MARKERS = ("├──", "└──", "│")

_SHELL_LANGS = frozenset({"bash", "sh", "shell", "zsh"})
_PYTHON_LANGS = frozenset({"python", "py"})
_PYCON_LANG = "pycon"
_RESULT_LANG = "result"

# What the child process runs for the `pycon` fences: the joined transcript arrives on
# stdin, one doctest runs over it, and a JSON verdict goes back on stdout. A subprocess
# rather than an in-process run for the same reason the `python` fences get one — a
# README's examples import the repo's code and may mutate `sys.path`, and neither should
# leak into the checker.
_DOCTEST_CHILD = """
import doctest, io, json, sys
text = sys.stdin.read()
test = doctest.DocTestParser().get_doctest(
    text, {"__name__": "__main__"}, sys.argv[1], sys.argv[1], 0
)
buf = io.StringIO()
runner = doctest.DocTestRunner(optionflags=doctest.ELLIPSIS)
result = runner.run(test, out=buf.write, clear_globs=True)
print()
print(json.dumps({"failed": result.failed, "attempted": result.attempted,
                  "report": buf.getvalue()}))
"""


class Fence(NamedTuple):
    """One fenced code block: its language, its flags, its body and where it starts."""

    language: str
    flags: str
    body: str
    line: int


def fences(text: str) -> list[Fence]:
    """Return every fenced block in *text*, in document order."""
    found: list[Fence] = []
    for match in _FENCE.finditer(text):
        language, _, flags = match.group(1).strip().partition(" ")
        line = text.count("\n", 0, match.start()) + 1
        found.append(Fence(language.lower(), flags.strip(), match.group(2), line))
    return found


def should_skip(flags: str) -> bool:
    """Is this fence marked `+RHIZA_SKIP`?"""
    return SKIP_FLAG in flags


def shell_skip_reason(body: str) -> str | None:
    """Why *body* isn't shell worth parsing, or None when it is.

    Two shapes wear a ``bash`` label without being runnable shell: a directory tree drawn
    with box characters, and a block of nothing but comments. Either would pass or fail
    ``bash -n`` for reasons that say nothing about the documentation.
    """
    if any(marker in body for marker in _TREE_MARKERS):
        return "directory tree, not shell"
    lines = [line.strip() for line in body.splitlines() if line.strip()]
    if not [line for line in lines if not line.startswith("#")]:
        return "comments only"
    return None


def last_line(text: str, fallback: str) -> str:
    """Return the last non-empty line of *text*, or *fallback* when there is none."""
    stripped = text.strip()
    return stripped.splitlines()[-1] if stripped else fallback


def check_shell(fence: Fence) -> tuple[str, str]:
    """Parse a shell fence with ``bash -n``; return (status, detail).

    Parsing only — never execution. See this module's docstring for why.
    """
    bash = shutil.which("bash")
    if bash is None:  # pragma: no cover - bash is present everywhere this runs
        return "skipped", "bash not available"
    result = subprocess.run(  # nosec B603
        [bash, "-n"], input=fence.body, capture_output=True, text=True, check=False
    )
    if result.returncode == 0:
        return "ok", ""
    return "failed", last_line(result.stderr, "bash -n reported a syntax error")


def check_python(fence: Fence) -> tuple[str, str]:
    """Compile a Python fence without running it; return (status, detail)."""
    try:
        compile(fence.body, f"<readme:{fence.line}>", "exec")
    except SyntaxError as exc:
        return "failed", f"{exc.msg} (line {exc.lineno})"
    return "ok", ""


def check_pycon(fence: Fence) -> tuple[str, str]:
    """Parse a ``pycon`` transcript and compile each example without running it.

    Syntax only, like `check_python`: a transcript whose prompts are malformed or whose
    source doesn't compile is a documentation bug before anyone executes it.
    """
    try:
        examples = doctest.DocTestParser().get_examples(fence.body, f"<readme:{fence.line}>")
    except ValueError as exc:
        return "failed", str(exc)
    if not examples:
        return "skipped", "no `>>>` prompt in the fence"
    for example in examples:
        try:
            compile(example.source, f"<readme:{fence.line}>", "single")
        except SyntaxError as exc:
            where = fence.line + 1 + example.lineno
            return "failed", f"{exc.msg} (README line {where})"
    return "ok", ""


def check_fence(fence: Fence) -> tuple[str, str]:
    """Check one fence as far as its language allows; return (status, detail)."""
    if should_skip(fence.flags):
        return "skipped", f"{SKIP_FLAG} on the fence"
    if fence.language in _SHELL_LANGS:
        reason = shell_skip_reason(fence.body)
        return ("skipped", reason) if reason else check_shell(fence)
    if fence.language in _PYTHON_LANGS:
        return check_python(fence)
    if fence.language == _PYCON_LANG:
        return check_pycon(fence)
    if fence.language == _RESULT_LANG:
        return "skipped", "expected output for a python fence"
    if not fence.language:
        return "untagged", "no language on the fence — nothing can check it"
    return "skipped", f"`{fence.language}` fences are not checkable"


def run_python_fences(readme: Path, blocks: list[Fence]) -> dict[str, Any]:
    """Execute the README's Python fences and diff the output against its ``result`` blocks.

    The fences are concatenated and run as one program, exactly as the template's
    `test_readme_validation.py` does it: a README's examples are usually one session split
    across prose, so running each in isolation would break every one that builds on the
    last.

    **With no ``result`` block, only the exit status is asserted.** The template compares
    against the empty string there, which fails any example that prints — right for a repo
    whose README is expected to carry them, wrong as a general rule, and this script runs
    against repos that never adopted the convention. Undocumented output is a note, not a
    failure.
    """
    code = "".join(
        f.body for f in blocks if f.language in _PYTHON_LANGS and not should_skip(f.flags)
    )
    expected = "".join(f.body for f in blocks if f.language == _RESULT_LANG)
    if not code.strip():
        return {"ran": False, "violations": [], "notes": ["no executable python fence"]}

    result = subprocess.run(  # nosec B603
        [sys.executable, "-c", code],
        cwd=str(readme.parent),
        capture_output=True,
        text=True,
        check=False,
    )
    violations: list[str] = []
    notes: list[str] = []
    matched: bool | None = None
    if result.returncode != 0:
        detail = last_line(result.stderr, "no stderr")
        violations.append(f"{readme.name}: python fences exited {result.returncode} — {detail}")
    elif expected.strip():
        matched = result.stdout.strip() == expected.strip()
        if not matched:
            violations.append(
                f"{readme.name}: python fence output does not match its ```result``` block "
                f"(expected {expected.strip()[:60]!r}, got {result.stdout.strip()[:60]!r})"
            )
    else:
        notes.append("python fences ran, but no ```result``` block documents their output")
    return {
        "ran": True,
        "returncode": result.returncode,
        "matched": matched,
        "violations": violations,
        "notes": notes,
    }


def _first_failed_example(report: str) -> str:
    """Return the source line of the first failing example in a doctest *report*.

    That line, not the header doctest prints above it, is what a reader searches the
    README for.
    """
    lines = report.splitlines()
    for index, line in enumerate(lines[:-1]):
        if line.strip() == "Failed example:":
            return lines[index + 1].strip()
    return last_line(report, "see the doctest report")


def run_pycon_fences(readme: Path, blocks: list[Fence]) -> dict[str, Any]:
    """Doctest the README's ``pycon`` fences as one transcript; return a summary dict.

    Every unskipped ``pycon`` fence is joined in document order and run as a single
    doctest with ``ELLIPSIS``, in a subprocess whose working directory is the README's
    own — the same semantics as the template's `test_readme_validation.py`. One doctest
    rather than one per fence, because a README's examples are one session split across
    prose: the second fence uses the imports of the first.
    """
    text = "".join(
        f.body if f.body.endswith("\n") else f.body + "\n"
        for f in blocks
        if f.language == _PYCON_LANG and not should_skip(f.flags)
    )
    if not doctest.DocTestParser().get_examples(text):
        return {"ran": False, "violations": [], "notes": ["no executable pycon fence"]}

    proc = subprocess.run(  # nosec B603
        [sys.executable, "-c", _DOCTEST_CHILD, readme.name],
        input=text,
        cwd=str(readme.parent),
        capture_output=True,
        text=True,
        check=False,
    )
    try:
        # The last line only: an example that writes to fd 1 behind doctest's back (a
        # subprocess, say) would otherwise corrupt the verdict.
        verdict = json.loads(last_line(proc.stdout, ""))
    except ValueError:
        detail = last_line(proc.stderr, "no stderr")
        return {
            "ran": True,
            "failed": None,
            "attempted": None,
            "violations": [f"{readme.name}: pycon doctest exited {proc.returncode} — {detail}"],
            "notes": [],
        }
    violations: list[str] = []
    if verdict["failed"]:
        violations.append(
            f"{readme.name}: pycon fences — {verdict['failed']} of {verdict['attempted']} "
            f"example(s) failed, first: {_first_failed_example(verdict['report'])}"
        )
    return {
        "ran": True,
        "failed": verdict["failed"],
        "attempted": verdict["attempted"],
        "report": verdict["report"],
        "violations": violations,
        "notes": [],
    }


def _untagged_note(checked: list[dict[str, Any]]) -> list[str]:
    """Name the fences that carry no language, which nothing can check."""
    untagged = [block for block in checked if block["status"] == "untagged"]
    if not untagged:
        return []
    return [
        f"{len(untagged)} fence(s) carry no language, so nothing can check them: "
        + ", ".join(f"line {block['line']}" for block in untagged)
    ]


def readme_report(readme: Path, *, run: bool) -> dict[str, Any]:
    """Check every fence in *readme*; return a summary dict."""
    if not readme.is_file():
        return {
            "path": str(readme),
            "present": False,
            "blocks": [],
            "violations": [],
            "notes": [f"no {readme.name} — README examples are out of scope, not failing"],
        }

    checked: list[dict[str, Any]] = []
    violations: list[str] = []
    blocks = fences(readme.read_text(encoding="utf-8"))
    for fence in blocks:
        status, detail = check_fence(fence)
        checked.append(
            {
                "line": fence.line,
                "language": fence.language or "(none)",
                "status": status,
                "detail": detail,
            }
        )
        if status == "failed":
            violations.append(f"{readme.name}:{fence.line}: {fence.language} fence — {detail}")

    report: dict[str, Any] = {
        "path": str(readme),
        "present": True,
        "blocks": checked,
        "violations": violations,
        "notes": _untagged_note(checked),
    }
    if run:
        _run_fences(readme, blocks, report)
    return report


def _run_fences(readme: Path, blocks: list[Fence], report: dict[str, Any]) -> None:
    """Execute whichever convention *blocks* use, recording each under its own key.

    ``pycon`` is run when present; the legacy ``python``/``result`` pair is run when any
    ``python`` fence is present, or when there is no ``pycon`` fence either — so a README
    with no examples at all still gets the one note that says so.
    """
    has_pycon = any(f.language == _PYCON_LANG for f in blocks)
    if has_pycon:
        report["doctest"] = run_pycon_fences(readme, blocks)
    if not has_pycon or any(f.language in _PYTHON_LANGS for f in blocks):
        report["execution"] = run_python_fences(readme, blocks)
    for key in ("doctest", "execution"):
        if key in report:
            report["violations"].extend(report[key]["violations"])
            report["notes"].extend(report[key]["notes"])


def print_report(readme: dict[str, Any]) -> None:
    """Print the README half of a report as text."""
    if not readme["present"]:
        print(f"{'unavailable':<12} README fences ({readme['path']} is missing)")
        return
    counts: dict[str, int] = {}
    for block in readme["blocks"]:
        counts[block["status"]] = counts.get(block["status"], 0) + 1
    tally = ", ".join(f"{count} {status}" for status, count in sorted(counts.items()))
    print(f"{'readme':<12} {readme['path']}: {len(readme['blocks'])} fence(s) — {tally or 'none'}")
    for block in readme["blocks"]:
        detail = f" — {block['detail']}" if block["detail"] else ""
        print(f"{block['status']:<12} {readme['path']}:{block['line']} {block['language']}{detail}")
    _print_runs(readme)


def _print_runs(readme: dict[str, Any]) -> None:
    """Print one line per execution pass that actually ran over the README's fences."""
    execution = readme.get("execution")
    if execution is not None and execution["ran"]:
        print(
            f"{'ran':<12} python fences exited {execution['returncode']}, "
            f"output matched: {execution['matched']}"
        )
    doctest_run = readme.get("doctest")
    if doctest_run is not None and doctest_run["ran"]:
        print(
            f"{'ran':<12} pycon fences as one doctest: "
            f"{doctest_run['attempted']} example(s), {doctest_run['failed']} failed"
        )
