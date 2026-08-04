#!/usr/bin/env python3
"""Apply or change a project's license — the engine behind `/rhiza:license`.

Sets the SPDX ``license`` / ``license-files`` metadata in ``pyproject.toml``
(Python repos) and the ``license`` key in ``Cargo.toml``'s ``[package]`` table
(Rust repos), and writes the ``LICENSE`` file's full text from the bundled
templates. Unlike the *greenfield* scaffolder, this **changes** an existing
license: it replaces the metadata, and (with ``--force``) overwrites an existing
``LICENSE`` file. Stdlib-only, so `/init` and `/license` can run it without the
`rhiza` CLI.

Usage:
  uv run --python 3.12 --no-project python \
      scripts/set_license.py [TARGET] --license SPDX --owner OWNER \
      [--license-year YYYY] [--force] [--json]

`--license none` clears the metadata and leaves any existing `LICENSE` in place.
Exit code 3 means an existing `LICENSE` differs and `--force` was not given.
"""

from __future__ import annotations

import argparse
import datetime
import json
import re
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _rhiza_toml import rejoin, require_table, table_end  # noqa: E402

DEFAULT_LICENSE = "none"
# Full-text license templates (`<SPDX id>.txt`, with `{year}`/`{holder}` fills).
_LICENSES_DIR = Path(__file__).resolve().parent / "licenses"
_NEEDS_FORCE = 3


def bundled_licenses() -> list[str]:
    """SPDX ids with a bundled full text, sorted."""
    return sorted(p.stem for p in _LICENSES_DIR.glob("*.txt"))


def render_license(license_id: str, holder: str, year: str) -> str | None:
    """Return the LICENSE text for an SPDX id (``{year}``/``{holder}`` filled).

    Returns ``None`` when no full text is bundled for *license_id*.
    """
    path = _LICENSES_DIR / f"{license_id}.txt"
    if not path.is_file():
        return None
    return path.read_text().replace("{year}", year).replace("{holder}", holder)


def _strip_keys(lines: list[str], header: int, end: int, key: re.Pattern[str]) -> list[str]:
    """Return *lines* without the lines in ``(header, end)`` whose key matches *key*.

    Bounded to the one table so a ``license`` under some other table is left alone.
    """
    return [line for i, line in enumerate(lines) if not (header < i < end and key.match(line))]


def set_license_metadata(text: str, license_id: str) -> tuple[str, bool]:
    """Force-set (or clear) SPDX ``license``/``license-files`` in ``[project]``.

    Removes any existing ``license``/``license-files`` lines, then — unless
    *license_id* is ``none`` — reinserts them (the PEP 639 expression field, never
    a deprecated ``License ::`` trove classifier). Returns ``(new_text, changed)``.
    """
    lines = text.splitlines()
    header, end = require_table(lines, "project", "pyproject.toml")
    kept = _strip_keys(lines, header, end, re.compile(r"^\s*license(-files)?\s*="))
    if license_id != DEFAULT_LICENSE:
        header, _ = require_table(kept, "project", "pyproject.toml")
        kept[header + 1 : header + 1] = [
            f'license = "{license_id}"',
            'license-files = ["LICENSE"]',
        ]
    new_text = rejoin(text, kept)
    return new_text, new_text != text


def set_cargo_license_metadata(text: str, license_id: str) -> tuple[str, bool]:
    """Force-set (or clear) the SPDX ``license`` key in Cargo's ``[package]`` table.

    Cargo's manifest has no ``license-files`` array — the SPDX expression goes in
    ``license``, and ``license-file`` is the escape hatch for a licence with no SPDX
    id. Both are removed first, then ``license`` is reinserted unless *license_id* is
    ``none``: leaving a stale ``license-file`` pointing at a replaced LICENSE would
    make ``cargo publish`` describe the wrong terms.

    Returns ``(new_text, changed)``.
    """
    lines = text.splitlines()
    header, end = require_table(lines, "package", "Cargo.toml")
    kept = _strip_keys(lines, header, end, re.compile(r"^\s*license(-file)?\s*="))
    if license_id != DEFAULT_LICENSE:
        # Appended to the end of the table, not under the header, so repeated runs
        # leave `name`/`version` where cargo put them instead of walking them down.
        header, end = require_table(kept, "package", "Cargo.toml")
        kept.insert(table_end(kept, header, end), f'license = "{license_id}"')
    new_text = rejoin(text, kept)
    return new_text, new_text != text


def _overwrite_needs_force(lic_path: Path, body: str | None, *, force: bool) -> bool:
    """Would writing *body* replace a different existing LICENSE without permission?"""
    return body is not None and lic_path.exists() and lic_path.read_text() != body and not force


