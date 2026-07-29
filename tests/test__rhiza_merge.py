"""Property tests for the three-way merge (`scripts/_rhiza_merge.py`).

`sync.py` has three trees on disk when it merges — the base snapshot, the upstream
snapshot, and the working tree — and this module merges them. It replaced a diff
round-trip (`git diff --no-index` -> `git apply -3` -> parse the diff text back into a
file list -> `git merge-file` after all) that computed a diff from two directories only
to recover from it what those directories stated directly.

Two kinds of test here:

* **Unit tests** for `changed_files`, which reads the file list off the two snapshots,
  and for the outcome classification (merged / conflicted / unmergeable / deleted).
* **Property tests** over a generated cross-product of edits, asserting invariants
  about the merged *result* rather than which lines ran.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import _rhiza_git as git
import _rhiza_merge as merge
import pytest


# --- the merge algorithm's invariants, over generated triples ------------------
#
# Line coverage on a merge algorithm says every branch was *reached*, not that the
# merged *result* was right for the input, and this is the one component of the plugin
# that rewrites files the user wrote. So these assert invariants over a generated
# cross-product of edits instead (issue #65).
#
# They were written against the previous implementation — render a `git diff --no-index`
# of base against upstream, apply it with `git apply -3`, fall back to parsing that diff
# text and merging each file with `git merge-file` — and they are what made replacing it
# with a direct tree comparison safe to do. The only change needed was the harness call
# below; every property held unmodified, which is the whole argument that the rewrite
# preserved behaviour.

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

    outcome = merge.merge_trees(ctx, target, base_dir, upstream_dir)
    rejects, markers = git.scan_conflict_artifacts(target)
    return {
        "outcome": outcome,
        "clean": outcome.clean,
        "result": (target / "f.txt").read_text(),
        "rejects": rejects,
        "markers": markers,
        "mine": (target / "mine.txt").read_text(),
        "untouched": not rejects and not markers,
        "considered": outcome.merged + outcome.conflicted + outcome.unmergeable
        + outcome.deleted,
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
    assert out["considered"] == [], "an unchanged template must not touch any file"
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

    assert out["considered"] == []
    assert out["result"] == local
    assert out["untouched"]
    assert out["clean"]


# --- the outcome types --------------------------------------------------------


class TestMergeOutcome:
    """The per-path record of what the merge did."""

    def test_is_clean_when_nothing_conflicted_or_refused(self):
        outcome = merge.MergeOutcome(merged=["a"], deleted=["b"])
        assert outcome.clean is True

    def test_a_conflict_is_not_clean(self):
        assert merge.MergeOutcome(conflicted=["a"]).clean is False

    def test_an_unmergeable_file_is_not_clean(self):
        """A refusal has no marker to find it by, so it must still fail the sync."""
        assert merge.MergeOutcome(unmergeable=["a"]).clean is False


class TestChange:
    """One template file differing between the base and upstream snapshots."""

    def test_carries_the_path_and_its_kind(self):
        change = merge.Change("a.txt", is_new=True, is_deleted=False)
        assert (change.path, change.is_new, change.is_deleted) == ("a.txt", True, False)


# --- changed_files: read off the trees, not out of a diff ---------------------


def _trees(tmp_path: Path, base: dict[str, bytes], upstream: dict[str, bytes]):
    """Materialise a base and upstream snapshot from two {path: bytes} maps."""
    base_dir, upstream_dir = tmp_path / "b", tmp_path / "u"
    for directory, files in ((base_dir, base), (upstream_dir, upstream)):
        directory.mkdir()
        for rel, content in files.items():
            path = directory / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
    return base_dir, upstream_dir


def test_changed_files_omits_identical_files(tmp_path):
    """The rule that makes an untouched template file safe: it is never considered."""
    base, upstream = _trees(tmp_path, {"same.txt": b"x\n"}, {"same.txt": b"x\n"})
    assert merge.changed_files(base, upstream) == []


def test_changed_files_reports_modified_new_and_deleted(tmp_path):
    base, upstream = _trees(
        tmp_path,
        {"mod.txt": b"old\n", "gone.txt": b"bye\n", "same.txt": b"x\n"},
        {"mod.txt": b"new\n", "added.txt": b"hi\n", "same.txt": b"x\n"},
    )
    assert merge.changed_files(base, upstream) == [
        merge.Change("added.txt", is_new=True, is_deleted=False),
        merge.Change("gone.txt", is_new=False, is_deleted=True),
        merge.Change("mod.txt", is_new=False, is_deleted=False),
    ]


def test_changed_files_finds_nested_paths(tmp_path):
    base, upstream = _trees(tmp_path, {}, {".github/workflows/ci.yml": b"on: push\n"})
    assert merge.changed_files(base, upstream) == [
        merge.Change(".github/workflows/ci.yml", is_new=True, is_deleted=False)
    ]


# --- is_binary ----------------------------------------------------------------


@pytest.mark.parametrize(
    ("content", "expected"),
    [(b"plain text\n", False), (b"", False), (b"pre\x00post", True), (b"\x00", True)],
)
def test_is_binary(tmp_path, content, expected):
    path = tmp_path / "f"
    path.write_bytes(content)
    assert merge.is_binary(path) is expected


def test_is_binary_ignores_a_nul_beyond_the_sniff_window(tmp_path):
    """Matches git's heuristic: only the head of the file is inspected."""
    path = tmp_path / "f"
    path.write_bytes(b"a" * (merge._SNIFF_BYTES + 10) + b"\x00")
    assert merge.is_binary(path) is False


