#!/usr/bin/env python3
"""Map a **write** operation onto `gh` or `glab` — one home for "the two CLIs disagree".

Every rhiza command that touches the forge has to pick between GitHub's `gh` and
GitLab's `glab`, and the two differ in **subcommand, flag names, and output shape**:

    gh   pr create    --base B --head H          --title T --body-file F
    glab mr create    --target-branch B --source-branch H --title T --description TEXT

    gh   issue create --title T --body-file F
    glab issue create --title T --description TEXT

    gh   repo view    --json defaultBranchRef,visibility  -> {"visibility": "PUBLIC"}
    glab repo view    -F json                             -> {"visibility": "public"}

That mapping used to live in command prose, where nothing executes it and no test can
reach it. It showed: `/update` shipped with **no GitLab branch at all**, detecting
GitLab, offering `gitlab-project`, then calling `gh pr create` and failing.

Extracting it is not sufficient on its own. The first extraction still passed
``--description-file`` to `glab mr create` — a flag **glab has never had** — and the
tests did not catch it, because they stubbed the CLI and asserted the argv the code
itself produced. Self-consistency is not correctness. The flags below were read off
`glab --help` and checked against a real binary; ``tests/test_platform_cli.py`` records
what each one is, so a future edit has something to contradict.

Actions:
  auth-status      is the platform CLI installed and logged in?
  repo-view        default branch + visibility, **normalised** across the two shapes
  pr-create        open a pull/merge request      pr-update  edit its body
  issue-create     file an issue
  release-create   publish a release from an existing tag

Reading a request's CI state is the same problem one door down, and it lives in
``pr_status.py`` rather than here: its two CLIs disagree about *shape* far more than
about flags, and folding it in would push this module past the size and complexity bars
it is held to. What the two share — deciding which forge `origin` is on at all — is in
``_rhiza_forge.py``, so there is still exactly one answer to that question.

Two divergences are surfaced rather than papered over:

* **glab has no `--body-file`/`--description-file` anywhere.** The body is passed
  inline via ``--description``, so this script reads the file and puts its text on the
  command line. (`-d -` means "open an editor", which is useless non-interactively.)
* **glab has no `--generate-notes`.** `gh release create` can synthesise release notes;
  GitLab cannot. Asking for it on GitLab is an error naming the fix — pass
  ``--notes-file``, which `/rhiza:release` already has from `git-cliff`.

Usage:
  uv run --python 3.12 --no-project python \
      scripts/platform_cli.py ACTION [--target-dir DIR] [--dry-run] [--json] ...

Exit codes:
  0  done, or (with --dry-run) rendered
  1  the platform CLI failed, is absent, or is not authenticated
  2  the platform could not be determined, a required file is missing, or the
     action has no equivalent on this platform
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess  # nosec B404
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _rhiza_forge import PlatformError, detect_platform  # noqa: E402

EXIT_OK = 0
EXIT_CLI_FAILED = 1
EXIT_USAGE = 2

ACTIONS = (
    "auth-status",
    "repo-view",
    "pr-create",
    "pr-update",
    "issue-create",
    "release-create",
)

# The actions whose body text has to reach the CLI one way or the other.
_BODY_ACTIONS = ("pr-create", "pr-update", "issue-create")


class UnsupportedAction(Exception):
    """The requested action has no equivalent on this platform."""


def _github_command(action: str, opts: dict[str, Any]) -> list[str]:
    """Return the `gh` argv for *action*."""
    if action == "auth-status":
        return ["gh", "auth", "status"]
    if action == "repo-view":
        return ["gh", "repo", "view", "--json", "defaultBranchRef,visibility"]
    if action == "pr-update":
        return ["gh", "pr", "edit", opts["head"], "--body-file", opts["body_file"]]
    if action == "pr-create":
        return [
            "gh", "pr", "create",
            "--base", opts["base"], "--head", opts["head"],
            "--title", opts["title"], "--body-file", opts["body_file"],
        ]  # fmt: skip
    if action == "issue-create":
        return ["gh", "issue", "create", "--title", opts["title"], "--body-file", opts["body_file"]]
    command = ["gh", "release", "create", opts["tag"]]
    if opts.get("notes_file"):
        return [*command, "--notes-file", opts["notes_file"]]
    return [*command, "--generate-notes"]


def _gitlab_command(action: str, opts: dict[str, Any]) -> list[str]:
    """Return the `glab` argv for *action*.

    The body-carrying actions take their text **inline**: glab has no file flag for a
    description on `mr create`, `mr update` or `issue create`. Passing
    ``--description-file`` there is not a near-miss, it is ``Unknown flag``.
    """
    if action == "auth-status":
        return ["glab", "auth", "status"]
    if action == "repo-view":
        # `-F json` returns the Projects API object, which carries `default_branch`
        # and `visibility` directly. Parsed here rather than through glab's `--jq`, so
        # one piece of code normalises both platforms.
        return ["glab", "repo", "view", "-F", "json"]
    if action == "pr-update":
        return ["glab", "mr", "update", opts["head"], "--description", opts["body"]]
    if action == "pr-create":
        return [
            "glab", "mr", "create",
            "--target-branch", opts["base"], "--source-branch", opts["head"],
            "--title", opts["title"], "--description", opts["body"],
        ]  # fmt: skip
    if action == "issue-create":
        # Supplying both --title and --description is what stops glab opening an
        # editor, which would hang a non-interactive run.
        return ["glab", "issue", "create", "--title", opts["title"], "--description", opts["body"]]
    if not opts.get("notes_file"):
        raise UnsupportedAction(
            "glab has no --generate-notes; pass --notes-file (e.g. the git-cliff output "
            "that /rhiza:release already produces)"
        )
    return ["glab", "release", "create", opts["tag"], "--notes-file", opts["notes_file"]]


def build_command(platform: str, action: str, **opts: Any) -> list[str]:
    """Return the argv that performs *action* on *platform*.

    Kept separate from execution so a test can assert the exact argv for both
    platforms with neither CLI installed.
    """
    if platform == "github":
        return _github_command(action, opts)
    return _gitlab_command(action, opts)


def normalize_repo_view(platform: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Reduce either CLI's `repo view` JSON to ``{default_branch, visibility}``.

    The two disagree on key names *and* on case — gh answers ``"PUBLIC"``, glab
    ``"public"`` — so a caller comparing the raw value gets a platform-dependent
    answer. Visibility is lower-cased here.
    """
    if platform == "github":
        branch = (payload.get("defaultBranchRef") or {}).get("name")
    else:
        branch = payload.get("default_branch")
    visibility = payload.get("visibility")
    return {
        "default_branch": branch or None,
        "visibility": visibility.lower() if isinstance(visibility, str) else None,
    }