def _apply_manifest_metadata(
    target: Path, license_id: str, modified: list[str], notes: list[str]
) -> None:
    """Write the licence key into whichever manifests *target* has, recording each.

    Both manifests are attempted rather than dispatched on a declared language: a repo can
    legitimately carry a pyproject.toml *and* a Cargo.toml (a pyo3/maturin extension), and
    the licence must not disagree between them.
    """
    for name, setter in (
        ("pyproject.toml", set_license_metadata),
        ("Cargo.toml", set_cargo_license_metadata),
    ):
        manifest = target / name
        if not manifest.exists():
            continue
        try:
            new_text, changed = setter(manifest.read_text(), license_id)
        except ValueError as exc:
            notes.append(f"{name}: {exc}")
        else:
            if changed:
                manifest.write_text(new_text)
                modified.append(name)


def _write_license_file(
    lic_path: Path, license_id: str, body: str | None
) -> tuple[str | None, str | None]:
    """Write the LICENSE file if it needs writing; return ``(bucket, note)``.

    *bucket* is which summary list should record ``LICENSE`` — ``created``, ``modified``,
    ``skipped``, or None when nothing was touched — and *note* is the explanation for the
    two cases where no file can be written.
    """
    if license_id == DEFAULT_LICENSE:
        return None, "license set to none — cleared metadata; any existing LICENSE left in place"
    if body is None:
        return None, (
            f"license {license_id}: no bundled text; add a LICENSE file manually "
            f"(bundled: {', '.join(bundled_licenses())})"
        )
    if lic_path.exists() and lic_path.read_text() == body:
        return "skipped", None
    existed = lic_path.exists()
    lic_path.write_text(body)
    return ("modified" if existed else "created"), None


def set_license(
    target: Path, *, license_id: str, holder: str, year: str, force: bool
) -> dict[str, Any]:
    """Apply *license_id* to the repo at *target*; return a summary dict."""
    buckets: dict[str, list[str]] = {"created": [], "modified": [], "skipped": []}
    notes: list[str] = []
    lic_path = target / "LICENSE"

    # Resolve the LICENSE-file text first, and refuse *before* touching anything
    # when an overwrite needs confirmation — so metadata and file never diverge.
    body = None if license_id == DEFAULT_LICENSE else render_license(license_id, holder, year)
    if _overwrite_needs_force(lic_path, body, force=force):
        return {
            "license": license_id,
            "created": [],
            "modified": [],
            "skipped": ["LICENSE"],
            "notes": ["LICENSE exists and differs — pass --force to overwrite"],
            "needs_force": True,
        }

    _apply_manifest_metadata(target, license_id, buckets["modified"], notes)

    bucket, note = _write_license_file(lic_path, license_id, body)
    if bucket is not None:
        buckets[bucket].append("LICENSE")
    if note is not None:
        notes.append(note)

    return {
        "license": license_id,
        **buckets,
        "notes": notes,
        "needs_force": False,
    }


def main(argv: list[str] | None = None) -> int:
    """Entry point: parse args, apply the license, return an exit code."""
    parser = argparse.ArgumentParser(description="Apply or change a project's license.")
    parser.add_argument(
        "target", nargs="?", default=".", help="Repository root (default: current directory)."
    )
    parser.add_argument(
        "--license",
        dest="license_id",
        required=True,
        help="SPDX license id to apply (e.g. MIT), or 'none' to clear.",
    )
    parser.add_argument("--owner", default="your-org", help="Copyright holder (default: your-org).")
    parser.add_argument(
        "--license-year", dest="license_year", help="Copyright year (default: current year)."
    )
    parser.add_argument("--force", action="store_true", help="Overwrite an existing LICENSE file.")
    parser.add_argument(
        "--json", dest="json_output", action="store_true", help="Emit the summary as JSON."
    )
    args = parser.parse_args(argv)

    if args.license_id != DEFAULT_LICENSE and render_license(args.license_id, "", "") is None:
        parser.error(
            f"no bundled text for --license {args.license_id!r}; "
            f"choose from {', '.join(bundled_licenses())} (or 'none')"
        )
    year = args.license_year or str(datetime.date.today().year)

    summary = set_license(
        Path(args.target).resolve(),
        license_id=args.license_id,
        holder=args.owner,
        year=year,
        force=args.force,
    )

    if args.json_output:
        print(json.dumps(summary, indent=2))
    else:
        for path in summary["created"]:
            print(f"created  {path}")
        for path in summary["modified"]:
            print(f"modified {path}")
        for path in summary["skipped"]:
            print(f"skipped  {path}", file=sys.stderr)
        for note in summary["notes"]:
            print(f"note     {note}", file=sys.stderr)
    return _NEEDS_FORCE if summary["needs_force"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
