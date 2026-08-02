#!/usr/bin/env python3
"""Check that the prose commands are executable — the integration test for markdown.

Every file in ``commands/`` and ``prompts/`` is instructions a model executes at
runtime. The bundled scripts are covered by unit tests, but the **prose that drives
them** was previously unverified, and that is where the expensive failures have come
from: a command referring to a script that no longer exists, passing a flag that was
renamed, or invoking a slash command that was removed. Those surface only when a user
runs the command, mid-task, and the model improvises around the breakage.

This closes that gap by treating each command as a contract and checking it against
the code it actually calls:

1. **Frontmatter** — a command declares ``description``, ``argument-hint`` and
   ``allowed-tools``, and the block **parses**. That second half matters: five of seven
   commands once shipped frontmatter YAML could not read, because a description
   contained an unquoted ``": "`` — which YAML takes as a nested mapping. The key check
   was a substring search, so it passed happily on a file no parser would accept.
2. **Bash blocks parse** — every fenced ``bash`` block is valid shell (``bash -n``),
   with ``<placeholder>`` spans neutralised first since they aren't real syntax.
3. **Scripts exist** — every ``scripts/<name>.py`` a block invokes is shipped.
4. **Flags exist** — every ``--flag`` passed to a bundled script is one that script's
   ``argparse`` actually accepts. This is the check that catches a renamed CLI, the
   most likely silent breakage.
5. **Slash commands exist** — every ``/rhiza:<name>`` referenced resolves to a real
   command, so a removed one can't linger in another command's prose.
6. **allowed-tools covers the binaries used** — a command that runs ``git`` in a block
   must be permitted to, or the user gets a permission prompt mid-flow.
7. **Model-invocation policy** — exactly the commands in ``_MODEL_INVOCATION_OPT_OUT``
   declare ``disable-model-invocation: true``, and no others declare the key at all.
   The policy is a property of the whole command surface, not of one file, so it is
   asserted in both directions: a destructive command that quietly loses the key is as
   much a regression as a harmless one that grows it.

Usage:
  uv run --python 3.12 --no-project python \
      scripts/check_command_contracts.py [--root DIR]

Exits 0 when every contract holds, 1 (listing each violation) otherwise.
"""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess  # nosec B404
import sys
from pathlib import Path

_FRONTMATTER_KEYS = ("description", "argument-hint", "allowed-tools")
# Commands the model may not invoke off a description match — the user has to name them.
# The line is drawn at side effects that are not a reviewable proposal: `uninstall`
# deletes every managed file, `release` commits and tags. Everything else stays
# invocable on purpose — `init` and `update` open a PR but never push to the default
# branch, `docs` only writes files, and `quality` files issues solely from an explicit
# menu selection. Adding a command here is a deliberate change to the plugin's surface,
# which is why the set lives in code and is reviewed rather than inferred per file.
_MODEL_INVOCATION_OPT_OUT = frozenset({"release", "uninstall"})
_OPT_OUT_KEY = "disable-model-invocation"
_BASH_BLOCK = re.compile(r"```bash\n(.*?)```", re.S)
# The script path is usually quoted — `"${CLAUDE_PLUGIN_ROOT}/scripts/x.py" --flag` —
# so the closing quote must be consumed before the arguments, or the argument capture
# comes back empty and every flag goes unchecked.
_SCRIPT_CALL = re.compile(r"scripts/([a-z_]+)\.py[\"']?((?:\s+[^\n`]*)?)")
_SLASH_COMMAND = re.compile(r"/rhiza:([a-z-]+)")
# The documented way one command delegates to another. Case-insensitive: the phrase
# is often capitalised at the start of a sentence or a bullet.
_SKILL_INVOCATION = re.compile(r"invoke the `([a-z-]+)` command via the Skill tool", re.IGNORECASE)
_ADD_ARGUMENT = re.compile(r"add_argument\(")
_FLAG = re.compile(r"--[a-zA-Z][a-zA-Z0-9-]*")
# `Bash(git*)` and friends, from a command's allowed-tools line.
_ALLOWED_BASH = re.compile(r"Bash\(([a-zA-Z0-9_.-]+)\*?\)")

# Placeholders that are prose, not shell: `<github|gitlab>`, `<BODY>`, `<TARGET>`.
_ANGLE_PLACEHOLDER = re.compile(r"<[A-Za-z][A-Za-z0-9|_ -]*>")

# Binaries a block may call without being declared: shell builtins and control words.
_SHELL_BUILTINS = frozenset(
    {"cd", "echo", "test", "if", "then", "else", "fi", "for", "do", "done", "printf", "export"}
)


def frontmatter(text: str) -> str | None:
    """Return the YAML frontmatter block, or None when the file has none."""
    if not text.startswith("---\n"):
        return None
    end = text.find("\n---\n", 4)
    return None if end == -1 else text[4:end]