def run(target_dir: Path, action: str, *, dry_run: bool = False, **opts: Any) -> dict[str, Any]:
    """Perform *action* against *target_dir*'s platform; return a summary dict."""
    platform = detect_platform(target_dir)
    command = build_command(platform, action, **opts)

    summary: dict[str, Any] = {
        "platform": platform,
        "action": action,
        "command": command,
        "dry_run": dry_run,
        "url": None,
        "data": None,
        "notes": [],
        "exit_code": EXIT_OK,
    }
    if dry_run:
        summary["notes"].append("dry run — nothing was executed")
        return summary

    # Run the path `which` resolved, not the bare name again. On Windows the two are not
    # the same question: `shutil.which` honours PATHEXT and so finds a `gh.cmd`/`glab.cmd`
    # shim (how npm- and scoop-installed CLIs commonly arrive), while CreateProcess given
    # a bare name only ever appends `.exe` — so the check passed and the call then failed
    # with FileNotFoundError. Handing it the resolved path closes that gap, and matches
    # what `_rhiza_forge.git_stdout` already does for git.
    executable = shutil.which(command[0])
    if executable is None:
        summary.update(
            exit_code=EXIT_CLI_FAILED,
            notes=[f"{command[0]} is not installed — do this step manually"],
        )
        return summary

    result = subprocess.run(  # nosec B603
        [executable, *command[1:]], cwd=str(target_dir), capture_output=True, text=True, check=False
    )
    if result.returncode != 0:
        summary.update(
            exit_code=EXIT_CLI_FAILED,
            notes=[f"{command[0]} failed: {result.stderr.strip()[:300]}"],
        )
        return summary

    if action == "repo-view":
        try:
            payload = json.loads(result.stdout)
        except ValueError:
            summary.update(
                exit_code=EXIT_CLI_FAILED,
                notes=[f"{command[0]} returned output that is not JSON"],
            )
            return summary
        summary["data"] = normalize_repo_view(platform, payload)
        return summary

    summary["url"] = next(
        (line.strip() for line in result.stdout.splitlines() if line.strip().startswith("http")),
        None,
    )
    return summary


