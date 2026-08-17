"""Tests for the YAML read/write facade (`scripts/_rhiza_yaml.py`).

Three concerns live here: the public `load_yaml` contract, the emitter, and — the reason
this module is interesting — the **parity checks** that hold its two readers to each other.
PyYAML applies YAML 1.1 implicit resolution while the subset parser applies something close
to YAML 1.2 core, so the same file once produced different answers depending only on
whether PyYAML happened to be importable. The subset parser's own coercion rules are
asserted in `test__rhiza_yaml_parse.py`.
"""

from __future__ import annotations

from typing import Any

import _rhiza_yaml as y
import _rhiza_yaml_parse as yp
import pytest


@pytest.mark.skipif(y._pyyaml is None, reason="exercises the real PyYAML arm")
def test_load_yaml_with_pyyaml(tmp_path):
    """The document-level contract, against real PyYAML rather than a stand-in.

    This used to monkeypatch a `FakeYaml` with a hand-written `safe_load`. That made
    the arm *look* tested while asserting nothing about PyYAML's actual behaviour —
    and it broke the moment `load_yaml` stopped calling `safe_load`, which is the
    honest signal that it was testing the mock. PyYAML is now a test dependency, so
    the real thing is available.
    """
    f = tmp_path / "f.yml"
    f.write_text("a: 1\n", encoding="utf-8")
    assert y.load_yaml(f) == {"a": 1}
    f.write_text("# just a comment\n", encoding="utf-8")
    assert y.load_yaml(f) == {}
    f.write_text("- 1\n- 2\n", encoding="utf-8")
    with pytest.raises(ValueError, match="not a mapping"):
        y.load_yaml(f)


# --- dump / emit ----------------------------------------------------------------


def test_dumps_yaml_layout_and_roundtrip():
    lock = {
        "sha": "abc123",
        "repo": "owner/name",
        "host": "github",
        "ref": "v1.1.3",
        "include": [],
        "exclude": ["a/b.yml"],
        "templates": ["legal"],
        "files": ["Makefile", "docs/x.md"],
        "synced_at": "2026-07-13T10:00:00Z",
        "strategy": "merge",
    }
    text = y.dumps_yaml(lock)
    assert "include: []" in text
    assert "exclude:\n- a/b.yml" in text
    assert "synced_at: '2026-07-13T10:00:00Z'" in text  # timestamp must be quoted
    assert yp.parse_subset(text) == lock  # round-trips through the subset parser


def test_dumps_yaml_empty_dict():
    assert y.dumps_yaml({}) == ""


def test_dump_yaml_writes_file(tmp_path):
    path = tmp_path / "template.lock"
    y.dump_yaml({"sha": "x", "files": ["a"]}, path)
    assert path.read_text(encoding="utf-8") == "sha: x\nfiles:\n- a\n"


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, "null"),
        (True, "true"),
        (False, "false"),
        (7, "7"),
        ("plain", "plain"),
        ("owner/name", "owner/name"),
        ("", "''"),
        ("true", "'true'"),
        ("123", "'123'"),
        ("1.5", "'1.5'"),
        ("2026-07-13T10:00:00Z", "'2026-07-13T10:00:00Z'"),
        ("a: b", "'a: b'"),
        ("*anchor", "'*anchor'"),
        ("- dash", "'- dash'"),
        ("it's", "it's"),  # a mid-string apostrophe is valid unquoted
        ("'quoted'", "'''quoted'''"),  # leading quote forces quoting + doubling
    ],
)
def test_emit_scalar_quoting(value, expected):
    assert y._emit_scalar(value) == expected


def test_is_float():
    assert y._is_float("1.5") is True
    assert y._is_float("nan") is True
    assert y._is_float("abc") is False


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, []),
        (["a", "b"], ["a", "b"]),
        ("one\ntwo", ["one", "two"]),
        ("a\\nb", ["a", "b"]),
        (7, ["7"]),
    ],
)
def test_as_list(value: Any, expected: list[str]) -> None:
    assert y.as_list(value) == expected


# --- the two readers must agree ------------------------------------------------
#
# `load_yaml` has two implementations behind it and they used to disagree, invisibly:
# the PyYAML import was excluded from coverage, so which arm CI exercised was never
# measured. These are the differential tests. They need PyYAML installed — `make test`
# supplies it as a test-only dependency.

_pyyaml_only = pytest.mark.skipif(y._pyyaml is None, reason="differential test needs PyYAML")

# Every row here disagreed before the normalising loader. Each is a shape that can
# really appear in a template.yml or template.lock.
_DIVERGENT = [
    pytest.param("ref: 1.20\n", "ref", "1.20", id="a-ref-is-not-a-float"),
    pytest.param("synced_at: 2026-08-02T09:00:00Z\n", "synced_at", "2026-08-02T09:00:00Z",
                 id="a-timestamp-stays-a-string"),
    pytest.param("strategy: no\n", "strategy", "no", id="no-is-not-False"),
    pytest.param("verbose: yes\n", "verbose", "yes", id="yes-is-not-True"),
    pytest.param("mode: off\n", "mode", "off", id="off-is-not-False"),
    pytest.param("build: 0755\n", "build", 755, id="a-leading-zero-is-not-octal"),
]  # fmt: skip


