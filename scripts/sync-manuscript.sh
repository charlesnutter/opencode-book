#!/usr/bin/env bash
# Copy generated chapters from build/ into manuscript/ for release.
# Deliberate step, not automatic: syncing means "this output is worth shipping".
set -euo pipefail

cd "$(dirname "$0")/.."

shopt -s nullglob
chapters=(build/*.md)
chapters=("${chapters[@]/build\/manuscript.md}")

count=0
for f in "${chapters[@]}"; do
  [ -n "$f" ] || continue
  [ -f "$f" ] || continue
  cp "$f" "manuscript/$(basename "$f")"
  count=$((count + 1))
done

echo "synced $count chapter(s) to manuscript/"
echo "next: scripts/changelog.py --version vX.Y.Z"
