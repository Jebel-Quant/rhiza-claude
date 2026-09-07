"""Tests for the changelog parser (`scripts/_rhiza_changelog.py`).

The parser has two readers that must not disagree: `check_version_bump.py` reads the
local file to decide the release phase, and `wait_for_merge.py` reads the same file on
the remote default branch to decide whether the bump has landed. A pattern that accepts
`## [v1.7.0]` in one and not the other would leave the wait polling for a release the
phase check can already see, so the cases below are the *shared* contract rather than
either caller's.
"""

from __future__ import annotations

import _rhiza_changelog as changelog
import pytest

_CHANGELOG = "# Changelog\n\n## [1.7.0] - 2026-09-07\n\n- a change\n\n## [1.6.0]\n"


def test_the_first_version_shaped_heading_wins():
    """git-cliff prepends, so the newest release is the first version-shaped heading."""
    assert changelog.newest_changelog_version(_CHANGELOG) == "1.7.0"


def test_an_unreleased_heading_is_skipped():
    """`## [Unreleased]` is not version-shaped and must not hide the section below it."""
    assert changelog.newest_changelog_version("## [Unreleased]\n\n## [1.6.0]\n") == "1.6.0"


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("## [1.4.0] - 2026-01-01\n", "1.4.0"),
        ("## 1.4.0 - 2026-01-01\n", "1.4.0"),
        ("## [v1.4.0] - 2026-01-01\n", "1.4.0"),
        ("## v1.4.0\n", "1.4.0"),
        ("# [1.4.0]\n", "1.4.0"),
        ("### [1.4.0]\n", "1.4.0"),
        ("## [2.0.0-rc.1]\n", "2.0.0-rc.1"),
    ],
)
def test_the_spellings_a_changelog_actually_uses_all_parse(text, expected):
    """Level, brackets and the `v` are cliff.toml decisions; the digits are not."""
    assert changelog.newest_changelog_version(text) == expected


@pytest.mark.parametrize(
    "text", ["", "no headings at all\n", "## not a version\n", "## [Unreleased]\n"]
)
def test_no_version_heading_is_no_evidence(text):
    """Absence answers None — the callers turn that into a verdict, not this."""
    assert changelog.newest_changelog_version(text) is None


def test_read_changelog_version_reads_the_file(tmp_path):
    """The path form `check_version_bump.py`'s CLI passes.

    Args:
        tmp_path: A directory to write the changelog into.
    """
    (tmp_path / "CHANGELOG.md").write_text(_CHANGELOG, encoding="utf-8")
    assert changelog.read_changelog_version(tmp_path / "CHANGELOG.md") == "1.7.0"


def test_read_changelog_version_tolerates_a_missing_file(tmp_path):
    """A repo need not keep a changelog, so absence is not an error.

    Args:
        tmp_path: A directory with no changelog in it.
    """
    assert changelog.read_changelog_version(tmp_path / "nope.md") is None