@_pyyaml_only
@pytest.mark.parametrize(("text", "key", "expected"), _DIVERGENT)
def test_both_readers_agree_on_a_scalar_yaml_1_1_would_coerce(tmp_path, text, key, expected):
    """The regression this module's normalising loader exists to prevent.

    `ref` is the one that matters: it selects the template tag a sync pulls from, so
    `1.20` resolving to `1.2` would silently sync a different release depending only on
    whether PyYAML happened to be importable.
    """
    path = tmp_path / "t.yml"
    path.write_text(text, encoding="utf-8")
    via_pyyaml = y.load_yaml(path)
    assert via_pyyaml[key] == expected
    assert via_pyyaml == yp.parse_subset(text)


@_pyyaml_only
def test_the_two_readers_agree_on_a_whole_pointer_file(tmp_path):
    """A realistic file end to end, not one key at a time."""
    text = (
        "repository: jebel-quant/rhiza\n"
        "ref: 1.20\n"
        "branch: main\n"
        "host: github\n"
        "language: rust\n"
        "strategy: no\n"
        "build: 0755\n"
        "count: 42\n"
        "flag: true\n"
        "empty: null\n"
        'quoted: "true"\n'
        "profiles: [rust-local, core]\n"
    )
    path = tmp_path / "template.yml"
    path.write_text(text, encoding="utf-8")
    assert y.load_yaml(path) == yp.parse_subset(text)


@_pyyaml_only
def test_a_quoted_scalar_is_not_coerced_by_either_reader(tmp_path):
    """Why the fix edits resolvers rather than post-processing the parsed result.

    Once PyYAML has produced a value, an unquoted `true` and a quoted `"true"` are the
    same Python string — so coercing after the fact would trade one disagreement for
    another.
    """
    text = 'a: "true"\nb: true\nc: "1.20"\n'
    path = tmp_path / "t.yml"
    path.write_text(text, encoding="utf-8")
    loaded = y.load_yaml(path)
    assert loaded == {"a": "true", "b": True, "c": "1.20"}
    assert loaded == yp.parse_subset(text)


@_pyyaml_only
def test_structure_still_comes_from_pyyaml(tmp_path):
    """Deferring to PyYAML buys constructs the subset parser never promised — anchors.

    This is the reason the PyYAML arm exists at all, so it is worth pinning: the fix
    normalises *scalars*, and must not have flattened the capability it was protecting.
    """
    path = tmp_path / "t.yml"
    path.write_text("defaults: &d\n  branch: main\nrepo:\n  <<: *d\n  name: x\n", encoding="utf-8")
    assert y.load_yaml(path)["repo"] == {"branch": "main", "name": "x"}


def test_the_subset_parser_is_used_when_pyyaml_is_absent(tmp_path, monkeypatch):
    """The runtime case: the commands run under `uv run --no-project`, with no PyYAML."""
    monkeypatch.setattr(y, "_pyyaml", None)
    path = tmp_path / "t.yml"
    path.write_text("ref: 1.20\nstrategy: no\n", encoding="utf-8")
    assert y.load_yaml(path) == {"ref": "1.20", "strategy": "no"}


@_pyyaml_only
def test_both_readers_agree_on_a_block_scalar(tmp_path):
    """The fifth divergence, found by running the existing suite with PyYAML installed.

    `key: |` clips to one trailing newline per the spec; the subset parser strips.
    Nothing in a rhiza file depends on that newline, and agreement does.
    """
    text = "notes: |\n  first\n  second\n"
    path = tmp_path / "t.yml"
    path.write_text(text, encoding="utf-8")
    assert y.load_yaml(path)["notes"] == "first\nsecond"
    assert y.load_yaml(path) == yp.parse_subset(text)


@_pyyaml_only
def test_a_quoted_string_keeps_its_deliberate_whitespace(tmp_path):
    """Only block styles are stripped — stripping every string would be a new bug."""
    path = tmp_path / "t.yml"
    path.write_text('a: "  padded  "\n', encoding="utf-8")
    assert y.load_yaml(path)["a"] == "  padded  "


@_pyyaml_only
def test_a_damaged_document_raises_the_error_callers_actually_catch(tmp_path):
    """PyYAML's YAMLError is neither OSError nor ValueError.

    All eight `load_yaml` call sites guard with `except (OSError, ValueError)`, so a
    raw YAMLError escaped every one of them — and `stage_synced` stopped degrading to
    "stage the pointer only" on a damaged lock, which is a safety property rather than
    a nicety. Parity here is about the *error type*: the subset parser is lenient and
    the PyYAML one strict, but both must fail in a way the callers handle.
    """
    path = tmp_path / "template.lock"
    path.write_text("\t: not: valid: yaml: [\n", encoding="utf-8")
    with pytest.raises(ValueError, match="could not parse YAML"):
        y.load_yaml(path)


def test_load_yaml_missing_file(tmp_path):
    with pytest.raises(OSError):
        y.load_yaml(tmp_path / "nope.yml")


def test_load_yaml_empty_returns_empty_dict(tmp_path):
    f = tmp_path / "empty.yml"
    f.write_text("# just a comment\n", encoding="utf-8")
    assert y.load_yaml(f) == {}


# --- branch coverage: the arms line coverage could not see ---------------------


def test_a_block_scalar_running_to_the_end_of_the_document(tmp_path):
    """The scan exhausts the file instead of breaking on a dedented line."""
    path = tmp_path / "t.yml"
    path.write_text("name: x\nnotes: |\n  first\n  second\n", encoding="utf-8")
    assert y.load_yaml(path)["notes"] == "first\nsecond"
