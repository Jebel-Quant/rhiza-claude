#!/usr/bin/env python3
"""Does the template define the profile a pointer is about to name? Ask it, don't assume.

`.rhiza/template.yml` names a template repository, a ref, and a profile. The first two
are checked before `/rhiza:init` writes the pointer — `git ls-remote` proves the repo is
reachable, and the ref comes from the template's own release list. The third was not
checked at all, and it is the one that has been wrong twice:

* `rust-github-project` was written into the pointer for a Rust repo. The template has
  never defined it (commit `7021d43`).
* `rust-local` replaced it. That profile exists on `jebel-quant/rhiza`'s default branch
  and in **no release** — and `/init` pins the latest *release*.

Both fail the same way: `/init` succeeds, its PR merges, and the *first* `/rhiza:update`
dies with "Profile 'rust-local' was not found". The cost lands on the user, one step
removed from the mistake, in the command that did nothing wrong.

The fix is not a table of which profile each template defines at each ref — that is the
per-language table `language_profile.py` deliberately refuses to keep, for the same
reason: it describes repositories this plugin does not own and cannot see. Profiles vary
by template, by fork, and by ref, so they are **discovered**, exactly as `make` targets
are discovered by `check_make_targets.py`. This script reads the one file that knows —
the template's `.rhiza/template-bundles.yml`, at the ref in question — and reports.

Only that one file is fetched (a sparse, blobless clone), so the check costs a fraction
of a sync.

Usage:
  uv run --python 3.12 --no-project python \
      scripts/check_template_profile.py PROFILE [PROFILE ...] \
      --template-repo owner/repo --ref REF \
      [--template-host github|gitlab] [--bundles-path PATH] [--json]

Exit codes:
  0  every requested profile is defined at that ref
  1  at least one is not — the pointer would be unsatisfiable; **our** mistake to fix
  2  the template could not be read (network, unknown ref, no bundles file) — nothing
     was learned about the profile, so a caller should warn and continue rather than
     treat it as a missing profile. The two have different owners and different fixes,
     which is why they are different exit codes.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess  # nosec B404
import sys
import tempfile
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _rhiza_bundles import Bundles  # noqa: E402
from _rhiza_common import SyncError  # noqa: E402
from _rhiza_git import GitContext, clone  # noqa: E402
from _rhiza_template import Template  # noqa: E402
from _rhiza_yaml import load_yaml  # noqa: E402

EXIT_OK = 0
EXIT_MISSING = 1
EXIT_UNREADABLE = 2


def _reason(exc: Exception) -> str:
    """Render *exc* as one line a user can act on.

    A failed clone raises ``CalledProcessError``, whose ``str()`` is the whole argv —
    a temp path and a token-length URL, with git's own explanation ("Remote branch v9.9.9
    not found", "could not resolve host") nowhere in it. That explanation is on stderr,
    so prefer it.
    """
    stderr = getattr(exc, "stderr", None)
    if stderr:
        text = stderr.decode(errors="replace") if isinstance(stderr, bytes) else str(stderr)
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        if lines:
            return lines[-1]
    return str(exc)


def available_profiles(
    repository: str, ref: str, *, host: str = "github", bundles_path: str | None = None
) -> list[str]:
    """Return the profile names *repository* defines at *ref*, sorted.

    Raises:
        SyncError: If the template could not be cloned, or its bundles file is absent
            or unparseable — i.e. nothing could be learned, as opposed to learning that
            a profile is missing.
    """
    template = (
        Template(repository=repository, ref=ref, host=host, bundles_path=bundles_path)
        if bundles_path
        else Template(repository=repository, ref=ref, host=host)
    )
    work_dir = Path(tempfile.mkdtemp())
    try:
        clone(GitContext.default(), template.git_url, work_dir, [template.bundles_path], branch=ref)
        bundles_file = work_dir / template.bundles_path
        if not bundles_file.is_file():
            raise SyncError(
                f"{repository}@{ref} has no {template.bundles_path} — "
                "it may not be a rhiza template, or the path is configured elsewhere"
            )
        config = load_yaml(bundles_file)
    except (subprocess.CalledProcessError, OSError, RuntimeError, ValueError) as exc:
        raise SyncError(f"could not read {repository}@{ref}: {_reason(exc)}") from exc
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)
    return sorted(Bundles.from_config(config).profiles)


def check(
    repository: str,
    ref: str,
    profiles: list[str],
    *,
    host: str = "github",
    bundles_path: str | None = None,
) -> dict[str, Any]:
    """Report which of *profiles* the template defines at *ref*; return a summary dict."""
    summary: dict[str, Any] = {
        "repository": repository,
        "ref": ref,
        "host": host,
        "requested": profiles,
        "defined": [],
        "missing": [],
        "available": [],
        "error": None,
        "exit_code": EXIT_OK,
    }
    try:
        available = available_profiles(repository, ref, host=host, bundles_path=bundles_path)
    except SyncError as exc:
        summary["error"] = str(exc)
        summary["exit_code"] = EXIT_UNREADABLE
        return summary

    summary["available"] = available
    summary["defined"] = [p for p in profiles if p in available]
    summary["missing"] = [p for p in profiles if p not in available]
    if summary["missing"]:
        summary["exit_code"] = EXIT_MISSING
    return summary


def _report(summary: dict[str, Any]) -> list[str]:
    """Render the human-readable lines for *summary*, most important first."""
    where = f"{summary['repository']}@{summary['ref']}"
    if summary["exit_code"] == EXIT_UNREADABLE:
        return [
            f"unknown      {summary['error']}",
            "             Nothing was learned about the profile — warn and continue; "
            "this is a network or template-side problem, not a wrong pointer.",
        ]
    lines = [f"defined      {where} defines {p}" for p in summary["defined"]]
    for profile in summary["missing"]:
        lines.append(f"MISSING      {where} does not define {profile}")
    if summary["missing"]:
        lines.append(
            f"             available profiles: {', '.join(summary['available']) or 'none'}"
        )
        lines.append(
            "             A pointer naming it would sync fine at /init and fail at the "
            "first /rhiza:update. Pin a ref that defines it, or pick a profile that "
            "exists."
        )
    return lines


def main(argv: list[str] | None = None) -> int:
    """Entry point: check the profiles against the template and return an exit code."""
    parser = argparse.ArgumentParser(
        description="Check that a template defines the profiles a pointer would name.",
    )
    parser.add_argument("profiles", nargs="+", help="Profile name(s) to look for.")
    parser.add_argument(
        "--template-repo", required=True, help="Template repository, as owner/repo or a URL."
    )
    parser.add_argument("--ref", required=True, help="Template branch or tag to read.")
    parser.add_argument(
        "--template-host",
        choices=("github", "gitlab"),
        default="github",
        help="Where the TEMPLATE lives; sets the clone URL (default: github).",
    )
    parser.add_argument(
        "--bundles-path", help="Override the template's bundles file path (rarely needed)."
    )
    parser.add_argument(
        "--json", dest="json_output", action="store_true", help="Emit the summary as JSON."
    )
    args = parser.parse_args(argv)

    summary = check(
        args.template_repo,
        args.ref,
        list(args.profiles),
        host=args.template_host,
        bundles_path=args.bundles_path,
    )
    if args.json_output:
        print(json.dumps(summary, indent=2))
    else:
        stream = sys.stdout if summary["exit_code"] == EXIT_OK else sys.stderr
        for line in _report(summary):
            print(line, file=stream)
    return int(summary["exit_code"])


if __name__ == "__main__":
    raise SystemExit(main())
