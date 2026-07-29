"""Integration tests for `scripts/sync.py`, driving the real `git` binary.

These build throwaway template + downstream repos on disk (cloned over local
`file`/path remotes) and run the actual sync, so the 3-way merge, sparse
checkout, lock writing, and orphan cleanup are exercised end-to-end. Only error
branches that real git will not reach on demand are left to `test_sync_branches`.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import pytest
import sync
from _rhiza_yaml import load_yaml
from conftest import Repo

pytestmark = pytest.mark.usefixtures("hermetic_git")


def _template(make_repo: Any, files: dict[str, str]) -> Repo:
    """Create an include-mode template repo committed at v1 with *files*."""
    tmpl = make_repo("tmpl")
    for rel, content in files.items():
        tmpl.write(rel, content)
    tmpl.commit("v1")
    return tmpl


def _project(make_repo: Any, template: Repo, body_lines: list[str]) -> Repo:
    """Create a downstream repo whose template.yml points at *template*."""
    proj = make_repo("proj")
    body = f'repository: "{template.path}"\nref: main\n' + "\n".join(body_lines) + "\n"
    proj.write(".rhiza/template.yml", body)
    proj.commit("init")
    return proj


def _include(*paths: str) -> list[str]:
    """Return template.yml lines for an ``include:`` block."""
    return ["include:", *(f"  - {p}" for p in paths)]


# --- first sync ---------------------------------------------------------------


def test_first_sync_copies_all_files(make_repo: Any) -> None:
    tmpl = _template(make_repo, {"Makefile": "all:\n", "docs/g.md": "hi\n"})
    proj = _project(make_repo, tmpl, _include("Makefile", "docs"))
    assert sync.sync(proj.path, "main") == sync.EXIT_OK
    assert proj.read("Makefile") == "all:\n"
    assert proj.read("docs/g.md") == "hi\n"


def test_first_sync_writes_lock(make_repo: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sync, "_now", lambda: "2026-01-02T03:04:05Z")
    tmpl = _template(make_repo, {"Makefile": "all:\n"})
    proj = _project(make_repo, tmpl, _include("Makefile"))
    sync.sync(proj.path, "main")
    lock = load_yaml(proj.path / ".rhiza" / "template.lock")
    assert lock["ref"] == "main"
    assert lock["files"] == ["Makefile"]
    assert lock["synced_at"] == "2026-01-02T03:04:05Z"
    assert lock["strategy"] == "merge"


# --- incremental merge --------------------------------------------------------


def _first_synced(
    make_repo: Any, v1_files: dict[str, str], include: list[str]
) -> tuple[Repo, Repo]:
    """First-sync a project and commit it, ready for an incremental sync."""
    tmpl = _template(make_repo, v1_files)
    proj = _project(make_repo, tmpl, _include(*include))
    sync.sync(proj.path, "main")
    proj.commit("first sync")
    return tmpl, proj


def test_incremental_clean_apply(make_repo: Any) -> None:
    # A change far from any local edit applies cleanly via git apply -3.
    body = "".join(f"line{n}\n" for n in range(1, 21))
    tmpl, proj = _first_synced(make_repo, {"f.txt": body}, ["f.txt"])
    tmpl.write("f.txt", body.replace("line1\n", "CHANGED\n"))
    tmpl.commit("v2")
    proj.write("f.txt", body.replace("line20\n", "LOCAL\n"))  # far from line1
    proj.commit("local edit")
    assert sync.sync(proj.path, "main") == sync.EXIT_OK
    merged = proj.read("f.txt")
    assert "CHANGED\n" in merged and "LOCAL\n" in merged
    assert "<<<<<<<" not in merged


def test_incremental_conflict_marks_and_exits_one(
    make_repo: Any, capsys: pytest.CaptureFixture[str]
) -> None:
    tmpl, proj = _first_synced(make_repo, {"f.txt": "l1\nl2\nl3\n"}, ["f.txt"])
    tmpl.write("f.txt", "UPSTREAM\nl2\nl3\n")
    tmpl.commit("v2")
    proj.write("f.txt", "LOCAL\nl2\nl3\n")  # same line as upstream -> conflict
    proj.commit("local edit")
    assert sync.sync(proj.path, "main") == sync.EXIT_CONFLICTS
    assert "<<<<<<<" in proj.read("f.txt")
    assert "Conflicts remain" in capsys.readouterr().err


def test_a_locally_modified_binary_fails_the_sync_by_name(
    make_repo: Any, capsys: pytest.CaptureFixture[str]
) -> None:
    """A binary collision leaves no marker, so the report has to name the file itself.

    `git merge-file` refuses binary input. The file is left exactly as the user had it —
    overwriting would lose work — but that means `grep '<<<<<<<'` finds nothing, and a
    silent exit 1 would send the user looking for a conflict that isn't there.
    """
    tmpl, proj = _first_synced(make_repo, {"logo.png": "BASE\x00\x01"}, ["logo.png"])
    tmpl.write("logo.png", "UPSTREAM\x00\x02")
    tmpl.commit("v2")
    proj.write("logo.png", "LOCAL\x00\x03")
    proj.commit("local binary edit")

    assert sync.sync(proj.path, "main") == sync.EXIT_CONFLICTS
    assert proj.read("logo.png") == "LOCAL\x00\x03", "the local binary was clobbered"
    assert "cannot merge: logo.png" in capsys.readouterr().err


def test_upstream_added_file_appears(make_repo: Any) -> None:
    tmpl, proj = _first_synced(make_repo, {"a.txt": "a\n"}, ["a.txt", "b.txt"])
    tmpl.write("b.txt", "brand new\n")
    tmpl.commit("v2")
    assert sync.sync(proj.path, "main") == sync.EXIT_OK
    assert proj.read("b.txt") == "brand new\n"


def test_upstream_deleted_file_removed(make_repo: Any) -> None:
    tmpl, proj = _first_synced(make_repo, {"a.txt": "a\n", "b.txt": "b\n"}, ["a.txt", "b.txt"])
    (tmpl.path / "b.txt").unlink()
    tmpl.commit("v2 drop b")
    assert sync.sync(proj.path, "main") == sync.EXIT_OK
    assert not proj.exists("b.txt")


# --- orphan cleanup + excludes ------------------------------------------------


def _retarget(proj: Repo, template: Repo, body_lines: list[str]) -> None:
    """Rewrite the project's template.yml and commit it."""
    body = f'repository: "{template.path}"\nref: main\n' + "\n".join(body_lines) + "\n"
    proj.write(".rhiza/template.yml", body)
    proj.commit("retarget")


