#!/usr/bin/env bash
# Weekly base backup of the primary, verified, then prune. WAL comes from the pg_receivewal
# archive (indicagent-pg-wal-archive), so the base backup carries none (--wal-method=none).
# Keeps the newest KEEP backups and only the WAL the oldest kept one needs.
set -euo pipefail
HOST=${PG_HOST:-192.168.68.60}
ROOT=${BACKUP_ROOT:-/home/bg/backup}
KEEP=${KEEP_BASE_BACKUPS:-3}
exec 9>"$ROOT/.base_backup.lock"
flock -n 9 || { echo "another base backup is running" >&2; exit 1; }

stamp=$(date -u +%Y%m%dT%H%M%SZ)
tmp="$ROOT/base/$stamp.partial"
mkdir -p "$ROOT/base" "$ROOT/wal"
pg_basebackup -h "$HOST" -U replicator -D "$tmp" -Ft --compress=gzip:1 \
  --wal-method=none --no-slot --checkpoint=fast --manifest-checksums=sha256 \
  --label="ubuntu2-$stamp" --no-password
/usr/lib/postgresql/18/bin/pg_verifybackup -F tar --no-parse-wal "$tmp"
mv "$tmp" "${tmp%.partial}"
echo "base backup $stamp verified"

mapfile -t done_backups < <(find "$ROOT/base" -mindepth 1 -maxdepth 1 -type d -not -name '*.partial' | sort)
excess=$(( ${#done_backups[@]} - KEEP ))
(( excess > 0 )) || excess=0
for old in "${done_backups[@]:0:excess}"; do rm -rf -- "$old"; done
oldest_kept=${done_backups[excess]}
start_file=$(tar -xzOf "$oldest_kept/base.tar.gz" --occurrence=1 backup_label \
  | sed -n 's/^START WAL LOCATION: .*(file \([0-9A-F]\{24\}\))$/\1/p')
[[ -n $start_file ]] || { echo "could not read START WAL from $oldest_kept; WAL not pruned" >&2; exit 1; }
for f in "$ROOT"/wal/*; do
  name=${f##*/}
  [[ $name == *.history* ]] && continue
  segment=${name%%.*}
  if [[ $segment < $start_file ]]; then rm -f -- "$f"; fi
done
echo "pruned WAL older than $start_file; kept $(( ${#done_backups[@]} - excess )) backups"