def script_flags(path: Path) -> set[str]:
    """Return every ``--flag`` the script at *path* declares via argparse.

    Scans a window after each ``add_argument(`` rather than parsing the call, which
    handles both the single-line and multi-line styles used across the scripts without
    importing them (importing would run module-level code).
    """
    source = path.read_text()
    flags: set[str] = set()
    for match in _ADD_ARGUMENT.finditer(source):
        window = source[match.end() : match.end() + 400]
        # Stop at the next add_argument so a long call can't leak into the next one.
        nxt = window.find("add_argument(")
        if nxt != -1:
            window = window[:nxt]
        flags |= set(_FLAG.findall(window))
    return flags


def bash_blocks(text: str) -> list[str]:
    """Return the fenced ``bash`` blocks in *text*."""
    return _BASH_BLOCK.findall(text)


def unquoted_mapping_colon(value: str) -> bool:
    """Does *value* contain a `: ` that YAML would read as a nested mapping?

    A plain (unquoted) YAML scalar may not contain ``": "``. Writing
    ``description: procedures under prompts/: install-uv`` therefore makes the whole
    frontmatter unparseable — and five of seven commands shipped exactly that, because
    the key check below was a substring search that never tried to parse anything.
    """
    stripped = value.strip()
    if not stripped or stripped[0] in "'\"|>":  # quoted or a block scalar: fine
        return False
    return ": " in stripped


def parse_frontmatter(block: str) -> tuple[dict[str, str], list[str]]:
    """Parse a simple ``key: value`` frontmatter block; return (mapping, problems).

    Deliberately a strict subset rather than a YAML library: the scripts are
    stdlib-only, and the failure being guarded against is precisely a value that a real
    YAML parser would choke on.
    """
    mapping: dict[str, str] = {}
    problems: list[str] = []
    for number, line in enumerate(block.splitlines(), start=2):
        if not line.strip() or line.startswith("#"):
            continue
        if line[0].isspace():  # a continuation of the previous value
            continue
        if ":" not in line:
            problems.append(f"line {number} is not `key: value`: {line[:60]!r}")
            continue
        key, _, value = line.partition(":")
        mapping[key.strip()] = value.strip()
        if unquoted_mapping_colon(value):
            problems.append(
                f"`{key.strip()}` contains an unquoted `: `, which YAML reads as a "
                "nested mapping — quote the value or rewrite the colon"
            )
    return mapping, problems


def check_frontmatter(rel: str, text: str, *, is_command: bool) -> list[str]:
    """Rule 1: commands declare parseable frontmatter; procedures declare none."""
    block = frontmatter(text)
    if not is_command:
        if block is not None:
            return [f"{rel}: has frontmatter, but a procedure is not invocable"]
        return []
    if block is None:
        return [f"{rel}: missing frontmatter"]

    mapping, problems = parse_frontmatter(block)
    violations = [f"{rel}: {problem}" for problem in problems]
    violations += [
        f"{rel}: frontmatter has no `{key}`" for key in _FRONTMATTER_KEYS if key not in mapping
    ]
    return violations


def check_bash_syntax(rel: str, blocks: list[str]) -> list[str]:
    """Rule 2: every bash block is syntactically valid shell."""
    bash = shutil.which("bash")
    if bash is None:  # pragma: no cover - bash is present everywhere this runs
        return []
    violations = []
    for i, block in enumerate(blocks, 1):
        cleaned = _ANGLE_PLACEHOLDER.sub("PLACEHOLDER", block)
        result = subprocess.run(  # nosec B603
            [bash, "-n"], input=cleaned, capture_output=True, text=True, check=False
        )
        if result.returncode != 0:
            detail = result.stderr.strip().splitlines()[-1] if result.stderr.strip() else "?"
            violations.append(f"{rel}: bash block {i} is not valid shell — {detail}")
    return violations


def check_script_calls(rel: str, blocks: list[str], scripts_dir: Path) -> list[str]:
    """Rules 3 and 4: invoked scripts exist, and their flags are real.

    Backslash continuations are joined first. Nearly every invocation in this prose is
    wrapped across lines, so without joining, only the first line's flags are seen —
    and a bad flag on a later line would pass unnoticed.
    """
    violations = []
    for raw in blocks:
        block = raw.replace("\\\n", " ")
        for name, args in _SCRIPT_CALL.findall(block):
            path = scripts_dir / f"{name}.py"
            if not path.is_file():
                violations.append(f"{rel}: invokes scripts/{name}.py, which does not exist")
                continue
            declared = script_flags(path)
            for flag in _FLAG.findall(args):
                if flag not in declared:
                    violations.append(
                        f"{rel}: passes {flag} to scripts/{name}.py, which does not accept it"
                    )
    return violations


