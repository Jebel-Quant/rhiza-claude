#!/usr/bin/env python3
"""Guard the Bash calls this plugin's commands make, at the moment they run.

The prose gates (``check_command_contracts.py``, ``check_prompt_wiring.py``) verify the
commands *before* they ship: that a referenced script exists, that a ``--flag`` is real,
that a ``/rhiza:<name>`` resolves. What they cannot verify is that a **correct command
gets executed correctly**. Two rules in the prose are exactly the kind a model drops
under pressure, and both fail quietly:

1. **Bare ``make <target>``.** ``skills/quality/SKILL.md`` asks for one bare ``make`` per
   gate, because that matches the allow-listed ``Bash(make *)`` rule and runs without a
   permission prompt. Piping to ``tail`` is the reflex when output is long, and the cost
   lands on the *user* as a prompt per gate — eight of them in one ``/quality`` run.
2. **Never push to the default branch, never force-push.** Promised separately by
   ``/init``, ``/update`` and ``/release``. Four prose promises, no invariant.

This module is the ``PreToolUse`` hook that makes both structural. It reads the hook
payload on stdin and writes a ``hookSpecificOutput`` decision on stdout.

**It fails open, deliberately.** Unparseable input, an unrecognised payload, a missing
``git``, an unreadable repo — every one of those returns *no decision*, so the normal
permission flow applies. A guard that blocks when it is confused is worse than no guard:
the user cannot argue with it, and the failure mode is a plugin that bricks a session.
The only paths that decide are the two narrow ones above.

The three decisions it can reach:

- ``deny`` — ``make`` combined with a pipe/redirect/chain. The model reads the reason
  and re-runs bare, so no human is involved. Denying is *less* intrusive than asking
  here: asking would surface the very prompt the rule exists to avoid.
- ``deny`` — ``git push --force`` / ``git tag -f``. Irreversible, and no rhiza command
  has a legitimate use for either.
- ``ask`` — a push whose target resolves to the default branch. Not denied, because a
  session with this plugin installed may be doing unrelated work in an unrelated repo,
  and this hook has no way to tell. Escalating puts the human in the loop without
  making the call for them.

Usage (not normally invoked by hand):
  echo '<hook payload>' | python3 scripts/hook_bash_guard.py

Always exits 0. Blocking is expressed as JSON on stdout, never as an exit code, so a
crash can never be mistaken for a decision.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess  # nosec B404
import sys
from typing import NamedTuple

# Quoted spans are removed before any analysis, so `git commit -m "make it | better"`
# is not read as a piped `make`. Replaced with a space rather than deleted, so the
# tokens either side stay separate.
_QUOTED = re.compile(r"'[^']*'|\"[^\"]*\"")

# A heredoc body is *data*, not shell, and unlike a quoted span nothing about it is
# quoted — so `git commit -F - <<EOF` carrying a message that happens to say
# "…; make deptry is deprecated" would otherwise be read as a chained `make`. Blanked
# for the same reason quoted spans are. The delimiter may itself be quoted (`<<'EOF'`)
# and `<<-` allows an indented terminator; both are matched here rather than left to
# `strip_quoted`, which would blank only the delimiter and leave the body behind.
_HEREDOC = re.compile(r"<<-?\s*(['\"]?)(\w+)\1.*?^\s*\2\s*$", re.DOTALL | re.MULTILINE)

# `make` as a *command word*: at the start of any line, or straight after an operator
# that begins a new command. Prevents `git commit -m make-it-better` from matching.
# `re.MULTILINE` is what lets `^` see the second line of a multi-line command; it is only
# safe *because* heredoc bodies are blanked first, or a body line beginning with the word
# `make` would start matching.
_MAKE_WORD = re.compile(r"(?:^|[|&;(])\s*(?:sudo\s+)?make\b", re.MULTILINE)

# Any shell metacharacter that turns one command into a compound one. `<` and `>` cover
# redirects including `2>&1`; `|` covers both pipe and `||`; `&` covers `&&` and
# backgrounding. A single class is used rather than an alternation of exact operators
# because the question is only ever "is this bare?", never "which operator is it?".
_COMPOUND = re.compile(r"[|;<>&]")

# Operators that separate one command from the next, for splitting a line into segments.
# A newline is one of them: a `git push` on the second line of a multi-line command is a
# command like any other.
_SEPARATOR = re.compile(r"\|\||&&|[|;&\n]")

# `git` global options that consume the following token, so a subcommand scan can skip
# past `git -C /path push` without mistaking `/path` for the subcommand.
_GIT_OPTS_WITH_VALUE = frozenset({"-C", "-c", "--git-dir", "--work-tree", "--namespace"})

# `git push` options that consume the following token, so the positional scan does not
# mistake an option's value for a remote or refspec.
_PUSH_OPTS_WITH_VALUE = frozenset({"-o", "--push-option", "--repo", "--receive-pack", "--exec"})

_FORCE_FLAGS = frozenset({"-f", "--force"})

# Fallback default-branch names, used only when git cannot tell us. `--force-with-lease`
# is deliberately absent from _FORCE_FLAGS: it is the safe form, and blocking it would
# push people toward the unsafe one.
_LIKELY_DEFAULTS = frozenset({"main", "master"})

_MAKE_REASON = (
    "Run `make` bare — one target per Bash call. This command combines `make` with a "
    "pipe, redirect, or chain, which no longer matches the allow-listed `Bash(make *)` "
    "rule and so prompts the user on every gate. Re-run it as `make <target>` alone and "
    "read the output directly from the tool result."
)

_FORCE_REASON = (
    "Force-pushing and force-tagging are irreversible, and no rhiza command needs "
    "either — /release stops before pushing and prints the commands instead. If this is "
    "genuinely intended, run it outside the agent."
)


class Decision(NamedTuple):
    """A permission decision to hand back to Claude Code."""

    permission: str
    """One of ``deny`` or ``ask``. ``allow`` is never returned — this guard only ever
    restricts, and letting it *grant* permission would widen the session's surface."""

    reason: str
    """Shown to the model (and the user on ``ask``). Says what to do instead."""


