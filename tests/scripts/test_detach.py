"""Tests for the `rhiza uninstall` port (`scripts/detach.py`), which backs /rhiza:detach."""

from __future__ import annotations

from pathlib import Path

import detach


def _write_lock(repo, body: str):
    """Write .rhiza/template.lock under repo with the given body."""
    rhiza = repo / ".rhiza"
    rhiza.mkdir(parents=True, exist_ok=True)
    (rhiza / "template.lock").write_text(body, encoding="utf-8")


def _make_repo(repo, files: list[str], *, extra: list[str] | None = None):
    """Create a repo with a lock listing `files`, plus untracked `extra` files."""
    rhiza = repo / ".rhiza"
    rhiza.mkdir(parents=True, exist_ok=True)
    body = "sha: abc\nfiles:\n" + "".join(f"- {f}\n" for f in files)
    (rhiza / "template.lock").write_text(body, encoding="utf-8")
    for rel in [*files, *(extra or [])]:
        p = repo / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("x", encoding="utf-8")
    return repo


def test_force_removes_files_lock_and_empty_dirs(tmp_path):
    repo = _make_repo(
        tmp_path,
        ["docs/index.md", ".github/workflows/ci.yml", "LICENSE"],
        extra=["keep.txt"],
    )
    rc = detach.detach(repo, force=True)
    assert rc == 0
    # tracked files gone
    assert not (repo / "docs/index.md").exists()
    assert not (repo / ".github/workflows/ci.yml").exists()
    assert not (repo / "LICENSE").exists()
    # lock removed, empty dirs pruned, untracked file kept
    assert not (repo / ".rhiza/template.lock").exists()
    assert not (repo / "docs").exists()
    assert not (repo / ".github").exists()
    assert (repo / "keep.txt").exists()


def test_no_lock_is_clean_noop(tmp_path, capsys):
    rc = detach.detach(tmp_path, force=True)
    assert rc == 0
    assert "Nothing to detach" in capsys.readouterr().err


def test_empty_file_list_is_noop(tmp_path, capsys):
    (tmp_path / ".rhiza").mkdir()
    (tmp_path / ".rhiza/template.lock").write_text("sha: abc\nfiles: []\n", encoding="utf-8")
    rc = detach.detach(tmp_path, force=True)
    assert rc == 0
    assert "Nothing to do" in capsys.readouterr().err


def test_cancel_when_not_forced_and_no_tty(tmp_path, monkeypatch):
    repo = _make_repo(tmp_path, ["LICENSE"])

    def _raise_eof(_prompt):
        raise EOFError

    monkeypatch.setattr("builtins.input", _raise_eof)
    rc = detach.detach(repo, force=False)
    assert rc == 0
    # nothing deleted on cancel
    assert (repo / "LICENSE").exists()
    assert (repo / ".rhiza/template.lock").exists()


def test_confirm_yes_proceeds(tmp_path, monkeypatch):
    repo = _make_repo(tmp_path, ["LICENSE"])
    monkeypatch.setattr("builtins.input", lambda _prompt: "y")
    rc = detach.detach(repo, force=False)
    assert rc == 0
    assert not (repo / "LICENSE").exists()


def test_confirm_no_cancels(tmp_path, monkeypatch):
    repo = _make_repo(tmp_path, ["LICENSE"])
    monkeypatch.setattr("builtins.input", lambda _prompt: "n")
    rc = detach.detach(repo, force=False)
    assert rc == 0
    assert (repo / "LICENSE").exists()


def test_skips_already_deleted_files(tmp_path, capsys):
    repo = _make_repo(tmp_path, ["a.txt", "b.txt"])
    (repo / "a.txt").unlink()  # a tracked file was already removed
    rc = detach.detach(repo, force=True)
    assert rc == 0
    err = capsys.readouterr().err
    assert "skipped (already deleted): 1" in err


def test_unreadable_lock_returns_error(tmp_path, monkeypatch, capsys):
    (tmp_path / ".rhiza").mkdir()
    (tmp_path / ".rhiza/template.lock").write_text("sha: abc\nfiles:\n- x\n", encoding="utf-8")

    def _boom(_path):
        raise ValueError("corrupt")

    monkeypatch.setattr(detach, "load_yaml", _boom)
    rc = detach.detach(tmp_path, force=True)
    assert rc == 1
    assert "Failed to read template.lock" in capsys.readouterr().err


def test_main_force_flag(tmp_path):
    repo = _make_repo(tmp_path, ["LICENSE"])
    assert detach.main([str(repo), "--force"]) == 0
    assert not (repo / "LICENSE").exists()


def test_remove_files_permission_then_success(tmp_path, monkeypatch):
    (tmp_path / "a.txt").write_text("x", encoding="utf-8")
    real_unlink = Path.unlink
    state = {"raised": False}

    def fake_unlink(self, *a, **k):
        if self.name == "a.txt" and not state["raised"]:
            state["raised"] = True
            raise PermissionError("read-only")
        return real_unlink(self, *a, **k)

    monkeypatch.setattr(Path, "unlink", fake_unlink)
    removed, skipped, errors = detach._remove_files([Path("a.txt")], tmp_path)
    assert (removed, errors) == (1, 0)  # chmod + retry succeeded


def test_remove_files_permission_then_oserror(tmp_path, monkeypatch):
    (tmp_path / "b.txt").write_text("x", encoding="utf-8")
    seq = iter([PermissionError("ro"), OSError("io")])

    def fake_unlink(self, *a, **k):
        if self.name == "b.txt":
            raise next(seq)

    monkeypatch.setattr(Path, "unlink", fake_unlink)
    removed, skipped, errors = detach._remove_files([Path("b.txt")], tmp_path)
    assert (removed, errors) == (0, 1)  # retry raised OSError


