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
    (tmp_path / "f.txt").write_text("x", encoding="utf-8")
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
    lock_path.write_text("garbage", encoding="utf-8")
    (tmp_path / "f.txt").write_text("x", encoding="utf-8")
    monkeypatch.setattr(rl, "load_yaml", lambda _p: (_ for _ in ()).throw(ValueError("bad")))
    lock = rl.build_lock("sha1", Template("o/r", "v1"), ["f.txt"], "t1")
    rl.write_lock(tmp_path, lock, lock_path)
    # dump_yaml is the real one; file should have been (re)written with our sha.
    assert "sha: sha1" in lock_path.read_text(encoding="utf-8")


def test_write_lock_filters_missing_files(tmp_path: Path) -> None:
    lock_path = tmp_path / "template.lock"
    (tmp_path / "present.txt").write_text("x", encoding="utf-8")
    lock = rl.build_lock("sha1", Template("o/r", "v1"), ["present.txt", "ghost.txt"], "t1")
    rl.write_lock(tmp_path, lock, lock_path)
    written = load_yaml(lock_path)
    assert written["files"] == ["present.txt"]


def test_clean_orphaned_unlink_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / "orphan.txt").write_text("x", encoding="utf-8")
    monkeypatch.setattr(
        Path, "unlink", lambda self, *a, **k: (_ for _ in ()).throw(OSError("locked"))
    )
    rl.clean_orphaned_files(tmp_path, [], set(), {Path("orphan.txt")})
    assert "Failed to delete" in capsys.readouterr().err


