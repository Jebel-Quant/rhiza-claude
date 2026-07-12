"""Tests for the stats dashboard (`scripts/stats.py`).

Everything in stats.py routes external data through `out()` / `ls_files()` /
`have()`, so the strategy is: (1) a broad "everything absent" pass that drives
every `n/a` fallback branch across all sections, and (2) targeted success-path
tests that feed canned command output for the GitHub / GitLab / scc / radon /
rhiza-status branches. Pure helpers and the renderers are tested directly.
"""

from __future__ import annotations

import json

import pytest
import stats


def make_out(mapping: dict[str, str | None]):
    """Return a fake `out(cmd)` that matches the longest substring key in the command."""
    keys = sorted(mapping, key=len, reverse=True)

    def _out(cmd, timeout=60):
        joined = " ".join(cmd)
        for k in keys:
            if k in joined:
                return mapping[k]
        return None

    return _out


# --------------------------------------------------------------------------- #
# pure helpers
# --------------------------------------------------------------------------- #
def test_na_and_fmt():
    assert stats.na("boom") == "n/a (boom)"
    assert stats.fmt(None) == "—"
    assert stats.fmt(42) == "42"


def test_count_lines(tmp_path):
    f = tmp_path / "f.txt"
    f.write_text("a\nb\nc\n")
    assert stats.count_lines(f) == 3
    assert stats.count_lines(tmp_path / "missing.txt") == 0  # OSError → 0


@pytest.mark.parametrize(
    ("url", "platform", "path"),
    [
        ("git@github.com:acme/tool.git", "GitHub", "acme/tool"),
        ("https://github.com/acme/tool", "GitHub", "acme/tool"),
        ("https://gitlab.com/grp/proj.git", "GitLab", "grp/proj"),
        ("https://x@gitlab.example.com/g/p", "GitLab", "g/p"),
        ("https://example.org/a/b", "example.org", "a/b"),
    ],
)
def test_parse_remote(url, platform, path):
    assert stats.parse_remote(url) == (platform, path)


def test_read_toml(tmp_path):
    good = tmp_path / "ok.toml"
    good.write_text('[project]\nname = "x"\n')
    assert stats.read_toml(good)["project"]["name"] == "x"
    assert stats.read_toml(tmp_path / "missing.toml") is None
    bad = tmp_path / "bad.toml"
    bad.write_text("not = = valid")
    assert stats.read_toml(bad) is None


def test_detect_license(tmp_path):
    assert stats.detect_license(tmp_path, {"project": {"license": "MIT"}}) == "MIT"
    assert (
        stats.detect_license(tmp_path, {"project": {"license": {"text": "Apache-2.0"}}})
        == "Apache-2.0"
    )
    (tmp_path / "LICENSE").write_text("MIT License\n\nCopyright…")
    assert stats.detect_license(tmp_path, None) == "MIT License"
    assert stats.detect_license(tmp_path / "empty", None).startswith("n/a")


def test_section_row_and_table():
    s = stats.Section("T")
    s.row("k", 1)
    s.table("cap", ["h"], [[1], [2]])
    assert s.rows == [("k", 1)]
    assert s.tables[0]["caption"] == "cap" and len(s.tables[0]["rows"]) == 2


def test_language_split_scc(monkeypatch):
    monkeypatch.setattr(stats, "have", lambda b: b == "scc")
    payload = json.dumps([{"Code": 100, "Comment": 20, "Blank": 5}])
    monkeypatch.setattr(stats, "out", make_out({"scc --format json": payload}))
    split = stats.language_split(None)
    assert split == {"tool": "scc", "code": 100, "comment": 20, "blank": 5}


def test_language_split_tokei(monkeypatch):
    monkeypatch.setattr(stats, "have", lambda b: b == "tokei")
    payload = json.dumps({"Total": {"code": 7, "comments": 3, "blanks": 1}})
    monkeypatch.setattr(stats, "out", make_out({"tokei --output json": payload}))
    assert stats.language_split(None)["tool"] == "tokei"


def test_language_split_none(monkeypatch):
    monkeypatch.setattr(stats, "have", lambda b: False)
    assert stats.language_split(None) is None


