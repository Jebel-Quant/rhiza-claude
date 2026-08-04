"""Tests for template.yml parsing and validation (`scripts/_rhiza_template.py`).

The sync's input contract: which repository, at which ref, with which
profiles/bundles/includes. No git and no filesystem beyond reading that one file, so
every case here is expressible as a string.
"""

from __future__ import annotations

from pathlib import Path

import _rhiza_template as tmpl
import pytest
from _rhiza_common import SyncError


class TestTemplate:
    def test_load_reads_fields(self, tmp_path):
        tf = tmp_path / "template.yml"
        tf.write_text('repository: "o/r"\nref: v1\ninclude:\n  - Makefile\n')
        template = tmpl.load_template(tmp_path, tf)
        assert template.repository == "o/r"
        assert template.include == ["Makefile"]


def test_git_url_variants() -> None:
    assert tmpl.Template("o/r", "main").git_url == "https://github.com/o/r.git"
    assert tmpl.Template("o/r", "main", host="gitlab").git_url == "https://gitlab.com/o/r.git"
    assert tmpl.Template("/local/path", "main").git_url == "/local/path"
    assert tmpl.Template("https://x/y.git", "main").git_url == "https://x/y.git"


def test_git_url_unset_repository_raises() -> None:
    with pytest.raises(SyncError, match="not configured"):
        _ = tmpl.Template("", "main").git_url


def test_git_url_unsupported_host_raises() -> None:
    with pytest.raises(SyncError, match="Unsupported template-host"):
        _ = tmpl.Template("o/r", "main", host="bitbucket").git_url


def test_load_template_missing_file(tmp_path: Path) -> None:
    with pytest.raises(SyncError, match="No template.yml"):
        tmpl.load_template(tmp_path, tmp_path / "nope.yml")


def test_load_template_unreadable(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    tf = tmp_path / "template.yml"
    tf.write_text("x")
    monkeypatch.setattr(tmpl, "load_yaml", lambda _p: (_ for _ in ()).throw(ValueError("bad")))
    with pytest.raises(SyncError, match="Could not read"):
        tmpl.load_template(tmp_path, tf)


def test_load_template_missing_repository(tmp_path: Path) -> None:
    tf = tmp_path / "template.yml"
    tf.write_text("ref: main\ninclude:\n  - x\n")
    with pytest.raises(SyncError, match="template-repository is required"):
        tmpl.load_template(tmp_path, tf)


def test_load_template_no_sources(tmp_path: Path) -> None:
    tf = tmp_path / "template.yml"
    tf.write_text('repository: "o/r"\nref: main\n')
    with pytest.raises(SyncError, match="at least one of"):
        tmpl.load_template(tmp_path, tf)


# --- exclude normalisation and matching ---------------------------------------
#
# `exclude:` is declared in destination paths, so neither of these may consult the
# template clone. Resolving against the clone is what silently dropped every
# bundle-sourced entry: a destination path need not exist at the clone root.


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("docs/", "docs"),
        ("./docs", "docs"),
        ("./docs/", "docs"),
        ("  spaced.yaml  ", "spaced.yaml"),
        ("a\\b.txt", "a/b.txt"),
    ],
)
def test_normalise_excludes_tidies_an_entry(raw: str, expected: str) -> None:
    assert expected in tmpl.normalise_excludes([raw])


def test_normalise_excludes_drops_blanks_and_always_adds_the_pointer() -> None:
    """A blank entry would otherwise normalise to `""` and prefix-match every path."""
    assert tmpl.normalise_excludes(["", "   ", "./"]) == {".rhiza/template.yml"}


def test_normalise_excludes_does_not_touch_the_filesystem() -> None:
    """A destination path that exists nowhere is still honoured — the whole bug."""
    assert "no/such/file.yml" in tmpl.normalise_excludes(["no/such/file.yml"])


def test_is_excluded_matches_exactly() -> None:
    assert tmpl.is_excluded("a.txt", {"a.txt"})


def test_is_excluded_matches_under_an_excluded_directory() -> None:
    assert tmpl.is_excluded("docs/guide.md", {"docs"})


def test_is_excluded_rejects_an_unrelated_path() -> None:
    assert not tmpl.is_excluded("src/a.txt", {"docs", "b.txt"})


def test_is_excluded_does_not_match_a_sibling_sharing_a_prefix() -> None:
    """`docs` must not exclude `docsite/`, which a bare startswith would."""
    assert not tmpl.is_excluded("docsite/index.md", {"docs"})
