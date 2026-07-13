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
    lock = sync.load_yaml(proj.path / ".rhiza" / "template.lock")
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


# --- _as_list -----------------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, []),
        (["a", "b"], ["a", "b"]),
        ("one\ntwo", ["one", "two"]),
        ("a\\nb", ["a", "b"]),
        (7, ["7"]),
    ],
)
def test_as_list(value: Any, expected: list[str]) -> None:
    assert sync._as_list(value) == expected


# --- Template.git_url ---------------------------------------------------------


def test_git_url_variants() -> None:
    assert sync.Template("o/r", "main").git_url == "https://github.com/o/r.git"
    assert sync.Template("o/r", "main", host="gitlab").git_url == "https://gitlab.com/o/r.git"
    assert sync.Template("/local/path", "main").git_url == "/local/path"
    assert sync.Template("https://x/y.git", "main").git_url == "https://x/y.git"


def test_git_url_unset_repository_raises() -> None:
    with pytest.raises(sync.SyncError, match="not configured"):
        _ = sync.Template("", "main").git_url


def test_git_url_unsupported_host_raises() -> None:
    with pytest.raises(sync.SyncError, match="Unsupported template-host"):
        _ = sync.Template("o/r", "main", host="bitbucket").git_url


# --- _load_template -----------------------------------------------------------


def test_load_template_missing_file(tmp_path: Path) -> None:
    with pytest.raises(sync.SyncError, match="No template.yml"):
        sync._load_template(tmp_path, tmp_path / "nope.yml")


