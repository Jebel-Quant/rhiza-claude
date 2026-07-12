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