def strip_quoted(command: str) -> str:
    """Blank out single- and double-quoted spans so their contents can't match."""
    return _QUOTED.sub(" ", command)


def strip_heredocs(command: str) -> str:
    """Blank out heredoc bodies so prose inside them can't be read as shell syntax."""
    # `<< ` is left behind so a genuinely compound command *around* the heredoc — a
    # redirect into `make`, say — is still seen as compound.
    return _HEREDOC.sub("<< ", command)


def strip_data(command: str) -> str:
    """Blank every span that is data rather than shell: heredoc bodies, then quotes."""
    # Heredocs first: `strip_quoted` would otherwise blank a quoted `<<'EOF'` delimiter
    # and leave the body, which is exactly the text that must not be analysed.
    return strip_quoted(strip_heredocs(command))


def compound_make(command: str) -> Decision | None:
    """Deny a ``make`` invocation that is piped, redirected, chained, or backgrounded."""
    bare = strip_data(command)
    if not _MAKE_WORD.search(bare):
        return None
    if not _COMPOUND.search(bare):
        return None
    return Decision("deny", _MAKE_REASON)


def segments(command: str) -> list[list[str]]:
    """Split a command line into operator-delimited lists of tokens."""
    parts = _SEPARATOR.split(strip_data(command))
    return [tokens for tokens in (part.split() for part in parts) if tokens]


def git_subcommand(tokens: list[str]) -> tuple[str, list[str]] | None:
    """Return the git subcommand and its arguments, or ``None`` if this isn't git."""
    index = 1 if tokens[:1] == ["sudo"] else 0
    if tokens[index : index + 1] != ["git"]:
        return None
    index += 1
    while index < len(tokens) and tokens[index].startswith("-"):
        index += 2 if tokens[index] in _GIT_OPTS_WITH_VALUE else 1
    if index >= len(tokens):
        return None
    return tokens[index], tokens[index + 1 :]


