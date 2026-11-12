#!/usr/bin/env bash
# Restore drill: newest verified base backup + archived WAL, recovered to a given LSN in a
# scratch container (port 5433), then table counts compared with a reference file taken on the
# primary at that LSN. Usage: restore_drill.sh <target_lsn> <reference_counts_file>
# Reference lines are "<table> <count>". Removes the scratch container and volume at the end.
set -euo pipefail
LSN=$1; REF=$2
ROOT=${BACKUP_ROOT:-/home/bg/backup}
IMAGE=${PG_IMAGE:-production-timescaledb:latest}
VOL=drill_pgdata
BASE=$(find "$ROOT/base" -mindepth 1 -maxdepth 1 -type d -not -name '*.partial' | sort | tail -n1)
PGD=/var/lib/postgresql/18/docker
cleanup() { docker rm -f restore-drill >/dev/null 2>&1 || true; docker volume rm "$VOL" >/dev/null 2>&1 || true; }
cleanup; trap cleanup EXIT
# pg_receivewal writes mode 600; the container runs as another uid
chmod a+r "$ROOT"/wal/*
t0=$(date +%s)
docker volume create "$VOL" >/dev/null
docker run --rm --user root -v "$VOL":/var/lib/postgresql -v "$BASE":/backup:ro "$IMAGE" sh -c \
  "mkdir -p $PGD && tar -xzf /backup/base.tar.gz -C $PGD && \
   printf \"restore_command = 'test -f /wal/%%f.gz && gunzip -c /wal/%%f.gz > %%p'\nrecovery_target_lsn = '$LSN'\nrecovery_target_action = 'promote'\n\" >> $PGD/postgresql.auto.conf && \
   touch $PGD/recovery.signal && chown -R postgres:postgres /var/lib/postgresql && chmod 700 $PGD"
t1=$(date +%s)
docker run -d --name restore-drill -p 127.0.0.1:5433:5432 --shm-size 4g \
  -v "$VOL":/var/lib/postgresql -v "$ROOT/wal":/wal:ro "$IMAGE" \
  postgres -c max_connections=200 -c max_locks_per_transaction=16384 -c wal_buffers=8192 -c shared_buffers=4GB >/dev/null
for _ in $(seq 1 360); do
  state=$(docker exec restore-drill psql -U postgres -Atc "select pg_is_in_recovery()" 2>/dev/null || echo starting)
  [[ $state == f ]] && break
  [[ $(docker inspect -f '{{.State.Running}}' restore-drill) == true ]] || break
  sleep 10
done
[[ $state == f ]] || { docker logs --tail 20 restore-drill; echo "recovery did not finish" >&2; exit 1; }
t2=$(date +%s)
fail=0
while read -r table expected; do
  [[ $table == LSN_* ]] && continue
  got=$(docker exec restore-drill psql -U postgres -d indicagent -Atc "select count(*) from $table")
  if [[ $got == "$expected" ]]; then echo "OK    $table $got"; else echo "DIFF  $table restored=$got reference=$expected"; fail=1; fi
done < "$REF"
echo "extract $((t1-t0)) s, recovery $((t2-t1)) s, total $(( $(date +%s)-t0 )) s"
exit "$fail"
