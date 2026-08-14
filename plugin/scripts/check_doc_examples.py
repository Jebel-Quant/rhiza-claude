#!/usr/bin/env python3
"""Check a repo's *examples* — the doctests in its docstrings and the fences in its README.

`/rhiza:quality` has always measured docstring **coverage** and never docstring **truth**.
`interrogate` answers "is there a docstring?"; nothing answered "does the example inside it
still evaluate to what it claims?". The same hole sits under the README: `markdownlint`
checks that a fence is well-formed markdown and says nothing about whether the shell inside
it parses or the Python inside it runs. Both are documentation that fails silently — it
keeps rendering long after it stopped being true, and the person it misleads is a newcomer
running the quickstart.

The rhiza template already closes this in a *managed* repo: `.rhiza/tests/` ships
`test_docstrings.py`, `test_readme.py` and `test_readme_validation.py`, all of which
`make rhiza-test` runs. This script is that same trio for **any** repo — the degraded-mode
case above all, where there is no `.rhiza/` and so nothing checks any of it. Its
conventions mirror the template's, `+RHIZA_SKIP` included, so a repo that adopts rhiza
later keeps the verdict it had here.

The two halves live in `_doc_examples_source.py` and `_doc_examples_readme.py`; this file
is the dispatcher, the combined verdict and the CLI. Each half degrades on its own: a repo
with no source root still gets its README checked, and vice versa.

`--run` adds execution, and is opt-in for a reason: running examples means importing the
repo's modules and executing its README's Python, which runs whatever module-level code
they carry. That is the same trust boundary `make test` already crosses, but `/quality` is
an *assessment* command, so it is never crossed unasked. Shell fences are never executed
under any flag.

Usage:
  uv run --python 3.12 --no-project python \
      scripts/check_doc_examples.py [--target-dir DIR] [--source-root DIR] \
      [--readme FILE] [--run] [--json]

Exit codes:
  0  every example that could be checked holds
  1  an example is broken (bad syntax, a failing doctest, output that doesn't match)
  2  nothing was checkable — no source root and no README
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _doc_examples_readme import readme_report  # noqa: E402
from _doc_examples_readme import print_report as print_readme  # noqa: E402
from _doc_examples_source import docstring_report  # noqa: E402
from _doc_examples_source import print_report as print_docstrings  # noqa: E402

EXIT_OK = 0
EXIT_VIOLATION = 1
EXIT_NOTHING = 2


def report(target: Path, source_root: str, readme: str, *, run: bool) -> dict[str, Any]:
    """Check both halves and return the combined summary, exit code included.

    The distinction between exit 1 and exit 2 is the one that matters to a caller that
    scores: a broken example is a finding, while *nothing to check* is out-of-scope — the
    same rule an unavailable `make` target already follows in `/quality`.
    """
    docs = docstring_report(target / source_root, run=run)
    readme_part = readme_report(target / readme, run=run)
    violations = list(docs["violations"]) + list(readme_part["violations"])

    if violations:
        exit_code = EXIT_VIOLATION
    elif not docs["present"] and not readme_part["present"]:
        exit_code = EXIT_NOTHING
    else:
        exit_code = EXIT_OK
    return {
        "docstrings": docs,
        "readme": readme_part,
        "violations": violations,
        "notes": list(docs["notes"]) + list(readme_part["notes"]),
        "exit_code": exit_code,
    }


def _parser() -> argparse.ArgumentParser:
    """Build the CLI parser."""
    parser = argparse.ArgumentParser(
        description="Check a repo's doctest examples and README code fences.",
    )
    parser.add_argument("--target-dir", default=".", help="Repository root (default: cwd).")
    parser.add_argument(
        "--source-root",
        default="src",
        help="Source root holding the docstrings (default: src; ask language_profile.py).",
    )
    parser.add_argument(
        "--readme", default="README.md", help="README to check (default: README.md)."
    )
    parser.add_argument(
        "--run",
        action="store_true",
        help="Execute the examples, not just parse them (imports the repo's modules).",
    )
    parser.add_argument(
        "--json", dest="json_output", action="store_true", help="Emit the summary as JSON."
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """Entry point: check the repo's examples and return an exit code."""
    args = _parser().parse_args(argv)
    # Deliberately not resolved: every path in the report is quoted back as it was given,
    # so a run from the repo root prints `README.md:59` rather than an absolute path
    # nobody can paste into an editor.
    summary = report(Path(args.target_dir), args.source_root, args.readme, run=args.run)

    if args.json_output:
        print(json.dumps(summary, indent=2))
    else:
        print_docstrings(summary["docstrings"])
        print_readme(summary["readme"])
        for violation in summary["violations"]:
            print(f"violation    {violation}", file=sys.stderr)
        for note in summary["notes"]:
            print(f"note         {note}", file=sys.stderr)
    return int(summary["exit_code"])


if __name__ == "__main__":
    raise SystemExit(main())
