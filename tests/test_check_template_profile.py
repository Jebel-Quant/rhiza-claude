"""Tests for the profile preflight (`scripts/check_template_profile.py`).

Two halves, and both matter:

* **Unit** — the summary and exit codes, against a fake clone. The three outcomes are
  deliberately distinct (defined / missing / unreadable) because the fixes have
  different owners, and only a test can keep them from collapsing into "failed".
* **End-to-end** — the real `jebel-quant/rhiza`, at the ref the rest of the suite pins.
  This is the assertion that would have caught both historical bugs: a pointer naming
  `rust-github-project`, and one naming `rust-local` against a release that defines
  neither. Neither was catchable without reading the template.
"""

from __future__ import annotations

import json
import subprocess

import check_template_profile as ctp
import pytest
from conftest import TEMPLATE_REF, TEMPLATE_REPO

BUNDLES = """\
bundles:
  core:
    required: true
  rust-core:
    requires: [core]
profiles:
  local:
    bundles:
      - core
  rust-local:
    bundles:
      - core
      - rust-core
"""


@pytest.fixture
def fake_template(monkeypatch: pytest.MonkeyPatch) -> None:
    """Patch the clone seam so `available_profiles` reads a local bundles file."""

    def _clone(ctx, url, dest, include_paths, *, branch=None, sha=None):  # noqa: ANN001, ANN202
        path = dest / include_paths[0]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(BUNDLES)

    monkeypatch.setattr(ctp, "clone", _clone)
    monkeypatch.setattr(ctp.GitContext, "default", classmethod(lambda cls: cls(executable="git")))


@pytest.fixture
def unreadable_template(monkeypatch: pytest.MonkeyPatch) -> None:
    """Patch the clone seam to fail the way an unknown ref does."""

    def _clone(ctx, url, dest, include_paths, *, branch=None, sha=None):  # noqa: ANN001, ANN202
        raise subprocess.CalledProcessError(
            128, ["git", "clone"], stderr=b"warning: noise\nfatal: Remote branch nope not found\n"
        )

    monkeypatch.setattr(ctp, "clone", _clone)
    monkeypatch.setattr(ctp.GitContext, "default", classmethod(lambda cls: cls(executable="git")))


# --- available_profiles -------------------------------------------------------


def test_available_profiles_lists_what_the_template_defines(fake_template: None):
    assert ctp.available_profiles("o/r", "v1") == ["local", "rust-local"]


def test_a_bundles_file_the_clone_did_not_deliver_is_unreadable(monkeypatch: pytest.MonkeyPatch):
    """An empty cone means the path is wrong or the repo is not a rhiza template."""
    monkeypatch.setattr(ctp, "clone", lambda *a, **k: None)
    monkeypatch.setattr(ctp.GitContext, "default", classmethod(lambda cls: cls(executable="git")))
    with pytest.raises(ctp.SyncError, match="has no .rhiza/template-bundles.yml"):
        ctp.available_profiles("o/r", "v1")


def test_a_custom_bundles_path_is_honoured(monkeypatch: pytest.MonkeyPatch):
    seen: list[list[str]] = []

    def _clone(ctx, url, dest, include_paths, *, branch=None, sha=None):  # noqa: ANN001, ANN202
        seen.append(include_paths)
        path = dest / include_paths[0]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(BUNDLES)

    monkeypatch.setattr(ctp, "clone", _clone)
    monkeypatch.setattr(ctp.GitContext, "default", classmethod(lambda cls: cls(executable="git")))
    assert ctp.available_profiles("o/r", "v1", bundles_path="custom/b.yml") == [
        "local",
        "rust-local",
    ]
    assert seen == [["custom/b.yml"]]


def test_a_failed_clone_becomes_a_sync_error_carrying_gits_own_words(
    unreadable_template: None,
):
    """Not the argv: git's explanation is on stderr, and it is the actionable part."""
    with pytest.raises(ctp.SyncError, match="Remote branch nope not found"):
        ctp.available_profiles("o/r", "nope")


def test_reason_falls_back_to_the_exception_text():
    assert ctp._reason(ValueError("plain")) == "plain"


def test_reason_reads_a_text_stderr_too():
    exc = subprocess.CalledProcessError(1, ["git"], stderr="fatal: nope\n")
    assert ctp._reason(exc) == "fatal: nope"


def test_reason_ignores_an_empty_stderr():
    exc = subprocess.CalledProcessError(1, ["git"], stderr=b"   \n")
    assert "git" in ctp._reason(exc)


# --- check: the three outcomes ------------------------------------------------


def test_a_defined_profile_exits_zero(fake_template: None):
    summary = ctp.check("o/r", "v1", ["rust-local"])
    assert summary["exit_code"] == ctp.EXIT_OK
    assert summary["defined"] == ["rust-local"]
    assert summary["missing"] == []


def test_a_missing_profile_exits_one_and_names_the_alternatives(fake_template: None):
    """Exactly the /init failure: the pointer would die at the first /update."""
    summary = ctp.check("o/r", "v1", ["rust-local", "rust-github-project"])
    assert summary["exit_code"] == ctp.EXIT_MISSING
    assert summary["missing"] == ["rust-github-project"]
    assert summary["available"] == ["local", "rust-local"]


