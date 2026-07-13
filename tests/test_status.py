"""Tests for the `rhiza status` port (`scripts/status.py`)."""

from __future__ import annotations

import json

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
