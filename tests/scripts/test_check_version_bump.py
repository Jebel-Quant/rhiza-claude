"""Tests for the release guard (`scripts/check_version_bump.py`).

The property under test is the one `bump-my-version` does not provide: a release must
strictly increase. bump-my-version accepts `0.4.2 -> 0.4.1` without complaint and knows
nothing about git tags, and a pushed tag is effectively permanent — so this is the
check that prevents the one unrecoverable mistake in the release flow.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import check_version_bump as cvb
import pytest

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git not available")


def _git(repo: Path, *args: str) -> None:
    """Run a git command, raising with output on failure."""
    result = subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True)
    assert result.returncode == 0, f"git {' '.join(args)}:\n{result.stderr}"


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A git repo with one commit and no tags."""
    _git(tmp_path, "init", "-q", "-b", "main")
    _git(tmp_path, "config", "user.email", "t@example.com")
    _git(tmp_path, "config", "user.name", "T")
    (tmp_path / "f.txt").write_text("x\n", encoding="utf-8")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-qm", "initial")
    return tmp_path


def _tag(repo: Path, *tags: str) -> None:
    """Create lightweight tags."""
    for t in tags:
        _git(repo, "tag", t)


class TestVersionError:
    """The error raised for a malformed version string."""

    def test_is_exception_with_message(self):
        err = cvb.VersionError("boom")
        assert isinstance(err, Exception)
        assert str(err) == "boom"


# --- semver parsing and ordering ---------------------------------------------


@pytest.mark.parametrize(
    "raw", ["1.2.3", "v1.2.3", "v0.0.1", "v10.20.30", "v1.0.0-rc1", "1.0.0+b1"]
)
def test_parse_accepts_semver(raw):
    assert cvb.parse_semver(raw)


@pytest.mark.parametrize("raw", ["1.2", "v1", "main", "", "v1.2.3.4", "vX.Y.Z", "1.2.3-"])
def test_parse_rejects_non_semver(raw):
    with pytest.raises(cvb.VersionError):
        cvb.parse_semver(raw)


def test_numeric_not_lexical_ordering():
    """The bug a string sort produces: v1.9.0 must be below v1.10.0."""
    assert cvb.compare("v1.10.0", "v1.9.0") == 1
    assert cvb.compare("v0.10.0", "v0.4.2") == 1
    assert cvb.compare("v2.0.0", "v10.0.0") == -1


def test_equal_versions_compare_zero():
    assert cvb.compare("1.2.3", "v1.2.3") == 0
    assert cvb.compare("1.2.3+build", "1.2.3") == 0  # build metadata ignored per semver


def test_prerelease_sorts_below_its_release():
    """semver §11: 1.0.0-rc1 < 1.0.0."""
    assert cvb.compare("v1.0.0-rc1", "v1.0.0") == -1
    assert cvb.compare("v1.0.0", "v1.0.0-rc1") == 1


def test_prerelease_identifiers_order_per_spec():
    """semver §11.4: numeric identifiers compare numerically, others lexically."""
    assert cvb.compare("v1.0.0-alpha", "v1.0.0-beta") == -1
    assert cvb.compare("v1.0.0-1", "v1.0.0-alpha") == -1  # numeric ranks below alphanumeric
    assert cvb.compare("v1.0.0-rc.2", "v1.0.0-rc.10") == -1  # dot-separated -> numeric


def test_undotted_prerelease_counters_order_lexically_not_numerically():
    """A footgun worth pinning: `-rc10` sorts *below* `-rc2`.

    "rc2" and "rc10" are single alphanumeric identifiers, so semver §11.4.2 compares
    them as ASCII strings — "rc10" < "rc2". Anyone wanting rc2 < rc10 must write
    `-rc.2` and `-rc.10`. This is spec-correct, not a bug, and the guard will refuse
    v1.0.0-rc10 after v1.0.0-rc2 as "not increasing" — which is the safe direction.
    """
    assert cvb.compare("v1.0.0-rc2", "v1.0.0-rc10") == 1


# --- the floor ---------------------------------------------------------------


