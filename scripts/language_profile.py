#!/usr/bin/env python3
"""Report a repo's language and the facts that follow from it — one place, not five.

`/rhiza:init` learned Go and Rust, and nothing downstream did. `/quality` ran gates
named for `src/` and `pyproject.toml`, `design-analysis` reached for `radon`, and
`render_badges` could only describe a Python project — so a synced Go repo scored as
*broken* rather than as *a Go repo*, which is the same category error `/quality`
already guards against for unsynced repos.

The cause was that "what this language looks like" was written down independently
wherever it was needed. This module is the single answer: each language's manifest,
source root, lockfile, toolchain pin, and the complexity tooling its ecosystem
actually ships. Adding a language is one entry here plus its tests, and the consumers
follow.

**Facts only.** Everything here is a property of the language ecosystem — that a Rust
crate is described by `Cargo.toml`, that `radon` is a Python tool. Nothing about which
`make` targets a rhiza template provides lives here: those vary by template and
profile, are discovered at runtime by `check_make_targets.py`, and asserting them from
a table is how prose starts lying about repos it has never seen.

Detection prefers what the repo declares over what it looks like: an explicit
`--language`, then `language:` in `.rhiza/template.yml`, then the manifest on disk.
A repo with no manifest and no pointer is reported as `unknown` rather than guessed
into a default, because a wrong language is worse than an absent one — it produces a
confident scorecard measuring the wrong things.

Usage:
  uv run --python 3.12 --no-project python \\
      scripts/language_profile.py [TARGET] [--language python|go|rust] [--json]

Exit codes:
  0  a language was determined
  1  the language could not be determined (or is not one this plugin knows)
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class Language:
    """The facts about one language ecosystem that the commands need."""

    name: str
    manifest: str
    """The file that declares the project — the analogue of `pyproject.toml`."""
    source_root: str
    """Where the code lives, relative to the repo root. `.` when it isn't nested."""
    lockfile: str | None
    toolchain_pin: str | None
    """Where the language version is pinned, when it is pinned in a file of its own."""
    complexity: tuple[str, ...] = ()
    """Commands that yield complexity evidence. May not be installed; the caller falls
    back to reading the code, exactly as `design-analysis.md` already does for radon."""
    graph: tuple[str, ...] = ()
    """Commands that expose the dependency/import graph."""
    test_layout: bool = False
    """Whether `check_test_layout.py`'s 1:1 mirror rule applies. It is written around
    Python module and class naming, so it is not portable by assertion."""
    aliases: tuple[str, ...] = field(default_factory=tuple)


_LANGUAGES: dict[str, Language] = {
    "python": Language(
        name="python",
        manifest="pyproject.toml",
        source_root="src",
        lockfile="uv.lock",
        toolchain_pin=".python-version",
        complexity=("uvx radon cc {src} -a -s", "uvx radon mi {src} -s"),
        graph=("uvx pydeps {src} --max-bacon=2 --no-show",),
        test_layout=True,
    ),
    "go": Language(
        name="go",
        manifest="go.mod",
        source_root=".",
        lockfile="go.sum",
        # Go pins its toolchain inside go.mod (the `go` directive), not beside it.
        toolchain_pin=None,
        complexity=("gocyclo -avg -over 15 .", "go vet ./..."),
        graph=("go mod graph", "go list -deps ./..."),
        aliases=("golang",),
    ),
    "rust": Language(
        name="rust",
        manifest="Cargo.toml",
        source_root="src",
        lockfile="Cargo.lock",
        toolchain_pin="rust-toolchain.toml",
        # clippy's cognitive_complexity is the closest analogue to radon's CC that the
        # stock toolchain ships; it is allow-by-default, hence the explicit -W.
        complexity=("cargo clippy --all-targets -- -W clippy::cognitive_complexity",),
        graph=("cargo tree --edges normal",),
    ),
}

