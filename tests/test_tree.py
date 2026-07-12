"""Tests for the `rhiza tree` port (`scripts/tree.py`)."""

from __future__ import annotations

import tree


def _write_lock(repo, body: str):
    rhiza = repo / ".rhiza"
    rhiza.mkdir(parents=True, exist_ok=True)
    (rhiza / "template.lock").write_text(body)


def test_build_tree_nests_paths():
    built = tree._build_tree(["a/b/c.txt", "a/d.txt", "top.txt"])
    assert built == {"a": {"b": {"c.txt": {}}, "d.txt": {}}, "top.txt": {}}


def test_render_connectors():
    lines = tree._render(tree._build_tree(["a/b.txt", "a/c.txt", "d.txt"]))
    assert lines == [
        "├── a",
        "│   ├── b.txt",
        "│   └── c.txt",
        "└── d.txt",
    ]


def test_tree_missing_lock_is_not_an_error(tmp_path, capsys):
    rc = tree.tree(tmp_path)
    assert rc == 0
    assert "run `rhiza sync`" in capsys.readouterr().err


def test_tree_empty_files(tmp_path, capsys):
    _write_lock(tmp_path, "sha: abc\nfiles: []\n")
    rc = tree.tree(tmp_path)
    assert rc == 0
    assert "No files are tracked" in capsys.readouterr().err


def test_tree_output_and_count(tmp_path, capsys):
    _write_lock(tmp_path, "sha: abc\nfiles:\n- .github/ci.yml\n- LICENSE\n")
    rc = tree.tree(tmp_path)
    out = capsys.readouterr().out
    assert rc == 0
    assert out.splitlines()[0] == "."
    assert "├── .github" in out
    assert "│   └── ci.yml" in out
    assert "└── LICENSE" in out
    assert "2 files managed by Rhiza" in out


def test_tree_singular_file_count(tmp_path, capsys):
    _write_lock(tmp_path, "sha: abc\nfiles:\n- solo.txt\n")
    tree.tree(tmp_path)
    assert "1 file managed by Rhiza" in capsys.readouterr().out


def test_main_returns_zero(tmp_path):
    _write_lock(tmp_path, "sha: abc\nfiles:\n- a.txt\n")
    assert tree.main([str(tmp_path)]) == 0
