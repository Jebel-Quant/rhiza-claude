"""Tests for the TOML table primitives (`scripts/_rhiza_toml.py`).

The invariant every skeleton finisher rests on: a key the user wrote is never
overwritten, and nothing outside the targeted key is reformatted — down to whether the
file ended in a newline. These edits land in somebody's `pyproject.toml` and `Cargo.toml`,
so a stray reflow would show up as noise in their next diff.
"""

from __future__ import annotations

import pytest
from _rhiza_toml import (
    append_table,
    merge_table,
    present_keys,
    rejoin,
    require_table,
    set_key,
    table_span,
)

_PYPROJECT = '[project]\nname = "x"\nversion = "0.1"\n\n[build-system]\nrequires = []\n'


# --- table_span ---------------------------------------------------------------


def test_table_span_bounds_the_body_up_to_the_next_header():
    lines = _PYPROJECT.splitlines()
    header, end = table_span(lines, "project")
    assert (header, end) == (0, 4)
    assert lines[header + 1 : end] == ['name = "x"', 'version = "0.1"', ""]


def test_table_span_ends_at_eof_when_it_is_the_last_table():
    """The loop exhausts instead of breaking — where an off-by-one would eat a line."""
    lines = ["[project]", 'name = "x"', 'version = "0.1"']
    assert table_span(lines, "project") == (0, 3)


def test_table_span_of_an_absent_table_is_none():
    assert table_span(["[workspace]", "members = []"], "package") is None


def test_table_span_ignores_a_subtable_with_the_same_prefix():
    """`[project.urls]` is not `[project]`, and matching it would bound the wrong body."""
    lines = ["[project.urls]", 'Homepage = "h"']
    assert table_span(lines, "project") is None
    assert table_span(lines, "project.urls") == (0, 2)


# --- require_table ------------------------------------------------------------


def test_require_table_returns_the_span_when_present():
    assert require_table(["[package]", 'name = "x"'], "package", "Cargo.toml") == (0, 2)


def test_require_table_names_the_file_it_read():
    """A bare "no [package] table" leaves the user guessing which file was meant."""
    with pytest.raises(ValueError, match=r"Cargo\.toml has no \[package\] table"):
        require_table(["[workspace]"], "package", "Cargo.toml")


# --- present_keys -------------------------------------------------------------


def test_present_keys_reads_only_the_bounded_body():
    lines = _PYPROJECT.splitlines()
    header, end = table_span(lines, "project")
    assert present_keys(lines, header, end) == {"name", "version"}


def test_present_keys_accepts_dotted_and_hyphenated_names():
    lines = ["[t]", "a-b = 1", "c.d = 2", "e_f = 3", "not a key"]
    assert present_keys(lines, 0, len(lines)) == {"a-b", "c.d", "e_f"}


# --- append_table -------------------------------------------------------------


def test_append_table_leaves_exactly_one_blank_line_before_it():
    lines = ["[project]", 'name = "x"', "", "", ""]
    append_table(lines, "[project.urls]", ['Homepage = "h"'])
    assert lines == ["[project]", 'name = "x"', "", "[project.urls]", 'Homepage = "h"']


def test_append_table_onto_an_empty_document():
    lines: list[str] = []
    append_table(lines, "[t]", ["a = 1"])
    assert lines == ["", "[t]", "a = 1"]


# --- rejoin -------------------------------------------------------------------


@pytest.mark.parametrize(
    ("original", "expected"),
    [("a\nb\n", "x\ny\n"), ("a\nb", "x\ny")],
)
def test_rejoin_preserves_the_trailing_newline_decision(original, expected):
    assert rejoin(original, ["x", "y"]) == expected


# --- merge_table --------------------------------------------------------------


def test_merge_table_appends_the_table_when_it_is_absent():
    out, added = merge_table(_PYPROJECT, "project.urls", {"Homepage": '"h"'}, filename="p.toml")
    assert added == ["Homepage"]
    assert out.endswith('[project.urls]\nHomepage = "h"\n')


