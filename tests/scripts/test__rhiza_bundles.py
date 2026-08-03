"""Tests for profile/bundle resolution (`scripts/_rhiza_bundles.py`).

The largest job in the sync and the one with no I/O: profiles expand to bundle names,
bundle names to `(source, dest)` entries, and the result to an ordered path list plus a
remap table. Includes the path-safety check, which guards untrusted `dest` values from
the template repo against escaping the project directory.
"""

from __future__ import annotations

from typing import Any

import _rhiza_bundles as rb
import pytest
from _rhiza_common import SyncError
from _rhiza_template import Template


class TestBundles:
    def test_order_is_topological(self):
        b = rb.Bundles.from_config(
            {"bundles": {"a": {"requires": ["b"]}, "b": {}, "c": {"requires": ["a"]}}}
        )
        assert b._order(["c"], strict=True) == ["b", "a", "c"]


@pytest.mark.parametrize("bad", ["/abs/path", "C:/win", "../escape", "a/../../b"])
def test_ensure_safe_bundle_path_rejects(bad: str) -> None:
    with pytest.raises(SyncError, match="Unsafe bundle path"):
        rb._ensure_safe_bundle_path(bad)


def test_ensure_safe_bundle_path_allows_relative() -> None:
    rb._ensure_safe_bundle_path("a/b/c.txt")  # no raise


def test_bundle_file_entries_forms() -> None:
    entries = rb._bundle_file_entries(["plain.txt", {"source": "s", "dest": "d"}, {"source": "x"}])
    assert entries == [("plain.txt", "plain.txt"), ("s", "d"), ("x", "x")]


def test_bundle_file_entries_string_scalar() -> None:
    assert rb._bundle_file_entries("only.txt") == [("only.txt", "only.txt")]


def test_bundle_file_entries_bad_entry() -> None:
    with pytest.raises(SyncError, match="must be a string or"):
        rb._bundle_file_entries([{"dest": "d"}])


def _bundles(**bundles: dict[str, Any]) -> rb.Bundles:
    return rb.Bundles.from_config({"bundles": bundles})


def test_resolve_unknown_bundle_strict_raises() -> None:
    with pytest.raises(SyncError, match="does not exist"):
        _bundles(a={}).resolve_to_paths(["missing"])


def test_resolve_cycle_strict_raises() -> None:
    b = rb.Bundles.from_config({"bundles": {"a": {"requires": ["b"]}, "b": {"requires": ["a"]}}})
    with pytest.raises(SyncError, match="Circular dependency"):
        b.resolve_to_paths(["a"])


def test_order_non_strict_skips_unknown_and_cycle() -> None:
    # _order(strict=False) (used by resolve_to_path_map) drops unknown + cyclic bundles.
    b = rb.Bundles.from_config({"bundles": {"a": {"requires": ["a"]}}})
    assert b._order(["a", "ghost"], strict=False) == ["a"]


def test_resolve_to_path_map_ignores_unresolved_remap() -> None:
    # A remapped source not in the resolved set is skipped from the path map.
    b = _bundles(a={"files": [{"source": "s", "dest": "d"}]})
    assert b.resolve_to_path_map(["a"]) == {"s": "d"}


def test_resolve_to_paths_dir_bundle() -> None:
    assert _bundles(core={}).resolve_to_paths(["core"]) == ["bundles/core/"]


def test_resolve_to_path_map_dir_bundle_maps_to_empty() -> None:
    assert _bundles(core={}).resolve_to_path_map(["core"]) == {"bundles/core/": ""}


def test_resolve_to_paths_dedups_shared_sources() -> None:
    b = _bundles(
        a={"files": [{"source": "shared.txt"}]},
        c={"requires": ["a"], "files": [{"source": "shared.txt"}]},
    )
    assert b.resolve_to_paths(["a", "c"]) == ["shared.txt"]


def test_resolve_bundle_names_no_profiles_returns_templates() -> None:
    template = Template("o/r", "main", templates=["core"])
    assert rb.resolve_bundle_names(template, _bundles(core={})) == ["core"]


def test_resolve_bundle_names_unknown_profile() -> None:
    template = Template("o/r", "main", profiles=["ghost"])
    with pytest.raises(SyncError, match="Available profiles"):
        rb.resolve_bundle_names(template, rb.Bundles.from_config({"profiles": {}}))


def test_resolve_bundle_names_expands_and_dedups() -> None:
    template = Template("o/r", "main", profiles=["p"], templates=["core"])
    bundles = rb.Bundles.from_config(
        {"bundles": {"core": {}, "extra": {}}, "profiles": {"p": {"bundles": ["core", "extra"]}}}
    )
    assert rb.resolve_bundle_names(template, bundles) == ["core", "extra"]


# --- branch coverage: the arms line coverage could not see ---------------------


def test_resolve_to_path_map_omits_entries_that_are_not_remapped() -> None:
    """A file kept at its own path contributes nothing — the map is remaps only."""
    b = _bundles(a={"files": ["same.txt", {"source": "s", "dest": "d"}]})
    assert b.resolve_to_path_map(["a"]) == {"s": "d"}


def test_resolve_bundle_names_dedups_a_bundle_shared_by_two_profiles() -> None:
    """Profiles overlap by design (`core` is in most), so the skip arm is the normal case."""
    template = Template("o/r", "main", profiles=["p1", "p2"])
    bundles = rb.Bundles.from_config(
        {
            "bundles": {"core": {}, "extra": {}},
            "profiles": {"p1": {"bundles": ["core", "extra"]}, "p2": {"bundles": ["core"]}},
        }
    )
    assert rb.resolve_bundle_names(template, bundles) == ["core", "extra"]