# --- merge_one: the classification branches -----------------------------------


def _ctx() -> git.GitContext:
    return git.GitContext.default()


def test_a_deleted_file_is_removed_and_recorded(tmp_path):
    base, upstream = _trees(tmp_path, {"gone.txt": b"bye\n"}, {})
    target = tmp_path / "t"
    target.mkdir()
    (target / "gone.txt").write_text("bye\n")

    outcome = merge.merge_trees(_ctx(), target, base, upstream)

    assert outcome.deleted == ["gone.txt"]
    assert not (target / "gone.txt").exists()
    assert outcome.clean


def test_deleting_an_already_absent_file_is_not_an_error(tmp_path):
    base, upstream = _trees(tmp_path, {"gone.txt": b"bye\n"}, {})
    target = tmp_path / "t"
    target.mkdir()

    outcome = merge.merge_trees(_ctx(), target, base, upstream)

    assert outcome.deleted == ["gone.txt"]
    assert outcome.clean


def test_a_file_missing_from_the_target_is_restored(tmp_path):
    """Nothing local to preserve, so there is nothing to merge — take upstream."""
    base, upstream = _trees(tmp_path, {"f.txt": b"old\n"}, {"f.txt": b"new\n"})
    target = tmp_path / "t"
    target.mkdir()

    outcome = merge.merge_trees(_ctx(), target, base, upstream)

    assert (target / "f.txt").read_text() == "new\n"
    assert outcome.merged == ["f.txt"]


def test_a_locally_modified_binary_is_left_untouched_and_reported(tmp_path):
    """`git merge-file` cannot merge binary, and overwriting would lose work silently."""
    base, upstream = _trees(tmp_path, {"logo.png": b"BASE\x00\x01"}, {"logo.png": b"UP\x00\x02"})
    target = tmp_path / "t"
    target.mkdir()
    (target / "logo.png").write_bytes(b"LOCAL\x00\x03")

    outcome = merge.merge_trees(_ctx(), target, base, upstream)

    assert outcome.unmergeable == ["logo.png"]
    assert (target / "logo.png").read_bytes() == b"LOCAL\x00\x03", "local binary was clobbered"
    assert not outcome.clean, "a refusal must fail the sync — it leaves no marker to find"


def test_an_unmodified_binary_is_updated_without_a_merge(tmp_path):
    """No local change, so upstream wins outright — no `git merge-file` involved."""
    base, upstream = _trees(tmp_path, {"logo.png": b"BASE\x00\x01"}, {"logo.png": b"UP\x00\x02"})
    target = tmp_path / "t"
    target.mkdir()
    (target / "logo.png").write_bytes(b"BASE\x00\x01")

    outcome = merge.merge_trees(_ctx(), target, base, upstream)

    assert outcome.merged == ["logo.png"]
    assert (target / "logo.png").read_bytes() == b"UP\x00\x02"


def test_a_merge_file_refusal_is_classified_as_unmergeable(tmp_path, monkeypatch):
    """255 means "I will not merge this" — distinct from a conflict count."""
    base, upstream = _trees(tmp_path, {"f.txt": b"old\n"}, {"f.txt": b"new\n"})
    target = tmp_path / "t"
    target.mkdir()
    (target / "f.txt").write_text("local\n")
    monkeypatch.setattr(merge.git, "merge_file", lambda *a: merge._MERGE_REFUSED)

    outcome = merge.merge_trees(_ctx(), target, base, upstream)

    assert outcome.unmergeable == ["f.txt"]
    assert outcome.conflicted == []
