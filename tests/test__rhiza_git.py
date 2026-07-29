"""Unit and property tests for `scripts/_rhiza_git.py`.

Two halves, with different jobs:

* **Branch tests** (first half) fault the single `_run_git` seam to reach the error
  paths real git will not produce on demand. They establish that each branch *runs*.
* **Property tests** (second half) drive the real merge over a generated cross-product
  of edits and assert invariants about the *result*. Line coverage cannot speak to
  whether a merge was correct, and this is the one component that rewrites files the
  user wrote — see the section header below.

Happy paths at the repo level live in `test_sync.py`.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import _rhiza_git as git
import pytest


def _completed(
    returncode: int = 0, stdout: bytes = b"", stderr: bytes = b""
) -> subprocess.CompletedProcess[bytes]:
    """Build a fake CompletedProcess for a stubbed git call."""
    return subprocess.CompletedProcess(
        args=["git"], returncode=returncode, stdout=stdout, stderr=stderr
    )


@pytest.fixture
def ctx() -> git.GitContext:
    """A GitContext with a placeholder executable (real git is never run here)."""
    return git.GitContext(executable="git", env={})


# --- executable discovery + context -------------------------------------------


def test_get_git_executable_found(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(git.shutil, "which", lambda _: "/usr/bin/git")
    assert git.get_git_executable() == "/usr/bin/git"


def test_get_git_executable_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(git.shutil, "which", lambda _: None)
    with pytest.raises(RuntimeError, match="git executable not found"):
        git.get_git_executable()


def test_scan_conflict_artifacts_rej_and_markers(tmp_path: Path) -> None:
    (tmp_path / "a.rej").write_text("hunk\n")
    (tmp_path / "b.txt").write_text("x\n<<<<<<< HEAD\n")
    (tmp_path / "clean.txt").write_text("fine\n")
    (tmp_path / "sub").mkdir()
    rej, markers = git.scan_conflict_artifacts(tmp_path)
    assert rej == ["a.rej"]
    assert markers == ["b.txt"]


def test_scan_conflict_artifacts_tolerates_unreadable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "x.txt").write_text("data\n")
    orig = Path.read_bytes

    def boom(self: Path, *a: Any, **k: Any) -> bytes:
        if self.name == "x.txt":
            raise OSError("unreadable")
        return orig(self, *a, **k)

    monkeypatch.setattr(Path, "read_bytes", boom)
    rej, markers = git.scan_conflict_artifacts(tmp_path)
    assert rej == [] and markers == []


class TestGitContext:
    def test_default_sets_prompt_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(git.shutil, "which", lambda _: "/usr/bin/git")
        ctx = git.GitContext.default()
        assert ctx.executable == "/usr/bin/git"
        assert ctx.env["GIT_TERMINAL_PROMPT"] == "0"


# --- the merge algorithm's invariants, over generated triples ------------------
#
# Everything above this line faults `_run_git`, so no test in this file ever merged
# real content. That is what issue #65 is about: `sync.py` plus these helpers are a
# 3-way merge, they have 100% line coverage, and line coverage on a merge algorithm
# says every branch was *reached* — not that the merged *result* was right for the
# input. The interesting failures are wrong output on inputs no test constructed.
#
# These tests assert invariants over a generated cross-product of edits instead. The
# pair `get_diff` + `apply_diff` below *is* the merge: `sync.py::_merge_with_base`
# diffs the previously-synced snapshot against the new upstream snapshot and applies
# that diff to the working tree, passing those same two snapshots as the
# `git merge-file` fallback's inputs.

# Long enough that edits 3+ lines apart land in separate hunks. `git apply` uses three
# lines of context, so in a short file every edit overlaps every other and the
# "disjoint edits merge cleanly" property could never be tested at all.
_BASE_LINES = [f"line-{i:02d}" for i in range(1, 21)]
_BASE = "".join(f"{line}\n" for line in _BASE_LINES)

# Where each edit touches, in base line numbers — used to predict whether two edits
# collide, rather than hand-listing the colliding pairs.
_REGION: dict[str, frozenset[int]] = {
    "noop": frozenset(),
    "head": frozenset({1}),
    "mid": frozenset({10}),
    "tail": frozenset({18}),
    "del-mid": frozenset({10}),
    "ins-mid": frozenset({10}),
    "append": frozenset({20}),
    "truncate": frozenset(range(21)),
    "rewrite": frozenset(range(21)),
}
_OPS = tuple(_REGION)


def _edit(op: str, tag: str) -> str:
    """Return `_BASE` with edit *op* applied, marking every new line with *tag*."""
    lines = list(_BASE_LINES)
    if op == "noop":
        pass
    elif op == "head":
        lines[1] = f"{tag}-head"
    elif op == "mid":
        lines[10] = f"{tag}-mid"
    elif op == "tail":
        lines[18] = f"{tag}-tail"
    elif op == "del-mid":
        del lines[10]
    elif op == "ins-mid":
        lines.insert(10, f"{tag}-inserted")
    elif op == "append":
        lines.append(f"{tag}-appended")
    elif op == "truncate":
        lines = []
    else:  # rewrite
        lines = [f"{tag}-{i:02d}" for i in range(len(lines))]
    return "".join(f"{line}\n" for line in lines)


def _collide(local_op: str, upstream_op: str, *, margin: int = 0) -> bool:
    """Do these two edits change the same lines?

    `margin=0` — strict intersection — on purpose. Proximity is not collision: git's
    three lines of context decide how edits are *grouped into hunks*, not whether they
    conflict, and a 3-way merge resolves non-overlapping changes inside one hunk
    perfectly well. Writing this with `margin=3` predicted a conflict for `tail` (line
    19) against `append` (past line 20); the merge in fact kept both, which is correct.
    The test was wrong, not the code.
    """
    local, upstream = _REGION[local_op], _REGION[upstream_op]
    if not local or not upstream:
        return False
    return any(abs(a - b) <= margin for a in local for b in upstream)


def _merge(tmp_path: Path, *, base: str, local: str, upstream: str) -> dict[str, Any]:
    """Run the real merge over three trees; report the result and any artifacts."""
    ctx = git.GitContext.default()
    base_dir, upstream_dir, target = (tmp_path / n for n in ("base", "upstream", "target"))
    for directory in (base_dir, upstream_dir, target):
        directory.mkdir()
    (base_dir / "f.txt").write_text(base)
    (upstream_dir / "f.txt").write_text(upstream)
    (target / "f.txt").write_text(local)
    # A file the template does not own, to prove the merge stays inside its lane.
    (target / "mine.txt").write_text("user-owned\n")

    for args in (
        ["init", "-q", "-b", "main", "."],
        ["config", "user.email", "t@e.com"],
        ["config", "user.name", "T"],
        ["add", "-A"],
        ["commit", "-qm", "local"],
    ):
        subprocess.run(["git", *args], cwd=target, check=True, capture_output=True)

    diff = git.get_diff(ctx, base_dir, upstream_dir)
    clean = git.apply_diff(ctx, diff, target, base_dir, upstream_dir)
    rejects, markers = git.scan_conflict_artifacts(target)
    return {
        "diff": diff,
        "clean": clean,
        "result": (target / "f.txt").read_text(),
        "rejects": rejects,
        "markers": markers,
        "mine": (target / "mine.txt").read_text(),
        "untouched": not rejects and not markers,
    }


@pytest.mark.parametrize("upstream_op", _OPS)
def test_property_a_file_untouched_locally_ends_at_upstream(upstream_op: str, tmp_path: Path):
    """No local edit ⇒ the template's content wins outright, with no artifacts.

    This is the ordinary case — the vast majority of synced files — so a conflict here
    would mean /update produced markers in a file nobody had touched.
    """
    upstream = _edit(upstream_op, "UP")
    out = _merge(tmp_path, base=_BASE, local=_BASE, upstream=upstream)

    assert out["result"] == upstream, "a locally-untouched file must end at upstream"
    assert out["untouched"], f"unexpected artifacts: {out['rejects']} {out['markers']}"
    assert out["clean"]


@pytest.mark.parametrize("local_op", _OPS)
def test_property_a_file_untouched_upstream_keeps_local_content(local_op: str, tmp_path: Path):
    """No template change ⇒ the local file is never rewritten.

    The strongest safety property in the file: if upstream didn't change, a local edit
    cannot be clobbered no matter what it was.
    """
    local = _edit(local_op, "LOCAL")
    out = _merge(tmp_path, base=_BASE, local=local, upstream=_BASE)

    assert out["result"] == local, "an unchanged template must not touch local content"
    assert out["diff"].strip() == "", "an unchanged template must produce an empty diff"
    assert out["untouched"]
    assert out["clean"]


@pytest.mark.parametrize(
    ("local_op", "upstream_op"),
    [
        (local, upstream)
        for local in _OPS
        for upstream in _OPS
        if local != "noop" and upstream != "noop" and _collide(local, upstream)
    ],
)
def test_property_a_collision_is_never_resolved_silently(
    local_op: str, upstream_op: str, tmp_path: Path
):
    """Both sides touched the same region ⇒ say so; never pick a winner quietly.

    Silently choosing a side is the corruption mode that matters: the user's edit
    disappears, /update reports success, and nothing looks wrong until much later.
    """
    local, upstream = _edit(local_op, "LOCAL"), _edit(upstream_op, "UP")
    if local == upstream:
        pytest.skip("both sides made the identical edit — nothing to resolve")

    out = _merge(tmp_path, base=_BASE, local=local, upstream=upstream)

    assert not out["untouched"], (
        f"{local_op} vs {upstream_op} collided but merged silently to:\n{out['result']}"
    )
    assert not out["clean"], "a collision must be reported to the caller"


@pytest.mark.parametrize(
    ("local_op", "upstream_op"),
    [
        (local, upstream)
        for local in _OPS
        for upstream in _OPS
        if local != "noop" and upstream != "noop" and not _collide(local, upstream)
    ],
)
def test_property_disjoint_edits_merge_cleanly_and_keep_both(
    local_op: str, upstream_op: str, tmp_path: Path
):
    """Edits far enough apart must both survive, with no conflict at all."""
    local, upstream = _edit(local_op, "LOCAL"), _edit(upstream_op, "UP")
    out = _merge(tmp_path, base=_BASE, local=local, upstream=upstream)

    assert out["untouched"], f"disjoint edits conflicted: {out['rejects']} {out['markers']}"
    assert out["clean"]
    for line in (ln for ln in local.splitlines() if ln.startswith("LOCAL-")):
        assert line in out["result"], f"local edit {line!r} was dropped"
    for line in (ln for ln in upstream.splitlines() if ln.startswith("UP-")):
        assert line in out["result"], f"upstream edit {line!r} was dropped"


@pytest.mark.parametrize(("local_op", "upstream_op"), [(a, b) for a in _OPS for b in _OPS])
def test_property_no_local_edit_is_ever_lost_without_a_marker(
    local_op: str, upstream_op: str, tmp_path: Path
):
    """Across every pair: a clean merge must not have quietly dropped a local line.

    The universal invariant. Whatever the merge decides, it may only discard a line the
    user wrote if it also leaves a marker or a `.rej` for a human to look at.
    """
    local, upstream = _edit(local_op, "LOCAL"), _edit(upstream_op, "UP")
    out = _merge(tmp_path, base=_BASE, local=local, upstream=upstream)

    if not out["untouched"]:
        return  # conflict declared — the user is being asked, which is allowed
    for line in (ln for ln in local.splitlines() if ln.startswith("LOCAL-")):
        assert line in out["result"], (
            f"{local_op} vs {upstream_op}: local line {line!r} vanished from a "
            f"merge reported as clean:\n{out['result']}"
        )


@pytest.mark.parametrize(("local_op", "upstream_op"), [(a, b) for a in _OPS for b in _OPS])
def test_property_files_the_template_does_not_own_are_never_touched(
    local_op: str, upstream_op: str, tmp_path: Path
):
    """The merge must stay inside the template's file set, conflict or not."""
    out = _merge(
        tmp_path,
        base=_BASE,
        local=_edit(local_op, "LOCAL"),
        upstream=_edit(upstream_op, "UP"),
    )
    assert out["mine"] == "user-owned\n"


@pytest.mark.parametrize("local_op", _OPS)
def test_property_re_syncing_the_same_ref_is_a_no_op(local_op: str, tmp_path: Path):
    """Idempotency: once synced, base == upstream, so a re-run must change nothing.

    This is what makes /update safe to re-run — and it is the reason the "unchanged
    template" branch exists in `_merge_with_base`.
    """
    local = _edit(local_op, "LOCAL")
    upstream = _edit("mid", "UP")
    out = _merge(tmp_path, base=upstream, local=local, upstream=upstream)

    assert out["diff"].strip() == ""
    assert out["result"] == local
    assert out["untouched"]
    assert out["clean"]