def test_floor_is_the_current_version_when_untagged():
    assert cvb.compute_floor("0.4.2", []) == "v0.4.2"


def test_floor_prefers_the_highest_tag_over_a_lower_current():
    """A reverted bump or hand-edited manifest can leave current below the newest tag."""
    assert cvb.compute_floor("0.1.0", ["v0.9.0", "v0.2.0"]) == "v0.9.0"


def test_floor_prefers_current_when_it_leads_the_tags():
    assert cvb.compute_floor("2.0.0", ["v1.9.0"]) == "v2.0.0"


def test_floor_uses_semver_not_string_order():
    assert cvb.compute_floor("0.1.0", ["v0.9.0", "v0.10.0"]) == "v0.10.0"


# --- suggestions -------------------------------------------------------------


def test_suggestions_are_the_three_bump_kinds():
    assert cvb.suggest("v1.2.3") == {
        "patch": "v1.2.4",
        "minor": "v1.3.0",
        "major": "v2.0.0",
    }


def test_suggestions_reset_lower_components():
    """A minor bump zeroes the patch; a major zeroes both."""
    assert cvb.suggest("v1.9.7")["minor"] == "v1.10.0"
    assert cvb.suggest("v1.9.7")["major"] == "v2.0.0"


def test_suggestions_for_a_pre_1_0_project():
    """The case that motivated the menu: v0.5.0 must be offered beside v1.0.0."""
    suggestions = cvb.suggest("v0.4.2")
    assert suggestions["minor"] == "v0.5.0"
    assert suggestions["major"] == "v1.0.0"


def test_every_suggestion_strictly_increases_past_the_floor(repo):
    """The menu must never offer an illegal option."""
    _tag(repo, "v0.4.2")
    for candidate in cvb.suggest("v0.4.2").values():
        assert cvb.check(repo, candidate, "0.4.2")["ok"], candidate


def test_suggestions_ignore_a_prerelease_on_the_floor():
    """Bumping from a prerelease offers releases, not more prereleases."""
    assert cvb.suggest("v1.0.0-rc1") == {
        "patch": "v1.0.1",
        "minor": "v1.1.0",
        "major": "v2.0.0",
    }


def test_check_includes_the_suggestions(repo):
    _tag(repo, "v0.4.2")
    assert cvb.check(repo, "v1.0.0", "0.4.2")["suggestions"]["minor"] == "v0.5.0"


# --- tag discovery ----------------------------------------------------------


def test_existing_tags_sorted_highest_first_and_filtered(repo):
    _tag(repo, "v0.1.0", "v0.10.0", "v0.2.0", "not-a-version", "v1.0.0-rc1")
    assert cvb.existing_tags(repo) == ["v1.0.0-rc1", "v0.10.0", "v0.2.0", "v0.1.0"]


def test_existing_tags_outside_a_repo_is_empty(tmp_path):
    assert cvb.existing_tags(tmp_path) == []


# --- check() ----------------------------------------------------------------


def test_accepts_a_forward_bump(repo):
    _tag(repo, "v0.4.2")
    result = cvb.check(repo, "v1.0.0", "0.4.2")
    assert result["ok"] and result["exit_code"] == cvb.EXIT_OK
    assert result["floor"] == "v0.4.2"


def test_rejects_a_backwards_bump(repo):
    """The case bump-my-version accepts silently."""
    _tag(repo, "v0.9.0")
    result = cvb.check(repo, "v0.8.0", "0.9.0")
    assert not result["ok"]
    assert result["exit_code"] == cvb.EXIT_NOT_INCREASING
    assert "does not strictly increase" in result["reason"]


def test_rejects_the_same_version_when_untagged(repo):
    result = cvb.check(repo, "v0.4.2", "0.4.2")
    assert not result["ok"]
    assert "does not strictly increase" in result["reason"]


def test_rejects_an_existing_tag_by_name(repo):
    """Distinct from 'not increasing' — re-tagging must be named as such."""
    _tag(repo, "v1.0.0", "v0.4.2")
    result = cvb.check(repo, "v1.0.0", "1.0.0")
    assert not result["ok"]
    assert "already exists" in result["reason"]