def test_remove_files_hard_oserror(tmp_path):
    (tmp_path / "d").mkdir()  # a dir where a file is expected → IsADirectoryError (OSError)
    removed, skipped, errors = detach._remove_files([Path("d")], tmp_path)
    assert errors == 1


def test_remove_files_direct_oserror(tmp_path, monkeypatch):
    (tmp_path / "c.txt").write_text("x", encoding="utf-8")

    def fake_unlink(self, *a, **k):
        if self.name == "c.txt":
            raise OSError("disk full")  # not PermissionError → outer OSError branch

    monkeypatch.setattr(Path, "unlink", fake_unlink)
    removed, skipped, errors = detach._remove_files([Path("c.txt")], tmp_path)
    assert (removed, errors) == (0, 1)


def test_remove_files_skips_absent(tmp_path):
    removed, skipped, errors = detach._remove_files([Path("ghost.txt")], tmp_path)
    assert (removed, skipped, errors) == (0, 1, 0)


def test_cleanup_stops_at_nonempty_dir(tmp_path):
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "keep.txt").write_text("x", encoding="utf-8")
    assert detach._cleanup_empty_directories([Path("pkg/gone.txt")], tmp_path) == 0


def test_cleanup_handles_oserror(tmp_path, monkeypatch):
    (tmp_path / "empty").mkdir()
    monkeypatch.setattr(Path, "rmdir", lambda self, *a, **k: (_ for _ in ()).throw(OSError("x")))
    assert detach._cleanup_empty_directories([Path("empty/f.txt")], tmp_path) == 0


def test_cleanup_removes_empty(tmp_path):
    (tmp_path / "a" / "b").mkdir(parents=True)
    n = detach._cleanup_empty_directories([Path("a/b/f.txt")], tmp_path)
    assert n == 2  # b then a removed


def test_detach_reports_delete_errors(tmp_path):
    _write_lock(tmp_path, "files:\n  - somedir\n")
    (tmp_path / "somedir").mkdir()  # listed as a file but is a dir → delete error
    assert detach.detach(tmp_path, force=True) == 1


def test_detach_lock_unlink_oserror(tmp_path, monkeypatch):
    _write_lock(tmp_path, "files:\n  - a.txt\n")
    (tmp_path / "a.txt").write_text("x", encoding="utf-8")
    real_unlink = Path.unlink

    def fake_unlink(self, *a, **k):
        if self.name == "template.lock":
            raise OSError("locked")
        return real_unlink(self, *a, **k)

    monkeypatch.setattr(Path, "unlink", fake_unlink)
    assert detach.detach(tmp_path, force=True) == 1


# --- end-to-end: /detach against a real synced repo ------------------------


def test_e2e_detach_removes_the_synced_files_and_spares_the_repos_own(synced_repo_copy):
    """/detach's promise, measured on the files the real template delivered.

    The fixtures cannot prove this: the file list has to be the one `sync.py` actually
    wrote. What must survive is everything the repo owns — `src/`, `tests/`, the
    pyproject — because deleting those would be unrecoverable for a user.
    """
    repo = synced_repo_copy
    from _rhiza_yaml import load_yaml

    managed = load_yaml(repo / ".rhiza" / "template.lock")["files"]
    assert len(managed) > 20, f"expected the real template's file list, got {managed}"
    assert (repo / "Makefile").is_file() and (repo / ".rhiza" / "rhiza.mk").is_file()

    assert detach.detach(repo, force=True) == 0

    still_there = [f for f in managed if (repo / f).exists()]
    assert still_there == [], f"these managed files survived: {still_there}"
    assert not (repo / ".rhiza" / "template.lock").exists(), "the lock itself must go"

    # The repo's own work is untouched.
    assert (repo / "pyproject.toml").is_file()
    assert (repo / "src" / "widget" / "main.py").is_file()
    assert (repo / "tests" / "widget" / "test_main.py").is_file()
    assert (repo / ".rhiza" / "template.yml").is_file(), "the pointer is not the sync's to delete"


def test_e2e_detach_twice_reports_nothing_to_do(synced_repo_copy):
    """With the lock gone, a second run has no file list and says so rather than erroring."""
    assert detach.detach(synced_repo_copy, force=True) == 0
    assert detach.detach(synced_repo_copy, force=True) == 0


# --- branch coverage: the arms line coverage could not see ---------------------


def test_a_listed_file_that_is_already_gone_is_not_offered_for_deletion(tmp_path, monkeypatch):
    """The confirmation lists only what is really there — a stale lock entry is skipped."""
    repo = _make_repo(tmp_path, ["present.txt", "vanished.txt"])
    (repo / "vanished.txt").unlink()
    monkeypatch.setattr("builtins.input", lambda _: "y")
    detach.detach(repo, force=False)
    assert not (repo / "present.txt").exists()


def test_a_lock_listing_itself_is_not_deleted_twice(tmp_path):
    """A lock whose `files:` includes the lock leaves nothing for the final unlink.

    Realistic rather than contrived: the list is whatever the last sync recorded, and a
    template that manages its own lock path produces exactly this.
    """
    # Built by hand, not via _make_repo: that helper writes every listed file, which
    # would clobber the lock with placeholder text and leave nothing to parse.
    (tmp_path / ".rhiza").mkdir(parents=True)
    (tmp_path / "kept.txt").write_text("x", encoding="utf-8")
    (tmp_path / ".rhiza" / "template.lock").write_text(
        "sha: abc\nfiles:\n- .rhiza/template.lock\n- kept.txt\n"
    )
    assert detach.detach(tmp_path, force=True) == 0
    assert not (tmp_path / ".rhiza" / "template.lock").exists()
    assert not (tmp_path / "kept.txt").exists()
