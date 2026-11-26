#!/usr/bin/env bash
# Second copy of everything under ~/dev on ubuntu1 that git does not hold or that is not yet
# pushed: untracked data, logs, other projects, and .git (so unpushed commits survive). Pull
# only: the key on ubuntu1 is restricted to read-only rsync of /home/bg/dev (rrsync -ro), so this
# host cannot modify it. No --delete: a name removed on ubuntu1 stays in the mirror. Rebuildable
# trees (.venv, node_modules, caches) and the 92 GB tape slices (data/massive/tapes) are skipped.
# A live .git can be momentarily inconsistent mid-copy; the next run repairs it.
set -euo pipefail
SRC=${MIRROR_SRC:-bg@192.168.68.60}
KEY=${MIRROR_KEY:-/home/bg/.ssh/mirror_ed25519}
DST=${MIRROR_ROOT:-/home/bg/mirror/dev}
mkdir -p "$DST"
# Fail loudly before pulling when the mirror disk is nearly full (a full disk mid-pull leaves a
# torn copy); the floor is spare space in GB that must remain before the pull starts.
MIN_FREE_GB=${MIRROR_MIN_FREE_GB:-40}
avail_gb=$(( $(df -B1 --output=avail "$DST" | tail -1) / 1073741824 ))
if (( avail_gb < MIN_FREE_GB )); then
  echo "mirror REFUSED: ${avail_gb} GB free on $DST, floor ${MIN_FREE_GB} GB" >&2
  exit 3
fi
rc=0
rsync -a --partial -e "ssh -i $KEY -o BatchMode=yes" \
  --exclude .venv --exclude node_modules --exclude __pycache__ --exclude .next --exclude .pytest_cache --exclude /indicagent/data/massive/tapes \
  "$SRC:." "$DST/" || rc=$?
# 24 = source files vanished mid-transfer (rotating logs); not an error for a mirror
(( rc == 0 || rc == 24 )) || exit "$rc"
echo "mirror complete $(date -u +%FT%TZ)"
