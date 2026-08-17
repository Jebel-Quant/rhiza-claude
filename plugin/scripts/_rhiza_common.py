#!/usr/bin/env python3
"""The two things every part of the sync pipeline needs: its error type and its logger.

Both would naturally live in `sync.py`, but the modules it orchestrates raise the error
and write the log lines — so keeping them there would force each extracted module to
import its own orchestrator, which is a cycle. One small shared module is the cheaper
answer than five copies or a circular import.
"""

from __future__ import annotations

import sys


class SyncError(Exception):
    """A fatal, non-conflict sync failure (bad config, dirty tree, git error)."""


def has_drive_letter(value: str) -> bool:
    """Does *value* begin with a Windows drive letter (``C:``)?

    Shared because two callers ask it for opposite reasons and must agree on the answer:
    `_rhiza_bundles` **rejects** a drive-lettered bundle path as an escape from the
    project directory, while `_rhiza_template` **accepts** one as a local template to
    clone verbatim. A copy that drifted would either sync from `https://github.com/C:/…`
    or let a bundle write outside the repo.

    >>> has_drive_letter("C:/Users/dev/template")
    True
    >>> has_drive_letter(r"d:\\work\\rhiza")
    True

    A forward-slash path, a URL and an ``owner/repo`` are all unaffected — none has a
    colon in second position:

    >>> [has_drive_letter(v) for v in ("/tmp/t", "jebel-quant/rhiza", "https://x/y")]
    [False, False, False]
    """
    return len(value) >= 2 and value[0].isalpha() and value[1] == ":"


def log(message: str) -> None:
    """Emit a progress/diagnostic line to stderr.

    stderr, not stdout: `/update` reads the sync's exit code and shows this text to the
    user, while stdout stays free for machine-readable output.
    """
    print(message, file=sys.stderr)
