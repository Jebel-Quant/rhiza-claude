"""Tests for the hand-rolled YAML subset parser (`scripts/_rhiza_yaml_parse.py`).

These pin what a rhiza config *means*, not merely what this module does: where the parser
and PyYAML disagreed, PyYAML was normalised to match this — so the coercion rules asserted
here are the reference. `test__rhiza_yaml.py` owns the parity checks that hold the two
readers to each other.
"""

from __future__ import annotations

import _rhiza_yaml_parse as y
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
    assert y.scalar(raw) == expected


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
    assert y.parse_subset(text) == {"templates": ["core", "tests"]}


def test_parse_subset_zero_indent_sequence():
    # lock files write list items at column 0 under the key
    text = "files:\n- a\n- b\n"
    assert y.parse_subset(text) == {"files": ["a", "b"]}


def test_parse_subset_scalars_and_comments():
    text = '# leading comment\nrepository: "owner/repo"\nref: v1.1.3\n\ninclude: []\n'
    assert y.parse_subset(text) == {
        "repository": "owner/repo",
        "ref": "v1.1.3",
        "include": [],
    }


def test_parse_subset_bare_key_is_null():
    # a key with no value and no following items is null
    assert y.parse_subset("language:\n") == {"language": None}


def test_scalar_variants():
    assert y.scalar("") is None  # empty → None
    assert y.scalar('"q"') == "q"
    assert y.scalar("[a, b]") == ["a", "b"]
    assert y.scalar("null") is None
    assert y.scalar("true") is True
    assert y.scalar("42") == 42
    assert y.scalar("bare") == "bare"


def test_parse_subset_skips_line_without_colon():
    d = y.parse_subset("key: v\nlineWithoutColon\n")
    assert d == {"key": "v"}


# --- scalar/flow-map extensions -------------------------------------------------


def test_scalar_flow_map():
    assert y.scalar("{source: a, dest: b}") == {"source": "a", "dest": "b"}
    assert y.scalar("{}") == {}


def test_flow_map_ignores_entries_without_colon():
    assert y._flow_map("source: a, bogus") == {"source": "a"}


# --- nested parser --------------------------------------------------------------


def test_parse_nested_mapping():
    text = (
        "bundles:\n  core:\n    required: true\n    requires: [base]\n"
        "  base:\n    standalone: true\n"
    )
    assert y.parse_subset(text) == {
        "bundles": {
            "core": {"required": True, "requires": ["base"]},
            "base": {"standalone": True},
        }
    }


def test_parse_profile_with_block_sequence():
    text = "profiles:\n  std:\n    description: Std\n    bundles:\n      - core\n      - tests\n"
    assert y.parse_subset(text) == {
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
    result = y.parse_subset(text)
    assert result["book"]["standalone"] is True
    assert result["book"]["requires"] == ["core"]
    assert "a site" in result["book"]["description"]


def test_parse_block_form_list_of_maps():
    text = "files:\n  - source: a\n    dest: b\n  - source: c\n"
    assert y.parse_subset(text) == {"files": [{"source": "a", "dest": "b"}, {"source": "c"}]}


def test_parse_inline_flow_map_list_item():
    text = "files:\n  - {source: a, dest: b}\n"
    assert y.parse_subset(text) == {"files": [{"source": "a", "dest": "b"}]}


def test_parse_bare_seq_item_is_none():
    text = "items:\n  -\n  - x\n"
    assert y.parse_subset(text) == {"items": [None, "x"]}


def test_parse_dedent_ends_nested_block():
    text = "a:\n  x: 1\nb: 2\n"
    assert y.parse_subset(text) == {"a": {"x": 1}, "b": 2}


def test_parse_top_level_sequence_yields_empty_map():
    # A document that starts with a sequence is not a mapping -> {}.
    assert y.parse_subset("- a\n- b\n") == {}


def test_parse_bare_key_before_sibling_key_is_null():
    # `a:` with the next line a sibling key (same indent) leaves `a` as null.
    assert y.parse_subset("a:\nb: 2\n") == {"a": None, "b": 2}
