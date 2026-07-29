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


def log(message: str) -> None:
    """Emit a progress/diagnostic line to stderr.

    stderr, not stdout: `/update` reads the sync's exit code and shows this text to the
    user, while stdout stays free for machine-readable output.
    """
    print(message, file=sys.stderr)