def test_load_template_unreadable(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    tf = tmp_path / "template.yml"
    tf.write_text("x")
    monkeypatch.setattr(sync, "load_yaml", lambda _p: (_ for _ in ()).throw(ValueError("bad")))
    with pytest.raises(sync.SyncError, match="Could not read"):
        sync._load_template(tmp_path, tf)


def test_load_template_missing_repository(tmp_path: Path) -> None:
    tf = tmp_path / "template.yml"
    tf.write_text("ref: main\ninclude:\n  - x\n")
    with pytest.raises(sync.SyncError, match="template-repository is required"):
        sync._load_template(tmp_path, tf)


def test_load_template_no_sources(tmp_path: Path) -> None:
    tf = tmp_path / "template.yml"
    tf.write_text('repository: "o/r"\nref: main\n')
    with pytest.raises(sync.SyncError, match="at least one of"):
        sync._load_template(tmp_path, tf)


# --- bundle path safety + entries ---------------------------------------------


@pytest.mark.parametrize("bad", ["/abs/path", "C:/win", "../escape", "a/../../b"])
def test_ensure_safe_bundle_path_rejects(bad: str) -> None:
    with pytest.raises(sync.SyncError, match="Unsafe bundle path"):
        sync._ensure_safe_bundle_path(bad)


def test_ensure_safe_bundle_path_allows_relative() -> None:
    sync._ensure_safe_bundle_path("a/b/c.txt")  # no raise


def test_bundle_file_entries_forms() -> None:
    entries = sync._bundle_file_entries(
        ["plain.txt", {"source": "s", "dest": "d"}, {"source": "x"}]
    )
    assert entries == [("plain.txt", "plain.txt"), ("s", "d"), ("x", "x")]


def test_bundle_file_entries_string_scalar() -> None:
    assert sync._bundle_file_entries("only.txt") == [("only.txt", "only.txt")]


def test_bundle_file_entries_bad_entry() -> None:
    with pytest.raises(sync.SyncError, match="must be a string or"):
        sync._bundle_file_entries([{"dest": "d"}])


# --- Bundles resolution -------------------------------------------------------


def _bundles(**bundles: dict[str, Any]) -> sync.Bundles:
    return sync.Bundles.from_config({"bundles": bundles})


def test_resolve_unknown_bundle_strict_raises() -> None:
    with pytest.raises(sync.SyncError, match="does not exist"):
        _bundles(a={}).resolve_to_paths(["missing"])


def test_resolve_cycle_strict_raises() -> None:
    b = sync.Bundles.from_config({"bundles": {"a": {"requires": ["b"]}, "b": {"requires": ["a"]}}})
    with pytest.raises(sync.SyncError, match="Circular dependency"):
        b.resolve_to_paths(["a"])


def test_order_non_strict_skips_unknown_and_cycle() -> None:
    # _order(strict=False) (used by resolve_to_path_map) drops unknown + cyclic bundles.
    b = sync.Bundles.from_config({"bundles": {"a": {"requires": ["a"]}}})
    assert b._order(["a", "ghost"], strict=False) == ["a"]


def test_resolve_to_path_map_ignores_unresolved_remap() -> None:
    # A remapped source not in the resolved set is skipped from the path map.
    b = _bundles(a={"files": [{"source": "s", "dest": "d"}]})
    assert b.resolve_to_path_map(["a"]) == {"s": "d"}


def test_resolve_to_paths_dir_bundle() -> None:
    assert _bundles(core={}).resolve_to_paths(["core"]) == ["bundles/core/"]


def test_resolve_to_path_map_dir_bundle_maps_to_empty() -> None:
    assert _bundles(core={}).resolve_to_path_map(["core"]) == {"bundles/core/": ""}


def test_resolve_to_paths_dedups_shared_sources() -> None:
    b = _bundles(
        a={"files": [{"source": "shared.txt"}]},
        c={"requires": ["a"], "files": [{"source": "shared.txt"}]},
    )
    assert b.resolve_to_paths(["a", "c"]) == ["shared.txt"]


# --- _resolve_bundle_names ----------------------------------------------------


def test_resolve_bundle_names_no_profiles_returns_templates() -> None:
    template = sync.Template("o/r", "main", templates=["core"])
    assert sync._resolve_bundle_names(template, _bundles(core={})) == ["core"]


def test_resolve_bundle_names_unknown_profile() -> None:
    template = sync.Template("o/r", "main", profiles=["ghost"])
    with pytest.raises(sync.SyncError, match="Available profiles"):
        sync._resolve_bundle_names(template, sync.Bundles.from_config({"profiles": {}}))


def test_resolve_bundle_names_expands_and_dedups() -> None:
    template = sync.Template("o/r", "main", profiles=["p"], templates=["core"])
    bundles = sync.Bundles.from_config(
        {"bundles": {"core": {}, "extra": {}}, "profiles": {"p": {"bundles": ["core", "extra"]}}}
    )
    assert sync._resolve_bundle_names(template, bundles) == ["core", "extra"]


# --- _remap_path --------------------------------------------------------------


def test_remap_path_exact_prefix_and_none() -> None:
    assert sync._remap_path("a.txt", {"a.txt": "b.txt"}) == "b.txt"
    assert sync._remap_path("dir/x.txt", {"dir/": "out"}) == "out/x.txt"
    assert sync._remap_path("bundles/core/f", {"bundles/core/": ""}) == "f"
    assert sync._remap_path("unmapped.txt", {"a": "b"}) == "unmapped.txt"


# --- lock helpers -------------------------------------------------------------


def test_build_lock_includes_profiles() -> None:
    template = sync.Template("o/r", "v1", profiles=["p"], templates=["t"])
    lock = sync._build_lock("sha1", template, ["f.txt"], "2026-01-01T00:00:00Z")
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
    lock = sync._build_lock("sha1", sync.Template("o/r", "v1", include=["f.txt"]), ["f.txt"], "t1")
    sync._write_lock(tmp_path, lock, lock_path)
    lock2 = sync._build_lock(
        "sha1", sync.Template("o/r", "v1", include=["f.txt"]), ["f.txt"], "t2-different"
    )
    sync._write_lock(tmp_path, lock2, lock_path)
    assert "already up to date" in capsys.readouterr().err


def test_write_lock_rewrites_when_existing_malformed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lock_path = tmp_path / "template.lock"
    lock_path.write_text("garbage")
    (tmp_path / "f.txt").write_text("x")
    monkeypatch.setattr(sync, "load_yaml", lambda _p: (_ for _ in ()).throw(ValueError("bad")))
    lock = sync._build_lock("sha1", sync.Template("o/r", "v1"), ["f.txt"], "t1")
    sync._write_lock(tmp_path, lock, lock_path)
    # dump_yaml is the real one; file should have been (re)written with our sha.
    assert "sha: sha1" in lock_path.read_text()


def test_write_lock_filters_missing_files(tmp_path: Path) -> None:
    lock_path = tmp_path / "template.lock"
    (tmp_path / "present.txt").write_text("x")
    lock = sync._build_lock("sha1", sync.Template("o/r", "v1"), ["present.txt", "ghost.txt"], "t1")
    sync._write_lock(tmp_path, lock, lock_path)
    written = sync.load_yaml(lock_path)
    assert written["files"] == ["present.txt"]


# --- orphan cleanup unlink failure --------------------------------------------


def test_clean_orphaned_unlink_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / "orphan.txt").write_text("x")
    monkeypatch.setattr(
        Path, "unlink", lambda self, *a, **k: (_ for _ in ()).throw(OSError("locked"))
    )
    sync._clean_orphaned_files(tmp_path, [], set(), {Path("orphan.txt")})
    assert "Failed to delete" in capsys.readouterr().err