def test_orphan_dropped_from_include_is_removed(make_repo: Any) -> None:
    # b.txt is synced, then dropped from the include list -> orphan-cleaned.
    tmpl = _template(make_repo, {"a.txt": "a\n", "b.txt": "b\n"})
    proj = _project(make_repo, tmpl, _include("a.txt", "b.txt"))
    sync.sync(proj.path, "main")
    proj.commit("first")
    _retarget(proj, tmpl, _include("a.txt"))
    assert sync.sync(proj.path, "main") == sync.EXIT_OK
    assert proj.exists("a.txt")
    assert not proj.exists("b.txt")


def test_excluded_orphan_is_kept(make_repo: Any) -> None:
    # keep.txt was tracked, then excluded -> not deleted despite leaving the set.
    tmpl = _template(make_repo, {"a.txt": "a\n", "keep.txt": "k\n"})
    proj = _project(make_repo, tmpl, _include("a.txt", "keep.txt"))
    sync.sync(proj.path, "main")
    proj.commit("first")
    _retarget(proj, tmpl, [*_include("a.txt"), "exclude:", "  - keep.txt"])
    assert sync.sync(proj.path, "main") == sync.EXIT_OK
    assert proj.exists("keep.txt")


def test_excluded_file_not_synced(make_repo: Any) -> None:
    tmpl = _template(make_repo, {"a.txt": "a\n", "secret.txt": "s\n"})
    proj = _project(
        make_repo, tmpl, [*_include("a.txt", "secret.txt"), "exclude:", "  - secret.txt"]
    )
    assert sync.sync(proj.path, "main") == sync.EXIT_OK
    assert proj.exists("a.txt")
    assert not proj.exists("secret.txt")


# --- no-op syncs --------------------------------------------------------------


def test_template_unchanged_is_clean(make_repo: Any, capsys: pytest.CaptureFixture[str]) -> None:
    tmpl, proj = _first_synced(make_repo, {"a.txt": "a\n"}, ["a.txt"])
    tmpl.write("README.md", "unrelated\n")  # change something NOT tracked
    tmpl.commit("v2 unrelated")
    assert sync.sync(proj.path, "main") == sync.EXIT_OK
    assert "unchanged" in capsys.readouterr().err