def test_rejects_a_version_below_an_existing_tag_even_if_above_current(repo):
    """current lags the tags; a bump that beats current can still reuse a tag."""
    _tag(repo, "v0.9.0")
    result = cvb.check(repo, "v0.5.0", "0.1.0")
    assert not result["ok"]
    assert "v0.9.0" in result["reason"]


def test_accepts_a_prerelease_above_the_floor(repo):
    _tag(repo, "v0.4.2")
    assert cvb.check(repo, "v1.0.0-rc1", "0.4.2")["ok"]


def test_rejects_a_prerelease_of_the_current_release(repo):
    """1.0.0-rc1 is below 1.0.0, so it cannot follow it."""
    _tag(repo, "v1.0.0")
    assert not cvb.check(repo, "v1.0.0-rc1", "1.0.0")["ok"]


def test_a_bare_target_is_normalized_to_a_v_tag(repo):
    assert cvb.check(repo, "1.5.0", "0.4.2")["target"] == "v1.5.0"


def test_malformed_versions_raise(repo):
    with pytest.raises(cvb.VersionError):
        cvb.check(repo, "nope", "0.4.2")
    with pytest.raises(cvb.VersionError):
        cvb.check(repo, "v1.0.0", "nope")


# --- main() / CLI -----------------------------------------------------------


def test_main_accepts_and_reports(repo, capsys):
    _tag(repo, "v0.4.2")
    rc = cvb.main(["v1.0.0", "--current", "0.4.2", "--target-dir", str(repo)])
    assert rc == cvb.EXIT_OK
    out = capsys.readouterr().out
    assert "floor    v0.4.2" in out
    assert "ok       v1.0.0 > v0.4.2" in out


def test_main_rejects_with_exit_1(repo, capsys):
    _tag(repo, "v0.9.0")
    rc = cvb.main(["v0.8.0", "--current", "0.9.0", "--target-dir", str(repo)])
    assert rc == cvb.EXIT_NOT_INCREASING
    assert "does not strictly increase" in capsys.readouterr().err


def test_main_json_output(repo, capsys):
    _tag(repo, "v0.4.2")
    rc = cvb.main(["v1.0.0", "--current", "0.4.2", "--target-dir", str(repo), "--json"])
    assert rc == cvb.EXIT_OK
    payload = json.loads(capsys.readouterr().out)
    assert payload == {
        "target": "v1.0.0",
        "current": "0.4.2",
        "highest_tag": "v0.4.2",
        "tag_count": 1,
        "floor": "v0.4.2",
        "suggestions": {"patch": "v0.4.3", "minor": "v0.5.0", "major": "v1.0.0"},
        "ok": True,
        "reason": "v1.0.0 > v0.4.2",
        "exit_code": 0,
    }


def test_main_without_a_target_lists_suggestions(repo, capsys):
    """/release calls it this way to build its menu."""
    _tag(repo, "v0.4.2")
    rc = cvb.main(["--current", "0.4.2", "--target-dir", str(repo)])
    assert rc == cvb.EXIT_OK
    out = capsys.readouterr().out
    assert "floor    v0.4.2" in out
    assert "patch    v0.4.3" in out
    assert "minor    v0.5.0" in out
    assert "major    v1.0.0" in out
    # Nothing was proposed, so no target line and nothing guarded.
    assert not any(line.startswith("target ") for line in out.splitlines())
    assert "listing suggestions only" in out


def test_main_without_a_target_json(repo, capsys):
    rc = cvb.main(["--current", "0.4.2", "--target-dir", str(repo), "--json"])
    assert rc == cvb.EXIT_OK
    payload = json.loads(capsys.readouterr().out)
    assert payload["target"] is None
    assert payload["suggestions"]["major"] == "v1.0.0"


def test_main_without_a_target_still_validates_current(repo, capsys):
    rc = cvb.main(["--current", "not-a-version", "--target-dir", str(repo)])
    assert rc == cvb.EXIT_USAGE
    assert "is not a semver version" in capsys.readouterr().err


def test_main_exit_2_on_a_malformed_version(repo, capsys):
    rc = cvb.main(["not-a-version", "--current", "0.4.2", "--target-dir", str(repo)])
    assert rc == cvb.EXIT_USAGE
    assert "is not a semver version" in capsys.readouterr().err


