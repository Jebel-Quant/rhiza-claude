"""Tests for the `rhiza uninstall` port (`scripts/uninstall.py`)."""

from __future__ import annotations

import uninstall


def _make_repo(repo, files: list[str], *, extra: list[str] | None = None):
    """Create a repo with a lock listing `files`, plus untracked `extra` files."""
    rhiza = repo / ".rhiza"
    rhiza.mkdir(parents=True, exist_ok=True)
    body = "sha: abc\nfiles:\n" + "".join(f"- {f}\n" for f in files)
    (rhiza / "template.lock").write_text(body)
    for rel in [*files, *(extra or [])]:
        p = repo / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("x")
    return repo


def test_force_removes_files_lock_and_empty_dirs(tmp_path):
    repo = _make_repo(
        tmp_path,
        ["docs/index.md", ".github/workflows/ci.yml", "LICENSE"],
        extra=["keep.txt"],
    )
    rc = uninstall.uninstall(repo, force=True)
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
    rc = uninstall.uninstall(tmp_path, force=True)
    assert rc == 0
    assert "Nothing to uninstall" in capsys.readouterr().err


def test_empty_file_list_is_noop(tmp_path, capsys):
    (tmp_path / ".rhiza").mkdir()
    (tmp_path / ".rhiza/template.lock").write_text("sha: abc\nfiles: []\n")
    rc = uninstall.uninstall(tmp_path, force=True)
    assert rc == 0
    assert "Nothing to do" in capsys.readouterr().err


def test_cancel_when_not_forced_and_no_tty(tmp_path, monkeypatch):
    repo = _make_repo(tmp_path, ["LICENSE"])

    def _raise_eof(_prompt):
        raise EOFError

    monkeypatch.setattr("builtins.input", _raise_eof)
    rc = uninstall.uninstall(repo, force=False)
    assert rc == 0
    # nothing deleted on cancel
    assert (repo / "LICENSE").exists()
    assert (repo / ".rhiza/template.lock").exists()


def test_confirm_yes_proceeds(tmp_path, monkeypatch):
    repo = _make_repo(tmp_path, ["LICENSE"])
    monkeypatch.setattr("builtins.input", lambda _prompt: "y")
    rc = uninstall.uninstall(repo, force=False)
    assert rc == 0
    assert not (repo / "LICENSE").exists()


def test_confirm_no_cancels(tmp_path, monkeypatch):
    repo = _make_repo(tmp_path, ["LICENSE"])
    monkeypatch.setattr("builtins.input", lambda _prompt: "n")
    rc = uninstall.uninstall(repo, force=False)
    assert rc == 0
    assert (repo / "LICENSE").exists()


def test_skips_already_deleted_files(tmp_path, capsys):
    repo = _make_repo(tmp_path, ["a.txt", "b.txt"])
    (repo / "a.txt").unlink()  # a tracked file was already removed
    rc = uninstall.uninstall(repo, force=True)
    assert rc == 0
    err = capsys.readouterr().err
    assert "skipped (already deleted): 1" in err


def test_unreadable_lock_returns_error(tmp_path, monkeypatch, capsys):
    (tmp_path / ".rhiza").mkdir()
    (tmp_path / ".rhiza/template.lock").write_text("sha: abc\nfiles:\n- x\n")

    def _boom(_path):
        raise ValueError("corrupt")

    monkeypatch.setattr(uninstall, "load_yaml", _boom)
    rc = uninstall.uninstall(tmp_path, force=True)
    assert rc == 1
    assert "Failed to read template.lock" in capsys.readouterr().err


def test_main_force_flag(tmp_path):
    repo = _make_repo(tmp_path, ["LICENSE"])
    assert uninstall.main([str(repo), "--force"]) == 0
    assert not (repo / "LICENSE").exists()