# --------------------------------------------------------------------------- #
# every section, everything absent → exercises the n/a fallback branches
# --------------------------------------------------------------------------- #
def test_all_sections_when_everything_absent(tmp_path, monkeypatch):
    monkeypatch.setattr(stats, "out", lambda cmd, timeout=60: None)
    monkeypatch.setattr(stats, "have", lambda b: False)
    monkeypatch.setattr(stats, "tool", lambda name: None)

    id_sec, ctx = stats.section_identity(tmp_path, None)
    code_sec, code_ctx = stats.section_code_size(tmp_path, None)
    tests_sec = stats.section_tests(tmp_path)
    cx_sec = stats.section_complexity()
    deps_sec = stats.section_deps(tmp_path)
    git_sec, gc = stats.section_git(ctx)
    rhiza_sec, rc = stats.section_rhiza(tmp_path)

    for sec in (id_sec, code_sec, tests_sec, cx_sec, deps_sec, git_sec, rhiza_sec):
        assert isinstance(sec, stats.Section)
        assert sec.rows  # each produced at least one row
    assert ctx["platform"] is None
    assert code_ctx["total_loc"] == 0
    # rhiza section short-circuits when template.yml is absent
    assert any("not a rhiza-managed repo" in str(v) for _, v in rhiza_sec.rows)


# --------------------------------------------------------------------------- #
# success paths
# --------------------------------------------------------------------------- #
def test_section_identity_github(tmp_path, monkeypatch):
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "tool"\nversion = "1.0.0"\nrequires-python = ">=3.11"\nlicense = "MIT"\n'
    )
    gh_json = json.dumps({"stargazerCount": 5, "forkCount": 2, "isArchived": False})
    monkeypatch.setattr(
        stats,
        "out",
        make_out(
            {
                "branch --show-current": "main",
                "defaultBranchRef": "main",
                "remote get-url origin": "git@github.com:acme/tool.git",
                "stargazerCount,forkCount": gh_json,
                "subscribers_count": "9",
                "git ls-files | xargs du": "1.2M",
                "du -sh": "3.4M\t.git",
            }
        ),
    )
    s, ctx = stats.section_identity(tmp_path, None)
    assert ctx["platform"] == "GitHub" and ctx["slug"] == "acme/tool"
    assert ctx["stars"] == 5
    rows = dict(s.rows)
    assert rows["Stars"] == 5
    assert "tool" in rows["Project"]


def test_section_code_size_python(tmp_path, monkeypatch):
    (tmp_path / "src" / "pkg").mkdir(parents=True)
    (tmp_path / "src" / "pkg" / "m.py").write_text("class A:\n    def f(self):\n        return 1\n")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_m.py").write_text("def test_f():\n    assert True\n")
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "i.md").write_text("# hi\n")
    (tmp_path / "README.md").write_text("readme\n")

    files = {
        None: ["src/pkg/m.py", "tests/test_m.py", "docs/i.md", "README.md"],
        "src": ["src/pkg/m.py"],
        "tests": ["tests/test_m.py"],
        "docs": ["docs/i.md"],
    }
    monkeypatch.setattr(stats, "ls_files", lambda ps=None: files.get(ps, []))
    monkeypatch.setattr(stats, "have", lambda b: False)  # no scc/tokei
    monkeypatch.setattr(stats, "out", make_out({"git grep": "src/pkg/m.py:1:# TODO x"}))

    s, ctx = stats.section_code_size(tmp_path, None)
    assert ctx["src_loc"] > 0 and ctx["test_loc"] > 0
    assert ctx["ratio"] is not None
    rows = dict(s.rows)
    assert "1 modules, 1 classes, 1 functions" in rows["Definitions (src)"]
    assert rows["TODO/FIXME markers"] == 1


def test_section_tests_with_coverage(tmp_path, monkeypatch):
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_a.py").write_text(
        "def test_one():\n    pass\ndef test_two():\n    pass\n"
    )
    (tmp_path / "coverage.xml").write_text('<coverage line-rate="0.83"></coverage>')
    (tmp_path / "pyproject.toml").write_text("[tool.coverage.report]\nfail_under = 80\n")
    monkeypatch.setattr(
        stats, "ls_files", lambda ps=None: ["tests/test_a.py"] if ps == "tests" else []
    )
    monkeypatch.setattr(stats, "tool", lambda name: None)
    s = stats.section_tests(tmp_path)
    rows = dict(s.rows)
    assert "2 test functions" in rows["Tests"]
    assert rows["Coverage threshold"] == 80
    assert rows["Coverage (cached)"] == "83.0%"


