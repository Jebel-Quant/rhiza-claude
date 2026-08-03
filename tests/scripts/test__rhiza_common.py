"""Tests for the sync pipeline's shared error type and logger (`scripts/_rhiza_common.py`).

It lives in its own module because every `_rhiza_*` module raises it and `sync.py`
catches it — left in `sync.py`, the extracted modules would have to import their own
orchestrator.
"""

from __future__ import annotations

from _rhiza_common import SyncError, log


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
