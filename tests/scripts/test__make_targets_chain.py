"""Tests for the static half of the make-target probe (`scripts/_make_targets_chain.py`).

Everything here writes makefiles into a temporary directory and reads them back as text —
no `make` runs. Whether a target *resolves* is the orchestrator's question and is tested
in `test_check_make_targets.py`; these test what a repo's makefiles *say*.
"""

from __future__ import annotations

from pathlib import Path

import _make_targets_chain as chain
from conftest import write_include_chain

# --- finding the makefile ------------------------------------------------------


def test_find_makefile_accepts_the_conventional_names(tmp_path):
    assert chain.find_makefile(tmp_path) is None
    (tmp_path / "GNUmakefile").write_text("x: ; @:\n", encoding="utf-8")
    assert chain.find_makefile(tmp_path).name == "GNUmakefile"


# --- discovery: what the repo documents beyond the prose's list ---------------


def test_documented_targets_reads_the_help_convention(tmp_path):
    (tmp_path / "Makefile").write_text(
        "help:  ## Show this help\n\ttrue\n"
        "build:  ## Compile the crate\n\ttrue\n"
        "internal-thing:\n\ttrue\n",  # undocumented: deliberately not discovered
        encoding="utf-8",
    )
    found = chain.documented_targets(tmp_path)
    assert found == {"help": "Show this help", "build": "Compile the crate"}


def test_documented_targets_without_a_makefile_is_empty(tmp_path):
    assert chain.documented_targets(tmp_path) == {}


# --- discovery follows the include chain, because make does -------------------
#
# A synced repo's root Makefile is a stub: variables and `include .rhiza/rhiza.mk`,
# which itself ends in `-include .rhiza/make.d/*.mk`. Reading only the root file found
# nothing on every real repo — the one place discovery was supposed to work.


def test_documented_targets_reads_the_included_makefiles(tmp_path):
    """The regression: `deps` and `license` live two includes down, not in the Makefile."""
    write_include_chain(tmp_path)
    found = chain.documented_targets(tmp_path)
    assert set(found) == {"help", "test", "deps", "license"}
    assert found["deps"] == "report unused dependencies (the deptry analogue)"


def test_a_double_colon_rule_is_discovered(tmp_path):
    """`test::` is how rust.mk declares its test target; a single-colon regex missed it."""
    write_include_chain(tmp_path)
    assert chain.documented_targets(tmp_path)["test"] == "run the test suite with nextest"


def test_makefile_chain_is_ordered_root_first_and_visits_each_file_once(tmp_path):
    write_include_chain(tmp_path)
    # A second include of the same file (make tolerates it) must not duplicate.
    (tmp_path / "Makefile").write_text(
        "include .rhiza/rhiza.mk\ninclude .rhiza/rhiza.mk\n-include local.mk\n", encoding="utf-8"
    )
    order = [p.relative_to(tmp_path).as_posix() for p in chain.makefile_chain(tmp_path)]
    assert order == ["Makefile", ".rhiza/rhiza.mk", ".rhiza/make.d/rust.mk"]


def test_an_absent_optional_include_is_skipped(tmp_path):
    """`-include local.mk` is how rhiza offers developer-local extensions."""
    write_include_chain(tmp_path)
    assert not (tmp_path / "local.mk").exists()
    assert "local.mk" not in [p.name for p in chain.makefile_chain(tmp_path)]


def test_a_local_extension_is_read_when_present(tmp_path):
    write_include_chain(tmp_path)
    (tmp_path / "local.mk").write_text("mine:  ## my own target\n\ttrue\n", encoding="utf-8")
    assert "mine" in chain.documented_targets(tmp_path)


def test_an_include_naming_a_make_variable_is_left_alone(tmp_path):
    """`include $(EXTRA)` cannot be resolved without evaluating make — omit, don't guess."""
    (tmp_path / "Makefile").write_text(
        "include $(EXTRA_MK)\nhelp:  ## help\n\ttrue\n", encoding="utf-8"
    )
    assert [p.name for p in chain.makefile_chain(tmp_path)] == ["Makefile"]
    assert chain.documented_targets(tmp_path) == {"help": "help"}


def test_a_cyclic_include_terminates(tmp_path):
    (tmp_path / "Makefile").write_text("include a.mk\n", encoding="utf-8")
    (tmp_path / "a.mk").write_text(
        "include Makefile\nlooped:  ## still found\n\ttrue\n", encoding="utf-8"
    )
    assert [p.name for p in chain.makefile_chain(tmp_path)] == ["Makefile", "a.mk"]
    assert "looped" in chain.documented_targets(tmp_path)


def test_include_following_is_depth_limited(tmp_path):
    (tmp_path / "Makefile").write_text("include a.mk\n", encoding="utf-8")
    (tmp_path / "a.mk").write_text("include b.mk\n", encoding="utf-8")
    (tmp_path / "b.mk").write_text("deep:  ## too deep\n\ttrue\n", encoding="utf-8")
    assert [p.name for p in chain.makefile_chain(tmp_path, depth=1)] == ["Makefile", "a.mk"]
    assert [p.name for p in chain.makefile_chain(tmp_path, depth=2)] == ["Makefile", "a.mk", "b.mk"]


def test_makefile_chain_without_a_makefile_is_empty(tmp_path):
    assert chain.makefile_chain(tmp_path) == []


def test_this_repo_discovers_its_own_documented_targets(repo_root: Path):
    """rhiza-claude's own `local.mk` uses the convention, so this is a live check.

    `lint` used to head this list and was dropped from it deliberately: it is one of the
    three targets (`lint`, `book-serve`, `changelog`) now left to the shim's catch-all, so
    it is not defined anywhere `documented_targets` reads. The assertion on a description
    moved to `test` rather than being deleted — without one, this only checks that names
    are found and would pass with every description dropped on the floor.
    """
    found = chain.documented_targets(repo_root)
    assert {"test", "book", "clean"} <= set(found)
    assert found["test"] == "Run the script test suite with a 100% coverage gate"
