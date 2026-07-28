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
    (tmp_path / "f.txt").write_text("x\n")
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