def resolve_body(target_dir: Path, body_file: str | None) -> str | None:
    """Return the text of *body_file*, or None when it is absent or unreadable.

    The text is read even for GitHub, which takes a path: it is the only way to give
    the GitLab branch what it needs, and reading it here means a missing file is one
    error at the boundary rather than two divergent ones inside the CLIs.
    """
    if not body_file:
        return None
    candidate = target_dir / body_file
    if not candidate.is_file():
        candidate = Path(body_file)
    return candidate.read_text(encoding="utf-8") if candidate.is_file() else None


def main(argv: list[str] | None = None) -> int:
    """Entry point: perform the requested action and return an exit code."""
    parser = argparse.ArgumentParser(description="Run a forge operation on gh or glab.")
    parser.add_argument("action", choices=ACTIONS, help="The operation to perform.")
    parser.add_argument("--target-dir", default=".", help="Repository root (default: cwd).")
    parser.add_argument("--base", default="", help="Branch to merge into (pr-create).")
    parser.add_argument("--head", default="", help="Branch holding the work (pr-create/update).")
    parser.add_argument("--title", default="", help="Title (pr-create, issue-create).")
    parser.add_argument(
        "--body-file", default=None, help="File holding the body (pr-create/update, issue-create)."
    )
    parser.add_argument("--tag", default="", help="Tag to release (release-create).")
    parser.add_argument(
        "--notes-file", default=None, help="Release notes file; required on GitLab."
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Print the command without running it."
    )
    parser.add_argument(
        "--json", dest="json_output", action="store_true", help="Emit the summary as JSON."
    )
    args = parser.parse_args(argv)

    target_dir = Path(args.target_dir).resolve()
    body = resolve_body(target_dir, args.body_file)
    if args.action in _BODY_ACTIONS and body is None:
        print(f"error: --body-file is required and must exist for {args.action}", file=sys.stderr)
        return EXIT_USAGE

    try:
        summary = run(
            target_dir,
            args.action,
            dry_run=args.dry_run,
            base=args.base,
            head=args.head,
            title=args.title,
            body_file=args.body_file,
            body=body,
            tag=args.tag,
            notes_file=args.notes_file,
        )
    except (PlatformError, UnsupportedAction) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_USAGE

    if args.json_output:
        print(json.dumps(summary, indent=2))
    else:
        print(f"platform {summary['platform']}")
        print(f"command  {' '.join(summary['command'])}")
        if summary["url"]:
            print(f"url      {summary['url']}")
        for key, value in (summary["data"] or {}).items():
            print(f"{key:<14} {value}")
        for note in summary["notes"]:
            stream = sys.stdout if summary["exit_code"] == EXIT_OK else sys.stderr
            print(f"note     {note}", file=stream)
    return int(summary["exit_code"])


if __name__ == "__main__":
    raise SystemExit(main())
