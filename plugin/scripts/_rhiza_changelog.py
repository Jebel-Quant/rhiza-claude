#!/usr/bin/env python3
r"""Read the newest version a `CHANGELOG.md` names — the one parser, for both readers.

`/rhiza:release` asks this question twice, from two directions, and both answers have to
agree or the release strands:

* `check_version_bump.py` reads the **local** file to decide which phase the repo is in.
  On a tag-derived repo it is the only evidence that a bump has landed, because there the
  declared version *is* the newest tag and so can never exceed it.
* `wait_for_merge.py` reads the file **on the remote default branch**, through
  `git show`, to decide whether the release PR's bump has arrived.

Two copies of one regex is how those two come to disagree — one accepting `## [v1.7.0]`
and the other not, on a repo whose `cliff.toml` writes the prefix, would leave the wait
polling forever for a release the phase check can already see. So the pattern lives here
and neither caller owns it.

What counts as a release heading is deliberately loose about everything except the
version: the level (`#` to `###`), the brackets, and a `v` prefix are all `cliff.toml`
decisions or hand-editing habits, and all of them appear in real changelogs. The digits
are the part that is not optional, which is what makes an `Unreleased` section invisible
here rather than something to special-case.
"""

from __future__ import annotations

import re
from pathlib import Path

_CHANGELOG_HEADING = re.compile(r"^#{1,3}\s*\[?v?(\d+\.\d+\.\d+[0-9A-Za-z.+-]*)\]?", re.M)


def newest_changelog_version(text: str) -> str | None:
    r"""Return the newest version a changelog's headings name, or ``None``.

    This is the committed evidence a tag-derived repo has and a manifest-declared one
    does not. `/rhiza:release` writes the section with `git-cliff --prepend`, so the
    newest release is the **first** version-shaped heading in the file.

    >>> newest_changelog_version("# Changelog\n\n## [1.7.0] - 2026-09-07\n\n## [1.6.0]\n")
    '1.7.0'

    An `Unreleased` heading is not version-shaped, so it is skipped rather than
    swallowing the section under it:

    >>> newest_changelog_version("## [Unreleased]\n\n## [1.6.0] - 2026-09-04\n")
    '1.6.0'

    A `v` prefix, a bare heading with no brackets, and a deeper level all parse:

    >>> [
    ...     newest_changelog_version("## [v2.0.0]\n"),
    ...     newest_changelog_version("## 0.9.1 - 2026-01-01\n"),
    ...     newest_changelog_version("### [1.0.0-rc.1]\n"),
    ... ]
    ['2.0.0', '0.9.1', '1.0.0-rc.1']

    A file with no version heading at all yields nothing, rather than a guess:

    >>> print(newest_changelog_version("# Changelog\n\nNothing released yet.\n"))
    None
    """
    match = _CHANGELOG_HEADING.search(text)
    return match[1] if match else None


def read_changelog_version(path: Path) -> str | None:
    """Return the newest version named by the changelog at *path*, or ``None``.

    A missing or unreadable file is not an error: a repo need not keep a changelog, and
    the phase decision in `check_version_bump.py` is what turns "no evidence" into a
    verdict. Reading it here keeps the markdown parsing in tested Python rather than in a
    caller's regex.
    """
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    return newest_changelog_version(text)
