"""Tests for `scripts/check_version_parity.py`."""

from __future__ import annotations

import check_version_parity
import pytest


def _write(root, plugin_ver, market_ver):
    d = root / ".claude-plugin"
    d.mkdir()
    (d / "plugin.json").write_text(f'{{"name": "rhiza", "version": "{plugin_ver}"}}')
    (d / "marketplace.json").write_text(
        f'{{"plugins": [{{"name": "rhiza", "version": "{market_ver}"}}]}}'
    )


def test_match_passes(tmp_path, monkeypatch, capsys):
    _write(tmp_path, "0.3.0", "0.3.0")
    monkeypatch.chdir(tmp_path)
    check_version_parity.main()  # no exit
    assert "match" in capsys.readouterr().out


def test_mismatch_exits_nonzero(tmp_path, monkeypatch, capsys):
    _write(tmp_path, "0.3.0", "0.2.0")
    monkeypatch.chdir(tmp_path)
    with pytest.raises(SystemExit) as exc:
        check_version_parity.main()
    assert exc.value.code == 1
    assert "mismatch" in capsys.readouterr().err.lower()