def test_section_complexity_radon(tmp_path, monkeypatch):
    monkeypatch.setattr(stats, "ls_files", lambda ps=None: ["src/m.py"] if ps == "src" else [])
    monkeypatch.setattr(stats, "tool", lambda name: ["radon"] if name == "radon" else None)
    cc = "src/m.py\n    F 1:0 foo - C (12)\nAverage complexity: B (5.5)\n"
    mi = "src/m.py - B (55.0)\n"
    monkeypatch.setattr(stats, "out", make_out({"radon cc": cc, "radon mi": mi}))
    s = stats.section_complexity()
    rows = dict(s.rows)
    assert rows["Avg cyclomatic complexity"] == "B (5.5)"
    assert rows["Blocks rated C or worse"] == 1
    assert rows["Modules below MI rank A"] == 1


def test_section_deps_python(tmp_path, monkeypatch):
    (tmp_path / "pyproject.toml").write_text(
        "[project]\n"
        'requires-python = ">=3.11"\n'
        'dependencies = ["requests", "click"]\n'
        "[project.optional-dependencies]\n"
        'dev = ["pytest"]\n'
        "[dependency-groups]\n"
        'lint = ["ruff", "mypy"]\n'
    )
    (tmp_path / "uv.lock").write_text("[[package]]\nname='a'\n[[package]]\nname='b'\n")
    s = stats.section_deps(tmp_path)
    rows = dict(s.rows)
    assert rows["Runtime deps"] == 2
    assert rows["Optional/dev deps"] == 3
    assert rows["Locked packages"] == 2


def test_section_git_github(monkeypatch):
    ctx = {"platform": "GitHub", "slug": "acme/tool", "default_branch": "main"}
    rel = json.dumps([{"tagName": "v1.2.0", "publishedAt": "2026-06-01T00:00:00Z"}])
    mapping = {
        "rev-list --count HEAD": "150",
        "--since=30 days ago": "4",
        "--since=90 days ago": "20",
        "origin/main..HEAD": "0",
        "shortlog -sn": "   100\tAlice\n    50\tBob",
        "log --format=%as": "2026-07-01\n2026-01-01",
        "git tag": "v1.0.0\nv1.2.0",
        "release list": rel,
        "pr list": "3",
        "run list": "success",
        "open_issues_count": "12",
        "branch -r | grep": "5",
        "log --since=90.days": "  30 src/m.py\n  10 README.md",
    }
    monkeypatch.setattr(stats, "out", make_out(mapping))
    s, gc = stats.section_git(ctx)
    rows = dict(s.rows)
    assert gc["commits"] == "150"
    assert gc["contributors"] == 2
    assert rows["Tags"] == 2
    assert "v1.2.0" in rows["Latest release"]
    assert gc["open_prs"] == "3"
    # open_issues = open_issues_count - PRs = 12 - 3 = 9
    assert gc["open_issues"] == 9


def test_section_git_gitlab(monkeypatch):
    ctx = {"platform": "GitLab", "slug": "grp/proj", "default_branch": "main"}
    mapping = {
        "rev-list --count HEAD": "10",
        "mr list": "mr1\nmr2",
        "open_issues_count": "7",
        "branch -r | grep": "2",
    }
    monkeypatch.setattr(stats, "out", make_out(mapping))
    s, gc = stats.section_git(ctx)
    rows = dict(s.rows)
    assert rows["Open MRs"] == 2
    assert gc["open_issues"] == "7"


