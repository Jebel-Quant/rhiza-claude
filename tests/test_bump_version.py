"""Tests for `scripts/bump_version.py`."""

from __future__ import annotations

import sys

import bump_version
import pytest

_PLUGIN = '{\n  "name": "rhiza",\n  "version": "0.1.0"\n}\n'
_MARKET = '{\n  "plugins": [\n    { "name": "rhiza", "version": "0.1.0" }\n  ]\n}\n'


def _manifests(root):
    d = root / ".claude-plugin"
    d.mkdir()
    (d / "plugin.json").write_text(_PLUGIN)
    (d / "marketplace.json").write_text(_MARKET)
    return d


def test_bumps_both_manifests(tmp_path, monkeypatch, capsys):
    d = _manifests(tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", ["bump_version.py", "0.4.2"])
    bump_version.main()
    assert '"version": "0.4.2"' in (d / "plugin.json").read_text()
    assert '"version": "0.4.2"' in (d / "marketplace.json").read_text()
    assert "0.4.2" in capsys.readouterr().out


def test_strips_leading_v(tmp_path, monkeypatch):
    d = _manifests(tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", ["bump_version.py", "v2.0.0"])
    bump_version.main()
    assert '"version": "2.0.0"' in (d / "plugin.json").read_text()


def test_usage_error_without_arg(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", ["bump_version.py"])
    with pytest.raises(SystemExit) as exc:
        bump_version.main()
    assert exc.value.code == 2


def test_error_when_no_version_field(tmp_path, monkeypatch):
    d = tmp_path / ".claude-plugin"
    d.mkdir()
    (d / "plugin.json").write_text('{\n  "name": "rhiza"\n}\n')  # no version
    (d / "marketplace.json").write_text(_MARKET)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", ["bump_version.py", "0.5.0"])
    with pytest.raises(SystemExit) as exc:
        bump_version.main()
    assert exc.value.code == 1