# --- base sha + previously-tracked reads --------------------------------------


def test_read_base_sha_variants(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    assert sync._read_base_sha(tmp_path / "none.lock") is None
    lock = tmp_path / "template.lock"
    lock.write_text("sha: abc\n")
    assert sync._read_base_sha(lock) == "abc"
    lock.write_text("ref: main\n")  # no sha
    assert sync._read_base_sha(lock) is None
    monkeypatch.setattr(sync, "load_yaml", lambda _p: (_ for _ in ()).throw(ValueError("bad")))
    assert sync._read_base_sha(lock) is None


def test_previously_tracked_variants(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    assert sync._previously_tracked(tmp_path / "none.lock") == set()
    lock = tmp_path / "template.lock"
    lock.write_text("files:\n- a.txt\n- b.txt\n")
    assert sync._previously_tracked(lock) == {Path("a.txt"), Path("b.txt")}
    monkeypatch.setattr(sync, "load_yaml", lambda _p: (_ for _ in ()).throw(ValueError("bad")))
    assert sync._previously_tracked(lock) == set()


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
    monkeypatch.setattr(sync.git, "get_diff", lambda *a: "")  # empty diff -> clean
    ctx = sync.git.GitContext(executable="git", env={})
    base_snapshot = tmp_path / "base"
    base_snapshot.mkdir()
    clean = sync._merge_with_base(
        ctx, tmp_path, tmp_path, "deadbeef", base_snapshot, "/url", [], set(), {}
    )
    assert clean is True
    assert "Could not check out base commit" in capsys.readouterr().err


class TestSyncError:
    def test_is_exception_with_message(self):
        err = sync.SyncError("boom")
        assert isinstance(err, Exception)
        assert str(err) == "boom"


class TestTemplate:
    def test_load_reads_fields(self, tmp_path):
        tf = tmp_path / "template.yml"
        tf.write_text('repository: "o/r"\nref: v1\ninclude:\n  - Makefile\n')
        template = sync._load_template(tmp_path, tf)
        assert template.repository == "o/r"
        assert template.include == ["Makefile"]


class TestBundles:
    def test_order_is_topological(self):
        b = sync.Bundles.from_config(
            {"bundles": {"a": {"requires": ["b"]}, "b": {}, "c": {"requires": ["a"]}}}
        )
        assert b._order(["c"], strict=True) == ["b", "a", "c"]