def test_merge_table_adds_only_the_keys_that_are_missing():
    text = '[package]\nname = "x"\nversion = "1"\n'
    out, added = merge_table(
        text, "package", {"name": '"other"', "edition": '"2024"'}, filename="Cargo.toml"
    )
    assert added == ["edition"]
    assert '"other"' not in out, "a value the user wrote must win"
    assert 'edition = "2024"' in out


def test_merge_table_is_idempotent():
    once, _ = merge_table(_PYPROJECT, "project.urls", {"Homepage": '"h"'}, filename="p.toml")
    twice, added = merge_table(once, "project.urls", {"Homepage": '"h"'}, filename="p.toml")
    assert added == []
    assert twice == once


def test_merge_table_inserts_before_the_blank_lines_padding_the_table():
    """New keys belong inside the table, not after the blank line that ends it."""
    out, added = merge_table(_PYPROJECT, "project", {"edition": '"2024"'}, filename="p.toml")
    assert added == ["edition"]
    assert 'version = "0.1"\nedition = "2024"\n\n[build-system]' in out


def test_merge_table_appends_new_keys_at_the_end_not_under_the_header():
    """cargo and uv both put `name` and `version` first; readers expect them there."""
    text = '[package]\nname = "x"\nversion = "1"\n'
    out, _ = merge_table(text, "package", {"description": '"d"'}, filename="Cargo.toml")
    lines = out.splitlines()
    assert lines.index('name = "x"') < lines.index('description = "d"')


def test_merge_table_can_require_the_table_to_exist():
    with pytest.raises(ValueError, match=r"\[package\]"):
        merge_table(
            "[workspace]\nmembers = []\n",
            "package",
            {"description": '"d"'},
            filename="Cargo.toml",
            required=True,
        )


@pytest.mark.parametrize("text", ['[package]\nname = "x"', '[package]\nname = "x"\n'])
def test_merge_table_preserves_the_trailing_newline_decision(text):
    out, added = merge_table(text, "package", {"edition": '"2024"'}, filename="Cargo.toml")
    assert added == ["edition"]
    assert out.endswith("\n") is text.endswith("\n")


# --- set_key ------------------------------------------------------------------


def _always(_value: str) -> bool:
    """Treat any existing value as replaceable."""
    return True


def _never(_value: str) -> bool:
    """Treat any existing value as the user's."""
    return False


def test_set_key_replaces_a_value_the_predicate_accepts():
    out, changed = set_key(
        '[project]\ndescription = "old"\n', "project", "description", '"new"',
        filename="p.toml", replaceable=_always,
    )  # fmt: skip
    assert changed
    assert 'description = "new"' in out
    assert '"old"' not in out


def test_set_key_leaves_a_value_the_predicate_rejects():
    text = '[project]\ndescription = "mine"\n'
    out, changed = set_key(
        text, "project", "description", '"theirs"', filename="p.toml", replaceable=_never
    )
    assert not changed
    assert out == text


def test_set_key_inserts_under_the_header_when_the_key_is_absent():
    """These are keys the initialiser would have written near the top."""
    out, changed = set_key(
        '[project]\nname = "x"\n', "project", "description", '"d"',
        filename="p.toml", replaceable=_always,
    )  # fmt: skip
    assert changed
    assert out.splitlines()[1] == 'description = "d"'


def test_set_key_does_not_reach_into_the_next_table():
    """A `description` under `[build-system]` is not `[project]`'s to replace."""
    text = '[project]\nname = "x"\n\n[build-system]\ndescription = "not mine"\n'
    out, changed = set_key(
        text, "project", "description", '"d"', filename="p.toml", replaceable=_never
    )
    assert changed, "the key was absent from [project], so it is inserted"
    assert '"not mine"' in out
    assert out.count("description = ") == 2


def test_set_key_requires_the_table():
    with pytest.raises(ValueError, match=r"\[project\]"):
        set_key(
            "[build-system]\nrequires = []\n", "project", "description", '"d"',
            filename="pyproject.toml", replaceable=_always,
        )  # fmt: skip


@pytest.mark.parametrize("text", ['[project]\nname = "x"', '[project]\nname = "x"\n'])
def test_set_key_preserves_the_trailing_newline_decision(text):
    out, _ = set_key(text, "project", "description", '"d"', filename="p.toml", replaceable=_always)
    assert out.endswith("\n") is text.endswith("\n")
