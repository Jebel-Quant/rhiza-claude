#!/usr/bin/env bash
# Prepare a release: bump the manifest versions, regenerate CHANGELOG.md,
# commit, and tag. Does NOT push — review, then push commit + tag yourself.
#
# Usage: scripts/release.sh vX.Y.Z
set -euo pipefail

VERSION="${1:-}"
if [[ -z "$VERSION" ]]; then
  echo "usage: scripts/release.sh vX.Y.Z" >&2
  exit 2
fi
if [[ "$VERSION" != v* ]]; then
  echo "error: version must start with 'v' (e.g. v0.3.0)" >&2
  exit 1
fi
BARE="${VERSION#v}"

if [[ -n "$(git status --porcelain)" ]]; then
  echo "error: working tree is not clean — commit or stash first" >&2
  exit 1
fi
if git rev-parse -q --verify "refs/tags/$VERSION" >/dev/null; then
  echo "error: tag $VERSION already exists" >&2
  exit 1
fi

echo "==> Bumping manifests to $BARE"
uv run --python 3.12 --no-project python scripts/bump_version.py "$BARE"

echo "==> Verifying manifest version parity"
uv run --python 3.12 --no-project python scripts/check_version_parity.py

echo "==> Regenerating CHANGELOG.md (git-cliff, including $VERSION)"
uvx git-cliff --tag "$VERSION" --output CHANGELOG.md

echo "==> Committing and tagging"
git add .claude-plugin/plugin.json .claude-plugin/marketplace.json CHANGELOG.md
git commit -m "chore: release $VERSION"
git tag "$VERSION"

cat <<EOF

Release $VERSION prepared locally.

Next:
  git push origin HEAD          # push the release commit
  git push origin $VERSION       # push the tag -> triggers the Release workflow

The Release workflow re-verifies that the manifests match $VERSION before publishing.
EOF
