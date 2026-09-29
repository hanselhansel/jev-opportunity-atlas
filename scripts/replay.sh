#!/bin/sh
# Stranger replay: restore the public site bundle over plain HTTPS, verify its
# hashes, recompute every claim, build the site data, and (when node exists)
# build the site. Needs uv; no API key, no gh auth, no HN calls.
#
#   scripts/replay.sh <tag>
set -e
if [ -z "$1" ]; then
  echo "usage: scripts/replay.sh <tag>"
  exit 2
fi
TAG="$1"
DEST="${ATLAS_REPLAY_DEST:-data/releases}"
cd "$(dirname "$0")/.."
case "$DEST" in
  /*) ;;
  *) DEST="$(pwd)/$DEST" ;;
esac
START=$(date +%s)

uv sync --no-default-groups
# Keep later `uv run` calls (including the site's data loaders) on this env.
export UV_NO_SYNC=1

if [ -d "$DEST/$TAG" ]; then
  echo "restore: $DEST/$TAG already present, reusing it"
else
  uv run atlas release restore --release "$TAG" --dest "$DEST"
fi
uv run atlas release replay --release-dir "$DEST/$TAG" --site-out "$DEST/$TAG-site-data"

if command -v node >/dev/null 2>&1 && command -v npm >/dev/null 2>&1; then
  (cd site && npm ci)
  uv run atlas site build --data "$DEST/$TAG-site-data" --production
  echo "site: built into site/dist"
else
  echo "site: node not found, skipped the site build"
fi

END=$(date +%s)
echo "replay: done in $((END - START))s"
