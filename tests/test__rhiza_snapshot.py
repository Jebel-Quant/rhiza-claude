"""Tests for snapshot materialisation (`scripts/_rhiza_snapshot.py`).

Turning a template ref into a flat directory at destination paths — the input both
sides of the three-way merge are built from.
"""

from __future__ import annotations

import _rhiza_snapshot as snapshot


def test_remap_path_exact_prefix_and_none() -> None:
    assert snapshot._remap_path("a.txt", {"a.txt": "b.txt"}) == "b.txt"
    assert snapshot._remap_path("dir/x.txt", {"dir/": "out"}) == "out/x.txt"
    assert snapshot._remap_path("bundles/core/f", {"bundles/core/": ""}) == "f"
    assert snapshot._remap_path("unmapped.txt", {"a": "b"}) == "unmapped.txt"
