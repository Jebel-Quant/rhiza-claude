#!/usr/bin/env python3
"""The two things every part of the sync pipeline needs: its error type and its logger.

Both would naturally live in `sync.py`, but the modules it orchestrates raise the error
and write the log lines — so keeping them there would force each extracted module to
import its own orchestrator, which is a cycle. One small shared module is the cheaper
answer than five copies or a circular import.
"""

from __future__ import annotations

import sys
from pathlib import PurePosixPath


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


def escapes_root(value: str) -> bool:
    r"""Would joining *value* onto a project root land outside it?

    Every path this plugin joins onto a target directory arrives from the template repo —
    a bundle's ``dest``, a lock file's ``files`` entry — so none of them is the repo's own
    text. Three shapes leave the project: an absolute path, a Windows drive letter, and a
    ``..`` component. A backslash is normalised to a forward slash **first**, so a Windows
    separator cannot smuggle a traversal past the check:

    >>> [escapes_root(v) for v in ("Makefile", ".github/workflows/ci.yml", "a/./b")]
    [False, False, False]
    >>> [escapes_root(v) for v in ("/etc/passwd", "..\\secrets.env", "C:/Windows", "a/../../b")]
    [True, True, True, True]

    A predicate rather than a raiser because its two callers must fail differently: the
    sync raises :class:`SyncError` on a bad bundle path, while `stage_synced` returns a
    summary dict and an exit code. Sharing the *rule* is the point; a second copy of it
    is how one of them ends up enforcing something slightly different.
    """
    normalized = value.replace("\\", "/")
    pure = PurePosixPath(normalized)
    return pure.is_absolute() or has_drive_letter(normalized) or ".." in pure.parts


def log(message: str) -> None:
    """Emit a progress/diagnostic line to stderr.

    stderr, not stdout: `/update` reads the sync's exit code and shows this text to the
    user, while stdout stays free for machine-readable output.
    """
    print(message, file=sys.stderr)