def check_slash_commands(rel: str, text: str, commands_dir: Path) -> list[str]:
    """Rule 5: every command we tell the model to *invoke* exists.

    Only invocations are checked, not mentions. Prose legitimately refers to retired
    commands to explain history ("the view the retired ``/rhiza:tree`` gave",
    "absorbs ``/rhiza:validate``"), and flagging those would push authors to delete
    useful context. What must not dangle is an instruction to run something.
    """
    invoked = set(_SKILL_INVOCATION.findall(text))
    for block in bash_blocks(text):
        invoked |= set(_SLASH_COMMAND.findall(block))
    return [
        f"{rel}: tells the model to invoke `{name}`, which is not a command"
        for name in sorted(invoked)
        if not (commands_dir / f"{name}.md").is_file()
    ]


def _leading_binaries(blocks: list[str]) -> set[str]:
    """Return the binary invoked at the start of each command line across *blocks*.

    Backslash continuations are joined first: without that, the second line of a
    wrapped invocation looks like a command of its own and every flag reads as a
    binary name.
    """
    found: set[str] = set()
    for block in blocks:
        joined = block.replace("\\\n", " ")
        for raw in joined.splitlines():
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            word = line.split()[0]
            # Skip variable assignments (`BRANCH=...`) and anything flag-shaped.
            if word.startswith("-") or "=" in word:
                continue
            found.add(word)
    return found


def check_allowed_tools(rel: str, text: str, blocks: list[str]) -> list[str]:
    """Rule 6: a command may run the binaries its blocks actually call."""
    block_text = frontmatter(text)
    if block_text is None:
        return []
    line = next((ln for ln in block_text.splitlines() if ln.startswith("allowed-tools:")), None)
    if line is None:
        return []
    permitted = set(_ALLOWED_BASH.findall(line))
    return [
        f"{rel}: runs `{binary}` but allowed-tools has no Bash({binary}*)"
        for binary in sorted(_leading_binaries(blocks))
        if binary not in permitted and binary not in _SHELL_BUILTINS
    ]


def check_model_invocation(rel: str, stem: str, text: str) -> list[str]:
    """Rule 7: exactly the opt-out commands disable model invocation.

    Checked in both directions. A missing key on a destructive command is the
    dangerous failure, but an unexpected key elsewhere matters too: it silently
    removes a command from what the model can reach, and the user only finds out by
    the command never firing.
    """
    block = frontmatter(text)
    if block is None:  # already reported as missing frontmatter by rule 1
        return []
    declared = parse_frontmatter(block)[0].get(_OPT_OUT_KEY)
    if stem in _MODEL_INVOCATION_OPT_OUT:
        if declared != "true":
            return [
                f"{rel}: has side effects the user must ask for by name, so it must "
                f"declare `{_OPT_OUT_KEY}: true` (found: {declared or 'nothing'})"
            ]
        return []
    if declared is not None:
        return [
            f"{rel}: declares `{_OPT_OUT_KEY}: {declared}` but is not in the opt-out "
            f"set — add `{stem}` to _MODEL_INVOCATION_OPT_OUT or drop the key"
        ]
    return []


def check_contracts(root: Path) -> list[str]:
    """Run every rule over the plugin at *root*; return all violations."""
    commands_dir, prompts_dir, scripts_dir = root / "commands", root / "prompts", root / "scripts"
    violations: list[str] = []

    for directory, is_command in ((commands_dir, True), (prompts_dir, False)):
        if not directory.is_dir():
            continue
        for path in sorted(directory.glob("*.md")):
            rel = f"{directory.name}/{path.name}"
            text = path.read_text()
            blocks = bash_blocks(text)
            violations += check_frontmatter(rel, text, is_command=is_command)
            violations += check_bash_syntax(rel, blocks)
            violations += check_script_calls(rel, blocks, scripts_dir)
            violations += check_slash_commands(rel, text, commands_dir)
            if is_command:
                violations += check_allowed_tools(rel, text, blocks)
                violations += check_model_invocation(rel, path.stem, text)
    return violations


def main(argv: list[str] | None = None) -> int:
    """Entry point: check every command contract and return an exit code."""
    parser = argparse.ArgumentParser(description="Check the plugin's prose command contracts.")
    parser.add_argument("--root", default=".", help="Plugin root (default: current directory).")
    args = parser.parse_args(argv)

    root = Path(args.root).resolve()
    violations = check_contracts(root)
    if violations:
        print("Command-contract check failed:", file=sys.stderr)
        for violation in violations:
            print(f"  ✗ {violation}", file=sys.stderr)
        return 1

    count = len(list((root / "commands").glob("*.md"))) + len(list((root / "prompts").glob("*.md")))
    print(f"command contracts hold ({count} file(s) checked)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