def test_an_unreadable_template_exits_two_not_one(unreadable_template: None):
    """A network problem is not a wrong profile — different owner, different fix."""
    summary = ctp.check("o/r", "nope", ["rust-local"])
    assert summary["exit_code"] == ctp.EXIT_UNREADABLE
    assert summary["missing"] == []
    assert "Remote branch nope not found" in summary["error"]


# --- main ---------------------------------------------------------------------


def test_main_reports_a_defined_profile_on_stdout(fake_template: None, capsys):
    rc = ctp.main(["rust-local", "--template-repo", "o/r", "--ref", "v1"])
    assert rc == 0
    out = capsys.readouterr()
    assert "defined" in out.out
    assert out.err == ""


def test_main_reports_a_missing_profile_on_stderr(fake_template: None, capsys):
    rc = ctp.main(["nope", "--template-repo", "o/r", "--ref", "v1"])
    assert rc == 1
    err = capsys.readouterr().err
    assert "MISSING" in err
    assert "available profiles: local, rust-local" in err
    assert "first /rhiza:update" in err


def test_main_reports_an_unreadable_template_as_warn_and_continue(
    unreadable_template: None, capsys
):
    rc = ctp.main(["rust-local", "--template-repo", "o/r", "--ref", "nope"])
    assert rc == 2
    assert "warn and continue" in capsys.readouterr().err


def test_main_json_output(fake_template: None, capsys):
    rc = ctp.main(["rust-local", "--template-repo", "o/r", "--ref", "v1", "--json"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["available"] == ["local", "rust-local"]
    assert payload["error"] is None


def test_main_passes_the_host_through(fake_template: None, capsys):
    rc = ctp.main(
        ["local", "--template-repo", "o/r", "--ref", "v1", "--template-host", "gitlab", "--json"]
    )
    assert rc == 0
    assert json.loads(capsys.readouterr().out)["host"] == "gitlab"


def test_main_passes_the_bundles_path_through(monkeypatch: pytest.MonkeyPatch, capsys):
    seen: list[list[str]] = []

    def _clone(ctx, url, dest, include_paths, *, branch=None, sha=None):  # noqa: ANN001, ANN202
        seen.append(include_paths)
        path = dest / include_paths[0]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(BUNDLES)

    monkeypatch.setattr(ctp, "clone", _clone)
    monkeypatch.setattr(ctp.GitContext, "default", classmethod(lambda cls: cls(executable="git")))
    rc = ctp.main(["local", "--template-repo", "o/r", "--ref", "v1", "--bundles-path", "b.yml"])
    assert rc == 0
    assert seen == [["b.yml"]]


def test_an_empty_profile_list_in_a_template_is_reported_as_none(
    monkeypatch: pytest.MonkeyPatch, capsys
):
    """A bundles file with no profiles at all still yields a usable message."""

    def _clone(ctx, url, dest, include_paths, *, branch=None, sha=None):  # noqa: ANN001, ANN202
        path = dest / include_paths[0]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("bundles:\n  core:\n    required: true\n")

    monkeypatch.setattr(ctp, "clone", _clone)
    monkeypatch.setattr(ctp.GitContext, "default", classmethod(lambda cls: cls(executable="git")))
    rc = ctp.main(["local", "--template-repo", "o/r", "--ref", "v1"])
    assert rc == 1
    assert "available profiles: none" in capsys.readouterr().err


# --- end-to-end: the real template --------------------------------------------
#
# These read the actual template. They are the check that /init's pointer is
# satisfiable, which is the one thing no amount of local fixture work can establish.


def test_e2e_the_template_defines_every_profile_init_writes_for_python():
    """The profiles `/init` writes for Python exist at the ref the suite pins.

    Nothing else in the suite would notice an upstream rename of `github-project`
    until a user's first /update failed.
    """
    import init_scaffold

    profiles = sorted(
        {init_scaffold.profile_for_host(host, "python") for host in ("github", "gitlab")}
    )
    summary = ctp.check(TEMPLATE_REPO, TEMPLATE_REF, profiles)
    assert summary["exit_code"] == ctp.EXIT_OK, summary


def test_e2e_the_template_defines_the_profile_a_rust_pointer_names():
    """Rust's profile exists at the pinned ref, since v1.3.0 shipped it.

    Was written as "either defined or reported missing" while `rust-local` lived only on
    the template's default branch. It is a release fact now, so this asserts it: every
    Rust pointer `/init` writes names this profile, and a ref that does not define it
    cannot serve a Rust repo.
    """
    import init_scaffold

    profile = init_scaffold.profile_for_host("github", "rust")
    summary = ctp.check(TEMPLATE_REPO, TEMPLATE_REF, [profile])
    assert summary["exit_code"] == ctp.EXIT_OK, summary


def test_e2e_a_profile_no_template_defines_is_caught():
    """The historical bug, replayed: `rust-github-project` has never existed."""
    summary = ctp.check(TEMPLATE_REPO, TEMPLATE_REF, ["rust-github-project"])
    assert summary["exit_code"] == ctp.EXIT_MISSING, summary
