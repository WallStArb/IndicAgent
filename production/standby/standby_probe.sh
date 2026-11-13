#!/usr/bin/env bash
# Runs on ubuntu1. Reads the state of the ubuntu2 backup jobs over key-based ssh and writes
# node-exporter textfile metrics, so a stale or failed backup shows in Prometheus and Grafana.
# Read-only on ubuntu2; it never changes what the backup scripts do. A missing fact becomes 0
# (an ancient timestamp), so an unreadable job turns red instead of silently absent.
set -euo pipefail
STANDBY=${STANDBY_HOST:-bg@192.168.68.65}
OUT=${TEXTFILE_DIR:-/var/lib/node-exporter-textfile}/standby.prom
tmp=$(mktemp "$OUT.XXXXXX")
trap 'rm -f "$tmp"' EXIT

# The remote side prints finished metric lines.
metrics=$(ssh -o BatchMode=yes -o ConnectTimeout=10 "$STANDBY" bash -s <<'REMOTE'
job() { echo "standby_job_last_success_timestamp_seconds{task=\"$1\"} ${2:-0}"; }
echo "# TYPE standby_job_last_success_timestamp_seconds gauge"
job base_backup "$(stat -c %Y ~/backup/base/*Z/backup_manifest 2>/dev/null | sort -n | tail -1)"
job data_mirror "$(journalctl -u indicagent-data-mirror.service -g 'mirror complete' -n1 -o short-unix --no-pager 2>/dev/null | grep -E '^[0-9]' | cut -d. -f1)"
log=~/backup/restore_drill.log
# a drill counts only if it compared tables and found no difference
if grep -q '^extract' "$log" 2>/dev/null && ! grep -q '^DIFF' "$log"; then drill=$(stat -c %Y "$log"); fi
job restore_drill "${drill:-}"
echo "# TYPE standby_wal_archive_newest_timestamp_seconds gauge"
echo "standby_wal_archive_newest_timestamp_seconds $(stat -c %Y ~/backup/wal/* 2>/dev/null | sort -n | tail -1 | grep . || echo 0)"
echo "# TYPE standby_unit_active gauge"
echo "# TYPE standby_unit_failed gauge"
for unit in indicagent-pg-wal-archive.service indicagent-pg-base-backup.service indicagent-data-mirror.service; do
  systemctl is-active --quiet "$unit" && a=1 || a=0
  systemctl is-failed --quiet "$unit" && f=1 || f=0
  echo "standby_unit_active{unit=\"$unit\"} $a"
  echo "standby_unit_failed{unit=\"$unit\"} $f"
done
REMOTE
) || metrics=""

{
  echo "# TYPE standby_probe_success gauge"
  echo "standby_probe_success $([[ -n $metrics ]] && echo 1 || echo 0)"
  echo "# TYPE standby_probe_timestamp_seconds gauge"
  echo "standby_probe_timestamp_seconds $(date +%s)"
  echo "$metrics"
} >"$tmp"
chmod 644 "$tmp"
mv "$tmp" "$OUT"
trap - EXIT
