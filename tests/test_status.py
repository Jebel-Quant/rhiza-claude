"""Tests for the `rhiza status` port (`scripts/status.py`)."""

from __future__ import annotations

import json
from types import SimpleNamespace

import status


def _write_lock(repo, body: str):
    rhiza = repo / ".rhiza"
    rhiza.mkdir(parents=True, exist_ok=True)
    (rhiza / "template.lock").write_text(body)


def test_as_list_normalisation():
    assert status._as_list(None) == []
    assert status._as_list("solo") == ["solo"]
    assert status._as_list(["a", "b"]) == ["a", "b"]
    assert status._as_list([1, 2]) == ["1", "2"]


def test_status_dict_field_mapping():
    lock = {
        "host": "github",
        "repo": "owner/repo",
        "ref": "v1.0.0",
        "sha": "deadbeef",
        "synced_at": "2026-07-11T08:02:27Z",
        "strategy": "merge",
        "templates": ["legal"],
        "include": [],
        "files": ["a", "b"],
    }
    d = status._status_dict(lock)
    assert d["repository"] == "github/owner/repo"
    assert d["ref"] == "v1.0.0"
    assert d["templates"] == ["legal"]
    assert d["files"] == ["a", "b"]


def test_status_dict_defaults_when_lock_sparse():
    d = status._status_dict({"sha": "x"})
    assert d["ref"] == "main"  # documented default
    assert d["host"] == "github"
    assert d["repository"] == "github"  # no repo -> just the host
    assert d["templates"] == [] and d["include"] == [] and d["files"] == []


def test_status_missing_lock_is_not_an_error(tmp_path, capsys):
    rc = status.status(tmp_path)
    assert rc == 0
    assert "run `rhiza sync`" in capsys.readouterr().err


def test_status_human_output(tmp_path, capsys):
    _write_lock(
        tmp_path,
        "host: github\nrepo: owner/repo\nref: v1.0.0\n"
        "sha: 0123456789abcdef\nstrategy: merge\ntemplates:\n- legal\n",
    )
    rc = status.status(tmp_path)
    out = capsys.readouterr().out
    assert rc == 0
    assert "Repository : github/owner/repo" in out
    assert "SHA        : 0123456789ab" in out  # truncated to 12 chars
    assert "Templates  : legal" in out


def test_status_json_output(tmp_path, capsys):
    _write_lock(tmp_path, "host: github\nrepo: owner/repo\nref: v1.0.0\nsha: abc\n")
    rc = status.status(tmp_path, json_output=True)
    payload = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert payload["repository"] == "github/owner/repo"
    assert payload["sha"] == "abc"


def test_status_include_shown_when_no_templates(tmp_path, capsys):
    _write_lock(tmp_path, "host: github\nrepo: o/r\ninclude:\n- .github\n- .gitignore\n")
    status.status(tmp_path)
    assert "Include    : .github, .gitignore" in capsys.readouterr().out


def test_status_human_readable_templates(tmp_path, capsys):
    _write_lock(
        tmp_path,
        "host: github\nrepo: a/b\nref: main\nsha: abcdef1234567890\n"
        "synced_at: 2026-07-01\nstrategy: merge\ntemplates:\n  - legal\n",
    )
    rc = status.status(tmp_path, json_output=False)
    out = capsys.readouterr().out
    assert rc == 0
    assert "Repository : github/a/b" in out
    assert "SHA        : abcdef123456" in out
    assert "Templates  : legal" in out


def test_status_human_readable_include_and_unknown_sha(tmp_path, capsys):
    _write_lock(tmp_path, "repo: a/b\ninclude:\n  - .github\n")  # no sha → (unknown)
    status.status(tmp_path, json_output=False)
    out = capsys.readouterr().out
    assert "SHA        : (unknown)" in out
    assert "Include    : .github" in out


def test_status_unreadable_write_lock(tmp_path, monkeypatch, capsys):
    _write_lock(tmp_path, "x: 1\n")
    monkeypatch.setattr(status, "load_yaml", lambda p: (_ for _ in ()).throw(ValueError("bad")))
    rc = status.status(tmp_path)
    assert rc == 1
    assert "Could not read" in capsys.readouterr().err


def test_status_main(tmp_path):
    _write_lock(tmp_path, "repo: a/b\nref: main\n")
    assert status.main([str(tmp_path), "--json"]) == 0


# ---------------------------------------------------------------------------
# File-tree view (folded in from the retired `/tree` command)
# ---------------------------------------------------------------------------


def test_build_tree_nests_paths():
    built = status._build_tree(["a/b/c.txt", "a/d.txt", "top.txt"])
    assert built == {"a": {"b": {"c.txt": {}}, "d.txt": {}}, "top.txt": {}}