# Manifest -> language, for detecting a repo that has no pointer. Ordered, so a
# pyo3/maturin repo carrying both Cargo.toml and pyproject.toml resolves to rust —
# the Cargo manifest is the one that makes it a crate.
_BY_MANIFEST = (("Cargo.toml", "rust"), ("go.mod", "go"), ("pyproject.toml", "python"))


def languages() -> tuple[str, ...]:
    """Return every language name this plugin knows, in registry order."""
    return tuple(_LANGUAGES)


def resolve(name: str) -> Language | None:
    """Return the profile for *name* (or one of its aliases), or None."""
    key = name.strip().lower()
    for language in _LANGUAGES.values():
        if key == language.name or key in language.aliases:
            return language
    return None


def declared_language(target: Path) -> str | None:
    """Return the `language:` declared in `.rhiza/template.yml`, if any.

    Read with a deliberately small regex rather than the bundled YAML reader: this
    needs one top-level scalar, and a malformed pointer elsewhere in the file should
    not stop the language being found.
    """
    pointer = target / ".rhiza" / "template.yml"
    if not pointer.is_file():
        return None
    for line in pointer.read_text(errors="ignore").splitlines():
        key, sep, value = line.partition(":")
        if sep and key.strip() == "language":
            return value.strip().strip("\"'") or None
    return None


def detect(target: Path, explicit: str | None = None) -> tuple[Language | None, str]:
    """Determine *target*'s language; return the profile and how it was determined."""
    if explicit:
        return resolve(explicit), f"--language {explicit}"
    declared = declared_language(target)
    if declared:
        return resolve(declared), f".rhiza/template.yml declares language: {declared}"
    for manifest, name in _BY_MANIFEST:
        if (target / manifest).is_file():
            return _LANGUAGES[name], f"found {manifest}"
    return None, "no --language, no .rhiza/template.yml, and no recognised manifest"


def facts(language: Language, target: Path) -> dict[str, object]:
    """Render *language* as a flat dict, with its commands' `{src}` filled in."""
    src = language.source_root
    return {
        "language": language.name,
        "manifest": language.manifest,
        "manifest_present": (target / language.manifest).is_file(),
        "source_root": src,
        "lockfile": language.lockfile,
        "toolchain_pin": language.toolchain_pin,
        "complexity": [c.format(src=src) for c in language.complexity],
        "graph": [g.format(src=src) for g in language.graph],
        "test_layout_applies": language.test_layout,
    }


def _report(data: dict[str, object], reason: str) -> str:
    """Render the human-readable summary."""
    lines = [f"language: {data['language']}  ({reason})"]
    present = "present" if data["manifest_present"] else "MISSING"
    lines.append(f"  manifest      {data['manifest']} ({present})")
    lines.append(f"  source root   {data['source_root']}")
    lines.append(f"  lockfile      {data['lockfile'] or '—'}")
    lines.append(f"  toolchain pin {data['toolchain_pin'] or '— (declared in the manifest)'}")
    lines.append(f"  test layout   {'applies' if data['test_layout_applies'] else 'not portable'}")
    for label, key in (("complexity", "complexity"), ("graph", "graph")):
        for command in data[key]:  # type: ignore[attr-defined]
            lines.append(f"  {label:<13} $ {command}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    """Entry point: detect the language and report its facts."""
    parser = argparse.ArgumentParser(description="Report a repo's language and its facts.")
    parser.add_argument("target", nargs="?", default=".", help="Repo root (default: cwd).")
    parser.add_argument("--language", help=f"Override detection ({', '.join(languages())}).")
    parser.add_argument("--json", action="store_true", help="Emit the facts as JSON.")
    args = parser.parse_args(argv)

    target = Path(args.target).resolve()
    language, reason = detect(target, args.language)
    if language is None:
        message = f"could not determine the language: {reason}"
        if args.json:
            print(json.dumps({"language": None, "reason": reason}, indent=2))
        else:
            print(message, file=sys.stderr)
            print(f"known languages: {', '.join(languages())}", file=sys.stderr)
        return 1

    data = facts(language, target)
    print(json.dumps(data, indent=2) if args.json else _report(data, reason))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
