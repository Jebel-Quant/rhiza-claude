#!/usr/bin/env python3
"""Set the plugin version in both manifests, preserving JSON formatting.

Usage:
  python3 scripts/bump_version.py 0.3.0     # bare version, no leading 'v'

Rewrites the single `"version"` field in each of:
  - .claude-plugin/plugin.json      (top-level)
  - .claude-plugin/marketplace.json (the plugin entry)
"""

import re
import sys
from pathlib import Path

MANIFESTS = [
    ".claude-plugin/plugin.json",
    ".claude-plugin/marketplace.json",
]
VERSION_RE = re.compile(r'("version"\s*:\s*")[^"]*(")')


def main() -> None:
    if len(sys.argv) != 2 or not sys.argv[1]:
        print("usage: bump_version.py <version>  (e.g. 0.3.0)", file=sys.stderr)
        sys.exit(2)
    new = sys.argv[1].lstrip("v")

    for rel in MANIFESTS:
        path = Path(rel)
        text = path.read_text()
        text, n = VERSION_RE.subn(rf"\g<1>{new}\g<2>", text, count=1)
        if n != 1:
            print(f"error: expected exactly one version field in {rel}, found {n}", file=sys.stderr)
            sys.exit(1)
        path.write_text(text)
        print(f"{rel}: version -> {new}")


if __name__ == "__main__":
    main()