def test_lock_unchanged_skips_write(make_repo: Any, capsys: pytest.CaptureFixture[str]) -> None:
    tmpl, proj = _first_synced(make_repo, {"a.txt": "a\n"}, ["a.txt"])
    sync.sync(proj.path, "main")  # nothing changed upstream -> same lock content
    assert "already up to date" in capsys.readouterr().err


def test_re_syncing_an_unchanged_template_preserves_local_edits(make_repo: Any) -> None:
    """Re-running /update on an unmoved template must not clobber local work.

    `test_lock_unchanged_skips_write` already covers the re-sync path, but only asserts
    the lock is skipped — it would still pass if the file had been overwritten. The
    tree-level property `test_property_re_syncing_the_same_ref_is_a_no_op` covers the
    merge in isolation; this drives the whole pipeline (clone, snapshot, diff, lock) to
    confirm the invariant survives it.
    """
    _tmpl, proj = _first_synced(make_repo, {"a.txt": "upstream\n"}, ["a.txt"])
    proj.write("a.txt", "locally edited\n")
    proj.commit("local edit to a tracked file")

    assert sync.sync(proj.path, "main") == sync.EXIT_OK
    assert proj.read("a.txt") == "locally edited\n"


def test_missing_file_restored(make_repo: Any) -> None:
    tmpl, proj = _first_synced(make_repo, {"a.txt": "a\n"}, ["a.txt"])
    (proj.path / "a.txt").unlink()  # manually delete a tracked file
    proj.commit("remove a")
    assert sync.sync(proj.path, "main") == sync.EXIT_OK
    assert proj.read("a.txt") == "a\n"


# --- profiles / bundles / remap -----------------------------------------------


def _bundles_template(make_repo: Any, bundles_yaml: str, files: dict[str, str]) -> Repo:
    """Build a profiles/bundles template with a template-bundles.yml."""
    tmpl = make_repo("tmpl")
    tmpl.write(".rhiza/template-bundles.yml", bundles_yaml)
    for rel, content in files.items():
        tmpl.write(rel, content)
    tmpl.commit("v1")
    return tmpl


def test_profiles_resolve_and_strip_prefix(make_repo: Any) -> None:
    bundles = (
        "bundles:\n  core:\n    required: true\n  extra:\n    requires: [core]\n"
        "profiles:\n  std:\n    bundles:\n      - core\n      - extra\n"
    )
    tmpl = _bundles_template(
        make_repo, bundles, {"bundles/core/Makefile": "m\n", "bundles/extra/README.md": "r\n"}
    )
    proj = _project(make_repo, tmpl, ["profiles:", "  - std"])
    assert sync.sync(proj.path, "main") == sync.EXIT_OK
    assert proj.read("Makefile") == "m\n"  # bundles/core/ prefix stripped
    assert proj.read("README.md") == "r\n"


def test_path_map_remap(make_repo: Any) -> None:
    bundles = "bundles:\n  cfg:\n    files:\n      - {source: src/tool.cfg, dest: tool.cfg}\n"
    tmpl = _bundles_template(make_repo, bundles, {"src/tool.cfg": "cfg\n"})
    proj = _project(make_repo, tmpl, ["templates:", "  - cfg"])
    assert sync.sync(proj.path, "main") == sync.EXIT_OK
    assert proj.read("tool.cfg") == "cfg\n"
    assert not proj.exists("src/tool.cfg")


def test_hybrid_include_and_templates(make_repo: Any) -> None:
    bundles = "bundles:\n  core:\n    required: true\n"
    tmpl = _bundles_template(
        make_repo, bundles, {"bundles/core/Makefile": "m\n", "extra.txt": "e\n"}
    )
    proj = _project(make_repo, tmpl, ["templates:", "  - core", *_include("extra.txt")])
    assert sync.sync(proj.path, "main") == sync.EXIT_OK
    assert proj.read("Makefile") == "m\n"
    assert proj.read("extra.txt") == "e\n"


# --- merge-file fallback (base blob absent from target) -----------------------


