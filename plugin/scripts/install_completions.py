#!/usr/bin/env python3
"""Install shell tab-completion for make targets — the engine behind `/rhiza:completions`.

Copies the bundled completion scripts (``scripts/completions/``) into the user's
completion directory, so ``make <TAB>`` lists the targets of whatever project the shell
is sitting in.

**This is a per-machine concern that used to be driven by repo content.** The rhiza
template shipped these two scripts into every managed repo and gave each one a
``make install-completions`` target that copied them to
``${XDG_DATA_HOME:-$HOME/.local/share}/bash-completion/completions/make`` — a *global*
path for the ``make`` command in general. So N synced repos each carried an identical
copy of a script that installs to one shared location, and the last copy to run won.
Nothing in the scripts varies per repository: they discover targets by parsing the make
database in the current directory. The plugin is installed once per machine, which is
where a machine-wide file belongs.

Two things this does that ``cp`` did not:

* **It refuses to clobber a completion it did not write.** The installed filenames stay
  ``make`` and ``_make`` — namespacing them would be politer and would never fire for a
  bare ``make <TAB>``, which is the entire point — so the destination is exactly where a
  generic make completion from some other source would sit. A destination whose contents
  don't carry the ``_rhiza_make`` marker needs ``--force``, reported as exit code 3.
* **It can say what it would do.** ``--dry-run`` prints the destinations and the verdict
  for each shell without writing anything.

Usage:
  uv run --python 3.12 --no-project python \
      scripts/install_completions.py [--shell bash|zsh|both] [--dry-run] [--force] \
      [--json]

``--shell both`` is the default, for the same reason the retired make target defaulted
its ``SHELL_KIND`` to ``both``: nothing here can tell which shell the user actually logs
in with, and an unused completion file is inert. Exit code 3 means a destination holds a
foreign completion and ``--force`` was not given.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any, NamedTuple

# The bundled completion scripts. A sibling directory rather than a location of their
# own, for the same reason every script lives in `scripts/`: the tree is the unit that
# gates and ships, not the file.
_ASSETS = Path(__file__).resolve().parent / "completions"

MARKER = "_rhiza_make"
"""The function-name prefix both scripts define — how a destination is recognised as ours."""

NEEDS_FORCE = 3
"""Exit code for "a destination holds a completion this plugin did not write"."""

BOTH = "both"
"""The ``--shell`` value that selects every supported shell, and the default."""


class Shell(NamedTuple):
    """One shell: its bundled asset, where the asset installs, and the follow-up step.

    ``installed_as`` is deliberately the *generic* name — ``make`` for bash, ``_make``
    for zsh — because both shells resolve a completion by the name of the command it
    completes. There is no spelling that both avoids shadowing another make completion
    and still fires for a bare ``make <TAB>``.
    """

    kind: str
    asset: str
    subdir: str
    installed_as: str
    hint: str


SHELLS: tuple[Shell, ...] = (
    Shell(
        kind="bash",
        asset="rhiza-completion.bash",
        subdir="bash-completion/completions",
        installed_as="make",
        hint="start a new shell, or run: source {path}",
    ),
    Shell(
        kind="zsh",
        asset="rhiza-completion.zsh",
        subdir="zsh/site-functions",
        installed_as="_make",
        hint=(
            "if completion does not activate, add to ~/.zshrc: "
            "fpath=({parent} $fpath); autoload -U compinit && compinit"
        ),
    ),
)

# What happened, and what would have happened. Two maps rather than one verb plus a
# prefix: "would installed" is not English, and the dry-run wording is the half a
# reader is most likely to mistake for a change that landed.
_DONE = {
    "install": "installed",
    "update": "updated",
    "replace": "replaced",
    "unchanged": "already up to date",
}
_PLANNED = {
    "install": "would install",
    "update": "would update",
    "replace": "would replace",
    "unchanged": "already up to date",
}


def shells(kind: str) -> list[Shell]:
    """The shells ``--shell KIND`` selects — one of them, or all of them.

    >>> [shell.kind for shell in shells("zsh")]
    ['zsh']
    >>> [shell.kind for shell in shells(BOTH)]
    ['bash', 'zsh']
    """
    return [shell for shell in SHELLS if kind in (shell.kind, BOTH)]


def data_home(env: Mapping[str, str] | None = None) -> Path:
    """The XDG data home, with the same fallback the shell idiom uses.

    ``${XDG_DATA_HOME:-$HOME/.local/share}`` treats an *empty* value as unset, so an
    exported-but-blank variable falls back rather than resolving to the current
    directory:

    >>> data_home({"XDG_DATA_HOME": "/opt/data"}).as_posix()
    '/opt/data'
    >>> data_home({"XDG_DATA_HOME": "", "HOME": "/home/ada"}).as_posix()
    '/home/ada/.local/share'
    """
    environ = os.environ if env is None else env
    explicit = environ.get("XDG_DATA_HOME", "")
    if explicit:
        return Path(explicit)
    return Path(environ.get("HOME") or "~").expanduser() / ".local" / "share"


def destination(shell: Shell, env: Mapping[str, str] | None = None) -> Path:
    """Where *shell*'s completion is installed."""
    return data_home(env) / shell.subdir / shell.installed_as


