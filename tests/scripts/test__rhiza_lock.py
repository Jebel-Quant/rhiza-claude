"""Tests for the lock file and orphan cleanup (`scripts/_rhiza_lock.py`).

The lock records the synced SHA and the exact file list. The next sync reads the SHA to
find its merge base, and `stage_synced.py` reads the file list so `/update` stages
template-owned paths only. Orphan cleanup is the lock's inverse.
"""

from __future__ import annotations

from pathlib import Path

import _rhiza_lock as rl
import pytest
from _rhiza_template import Template
from _rhiza_yaml import load_yaml


def test_build_lock_includes_profiles() -> None:
    template = Template("o/r", "v1", profiles=["p"], templates=["t"])
    lock = rl.build_lock("sha1", template, ["f.txt"], "2026-01-01T00:00:00Z")
    assert list(lock) == [
        "sha",
        "repo",
        "host",
        "ref",
        "include",
        "exclude",
        "templates",
        "profiles",
        "files",
        "synced_at",
        "strategy",
    ]
    assert lock["profiles"] == ["p"]


def test_write_lock_skips_unchanged(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    lock_path = tmp_path / "template.lock"
    (tmp_path / "f.txt").write_text("x")
    lock = rl.build_lock("sha1", Template("o/r", "v1", include=["f.txt"]), ["f.txt"], "t1")
    rl.write_lock(tmp_path, lock, lock_path)
    lock2 = rl.build_lock(
        "sha1", Template("o/r", "v1", include=["f.txt"]), ["f.txt"], "t2-different"
    )
    rl.write_lock(tmp_path, lock2, lock_path)
    assert "already up to date" in capsys.readouterr().err


def test_write_lock_rewrites_when_existing_malformed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lock_path = tmp_path / "template.lock"
    lock_path.write_text("garbage")
    (tmp_path / "f.txt").write_text("x")
    monkeypatch.setattr(rl, "load_yaml", lambda _p: (_ for _ in ()).throw(ValueError("bad")))
    lock = rl.build_lock("sha1", Template("o/r", "v1"), ["f.txt"], "t1")
    rl.write_lock(tmp_path, lock, lock_path)
    # dump_yaml is the real one; file should have been (re)written with our sha.
    assert "sha: sha1" in lock_path.read_text()


def test_write_lock_filters_missing_files(tmp_path: Path) -> None:
    lock_path = tmp_path / "template.lock"
    (tmp_path / "present.txt").write_text("x")
    lock = rl.build_lock("sha1", Template("o/r", "v1"), ["present.txt", "ghost.txt"], "t1")
    rl.write_lock(tmp_path, lock, lock_path)
    written = load_yaml(lock_path)
    assert written["files"] == ["present.txt"]


def test_clean_orphaned_unlink_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / "orphan.txt").write_text("x")
    monkeypatch.setattr(
        Path, "unlink", lambda self, *a, **k: (_ for _ in ()).throw(OSError("locked"))
    )
    rl.clean_orphaned_files(tmp_path, [], set(), {Path("orphan.txt")})
    assert "Failed to delete" in capsys.readouterr().err


def test_read_base_sha_variants(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    assert rl.read_base_sha(tmp_path / "none.lock") is None
    lock = tmp_path / "template.lock"
    lock.write_text("sha: abc\n")
    assert rl.read_base_sha(lock) == "abc"
    lock.write_text("ref: main\n")  # no sha
    assert rl.read_base_sha(lock) is None
    monkeypatch.setattr(rl, "load_yaml", lambda _p: (_ for _ in ()).throw(ValueError("bad")))
    assert rl.read_base_sha(lock) is None


def test_previously_tracked_variants(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    assert rl.previously_tracked(tmp_path / "none.lock") == set()
    lock = tmp_path / "template.lock"
    lock.write_text("files:\n- a.txt\n- b.txt\n")
    assert rl.previously_tracked(lock) == {Path("a.txt"), Path("b.txt")}
    monkeypatch.setattr(rl, "load_yaml", lambda _p: (_ for _ in ()).throw(ValueError("bad")))
    assert rl.previously_tracked(lock) == set()
