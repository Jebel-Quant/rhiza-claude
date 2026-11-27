"""Tests for `scripts/check_complexity.py`."""

from __future__ import annotations

import json
import shutil
import subprocess

import check_complexity
import pytest


def _block(name, complexity, lineno=1, closures=()):
    return {"name": name, "lineno": lineno, "complexity": complexity, "closures": list(closures)}


def _fake_radon(monkeypatch, *, stdout="{}", returncode=0, stderr=""):
    """Stand in for `uvx radon` and record the argv it was asked to run."""
    calls = []

    def run(argv, **kwargs):
        calls.append(argv)
        return subprocess.CompletedProcess(argv, returncode, stdout=stdout, stderr=stderr)

    monkeypatch.setattr(check_complexity.subprocess, "run", run)
    monkeypatch.setattr(check_complexity.shutil, "which", lambda name: f"/bin/{name}")
    return calls


def test_a_block_at_the_ceiling_passes():
    assert check_complexity.violations({"a.py": [_block("f", 12)]}, 12) == []


def test_a_block_one_over_the_ceiling_fails():
    assert check_complexity.violations({"a.py": [_block("f", 13, lineno=7)]}, 12) == [
        "a.py:7 f — complexity 13 (max 12)"
    ]


def test_a_closure_is_held_to_the_bar_even_when_its_parent_is_not():
    # radon's text report hides closures, so nesting is how a bar that skipped them is met.
    nested = _block("outer", 2, closures=[_block("mid", 3, closures=[_block("deep", 15, 5)])])
    assert check_complexity.violations({"a.py": [nested]}, 12) == [
        "a.py:5 deep — complexity 15 (max 12)"
    ]


def test_a_block_without_a_closures_key_is_measured():
    # Classes carry `methods` rather than `closures`; their methods also appear flat.
    klass = {"name": "K", "lineno": 1, "complexity": 20, "methods": [_block("m", 20)]}
    assert check_complexity.violations({"a.py": [klass]}, 12) == [
        "a.py:1 K — complexity 20 (max 12)"
    ]


def test_an_unparseable_file_fails_rather_than_passing_unmeasured():
    report = {"b.py": {"error": "invalid syntax"}, "c.py": {}}
    assert check_complexity.violations(report, 12) == [
        "b.py — could not be measured: invalid syntax",
        "c.py — could not be measured: unknown error",
    ]


def test_main_passes_on_a_clean_tree_and_runs_radon_on_the_root(monkeypatch, capsys):
    calls = _fake_radon(monkeypatch, stdout=json.dumps({"a.py": [_block("f", 4)]}))
    assert check_complexity.main(["--root", "src"]) == 0
    assert calls == [["/bin/uvx", "radon", "cc", "--json", "src"]]
    assert capsys.readouterr().out == ""


def test_main_reports_each_violation_and_exits_one(monkeypatch, capsys):
    _fake_radon(monkeypatch, stdout=json.dumps({"a.py": [_block("f", 9, lineno=2)]}))
    assert check_complexity.main(["--max", "8"]) == 1
    captured = capsys.readouterr()
    assert "a.py:2 f — complexity 9 (max 8)" in captured.out
    assert "rather than raising the ceiling" in captured.err


def test_main_exits_two_when_radon_cannot_run(monkeypatch, capsys):
    _fake_radon(monkeypatch, returncode=2, stderr="No solution found\n")
    assert check_complexity.main([]) == 2
    assert "radon failed (exit 2): No solution found" in capsys.readouterr().err


def test_main_exits_two_without_uvx_rather_than_passing_unmeasured(monkeypatch, capsys):
    monkeypatch.setattr(check_complexity.shutil, "which", lambda name: None)
    assert check_complexity.main([]) == 2
    assert "uvx not found" in capsys.readouterr().err


@pytest.mark.skipif(shutil.which("uvx") is None, reason="needs uvx to fetch radon")
def test_a_real_c13_function_fails_the_gate(tmp_path, capsys):
    # The issue's acceptance criterion, measured by the real tool rather than a fixture:
    # twelve independent `if`s on top of the function's own path is complexity 13.
    body = "".join(f"    if a == {i}:\n        return {i}\n" for i in range(12))
    (tmp_path / "m.py").write_text(f"def f(a):\n{body}    return -1\n", encoding="utf-8")
    assert check_complexity.main(["--root", str(tmp_path)]) == 1
    assert "f — complexity 13 (max 12)" in capsys.readouterr().out
