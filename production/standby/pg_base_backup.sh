#!/usr/bin/env bash
# Weekly base backup of the primary, verified, then prune. WAL comes from the pg_receivewal
# archive (indicagent-pg-wal-archive), so the base backup carries none (--wal-method=none).
# Keeps the newest KEEP backups and only the WAL the oldest kept one needs. Every check that can
# fail runs before anything is deleted. The primary caps slot retention with
# max_slot_wal_keep_size (set there with ALTER SYSTEM, 100GB), so a dead archive cannot fill it.
set -euo pipefail
export LC_ALL=C
HOST=${PG_HOST:-192.168.68.60}
ROOT=${BACKUP_ROOT:-/home/bg/backup}
KEEP=${KEEP_BASE_BACKUPS:-3}
mkdir -p "$ROOT/base" "$ROOT/wal"
exec 9>"$ROOT/.base_backup.lock"
flock -n 9 || { echo "another base backup is running" >&2; exit 1; }
systemctl is-active --quiet indicagent-pg-wal-archive \
  || { echo "WAL archive is not running; a base backup without it cannot be restored" >&2; exit 1; }
VERIFY=$(command -v pg_verifybackup || ls /usr/lib/postgresql/*/bin/pg_verifybackup | sort -V | tail -n1)

# START WAL segment name of a base backup directory
start_wal() {
  tar -xzOf "$1/base.tar.gz" --occurrence=1 backup_label \
    | sed -n 's/^START WAL LOCATION: .*(file \([0-9A-F]\{24\}\))$/\1/p'
}
# the segment may still be the archive's open .partial one
in_archive() { compgen -G "$ROOT/wal/$1.gz*" >/dev/null; }

stamp=$(date -u +%Y%m%dT%H%M%SZ)
tmp="$ROOT/base/$stamp.partial"
rm -rf -- "$ROOT"/base/*.partial   # leftovers of failed runs; the lock means none is live
trap 'rm -rf -- "$tmp"' EXIT       # no-op after the rename below
pg_basebackup -h "$HOST" -U replicator -D "$tmp" -Ft --compress=gzip:1 \
  --wal-method=none --no-slot --checkpoint=fast --manifest-checksums=sha256 \
  --label="ubuntu2-$stamp" --no-password
"$VERIFY" -F tar --no-parse-wal "$tmp"
new_start=$(start_wal "$tmp")
[[ -n $new_start ]] && in_archive "$new_start" \
  || { echo "new backup's start segment '$new_start' is not in the WAL archive; not kept" >&2; exit 1; }
mv "$tmp" "${tmp%.partial}"
echo "base backup $stamp verified"

mapfile -t done_backups < <(find "$ROOT/base" -mindepth 1 -maxdepth 1 -type d | sort)
excess=$(( ${#done_backups[@]} - KEEP ))
(( excess > 0 )) || excess=0
oldest_kept=${done_backups[excess]}
start_file=$(start_wal "$oldest_kept")
[[ -n $start_file ]] && in_archive "$start_file" \
  || { echo "oldest kept backup's start segment '$start_file' is missing; nothing pruned" >&2; exit 1; }

for old in "${done_backups[@]:0:excess}"; do rm -rf -- "$old"; done
for f in "$ROOT"/wal/*; do
  name=${f##*/}
  [[ $name == *.history* ]] && continue
  segment=${name%%.*}
  # compare log+segment only: the oldest kept backup may sit on an older timeline than the newest
  if [[ ${segment:8} < ${start_file:8} ]]; then rm -f -- "$f"; fi
done
echo "pruned WAL before $start_file; kept $(( ${#done_backups[@]} - excess )) backups"