def test_section_rhiza_with_status_json(tmp_path, monkeypatch):
    rhiza = tmp_path / ".rhiza"
    rhiza.mkdir()
    (rhiza / "template.yml").write_text(
        'repository: "jebel-quant/rhiza"\nref: "v1.1.3"\nprofiles:\n  - github-project\n'
    )
    (rhiza / ".rhiza-version").write_text("0.18.0\n")
    status = json.dumps(
        {
            "ref": "v1.1.3",
            "sha": "abcdef1234567890",
            "synced_at": "2026-07-01",
            "strategy": "merge",
            "templates": ["legal"],
            "include": [],
            "files": ["a", "b", "c"],
        }
    )
    monkeypatch.setattr(
        stats,
        "out",
        make_out({"rhiza status": status, "release list": "v1.1.3"}),
    )
    s, rc = stats.section_rhiza(tmp_path)
    rows = dict(s.rows)
    assert rc["ref"] == "v1.1.3"
    assert rows["Synced commit"] == "abcdef123456"
    assert rows["Files synced from template"] == "3"
    assert "on latest" in rows["Latest rhiza release"]


def test_section_rhiza_fallback_to_lock(tmp_path, monkeypatch):
    rhiza = tmp_path / ".rhiza"
    rhiza.mkdir()
    (rhiza / "template.yml").write_text('template-branch: "v1.0.0"\nprofiles: [github-project]\n')
    (rhiza / "template.lock").write_text("files:\n  - a\n  - b\n")
    # no rhiza CLI, no gh → status None, latest None
    monkeypatch.setattr(stats, "out", lambda cmd, timeout=60: None)
    s, rc = stats.section_rhiza(tmp_path)
    rows = dict(s.rows)
    assert rc["ref"] == "v1.0.0"
    assert "github-project" in rows["Active profiles"]
    assert "rough count" in rows["Files synced from template"]


# --------------------------------------------------------------------------- #
# renderers
# --------------------------------------------------------------------------- #
def test_render_terminal(capsys):
    s = stats.Section("Sec")
    s.row("k", 1)
    s.table("cap", ["h1", "h2"], [["a", "b"]])
    stats.render_terminal([("Stars", 5)], "summary line", [s])
    out = capsys.readouterr().out
    assert "Repo statistics" in out
    assert "summary line" in out
    assert "## Sec" in out
    assert "cap" in out


def test_render_html_escapes_and_structure():
    s = stats.Section("S<x>")
    s.row("lbl&", "<v>")
    s.table("c", ["h"], [["<td>"]])
    doc = stats.render_html([("N", 3)], "sum", [s], "title", "2026-07-12")
    assert "<!doctype html>" in doc
    assert "S&lt;x&gt;" in doc  # section title escaped
    assert "&lt;v&gt;" in doc  # row value escaped
    assert "title — stats" in doc


# --------------------------------------------------------------------------- #
# main()
# --------------------------------------------------------------------------- #
def test_main_not_a_git_repo(monkeypatch):
    monkeypatch.setattr(stats, "out", lambda cmd, timeout=60: None)
    monkeypatch.setattr(stats.sys, "argv", ["stats.py"])
    with pytest.raises(SystemExit) as exc:
        stats.main()
    assert exc.value.code == 1


def test_main_writes_html(tmp_path, monkeypatch):
    monkeypatch.setattr(stats, "have", lambda b: False)
    monkeypatch.setattr(stats, "tool", lambda name: None)
    monkeypatch.setattr(stats.os, "chdir", lambda p: None)  # don't actually chdir
    monkeypatch.setattr(stats, "out", make_out({"rev-parse --show-toplevel": str(tmp_path)}))
    html_out = tmp_path / "stats.html"
    monkeypatch.setattr(stats.sys, "argv", ["stats.py", "--html-out", str(html_out)])
    stats.main()
    assert html_out.exists()
    assert "<!doctype html>" in html_out.read_text()


def test_main_no_html(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(stats, "have", lambda b: False)
    monkeypatch.setattr(stats, "tool", lambda name: None)
    monkeypatch.setattr(stats.os, "chdir", lambda p: None)
    monkeypatch.setattr(stats, "out", make_out({"rev-parse --show-toplevel": str(tmp_path)}))
    monkeypatch.setattr(stats.sys, "argv", ["stats.py", "--no-html"])
    stats.main()
    assert not (tmp_path / "docs" / "stats.html").exists()
    assert "Repo statistics" in capsys.readouterr().out
