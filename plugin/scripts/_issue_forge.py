"""The forge half of ``issue_status.py``: ask `gh` or `glab`, and read back one shape.

Split from ``issue_status.py`` for the same reason ``_issue_signals`` was: asking a forge
for a payload and deciding what that payload means are different instruments with
different failure modes. This half owns everything that knows a CLI exists — the argv,
the subprocess, and the per-platform key names — and hands the orchestrator issues in one
shared vocabulary. Nothing here reads an issue's prose or touches the working tree.

The two CLIs disagree about the **shape** of an issue, not merely about flag names, and
there are five disagreements in a single object:

    gh   issue list --state open --json number,title,body,labels,author,createdAt,url
         -> {"number": 95, "body": "…", "labels": [{"name": "bug"}],
             "author": {"login": "tschm"}, "createdAt": "…", "url": "…"}

    glab issue list --output json --per-page 20
         -> {"iid": 95, "description": "…", "labels": ["bug"],
             "author": {"username": "tschm"}, "created_at": "…", "web_url": "…"}

Read with the other's keys, every one of those yields an empty body or a nameless issue
rather than an error — which is the failure mode `platform_cli.py` records having
shipped once already, when `/update` reached GitLab with a flag `glab` does not have.
"""

from __future__ import annotations

import json
import shutil
import subprocess  # nosec B404
from pathlib import Path
from typing import Any

# Spelled out rather than globbed: `gh` errors on an unknown field, so this list is
# itself a contract with the CLI and a typo here fails loudly instead of silently
# dropping a signal the triage depends on.
_GH_FIELDS = "number,title,body,labels,author,createdAt,updatedAt,url,state,stateReason,closedAt"
_GH_REQUEST_FIELDS = "number,title,body,url"

# Which issues a listing asks for. GitHub takes the word; GitLab lists open issues by
# default and spells the other two as flags of their own.
STATES = ("open", "closed", "all")
_GLAB_STATE_FLAGS = {"open": [], "closed": ["--closed"], "all": ["--all"]}


class ForgeQueryError(Exception):
    """A platform CLI was absent, unauthenticated, or answered something unreadable."""


def build_issue_command(
    platform: str, *, limit: int, labels: list[str], state: str = "open"
) -> list[str]:
    """Return the argv listing issues in *state*, optionally narrowed to *labels*.

    >>> build_issue_command("github", limit=5, labels=[])[:5]
    ['gh', 'issue', 'list', '--state', 'open']

    GitLab's listing is open by default and takes its labels comma-joined, which is the
    second place these two CLIs stop lining up:

    >>> build_issue_command("gitlab", limit=5, labels=["bug", "docs"])[-2:]
    ['--label', 'bug,docs']

    and it has no ``--state``, so the history is a flag of its own:

    >>> build_issue_command("gitlab", limit=5, labels=[], state="all")[-1]
    '--all'
    """
    if platform == "github":
        command = ["gh", "issue", "list", "--state", state, "--json", _GH_FIELDS]
        command += ["--limit", str(limit)]
        for label in labels:
            command += ["--label", label]
        return command
    command = ["glab", "issue", "list", "--output", "json", "--per-page", str(limit)]
    command += _GLAB_STATE_FLAGS[state]
    return [*command, "--label", ",".join(labels)] if labels else command


def build_request_command(platform: str, *, limit: int) -> list[str]:
    """Return the argv listing open requests, so an issue already being worked is seen.

    >>> build_request_command("gitlab", limit=3)
    ['glab', 'mr', 'list', '--output', 'json', '--per-page', '3']
    """
    if platform == "github":
        return [
            "gh", "pr", "list", "--state", "open",
            "--json", _GH_REQUEST_FIELDS, "--limit", str(limit),
        ]  # fmt: skip
    return ["glab", "mr", "list", "--output", "json", "--per-page", str(limit)]