def test_read_base_sha_variants(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    assert rl.read_base_sha(tmp_path / "none.lock") is None
    lock = tmp_path / "template.lock"
    lock.write_text("sha: abc\n", encoding="utf-8")
    assert rl.read_base_sha(lock) == "abc"
    lock.write_text("ref: main\n", encoding="utf-8")  # no sha
    assert rl.read_base_sha(lock) is None
    monkeypatch.setattr(rl, "load_yaml", lambda _p: (_ for _ in ()).throw(ValueError("bad")))
    assert rl.read_base_sha(lock) is None


def test_previously_tracked_variants(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    assert rl.previously_tracked(tmp_path / "none.lock") == set()
    lock = tmp_path / "template.lock"
    lock.write_text("files:\n- a.txt\n- b.txt\n", encoding="utf-8")
    assert rl.previously_tracked(lock) == {Path("a.txt"), Path("b.txt")}
    monkeypatch.setattr(rl, "load_yaml", lambda _p: (_ for _ in ()).throw(ValueError("bad")))
    assert rl.previously_tracked(lock) == set()


def test_previously_tracked_drops_entries_that_escape_the_target(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The orphan cleaner *unlinks* what this returns, so containment is load-bearing here.

    `clean_orphaned_files` joins each tracked path onto the target and deletes it. An entry
    the template listed as `../../…` would therefore delete outside the repository, and
    nothing checked — the containment held because no upstream lock has ever carried one.
    """
    lock = tmp_path / "template.lock"
    lock.write_text(
        "files:\n- kept.txt\n- ../../etc/passwd\n- /etc/shadow\n- ..\\win.ini\n", encoding="utf-8"
    )

    assert rl.previously_tracked(lock) == {Path("kept.txt")}

    # Dropped loudly: a silent filter would hide a template that had started emitting them.
    err = capsys.readouterr().err
    assert err.count("outside the repository") == 3
    assert "../../etc/passwd" in err


# --- gaps that mutation testing found (the retired `make mutate`) -------------
#
# Every assertion below kills a mutant that survived the suite while it sat at 100% line
# and branch coverage. That is the distinction mutation testing exposed: these
# lines all *ran*, and nothing checked what they produced.


def test_the_pointer_is_protected_from_orphan_cleanup(tmp_path: Path) -> None:
    """Deleting `.rhiza/template.yml` would stop the repo being rhiza-managed at all.

    `_PROTECTED` was covered but unasserted — its path string could be changed to anything
    and the suite stayed green, which is the one mutant here with a genuinely bad outcome.
    """
    pointer = tmp_path / ".rhiza" / "template.yml"
    pointer.parent.mkdir(parents=True)
    pointer.write_text('repository: "o/r"\n', encoding="utf-8")

    # The pointer was tracked before and is not in the new template file set: an orphan by
    # every rule except the protection.
    rl.clean_orphaned_files(tmp_path, [], set(), {Path(".rhiza/template.yml")})

    assert pointer.exists(), "the pointer must survive orphan cleanup"
    assert Path(".rhiza/template.yml") in rl._PROTECTED


def test_an_excluded_orphan_does_not_stop_the_others_being_cleaned(tmp_path: Path) -> None:
    """The exclusion arm must `continue`, not `break`.

    With `break`, the first excluded path would end the loop and leave every later orphan
    on disk — a silent, order-dependent failure to clean up. Sorted order puts `a-kept`
    before `z-orphan`, so the bug only shows when the excluded file comes first.
    """
    for name in ("a-kept.txt", "z-orphan.txt"):
        (tmp_path / name).write_text("x", encoding="utf-8")

    rl.clean_orphaned_files(
        tmp_path, [], {"a-kept.txt"}, {Path("a-kept.txt"), Path("z-orphan.txt")}
    )

    assert (tmp_path / "a-kept.txt").exists(), "an excluded path is never an orphan"
    assert not (tmp_path / "z-orphan.txt").exists(), "the orphan after it must still go"


def test_the_lock_directory_is_created_recursively(tmp_path: Path) -> None:
    """`mkdir(parents=True)` — a first sync has no `.rhiza/` yet, nor its parent."""
    template = Template("o/r", "v1", templates=["t"])
    lock = rl.build_lock("sha1", template, [], "2026-01-01T00:00:00Z")
    nested = tmp_path / "deep" / ".rhiza" / "template.lock"

    rl.write_lock(tmp_path, lock, nested)

    assert nested.is_file()


def test_every_lock_field_round_trips_under_its_own_name(tmp_path: Path) -> None:
    """The field *names* are the contract two other tools read; assert them, not just shapes.

    `_lock_identity` reads `sha`/`repo`/`host`/`ref`/... by key, and each key could be
    misspelled without the suite noticing: a wrong key silently reads as the default, so
    the no-op-rewrite check would compare two identical blanks and skip a needed write.
    """
    template = Template("owner/repo", "v1.2.3", host="gitlab", templates=["core"])
    lock = rl.build_lock("abc123", template, [], "2026-01-01T00:00:00Z")

    assert lock["sha"] == "abc123"
    assert lock["repo"] == "owner/repo"
    assert lock["host"] == "gitlab"
    assert lock["ref"] == "v1.2.3"
    assert lock["templates"] == ["core"]
    assert lock["strategy"] == "merge"
    assert lock["synced_at"] == "2026-01-01T00:00:00Z"

    # And the identity key is built from those same names, so a rename breaks both.
    assert rl._lock_identity(lock)[:4] == ("abc123", "owner/repo", "gitlab", "v1.2.3")
    assert rl._lock_identity(lock)[-1] == "merge"


def test_a_rewrite_is_skipped_only_when_the_identity_really_matches(tmp_path: Path) -> None:
    """`synced_at` is excluded from the identity; every other field must count.

    This is what makes the skip safe: a lock differing only in its timestamp is a no-op,
    while one differing in `ref` must be rewritten.
    """
    template = Template("o/r", "v1", templates=["t"])
    path = tmp_path / ".rhiza" / "template.lock"

    rl.write_lock(tmp_path, rl.build_lock("sha1", template, [], "2026-01-01T00:00:00Z"), path)
    first = path.read_text(encoding="utf-8")

    # Same content, later timestamp → skipped, file untouched.
    rl.write_lock(tmp_path, rl.build_lock("sha1", template, [], "2026-06-06T00:00:00Z"), path)
    assert path.read_text(encoding="utf-8") == first

    # A different ref → rewritten.
    moved = Template("o/r", "v2", templates=["t"])
    rl.write_lock(tmp_path, rl.build_lock("sha1", moved, [], "2026-06-06T00:00:00Z"), path)
    assert load_yaml(path)["ref"] == "v2"
