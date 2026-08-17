"""Tests for the sync pipeline's shared error type and logger (`scripts/_rhiza_common.py`).

It lives in its own module because every `_rhiza_*` module raises it and `sync.py`
catches it — left in `sync.py`, the extracted modules would have to import their own
orchestrator.
"""

from __future__ import annotations

import pytest
from _rhiza_common import SyncError, has_drive_letter, log


class TestSyncError:
    def test_is_exception_with_message(self):
        err = SyncError("boom")
        assert isinstance(err, Exception)
        assert str(err) == "boom"


def test_log_writes_to_stderr(capsys):
    """stderr, so stdout stays free for machine-readable output."""
    log("progress")
    captured = capsys.readouterr()
    assert captured.err == "progress\n"
    assert captured.out == ""


# `has_drive_letter` is shared by two callers that ask it for opposite reasons — see its
# docstring — so the cases below are written from both sides: what `_rhiza_bundles` must
# reject, and what `_rhiza_template` must clone verbatim rather than paste onto a forge URL.
@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("C:/Users/dev/template", True),
        ("c:/users/dev", True),
        ("D:\\work\\rhiza", True),
        ("Z:", True),
        # An `owner/repo`, a POSIX path and a URL must all stay false, or a perfectly
        # ordinary template pointer would be treated as a local directory.
        ("jebel-quant/rhiza", False),
        ("/srv/templates/rhiza", False),
        ("./relative", False),
        ("https://github.com/acme/widget.git", False),
        ("git@github.com:acme/widget.git", False),
        # Too short to carry a drive letter, and a non-alphabetic first character.
        ("C", False),
        ("", False),
        ("1:/nope", False),
        (":/nope", False),
    ],
)
def test_has_drive_letter(value, expected):
    assert has_drive_letter(value) is expected