def test_main_reports_no_tags(repo, capsys):
    rc = cvb.main(["v1.0.0", "--current", "0.4.2", "--target-dir", str(repo)])
    assert rc == cvb.EXIT_OK
    assert "(no tags)" in capsys.readouterr().out


# --- end-to-end: /release's full chain on a real repo -------------------------

# What a repo adds *on top of* the base `[tool.bumpversion]` table that
# `init_skeleton.py` already wrote (the `[project]` anchor): a self-referencing CI stub
# pin, which is a location only this repo knows about. `[tool.unrelated]` shares the
# version number deliberately — it must not move.
#
# Re-declaring `[tool.bumpversion]` here would be a duplicate-key TOML error, which is
# itself worth knowing: appending a second table is how a repo breaks its own release
# config, so `/rhiza:release`'s locations are extended, never restated. `allow_dirty` is
# left as the skeleton set it (false) and the bump below passes `--no-commit`.
_BUMPVERSION_CONFIG = r"""
[tool.unrelated]
version = "0.1.0"

[[tool.bumpversion.files]]
filename = ".github/workflows/stub.yml"
search = "widget/.github/workflows/reusable.yml@v{current_version}"
replace = "widget/.github/workflows/reusable.yml@v{new_version}"
"""


def test_e2e_release_bumps_every_declared_location(synced_repo_copy, plugin_scripts: Path):
    """The whole /release chain, on a repo with a real pyproject and a stub pin.

    Proves the property that motivated adopting bump-my-version: every *declared*
    location moves, and nothing else does — not a dependency pinned at the same
    version, not an unrelated `[tool.*]` table, not a third-party action ref.
    """
    from conftest import PY, assert_ok, run_cmd

    repo = synced_repo_copy
    pyproject = repo / "pyproject.toml"

    # Declare the version locations the way prompts/skeleton.md scaffolds them, plus a
    # self-referencing CI stub pin — the case /release used to miss entirely.
    (repo / ".github" / "workflows" / "stub.yml").write_text(
        "jobs:\n  ci:\n    uses: jebel-quant/widget/.github/workflows/reusable.yml@v0.1.0\n"
        "  other:\n    uses: actions/checkout@v0.1.0\n"
    )
    pyproject.write_text(pyproject.read_text(encoding="utf-8") + _BUMPVERSION_CONFIG)
    assert 'version = "0.1.0"' in pyproject.read_text(encoding="utf-8")

    # The skeleton writes `allow_dirty = false` — a release is cut from a clean tree — so
    # commit what the sync left behind first. That constraint is part of what is under
    # test: passing `--allow-dirty` here would quietly stop exercising it.
    # `--no-verify`: an earlier gate in this session may have installed the template's
    # pre-commit hooks in the shared fixture, and they would reject the deliberately
    # minimal `stub.yml` above as an invalid workflow. The template's hooks are not what
    # this test is about.
    assert_ok(run_cmd(["git", "add", "-A"], repo), "git add")
    assert_ok(run_cmd(["git", "commit", "-qm", "chore: sync", "--no-verify"], repo), "git commit")

    # 1. The declared current version, read by /release's step 1.
    current = run_cmd(["uvx", "bump-my-version", "show", "current_version"], repo)
    assert_ok(current, "bump-my-version show")
    assert current.stdout.strip().endswith("0.1.0")

    # 2. The guard — /release's step 4, and the check bump-my-version does not do.
    guard = plugin_scripts / "check_version_bump.py"
    assert_ok(run_cmd([*PY, str(guard), "v0.2.0", "--current", "0.1.0",
                       "--target-dir", str(repo)], repo), "guard v0.2.0")  # fmt: skip
    backwards = run_cmd([*PY, str(guard), "v0.0.1", "--current", "0.1.0",
                         "--target-dir", str(repo)], repo)  # fmt: skip
    assert backwards.returncode == cvb.EXIT_NOT_INCREASING, "the guard let a backwards bump through"

    # 3. The bump — /release's step 6.
    assert_ok(
        run_cmd(["uvx", "bump-my-version", "bump", "--new-version", "0.2.0",
                 "--no-commit", "--no-tag"], repo),
        "bump-my-version bump",
    )  # fmt: skip

    body = pyproject.read_text(encoding="utf-8")
    stub = (repo / ".github" / "workflows" / "stub.yml").read_text(encoding="utf-8")
    # Count whole lines, not substrings: `current_version = "0.2.0"` in the bumpversion
    # config legitimately contains `version = "0.2.0"`, and it is *meant* to advance.
    version_lines = [ln.strip() for ln in body.splitlines() if ln.strip().startswith("version = ")]
    assert version_lines.count('version = "0.2.0"') == 1, f"expected one bump, got {version_lines}"
    assert 'version = "0.1.0"' in body, "[tool.unrelated] should still hold the old version"
    assert '[tool.unrelated]\nversion = "0.1.0"' in body, "an unrelated table was rewritten"
    assert "httpx" not in body or ">=0.2.0" not in body, "a dependency pin was rewritten"
    assert "reusable.yml@v0.2.0" in stub, "the self-referencing stub pin did not move"
    assert "actions/checkout@v0.1.0" in stub, "a third-party pin was rewritten"

    # The realistic shape that broke the first pattern I recommended: `classifiers = [`
    # sits inside the [project] table *before* `version`, so a pattern excluding every
    # `[` never matched a repo this plugin actually produces.
    before_version = body.split('version = "0.2.0"')[0]
    assert "classifiers = [" in before_version, "fixture no longer exercises the hard case"


