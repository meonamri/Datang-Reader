#!/usr/bin/env bash
# Pre-flight for the IDME in-place upgrade. Run BEFORE `docker compose up -d`.
# Safe to invoke from any directory — paths are resolved relative to this
# script's own location, not the current working directory.
#
# - Creates the idme data dir the merged compose mounts (../docker-data/idme).
# - Asserts the sqlite bind sources (queue.db, token) are FILES, not dirs.
#   Docker auto-creates a missing bind source as a DIRECTORY, after which sqlite
#   fails with "unable to open database file". If one is missing, this creates
#   it as an empty file; if it's wrongly a directory, this aborts loudly.
set -euo pipefail

# This script lives in server/; compose binds ../docker-data relative to server/.
# Anchor to the script's own dir so the resolved path matches compose regardless
# of the caller's CWD (running from the repo root would otherwise create the
# files in the wrong ~/docker-data).
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="$(cd "$SCRIPT_DIR/.." && pwd)/docker-data"

echo "Pre-flight: IDME volumes (data dir: $DATA_DIR)"

# 1. idme data dir (database + screenshots) — must exist as a directory.
mkdir -p "$DATA_DIR/idme"
echo "  ok   $DATA_DIR/idme (directory)"

# 2. sqlite / token bind sources must be files.
fail=0
for f in queue.db token; do
  path="$DATA_DIR/$f"
  if [ -d "$path" ]; then
    echo "  FAIL $path is a DIRECTORY — Docker created it from a missing bind"
    echo "       source. Stop the container, remove this dir, restore the real"
    echo "       file (or let this script create an empty one), and retry."
    fail=1
  elif [ -f "$path" ]; then
    echo "  ok   $path (file)"
  else
    : > "$path"
    echo "  made $path (was missing; created empty file)"
  fi
done

if [ "$fail" -ne 0 ]; then
  echo "Pre-flight FAILED — fix the directory bind sources above before 'up'." >&2
  exit 1
fi

echo "Pre-flight OK. Safe to run: docker compose up -d --build"