def build_reference_commands(platform: str, number: int) -> list[list[str]]:
    """Return the argv candidates that resolve reference *number*, in order.

    On GitHub one number may name an issue or a pull request, and only trying tells
    you which — so both are returned and the first that answers wins. On GitLab a `#N`
    is always an issue, so there is exactly one candidate and a merge request reached
    this way is simply not found:

    >>> build_reference_commands("gitlab", 75)
    [['glab', 'issue', 'view', '75', '--output', 'json']]
    >>> len(build_reference_commands("github", 75))
    2
    """
    if platform == "github":
        return [
            ["gh", "issue", "view", str(number), "--json", "number,state,title"],
            ["gh", "pr", "view", str(number), "--json", "number,state,title"],
        ]
    return [["glab", "issue", "view", str(number), "--output", "json"]]


def run_json(command: list[str], target_dir: Path) -> Any:
    """Run *command* in *target_dir* and parse its stdout as JSON.

    Raises:
        ForgeQueryError: the binary is missing, it failed, or stdout was not JSON.
    """
    binary = shutil.which(command[0])
    if binary is None:
        raise ForgeQueryError(f"{command[0]} is not installed")
    result = subprocess.run(  # nosec B603
        [binary, *command[1:]],
        cwd=str(target_dir),
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip().splitlines()
        raise ForgeQueryError(detail[0] if detail else f"{command[0]} failed")
    try:
        return json.loads(result.stdout or "[]")
    except json.JSONDecodeError as exc:  # pragma: no cover - defensive
        raise ForgeQueryError(f"{command[0]} did not answer JSON: {exc}") from exc


def _text(raw: dict[str, Any], key: str) -> str:
    """*raw*'s value at *key* as a string, with a missing or null value as ``''``."""
    return str(raw.get(key) or "")


def _state(value: str) -> str:
    """One forge's issue state in the shared vocabulary: ``open``, ``closed`` or ``''``.

    GitHub shouts (``OPEN``) and GitLab says ``opened``; neither is wrong, and a caller
    comparing against one spelling would silently miss the other:

    >>> [_state(v) for v in ("OPEN", "opened", "CLOSED", "")]
    ['open', 'open', 'closed', '']
    """
    lowered = value.lower()
    return "open" if lowered == "opened" else lowered


def _normalize_github(raw: dict[str, Any]) -> dict[str, Any]:
    """One `gh issue list` object in the shared vocabulary."""
    return {
        "id": raw.get("number"),
        "title": _text(raw, "title"),
        "body": _text(raw, "body"),
        "labels": [label.get("name", "") for label in raw.get("labels") or []],
        "author": (raw.get("author") or {}).get("login", ""),
        "created": _text(raw, "createdAt"),
        "url": _text(raw, "url"),
        "state": _state(_text(raw, "state")),
        "state_reason": _text(raw, "stateReason").lower(),
        "closed": _text(raw, "closedAt"),
    }


def _normalize_gitlab(raw: dict[str, Any]) -> dict[str, Any]:
    """One `glab issue list` object in the shared vocabulary.

    Five keys differ from GitHub's and none of them errors when read with the wrong
    name — `iid`/`number`, `description`/`body`, label strings against label objects,
    snake_case against camelCase, and `web_url`/`url`. A sixth is missing outright:
    GitLab records no reason for a close, so ``state_reason`` is always empty here.
    """
    return {
        "id": raw.get("iid"),
        "title": _text(raw, "title"),
        "body": _text(raw, "description"),
        "labels": list(raw.get("labels") or []),
        "author": (raw.get("author") or {}).get("username", ""),
        "created": _text(raw, "created_at"),
        "url": _text(raw, "web_url"),
        "state": _state(_text(raw, "state")),
        "state_reason": "",
        "closed": _text(raw, "closed_at"),
    }


def normalize(platform: str, raw: dict[str, Any]) -> dict[str, Any]:
    """Return one issue in the shared vocabulary, whichever CLI produced it.

    The whole point is that both sides land on the same object:

    >>> gh = {"number": 95, "title": "t", "body": "b", "labels": [{"name": "bug"}],
    ...       "author": {"login": "tschm"}, "createdAt": "x", "url": "u"}
    >>> lab = {"iid": 95, "title": "t", "description": "b", "labels": ["bug"],
    ...        "author": {"username": "tschm"}, "created_at": "x", "web_url": "u"}
    >>> normalize("github", gh) == normalize("gitlab", lab)
    True
    """
    return _normalize_github(raw) if platform == "github" else _normalize_gitlab(raw)