# --- end-to-end: where a Go module's version lives ----------------------------


def test_e2e_a_synced_go_module_has_a_discoverable_version_location(go_synced_repo):
    """The assertion #98 asked for, and it is about the *template's* file, not ours.

    `bump-my-version` auto-discovers exactly four filenames; a config anywhere else is
    silently ignored and the tool falls back to `git describe`. `go-core` therefore ships
    `.bumpversion.toml` at the root, and `/rhiza:release` — which passes no
    `--config-file` — depends on that being true.
    """
    import _skeleton_version

    assert _skeleton_version.bumpversion_config(go_synced_repo) == ".bumpversion.toml"

    body = (go_synced_repo / ".bumpversion.toml").read_text(encoding="utf-8")
    assert 'filename = "internal/version/version.go"' in body
    assert (go_synced_repo / "internal" / "version" / "version.go").is_file()
    # No `current_version` *assignment* — the mentions inside `search`/`replace` are the
    # tool's own placeholders. Deliberately absent: a Go module's version is its git tag,
    # so a synced value would be reset by the next /rhiza:update.
    assignments = [ln for ln in body.splitlines() if ln.strip().startswith("current_version")]
    assert assignments == [], f"go-core now pins a version it cannot own: {assignments}"


def test_e2e_the_first_go_release_needs_an_explicit_current_version(go_synced_repo):
    """A tagless Go module has a declared version location and no readable version.

    `/rhiza:release` step 1 distinguishes those, because the failure text is identical to
    "no config at all" and stopping on it would be the wrong diagnosis. Its answer is
    `CURRENT=0.0.0` — what `internal/version/version.go` ships — passed to the bump.
    """
    from conftest import assert_ok, run_cmd

    assert run_cmd(["git", "tag", "--list"], go_synced_repo).stdout.strip() == ""
    show = run_cmd(["uvx", "bump-my-version", "show", "current_version"], go_synced_repo)
    assert show.returncode != 0, "a tagless Go module cannot report a current version"

    constant = (go_synced_repo / "internal" / "version" / "version.go").read_text(encoding="utf-8")
    assert 'const Version = "0.0.0"' in constant, "the documented starting point moved"

    bump = run_cmd(
        ["uvx", "bump-my-version", "bump", "--current-version", "0.0.0",
         "--new-version", "0.1.0", "--no-commit", "--no-tag", "--allow-dirty"],
        go_synced_repo,
    )  # fmt: skip
    assert_ok(bump, "bump-my-version bump --current-version 0.0.0")
    assert 'const Version = "0.1.0"' in (
        go_synced_repo / "internal" / "version" / "version.go"
    ).read_text(encoding="utf-8")