def test_merge_file_fallback_clean(make_repo: Any) -> None:
    # Downstream file diverged from the template base and the pristine base
    # content was never committed here, so `git apply -3` lacks the blob and the
    # `git merge-file` fallback takes over. Non-overlapping edits merge cleanly.
    tmpl = _template(make_repo, {"f.txt": "l1\nl2\nl3\n"})
    base_sha = tmpl.git("rev-parse", "HEAD").stdout.strip()
    tmpl.write("f.txt", "TOP\nl2\nl3\n")  # v2 changes line 1
    tmpl.commit("v2")

    proj = _project(make_repo, tmpl, _include("f.txt"))
    proj.write("f.txt", "l1\nl2\nLOCAL\n")  # diverged on line 3; pristine base never committed
    lock = f'sha: {base_sha}\nrepo: "{tmpl.path}"\nhost: github\nref: main\nfiles:\n- f.txt\n'
    proj.write(".rhiza/template.lock", lock)
    proj.commit("diverged")

    assert sync.sync(proj.path, "main") == sync.EXIT_OK
    merged = proj.read("f.txt")
    assert merged == "TOP\nl2\nLOCAL\n"


# --- failure exit codes -------------------------------------------------------


def test_dirty_tree_is_error(make_repo: Any, capsys: pytest.CaptureFixture[str]) -> None:
    tmpl = _template(make_repo, {"a.txt": "a\n"})
    proj = _project(make_repo, tmpl, _include("a.txt"))
    proj.write("uncommitted.txt", "dirty\n")  # not committed
    assert sync.sync(proj.path, "main") == sync.EXIT_ERROR
    assert "not clean" in capsys.readouterr().err


def test_main_cli_returns_exit_code(make_repo: Any) -> None:
    tmpl = _template(make_repo, {"a.txt": "a\n"})
    proj = _project(make_repo, tmpl, _include("a.txt"))
    assert sync.main([str(proj.path)]) == sync.EXIT_OK
    assert proj.read("a.txt") == "a\n"


def test_main_cli_syncerror_is_exit_error(
    make_repo: Any, capsys: pytest.CaptureFixture[str]
) -> None:
    proj = make_repo("proj")
    proj.write(".rhiza/template.yml", "repository: ''\nref: main\ninclude:\n  - x\n")
    proj.commit("init")
    assert sync.main([str(proj.path)]) == sync.EXIT_ERROR
    assert "error:" in capsys.readouterr().err


# --- as_list -----------------------------------------------------------------


# --- Template.git_url ---------------------------------------------------------


# --- load_template -----------------------------------------------------------


# --- bundle path safety + entries ---------------------------------------------


# --- Bundles resolution -------------------------------------------------------


# --- resolve_bundle_names ----------------------------------------------------


# --- _remap_path --------------------------------------------------------------


# --- lock helpers -------------------------------------------------------------


# --- orphan cleanup unlink failure --------------------------------------------


# --- base sha + previously-tracked reads --------------------------------------


# --- main() error translation -------------------------------------------------


def test_main_syncerror(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(sync, "sync", lambda *a: (_ for _ in ()).throw(sync.SyncError("boom")))
    assert sync.main(["."]) == sync.EXIT_ERROR
    assert "error: boom" in capsys.readouterr().err


def test_main_called_process_error(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def boom(*_a: Any) -> int:
        raise subprocess.CalledProcessError(1, ["git"], b"", b"fatal: nope\n")

    monkeypatch.setattr(sync, "sync", boom)
    assert sync.main(["."]) == sync.EXIT_ERROR
    assert "git failed" in capsys.readouterr().err


def test_main_runtime_error(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(sync, "sync", lambda *a: (_ for _ in ()).throw(RuntimeError("weird")))
    assert sync.main(["."]) == sync.EXIT_ERROR
    assert "error: weird" in capsys.readouterr().err


# --- base snapshot clone failure ----------------------------------------------


def test_merge_with_base_tolerates_clone_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # When the base clone fails, sync logs a warning and diffs against an empty base.
    def boom(*_a: Any, **_k: Any) -> None:
        raise subprocess.CalledProcessError(1, ["git", "clone"], b"", b"boom")

    monkeypatch.setattr(sync.git, "clone", boom)
    # Base and upstream are both the (empty) tmp_path, so the merge finds no changed
    # files and reports clean without needing real git.
    ctx = sync.git.GitContext(executable="git", env={})
    base_snapshot = tmp_path / "base"
    base_snapshot.mkdir()
    clean = sync._merge_with_base(
        ctx, tmp_path, tmp_path, "deadbeef", base_snapshot, "/url", [], set(), {}
    )
    assert clean is True
    assert "Could not check out base commit" in capsys.readouterr().err
