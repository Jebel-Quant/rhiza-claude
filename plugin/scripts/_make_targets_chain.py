"""The static half of ``check_make_targets.py``: read a repo's makefiles as text.

Split from the orchestrator by instrument, the same line ``_make_targets_runner`` was cut
along. Everything here reads files and nothing runs: which makefile a repo has, the chain
of files it ``include``s, and the targets those files document with the ``## description``
convention. Asking ``make -n`` what resolves is behaviour, and stays with the
orchestrator — a makefile can answer a target this parser never sees (a shim's ``%:``
catch-all) and document one make cannot build, so the two answers are kept apart rather
than blended.

Like ``_make_targets_runner`` it never imports its orchestrator; the dependency runs one
way.
"""

from __future__ import annotations

import re
from pathlib import Path

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


def find_makefile(target_dir: Path) -> Path | None:
    """Return the repo's makefile, or None when there isn't one."""
    return next((target_dir / n for n in _MAKEFILES if (target_dir / n).is_file()), None)


def makefile_chain(target_dir: Path, *, depth: int = _INCLUDE_DEPTH) -> list[Path]:
    """Return the repo's makefile plus the files it ``include``s, in reading order.

    **Reading only the root makefile finds nothing on a pre-v1.4 repo.** Up to template
    v1.3 a synced repo's `Makefile` was a stub — a few variables and
    `include .rhiza/rhiza.mk` — which in turn ended with `-include .rhiza/make.d/*.mk`,
    and *that* is where every gate lived. Probing was unaffected (``make -n`` follows
    includes itself), but discovery read one file where make reads a dozen, so a synced
    Rust repo reported zero discovered targets while `.rhiza/make.d/rust.mk` was sitting
    there defining `deps`, `license` and `coverage`. The mechanism that exists to stop
    `/quality` reporting "nothing could be checked" was doing exactly that.

    Template v1.4 retired that layer: neither file is shipped any more, the gates are
    `rhiza-task` tasks, and the `Makefile` is a shim that forwards to the pinned CLI.
    Following includes is kept because a repo may pin any ref, so both shapes are live —
    and on a current one the chain is simply the root makefile plus whatever `local.mk`
    the repo added itself.

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
