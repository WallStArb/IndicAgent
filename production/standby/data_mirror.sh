#!/usr/bin/env bash
# Second copy of everything under ~/dev on ubuntu1 that git does not hold or that is not yet
# pushed: untracked data, logs, other projects, and .git (so unpushed commits survive). Pull
# only: the key on ubuntu1 is restricted to read-only rsync of /home/bg/dev (rrsync -ro), so this
# host cannot modify it. No --delete: a name removed on ubuntu1 stays in the mirror. Rebuildable
# trees (.venv, node_modules, caches) are skipped. A live .git can be momentarily inconsistent
# mid-copy; the next run repairs it.
set -euo pipefail
SRC=${MIRROR_SRC:-bg@192.168.68.60}
KEY=${MIRROR_KEY:-/home/bg/.ssh/mirror_ed25519}
DST=${MIRROR_ROOT:-/home/bg/mirror/dev}
mkdir -p "$DST"
rc=0
rsync -a --partial -e "ssh -i $KEY -o BatchMode=yes" \
  --exclude .venv --exclude node_modules --exclude __pycache__ --exclude .next --exclude .pytest_cache \
  "$SRC:." "$DST/" || rc=$?
# 24 = source files vanished mid-transfer (rotating logs); not an error for a mirror
(( rc == 0 || rc == 24 )) || exit "$rc"
echo "mirror complete $(date -u +%FT%TZ)"
