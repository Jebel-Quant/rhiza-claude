#!/usr/bin/env python3
"""List GitHub repositories tagged with a rhiza topic, as a JSON document.

A stdlib-only port of the `rhiza list` command (rhiza-cli's
`list_repos`), bundled with this plugin so `/rhiza:repos` works without the
`rhiza` CLI installed. It queries the GitHub Search API for repositories
carrying a given topic (default: ``rhiza``) and emits a single JSON document
on stdout.

Usage:
  uv run --python 3.12 --no-project python scripts/repos.py [--topic TOPIC] [--per-page N]

  --topic TOPIC   GitHub topic to search for (default: 'rhiza')
  --per-page N    maximum repositories to request (default: 50, max 100)

Set the ``GITHUB_TOKEN`` environment variable to raise the API rate limit.
On a network/API failure this prints the error to stderr and exits 1.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from typing import Any

_GITHUB_SEARCH_URL = "https://api.github.com/search/repositories"
_DEFAULT_TOPIC = "rhiza"
_DEFAULT_PER_PAGE = 50
_MAX_PER_PAGE = 100
_TIMEOUT = 15


def _fetch_repos(topic: str, per_page: int) -> list[dict[str, Any]]:
    """Fetch raw repository items from the GitHub Search API.

    Args:
        topic: GitHub topic to search for.
        per_page: Maximum number of repositories to request.

    Returns:
        The raw ``items`` list from the search response.

    Raises:
        urllib.error.URLError: If the API request fails.
    """
    url = f"{_GITHUB_SEARCH_URL}?q=topic:{topic}&per_page={per_page}"
    headers: dict[str, str] = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"

    req = urllib.request.Request(url, headers=headers)  # nosec B310  # noqa: S310
    with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:  # nosec B310  # noqa: S310
        data = json.loads(resp.read().decode())

    return list(data.get("items", []))


def _repo_record(item: dict[str, Any]) -> dict[str, Any]:
    """Project a GitHub Search API item down to the fields we report."""
    return {
        "name": item.get("name") or "",
        "full_name": item.get("full_name") or "",
        "description": item.get("description") or "",
        "url": item.get("html_url") or "",
        "topics": list(item.get("topics") or []),
        "language": item.get("language") or "",
        "stars": item.get("stargazers_count") or 0,
        "archived": bool(item.get("archived")),
        "updated_at": item.get("updated_at") or "",
        "pushed_at": item.get("pushed_at") or "",
    }


def build_document(topic: str, items: list[dict[str, Any]]) -> dict[str, Any]:
    """Assemble the JSON document from raw API items, sorted by full name."""
    repositories = sorted(
        (_repo_record(item) for item in items),
        key=lambda r: r["full_name"].lower(),
    )
    return {
        "topic": topic,
        "count": len(repositories),
        "repositories": repositories,
    }


def repos(topic: str, per_page: int) -> int:
    """Emit the JSON document for *topic*; return a process exit code."""
    try:
        items = _fetch_repos(topic, per_page)
    except urllib.error.URLError as exc:
        print(f"Failed to fetch repositories: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(build_document(topic, items), indent=2))
    return 0


def main(argv: list[str] | None = None) -> int:
    """Entry point: parse args and print the JSON document."""
    parser = argparse.ArgumentParser(
        description="List GitHub repositories with a rhiza topic as a JSON document.",
    )
    parser.add_argument(
        "-t",
        "--topic",
        default=_DEFAULT_TOPIC,
        help=f"GitHub topic to search for (default: {_DEFAULT_TOPIC!r}).",
    )
    parser.add_argument(
        "--per-page",
        type=int,
        default=_DEFAULT_PER_PAGE,
        help=f"Maximum repositories to request (default: {_DEFAULT_PER_PAGE}).",
    )
    args = parser.parse_args(argv)
    per_page = max(1, min(args.per_page, _MAX_PER_PAGE))
    return repos(args.topic, per_page)


if __name__ == "__main__":
    raise SystemExit(main())
