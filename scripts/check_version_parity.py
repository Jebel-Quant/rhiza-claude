#!/usr/bin/env python3
"""Assert plugin.json and marketplace.json declare the same plugin version.

Used as a pre-commit hook so the two manifests can never drift (the mistake
that produced a 0.1.0 / v0.2.0 mismatch). Exits non-zero on mismatch.
"""

import json
import sys
from pathlib import Path


def main() -> None:
    plugin = json.loads(Path(".claude-plugin/plugin.json").read_text())["version"]
    entries = json.loads(Path(".claude-plugin/marketplace.json").read_text())["plugins"]
    mismatches = [e["name"] for e in entries if e.get("version") != plugin]
    if mismatches:
        market = {e["name"]: e.get("version") for e in entries}
        print(
            f"Version mismatch: plugin.json={plugin} but marketplace.json entries={market}",
            file=sys.stderr,
        )
        sys.exit(1)
    print(f"manifest versions match: {plugin}")


if __name__ == "__main__":
    main()
