"""Tests for the validator's reporting sink (`scripts/_validate_log.py`)."""

from __future__ import annotations

from _validate_log import Log


class TestLog:
    """Two audiences from one call: stderr for a human, buffers for `--json`."""

    def test_error_and_warning_recorded(self):
        lg = Log()
        lg.error("boom")
        lg.warning("careful")
        assert lg.errors == ["boom"]
        assert lg.warnings == ["careful"]

    def test_levels_and_verbose_gating(self, capsys):
        quiet = Log(verbose=False)
        quiet.debug("hidden")
        assert capsys.readouterr().err == ""
        loud = Log(verbose=True)
        loud.success("ok")
        loud.info("fyi")
        loud.debug("shown")
        err = capsys.readouterr().err
        assert "ok" in err and "fyi" in err and "shown" in err

    def test_success_and_info_are_not_recorded_as_faults(self):
        """Only errors and warnings reach `--json`; the rest is progress noise."""
        lg = Log()
        lg.success("fine")
        lg.info("fyi")
        assert lg.errors == []
        assert lg.warnings == []
