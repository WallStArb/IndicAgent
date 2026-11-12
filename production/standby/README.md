# ubuntu2 standby, backup and mirror

Units and scripts for the second server (`ubuntu2`, `192.168.68.65`). Plan and record: `docs/reference/server-migration-runbook.md`, Phase 5. Not part of `production/systemd/` (those units belong to `ubuntu1`).

| Piece | What it does |
|---|---|
| `timescaledb` container (plain `docker run`) | streaming standby, slot `ubuntu2_standby`, `hot_standby_feedback` on |
| `indicagent-pg-wal-archive.service` | `pg_receivewal` into `~/backup/wal` (gzip), slot `ubuntu2_archive` |
| `pg_base_backup.sh` + timer (Sun 03:00 UTC) | `pg_basebackup` tar, `pg_verifybackup`, keep 3, prune WAL the oldest kept backup does not need |
| `restore_drill.sh` | newest base backup + WAL to an LSN in a scratch container, compare table counts with a reference file |
| `data_mirror.sh` + timer (04:30 UTC) | pull `~/dev` from `ubuntu1` with a read-only key (`rrsync -ro /home/bg/dev`), no delete |

Install: copy `*.sh` to `~/standby/`, units to `/etc/systemd/system/`, `systemctl enable --now` the archive service and both timers. Needs `~/.pgpass` with the `replicator` password for db `replication`, and `~/.ssh/mirror_ed25519` whose public half sits in `ubuntu1`'s `authorized_keys` with `command="/usr/bin/rrsync -ro /home/bg/dev",restrict`.

Drill: take counts and `pg_current_wal_lsn()` on the primary while it is quiet, `pg_switch_wal()`, wait for the segment to appear in `~/backup/wal`, then `restore_drill.sh <lsn> <counts file>`.