def push_positionals(args: list[str]) -> list[str]:
    """Strip flags (and their values) from ``git push`` arguments, leaving positionals."""
    positionals: list[str] = []
    index = 0
    while index < len(args):
        token = args[index]
        if token.startswith("-"):
            index += 2 if token in _PUSH_OPTS_WITH_VALUE else 1
            continue
        positionals.append(token)
        index += 1
    return positionals


def _git(cwd: str, *args: str) -> str | None:
    """Run a read-only git command in ``cwd``; ``None`` on any failure at all."""
    # The resolved absolute path, not the bare name: it is needed anyway to know git
    # exists, and passing it avoids resolving the command against PATH a second time.
    git = shutil.which("git")
    if git is None:
        return None
    try:
        result = subprocess.run(  # nosec B603
            [git, "-C", cwd, *args],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


def default_branch(cwd: str) -> str | None:
    """The remote's default branch, via the local ref — no network, no fetch."""
    head = _git(cwd, "symbolic-ref", "--short", "refs/remotes/origin/HEAD")
    if head is None:
        return None
    return head.split("/", 1)[1] if "/" in head else head


def current_branch(cwd: str) -> str | None:
    """The checked-out branch, or ``None`` when detached or unreadable."""
    branch = _git(cwd, "rev-parse", "--abbrev-ref", "HEAD")
    return None if branch == "HEAD" else branch


def push_targets(args: list[str], cwd: str) -> list[str]:
    """The branch names a ``git push`` would write to, as best they can be resolved."""
    positionals = push_positionals(args)
    refspecs = positionals[1:]
    if not refspecs:
        branch = current_branch(cwd)
        return [branch] if branch else []
    targets = []
    for refspec in refspecs:
        # `src:dst` writes to dst; a bare ref writes to itself; `+ref` is a force refspec.
        target = refspec.split(":")[-1].lstrip("+")
        if target in ("HEAD", ""):
            branch = current_branch(cwd)
            if branch:
                targets.append(branch)
            continue
        targets.append(target.removeprefix("refs/heads/"))
    return targets


def is_default(target: str, default: str | None) -> bool:
    """Whether ``target`` names the default branch, falling back to the usual names."""
    return target == default if default else target in _LIKELY_DEFAULTS


def git_guard(command: str, cwd: str) -> Decision | None:
    """Deny force-push/force-tag; ask before a push that lands on the default branch."""
    for tokens in segments(command):
        parsed = git_subcommand(tokens)
        if parsed is None:
            continue
        subcommand, args = parsed
        if subcommand in ("push", "tag") and _FORCE_FLAGS & set(args):
            return Decision("deny", _FORCE_REASON)
        if subcommand != "push":
            continue
        default = default_branch(cwd)
        for target in push_targets(args, cwd):
            if is_default(target, default):
                return Decision(
                    "ask",
                    f"This pushes to `{target}`, the default branch. Every rhiza command "
                    "delivers its work as a PR from a work branch and never pushes here. "
                    "Approve only if you intend to bypass that.",
                )
    return None


def evaluate(command: str, cwd: str) -> Decision | None:
    """Apply every guard to one Bash command; the first decision wins."""
    return compound_make(command) or git_guard(command, cwd)


def main() -> int:
    """Read the hook payload on stdin, print any decision, and always exit 0."""
    try:
        payload = json.loads(sys.stdin.read())
    except (json.JSONDecodeError, UnicodeDecodeError, ValueError):
        return 0
    if not isinstance(payload, dict) or payload.get("tool_name") != "Bash":
        return 0
    tool_input = payload.get("tool_input")
    command = tool_input.get("command") if isinstance(tool_input, dict) else None
    if not isinstance(command, str) or not command.strip():
        return 0
    cwd = payload.get("cwd")
    decision = evaluate(command, cwd if isinstance(cwd, str) and cwd else ".")
    if decision is None:
        return 0
    print(
        json.dumps(
            {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": decision.permission,
                    "permissionDecisionReason": decision.reason,
                }
            }
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
