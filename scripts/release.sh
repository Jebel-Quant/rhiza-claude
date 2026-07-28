#!/usr/bin/env bash
# Prepare a release without an agent: bump every declared version location,
# regenerate CHANGELOG.md, commit, and tag. Does NOT push — review, then push the
# commit and tag yourself.
#
# This is the agent-free twin of `/rhiza:release`, and deliberately shares its two
# sources of truth so the two paths cannot drift:
#
#   [tool.bumpversion]              which files state the version (declarative, so a
#                                   dependency sharing the version is never rewritten)
#   scripts/check_version_bump.py   the strictly-increasing guard
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
PY=(uv run --python 3.12 --no-project python)

if [[ -n "$(git status --porcelain)" ]]; then
  echo "error: working tree is not clean — commit or stash first" >&2
  exit 1
fi

echo "==> Reading the declared current version"
CURRENT="$(uvx bump-my-version show current_version)"
echo "    current: $CURRENT"

# The guard bump-my-version does not provide: it accepts a backwards version and
# knows nothing about tags. A pushed tag is effectively permanent, so this check is
# what stops the one unrecoverable mistake in the flow.
echo "==> Guarding that $VERSION strictly increases"
"${PY[@]}" scripts/check_version_bump.py "$VERSION" --current "$CURRENT"

echo "==> Bumping every declared version location to $BARE"
uvx bump-my-version bump --new-version "$BARE" --no-commit --no-tag

echo "==> Verifying manifest version parity"
"${PY[@]}" scripts/check_version_parity.py

echo "==> Regenerating CHANGELOG.md (git-cliff, including $VERSION)"
uvx git-cliff --tag "$VERSION" --output CHANGELOG.md

echo "==> Committing and tagging"
# Safe because the tree was verified clean above: the only changes are ours.
git add --all
git commit -m "chore: release $VERSION"
git tag "$VERSION"

cat <<EOF

Release $VERSION prepared locally.

Next:
  git push origin HEAD          # push the release commit
  git push origin $VERSION       # push the tag -> triggers the Release workflow

The Release workflow re-verifies that the manifests match $VERSION before publishing.
EOF