# --- end-to-end: where a Rust crate's version lives ---------------------------
#
# Rust reaches the same tag-derived state as Go, by a route that hides it: the skeleton
# writes a `.bumpversion.toml` *with* `current_version`, and the first `/rhiza:update`
# replaces that file wholesale with `rust-core`'s, which has no such key. So the config a
# crate ends up releasing from is not the one /init left behind, and only a synced fixture
# shows it. /release documented the tag-derived case as Go's alone until these ran.


def test_e2e_a_synced_crate_has_a_discoverable_version_location(rust_synced_repo):
    """`rust-core`'s config is root-level, anchored to `[package]`, and owns no version.

    The Rust half of `test_e2e_a_synced_go_module_has_a_discoverable_version_location`:
    `bump-my-version` auto-discovers four filenames and `/rhiza:release` passes no
    `--config-file`, so a config anywhere else is silently ignored.
    """
    import _skeleton_version

    assert _skeleton_version.bumpversion_config(rust_synced_repo) == ".bumpversion.toml"

    body = (rust_synced_repo / ".bumpversion.toml").read_text(encoding="utf-8")
    assert 'filename = "Cargo.toml"' in body
    # Anchored to `[package]`, or the rewrite would also hit a dependency pinned at the
    # crate's own version — the reason the entry is `regex = true`.
    assert r"^\[package\]" in body, "the [package] anchor went missing from rust-core"
    # Same reasoning as go-core: a synced file must not pin a value the repo alone owns,
    # so `current_version` is deliberately absent and the version comes from the tag.
    assignments = [ln for ln in body.splitlines() if ln.strip().startswith("current_version")]
    assert assignments == [], f"rust-core now pins a version it cannot own: {assignments}"


def test_e2e_the_first_rust_release_needs_its_own_explicit_current_version(
    rust_synced_repo, tmp_path
):
    """A tagless crate needs `--current-version`, and Go's `0.0.0` is the wrong value.

    The failure `show` reports is identical to Go's, so `/release` step 1 handles both the
    same way — but the value it must settle on differs, and guessing costs a confusing
    second failure deep in step 6 rather than a clean stop. `cargo init` starts a crate at
    `0.1.0`, so `0.0.0` matches nothing in `Cargo.toml`.

    Works on a copy: the bump rewrites the manifest, and `rust_synced_repo` is
    session-scoped, so mutating it in place would leak into whatever runs next.
    """
    import shutil

    from conftest import assert_ok, run_cmd

    repo = tmp_path / "widget"
    shutil.copytree(rust_synced_repo, repo)

    assert run_cmd(["git", "tag", "--list"], repo).stdout.strip() == ""
    show = run_cmd(["uvx", "bump-my-version", "show", "current_version"], repo)
    assert show.returncode != 0, "a tagless crate cannot report a current version"

    manifest = repo / "Cargo.toml"
    assert 'version = "0.1.0"' in manifest.read_text(encoding="utf-8"), (
        "the documented starting point moved"
    )

    # Go's answer, applied to a crate: rejected, because it is not what Cargo.toml holds.
    wrong = run_cmd(
        ["uvx", "bump-my-version", "bump", "--current-version", "0.0.0",
         "--new-version", "0.2.0", "--no-commit", "--no-tag", "--allow-dirty"],
        repo,
    )  # fmt: skip
    assert wrong.returncode != 0, "0.0.0 bumped a crate that never held it"
    assert 'version = "0.1.0"' in manifest.read_text(encoding="utf-8"), (
        "the failed bump still wrote"
    )

    # The value step 1 reads out of the manifest.
    bump = run_cmd(
        ["uvx", "bump-my-version", "bump", "--current-version", "0.1.0",
         "--new-version", "0.2.0", "--no-commit", "--no-tag", "--allow-dirty"],
        repo,
    )  # fmt: skip
    assert_ok(bump, "bump-my-version bump --current-version 0.1.0")
    assert 'version = "0.2.0"' in manifest.read_text(encoding="utf-8")