def test_render_connectors():
    lines = status._render(status._build_tree(["a/b.txt", "a/c.txt", "d.txt"]))
    assert lines == [
        "├── a",
        "│   ├── b.txt",
        "│   └── c.txt",
        "└── d.txt",
    ]


def test_status_files_output_and_count(tmp_path, capsys):
    _write_lock(tmp_path, "repo: o/r\nfiles:\n- .github/ci.yml\n- LICENSE\n")
    rc = status.status(tmp_path, show_files=True)
    out = capsys.readouterr().out
    assert rc == 0
    assert "Repository : github/o/r" in out  # summary still shown
    assert "Files managed by Rhiza:" in out
    assert "├── .github" in out
    assert "│   └── ci.yml" in out
    assert "└── LICENSE" in out
    assert "2 files managed by Rhiza" in out


def test_status_files_singular_count(tmp_path, capsys):
    _write_lock(tmp_path, "repo: o/r\nfiles:\n- solo.txt\n")
    status.status(tmp_path, show_files=True)
    assert "1 file managed by Rhiza" in capsys.readouterr().out


def test_status_files_empty_is_not_an_error(tmp_path, capsys):
    _write_lock(tmp_path, "repo: o/r\nfiles: []\n")
    rc = status.status(tmp_path, show_files=True)
    assert rc == 0
    assert "No files are tracked" in capsys.readouterr().err


def test_status_main_files_flag(tmp_path):
    _write_lock(tmp_path, "repo: a/b\nfiles:\n- a.txt\n")
    assert status.main([str(tmp_path), "--files"]) == 0


# ---------------------------------------------------------------------------
# Outdated check (--check): compare the pinned ref to the latest release
# ---------------------------------------------------------------------------


def test_parse_semver():
    assert status._parse_semver("v1.2.3") == (1, 2, 3)
    assert status._parse_semver("1.2.3") == (1, 2, 3)
    assert status._parse_semver("main") is None
    assert status._parse_semver("v1.2") is None


def test_remote_url_host_selection():
    assert status._remote_url("github", "o/r") == "https://github.com/o/r"
    assert status._remote_url("gitlab-project", "o/r") == "https://gitlab.com/o/r"


def test_remote_tags_parses_and_dedupes(monkeypatch):
    stdout = (
        "sha1\trefs/tags/v0.1.0\n"
        "sha2\trefs/tags/v0.2.0\n"
        "sha2\trefs/tags/v0.2.0^{}\n"  # annotated-tag peel — deduped
        "sha3\trefs/heads/main\n"  # not a tag — skipped
    )
    monkeypatch.setattr(status.subprocess, "run", lambda *a, **k: SimpleNamespace(stdout=stdout))
    assert status._remote_tags("github", "o/r") == ["v0.1.0", "v0.2.0"]


def test_remote_tags_failure_returns_empty(monkeypatch):
    def boom(*a, **k):
        raise OSError("git not found")

    monkeypatch.setattr(status.subprocess, "run", boom)
    assert status._remote_tags("github", "o/r") == []


def test_outdated_message_no_releases():
    assert "could not determine" in status._outdated_message("v1.0.0", ["not-a-version"])


def test_outdated_message_ref_not_a_tag():
    msg = status._outdated_message("main", ["v1.0.0", "v1.1.0"])
    assert "latest release is v1.1.0" in msg
    assert "not a release tag" in msg


def test_outdated_message_up_to_date():
    assert "up to date" in status._outdated_message("v1.1.0", ["v1.0.0", "v1.1.0"])


def test_outdated_message_behind_singular():
    msg = status._outdated_message("v1.0.0", ["v1.0.0", "v1.1.0"])
    assert "v1.0.0 → v1.1.0" in msg
    assert "1 release behind" in msg


def test_outdated_message_behind_plural():
    msg = status._outdated_message("v1.0.0", ["v1.0.0", "v1.1.0", "v2.0.0"])
    assert "2 releases behind" in msg


def test_print_outdated_no_repo(capsys):
    status._print_outdated({"repo": "", "host": "github", "ref": "main"})
    assert "no template repository recorded" in capsys.readouterr().out


def test_status_check_line(tmp_path, monkeypatch, capsys):
    _write_lock(tmp_path, "host: github\nrepo: o/r\nref: v1.0.0\n")
    monkeypatch.setattr(status, "_remote_tags", lambda host, repo: ["v1.0.0", "v1.1.0"])
    rc = status.status(tmp_path, check=True)
    out = capsys.readouterr().out
    assert rc == 0
    assert "1 release behind" in out


def test_status_main_check_flag(tmp_path, monkeypatch):
    _write_lock(tmp_path, "host: github\nrepo: o/r\nref: v1.0.0\n")
    monkeypatch.setattr(status, "_remote_tags", lambda host, repo: [])
    assert status.main([str(tmp_path), "--check"]) == 0
