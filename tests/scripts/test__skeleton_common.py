"""Tests for the cross-language skeleton helpers (`scripts/_skeleton_common.py`).

The README stub is the load-bearing one: `/rhiza:docs` owns the real README, so finding
its work overwritten would be the worst bug this module could have.
"""

from __future__ import annotations

import subprocess as sp

import _skeleton_common as common
import pytest

# --- host_domain / host_url ---------------------------------------------------


@pytest.mark.parametrize(
    ("host", "expected"),
    [("github", "github.com"), ("gitlab", "gitlab.com"), ("nonsense", "github.com")],
)
def test_host_domain_falls_back_to_github(host, expected):
    assert common.host_domain(host) == expected


def test_host_url_builds_the_canonical_project_url():
    assert common.host_url("gitlab.com", "grp", "proj") == "https://gitlab.com/grp/proj"


# --- seed_readme --------------------------------------------------------------


def test_seed_readme_fills_the_empty_file_uv_leaves(tmp_path):
    """`uv init --lib` writes README.md with zero bytes; the template rejects that."""
    (tmp_path / "README.md").write_text("")

    assert common.seed_readme(tmp_path, repo="widget", description="A widget.") is True

    body = (tmp_path / "README.md").read_text()
    assert body.startswith("# widget\n")
    assert "A widget." in body


def test_seed_readme_never_overwrites_a_real_readme(tmp_path):
    """/rhiza:docs owns the README; finding its work replaced would be the worst bug."""
    (tmp_path / "README.md").write_text("# Hand-written\n\nCarefully worded.\n")

    assert common.seed_readme(tmp_path, repo="widget", description="A widget.") is False
    assert (tmp_path / "README.md").read_text() == "# Hand-written\n\nCarefully worded.\n"


def test_seed_readme_treats_whitespace_only_as_empty(tmp_path):
    (tmp_path / "README.md").write_text("\n\n   \n")
    assert common.seed_readme(tmp_path, repo="widget", description=None) is True
    assert (tmp_path / "README.md").read_text().startswith("# widget\n")


def test_seed_readme_does_not_create_an_absent_readme(tmp_path):
    """Absence is a different finding, which the template reports on its own."""
    assert common.seed_readme(tmp_path, repo="widget", description=None) is False
    assert not (tmp_path / "README.md").exists()


def test_seed_readme_creates_one_when_asked(tmp_path):
    """`cargo init` and `go mod init` write no README at all — absence is the norm."""
    assert common.seed_readme(tmp_path, repo="widget", description=None, create=True) is True
    assert (tmp_path / "README.md").read_text().startswith("# widget\n")


def test_seed_readme_writes_no_code_blocks(tmp_path):
    """The same template test *executes* fenced blocks it finds in the README."""
    (tmp_path / "README.md").write_text("")
    common.seed_readme(tmp_path, repo="widget", description="A widget.")
    assert "```" not in (tmp_path / "README.md").read_text()


# --- git_identity -------------------------------------------------------------


def test_git_identity_reads_the_repo_config(tmp_path):
    sp.run(["git", "init", "-q", "-b", "main", "."], cwd=tmp_path, check=True)
    sp.run(["git", "config", "user.name", "Grace"], cwd=tmp_path, check=True)
    sp.run(["git", "config", "user.email", "grace@example.com"], cwd=tmp_path, check=True)
    assert common.git_identity(tmp_path) == ("Grace", "grace@example.com")


# --- author_entry -------------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "email", "expected"),
    [
        ("Ada", "ada@example.com", "Ada <ada@example.com>"),
        ("Ada", None, "Ada"),
        # No git identity at all is the CI case; the gate still needs a named author.
        (None, None, "acme"),
        (None, "ada@example.com", "acme <ada@example.com>"),
    ],
)
def test_author_entry_falls_back_to_the_owner(name, email, expected):
    assert common.author_entry("acme", name, email) == expected
