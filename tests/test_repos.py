"""Tests for the `rhiza list` port (`scripts/repos.py`)."""

from __future__ import annotations

import json
import urllib.error

import pytest
import repos


class _FakeResponse:
    """Minimal context-manager stand-in for `urllib.request.urlopen`."""

    def __init__(self, payload: dict):
        self._body = json.dumps(payload).encode()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self):
        return self._body


_ITEM = {
    "name": "cvxrisk",
    "full_name": "Jebel-Quant/cvxrisk",
    "description": "Risk models",
    "html_url": "https://github.com/Jebel-Quant/cvxrisk",
    "topics": ["rhiza", "python"],
    "language": "Python",
    "stargazers_count": 7,
    "archived": False,
    "updated_at": "2026-07-01T10:00:00Z",
    "pushed_at": "2026-07-02T10:00:00Z",
}


def test_repo_record_projects_and_defaults():
    rec = repos._repo_record({"name": "x"})
    assert rec == {
        "name": "x",
        "full_name": "",
        "description": "",
        "url": "",
        "topics": [],
        "language": "",
        "stars": 0,
        "archived": False,
        "updated_at": "",
        "pushed_at": "",
    }


def test_repo_record_full_item():
    rec = repos._repo_record(_ITEM)
    assert rec["full_name"] == "Jebel-Quant/cvxrisk"
    assert rec["url"] == "https://github.com/Jebel-Quant/cvxrisk"
    assert rec["stars"] == 7
    assert rec["topics"] == ["rhiza", "python"]


def test_build_document_sorts_and_counts():
    items = [
        {"full_name": "Jebel-Quant/zeta"},
        {"full_name": "Jebel-Quant/Alpha"},
    ]
    doc = repos.build_document("rhiza", items)
    assert doc["topic"] == "rhiza"
    assert doc["count"] == 2
    assert [r["full_name"] for r in doc["repositories"]] == [
        "Jebel-Quant/Alpha",
        "Jebel-Quant/zeta",
    ]


def test_build_document_empty():
    doc = repos.build_document("rhiza", [])
    assert doc == {"topic": "rhiza", "count": 0, "repositories": []}


def test_fetch_repos_uses_search_url_and_token(monkeypatch):
    captured: dict = {}

    def fake_urlopen(req, timeout):
        captured["url"] = req.full_url
        captured["headers"] = req.headers
        return _FakeResponse({"items": [_ITEM]})

    monkeypatch.setenv("GITHUB_TOKEN", "secret")
    monkeypatch.setattr(repos.urllib.request, "urlopen", fake_urlopen)

    items = repos._fetch_repos("rhiza-go", 25)
    assert items == [_ITEM]
    assert "q=topic:rhiza-go" in captured["url"]
    assert "per_page=25" in captured["url"]
    # urllib title-cases header keys.
    assert captured["headers"]["Authorization"] == "Bearer secret"


def test_fetch_repos_without_token(monkeypatch):
    captured: dict = {}

    def fake_urlopen(req, timeout):
        captured["headers"] = req.headers
        return _FakeResponse({"items": []})

    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.setattr(repos.urllib.request, "urlopen", fake_urlopen)

    assert repos._fetch_repos("rhiza", 50) == []
    assert "Authorization" not in captured["headers"]


def test_repos_emits_json_document(monkeypatch, capsys):
    monkeypatch.setattr(repos, "_fetch_repos", lambda topic, per_page: [_ITEM])
    rc = repos.repos("rhiza", 50)
    assert rc == 0
    doc = json.loads(capsys.readouterr().out)
    assert doc["topic"] == "rhiza"
    assert doc["count"] == 1
    assert doc["repositories"][0]["full_name"] == "Jebel-Quant/cvxrisk"


def test_repos_network_error_exits_one(monkeypatch, capsys):
    def boom(topic, per_page):
        raise urllib.error.URLError("no network")

    monkeypatch.setattr(repos, "_fetch_repos", boom)
    rc = repos.repos("rhiza", 50)
    assert rc == 1
    assert "Failed to fetch repositories" in capsys.readouterr().err


@pytest.mark.parametrize(
    ("requested", "expected"),
    [(0, 1), (-5, 1), (50, 50), (100, 100), (500, 100)],
)
def test_main_clamps_per_page(monkeypatch, requested, expected):
    seen: dict = {}

    def fake_repos(topic, per_page):
        seen["topic"] = topic
        seen["per_page"] = per_page
        return 0

    monkeypatch.setattr(repos, "repos", fake_repos)
    rc = repos.main(["--topic", "rhiza-rs", "--per-page", str(requested)])
    assert rc == 0
    assert seen == {"topic": "rhiza-rs", "per_page": expected}


def test_main_defaults(monkeypatch):
    seen: dict = {}
    monkeypatch.setattr(
        repos, "repos", lambda topic, per_page: seen.update(topic=topic, per_page=per_page) or 0
    )
    assert repos.main([]) == 0
    assert seen == {"topic": "rhiza", "per_page": 50}