def asset(shell: Shell) -> Path:
    """The bundled completion script for *shell*."""
    return _ASSETS / shell.asset


def is_ours(text: str) -> bool:
    """Was *text* written from one of the bundled scripts?

    Both define functions prefixed ``_rhiza_make``, which a generic make completion
    from another source will not:

    >>> is_ours("_rhiza_make_completion() { :; }")
    True
    >>> is_ours("# some other make completion\\ncomplete -W 'all' make")
    False
    """
    return MARKER in text


def classify(dest: Path, body: str, *, force: bool) -> str:
    """What installing *body* at *dest* would amount to.

    One of ``install`` (nothing there yet), ``unchanged`` (byte-identical),
    ``update`` (an older copy of ours), ``replace`` (a foreign file, forced) or
    ``blocked`` (a foreign file, not forced).
    """
    if dest.is_dir():  # not ours to replace, whatever --force says
        return "blocked"
    if not dest.exists():
        return "install"
    # `errors="replace"` rather than a guard: a destination that isn't valid UTF-8 is
    # certainly not one of ours, and it should reach the `blocked` verdict below by the
    # normal route rather than as a traceback.
    current = dest.read_text(encoding="utf-8", errors="replace")
    if current == body:
        return "unchanged"
    if is_ours(current):
        return "update"
    return "replace" if force else "blocked"


def install_one(
    shell: Shell, *, env: Mapping[str, str] | None, force: bool, dry_run: bool
) -> dict[str, Any]:
    """Install *shell*'s completion, or work out what doing so would mean."""
    dest = destination(shell, env)
    body = asset(shell).read_text(encoding="utf-8")
    action = classify(dest, body, force=force)
    written = action in ("install", "update", "replace") and not dry_run
    if written:
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(body, encoding="utf-8")
    return {
        "shell": shell.kind,
        "source": str(asset(shell)),
        "path": str(dest),
        "action": action,
        "written": written,
        "hint": shell.hint.format(path=dest, parent=dest.parent),
    }


def install(
    kind: str = BOTH,
    *,
    env: Mapping[str, str] | None = None,
    force: bool = False,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Install the completion for *kind* (``bash``, ``zsh`` or ``both``); return a summary."""
    entries = [install_one(shell, env=env, force=force, dry_run=dry_run) for shell in shells(kind)]
    return {
        "dry_run": dry_run,
        "force": force,
        "shells": entries,
        "needs_force": any(entry["action"] == "blocked" for entry in entries),
    }


def report(summary: dict[str, Any]) -> None:
    """Print the human summary — one line per shell, plus its follow-up step."""
    for entry in summary["shells"]:
        if entry["action"] == "blocked":
            print(
                f"{entry['shell']}: {entry['path']} holds a completion this plugin did "
                "not write — pass --force to replace it",
                file=sys.stderr,
            )
            continue
        verbs = _DONE if entry["written"] or entry["action"] == "unchanged" else _PLANNED
        print(f"{entry['shell']}: {verbs[entry['action']]} {entry['path']}")
        if not summary["dry_run"]:
            print(f"        next: {entry['hint']}")


def missing_assets(kind: str) -> list[str]:
    """Bundled completion scripts *kind* needs that aren't shipped — a packaging fault."""
    return [shell.asset for shell in shells(kind) if not asset(shell).is_file()]


def main(argv: list[str] | None = None) -> int:
    """Entry point: install the selected completions and return an exit code."""
    parser = argparse.ArgumentParser(description="Install make tab-completion for your shell.")
    parser.add_argument(
        "--shell",
        choices=[*(shell.kind for shell in SHELLS), BOTH],
        default=BOTH,
        help="Which shell to install for (default: both — the login shell is not detectable).",
    )
    parser.add_argument(
        "--force", action="store_true", help="Replace a completion this plugin did not write."
    )
    parser.add_argument(
        "--dry-run",
        dest="dry_run",
        action="store_true",
        help="Report the destinations and the verdict for each shell; write nothing.",
    )
    parser.add_argument(
        "--json", dest="json_output", action="store_true", help="Emit the summary as JSON."
    )
    args = parser.parse_args(argv)

    absent = missing_assets(args.shell)
    if absent:
        parser.error(f"bundled completion script(s) missing from {_ASSETS}: {', '.join(absent)}")

    summary = install(args.shell, force=args.force, dry_run=args.dry_run)
    if args.json_output:
        print(json.dumps(summary, indent=2))
    else:
        report(summary)
    return NEEDS_FORCE if summary["needs_force"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
