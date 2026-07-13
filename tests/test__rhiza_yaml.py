"""Tests for the dependency-free YAML subset reader (`scripts/_rhiza_yaml.py`)."""

from __future__ import annotations

import _rhiza_yaml as y
import pytest


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ('"quoted"', "quoted"),
        ("'single'", "single"),
        ("bare", "bare"),
        ("42", 42),
        ("true", True),
        ("False", False),
        ("null", None),
        ("~", None),
        ("[]", []),
        ("[a, b, c]", ["a", "b", "c"]),
        ('["x", y]', ["x", "y"]),
        ("v1.2.3", "v1.2.3"),  # dotted version stays a string, not an int
    ],
)
def test_scalar_coercion(raw, expected):
    assert y._scalar(raw) == expected


def test_strip_comment_outside_quotes():
    assert y._strip_comment("value  # trailing").strip() == "value"
    # a '#' inside quotes is part of the value, not a comment
    assert y._strip_comment('"a#b"') == '"a#b"'
    # a '#' with no leading whitespace is not a comment marker
    assert y._strip_comment("a#b") == "a#b"


def test_split_flow_respects_quotes():
    assert y._split_flow("a, b, c") == ["a", " b", " c"]
    assert y._split_flow('"a, b", c') == ['"a, b"', " c"]


def test_parse_subset_block_sequence():
    text = "templates:\n  - core\n  - tests\n"
    assert y._parse_subset(text) == {"templates": ["core", "tests"]}


def test_parse_subset_zero_indent_sequence():
    # lock files write list items at column 0 under the key
    text = "files:\n- a\n- b\n"
    assert y._parse_subset(text) == {"files": ["a", "b"]}


def test_parse_subset_scalars_and_comments():
    text = '# leading comment\nrepository: "owner/repo"\nref: v1.1.3\n\ninclude: []\n'
    assert y._parse_subset(text) == {
        "repository": "owner/repo",
        "ref": "v1.1.3",
        "include": [],
    }


def test_parse_subset_bare_key_is_null():
    # a key with no value and no following items is null
    assert y._parse_subset("language:\n") == {"language": None}


def test_load_yaml_missing_file(tmp_path):
    with pytest.raises(OSError):
        y.load_yaml(tmp_path / "nope.yml")


def test_load_yaml_empty_returns_empty_dict(tmp_path):
    f = tmp_path / "empty.yml"
    f.write_text("# just a comment\n")
    assert y.load_yaml(f) == {}


def test_scalar_variants():
    assert y._scalar("") is None  # empty → None
    assert y._scalar('"q"') == "q"
    assert y._scalar("[a, b]") == ["a", "b"]
    assert y._scalar("null") is None
    assert y._scalar("true") is True
    assert y._scalar("42") == 42
    assert y._scalar("bare") == "bare"


def test_parse_subset_skips_line_without_colon():
    d = y._parse_subset("key: v\nlineWithoutColon\n")
    assert d == {"key": "v"}


def test_load_yaml_with_pyyaml(tmp_path, monkeypatch):
    class FakeYaml:
        @staticmethod
        def safe_load(text):
            if "none" in text:
                return None
            if "list" in text:
                return [1, 2]
            return {"a": 1}

    monkeypatch.setattr(y, "_pyyaml", FakeYaml)
    f = tmp_path / "f.yml"
    f.write_text("dict")
    assert y.load_yaml(f) == {"a": 1}
    f.write_text("none")
    assert y.load_yaml(f) == {}
    f.write_text("list")
    with pytest.raises(ValueError):
        y.load_yaml(f)


# --- scalar/flow-map extensions -------------------------------------------------


def test_scalar_flow_map():
    assert y._scalar("{source: a, dest: b}") == {"source": "a", "dest": "b"}
    assert y._scalar("{}") == {}


def test_flow_map_ignores_entries_without_colon():
    assert y._flow_map("source: a, bogus") == {"source": "a"}


# --- nested parser --------------------------------------------------------------


def test_parse_nested_mapping():
    text = (
        "bundles:\n  core:\n    required: true\n    requires: [base]\n"
        "  base:\n    standalone: true\n"
    )
    assert y._parse_subset(text) == {
        "bundles": {
            "core": {"required": True, "requires": ["base"]},
            "base": {"standalone": True},
        }
    }


def test_parse_profile_with_block_sequence():
    text = "profiles:\n  std:\n    description: Std\n    bundles:\n      - core\n      - tests\n"
    assert y._parse_subset(text) == {
        "profiles": {"std": {"description": "Std", "bundles": ["core", "tests"]}}
    }


def test_parse_block_scalar_is_consumed_not_misparsed():
    # The `- Documentation` line inside a `|` block must NOT become a sequence.
    text = (
        "book:\n"
        "  description: |\n"
        "    Docs combining:\n"
        "    - a site\n"
        "    - notebooks\n"
        "  standalone: true\n"
        "  requires:\n"
        "    - core\n"
    )
    result = y._parse_subset(text)
    assert result["book"]["standalone"] is True
    assert result["book"]["requires"] == ["core"]
    assert "a site" in result["book"]["description"]


def test_parse_block_form_list_of_maps():
    text = "files:\n  - source: a\n    dest: b\n  - source: c\n"
    assert y._parse_subset(text) == {"files": [{"source": "a", "dest": "b"}, {"source": "c"}]}


def test_parse_inline_flow_map_list_item():
    text = "files:\n  - {source: a, dest: b}\n"
    assert y._parse_subset(text) == {"files": [{"source": "a", "dest": "b"}]}


def test_parse_bare_seq_item_is_none():
    text = "items:\n  -\n  - x\n"
    assert y._parse_subset(text) == {"items": [None, "x"]}


def test_parse_dedent_ends_nested_block():
    text = "a:\n  x: 1\nb: 2\n"
    assert y._parse_subset(text) == {"a": {"x": 1}, "b": 2}


def test_parse_top_level_sequence_yields_empty_map():
    # A document that starts with a sequence is not a mapping -> {}.
    assert y._parse_subset("- a\n- b\n") == {}


def test_parse_bare_key_before_sibling_key_is_null():
    # `a:` with the next line a sibling key (same indent) leaves `a` as null.
    assert y._parse_subset("a:\nb: 2\n") == {"a": None, "b": 2}


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
    assert y._parse_subset(text) == lock  # round-trips through the subset parser


def test_dumps_yaml_empty_dict():
    assert y.dumps_yaml({}) == ""


def test_dump_yaml_writes_file(tmp_path):
    path = tmp_path / "template.lock"
    y.dump_yaml({"sha": "x", "files": ["a"]}, path)
    assert path.read_text() == "sha: x\nfiles:\n- a\n"


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
