# Disaster Recovery

**Version:** 3.0
**Status:** current (rewritten 2026-11-13 for the ubuntu2 standby and backup build)
**Last Updated:** 2026-11-13

How the database and the permanent data survive the loss of `ubuntu1` (primary, `192.168.68.60`). Design and build record: `docs/reference/server-migration-runbook.md`, Phase 5. Units and scripts: `production/standby/`. The earlier pg_dump-era procedures (v2.x tables, `/var/backups/indicagent`, plugin-state and Kafka sections) are gone; they survive in git history.

## Design

A replica is not a backup: a destructive statement replicates at once. The backup is the WAL archive plus base backups, all pulled by `ubuntu2` (`192.168.68.65`).

| Piece | What it gives | Schedule |
|---|---|---|
| Streaming standby (slot `ubuntu2_standby`) | hot copy of the primary, read-only, promoted by hand and never automatically | continuous |
| WAL archive (`indicagent-pg-wal-archive`, `pg_receivewal`, slot `ubuntu2_archive`) | point-in-time restore to any moment since the oldest kept base backup | continuous |
| Base backup (`pg_base_backup.sh`, timer) | `pg_basebackup` tar, verified with `pg_verifybackup`, newest 3 kept, WAL older than the oldest kept backup pruned | Sunday 03:00 UTC |
| Restore drill (`restore_drill.sh`) | newest base backup plus WAL recovered to an LSN in a scratch container, table counts compared with the primary | manual, after any change to the backup scripts and at least monthly |
| Data mirror (`data_mirror.sh`, timer) | `~/dev` pulled to `~/mirror/dev` with a read-only key, no delete: untracked data, logs, `.env`, other projects, unpushed `.git` | daily 04:30 UTC |

The primary caps slot retention with `max_slot_wal_keep_size = 100GB`, so a dead archive cannot fill its disk. Off-site copy is an open owner decision (two machines in one room do not survive fire or theft).

## Recovery objectives

| Component | RPO | RTO | Basis |
|---|---|---|---|
| TimescaleDB | seconds (WAL streams continuously; bounded by archive lag) | about 10 minutes to a recovered scratch instance | drill 2026-11-12: extract 465 s, recovery 11 s, total 497 s; 10 of 10 table counts equal |
| Permanent files (data, logs, `.env`) | 24 hours | the time to copy `~/mirror/dev` back | daily mirror |
| Code | last push | `git clone`; the mirror holds unpushed commits | git |
| Python and Node environments | none | rebuild: `.venv` from `requirements.txt`, `npm ci` in `dashboard/` | excluded from the mirror |

RTO excludes provisioning a replacement server and restoring a 40 GB base backup to a new disk; those scale with the hardware.

## Recovery procedures

All run on `ubuntu2` unless stated. Confirm `hostname` first; a recovery here is declared by the owner.

**Primary lost, standby intact:** promote the standby by hand (runbook Phase 5, step 1; never automatic), then follow the Cloudflare step below. The standby is current to the last replayed WAL.

**Point-in-time restore (deleted data, bad write, standby also damaged):** stop writers on the primary first. Pick the target LSN or timestamp, then recover the newest verified base backup plus archived WAL into a scratch container exactly as `restore_drill.sh` does (its comments hold the container and `recovery_target` settings). The archive files are mode 600, so make them readable (`chmod a+r ~/backup/wal/*`) for the container's uid. Copy the needed tables or the whole cluster back with `pg_dump` and `pg_restore`.

**Server rebuilt from nothing:** install the same Ubuntu release, Docker and the repo path; bring up the Postgres image; restore as above. Then recover files from `~/mirror/dev` (`.env`, `production/.env`, `data/`), `git clone` the repo, rebuild the environments, `cd production && docker compose up -d`, and start the services in `_DAG_ORDER`.

**Remote access after a failover:** the web hostnames (`api`, `dash`, `grafana`) route through the `ubuntu1` tunnel. Move them to the `ubuntu2` tunnel in `production/cloudflare/tunnels.yml` and apply with `scripts/ops/cloudflare/apply_tunnel_ingress.py`. `ssh2.indicagent.com` already reaches `ubuntu2`.

## Verification

Run the restore drill after any change to the backup scripts and at least monthly: take table counts and `pg_current_wal_lsn()` on the primary while it is quiet, run `pg_switch_wal()`, wait for the segment in `~/backup/wal`, then `restore_drill.sh <lsn> <counts file> | tee ~/backup/restore_drill.log`. The log feeds the drill metric below; a log with a `DIFF` line or no `extract` line is treated as a failed drill. An untested backup does not count as a backup.

## Monitoring

`production/standby/standby_probe.sh` runs on `ubuntu1` every 5 minutes (`indicagent-standby-probe.timer`), reads `ubuntu2` over key-based ssh and writes node-exporter textfile metrics.

| Metric | Meaning |
|---|---|
| `standby_job_last_success_timestamp_seconds{task}` | newest verified base backup, last "mirror complete" in the journal, last passing drill log |
| `standby_unit_active{unit}`, `standby_unit_failed{unit}` | archive service, base backup and mirror units |
| `standby_wal_archive_newest_timestamp_seconds` | newest file in the WAL archive |
| `standby_probe_success`, `standby_probe_timestamp_seconds` | the probe itself; a missing fact becomes 0, so an unreadable job is red, never silent |

Prometheus rules (`alertmanager-rules.yml`, group `standby_backup`, tested by `alertmanager-rules.standby.test.yml` with `promtool test rules`): base backup older than 8 days, mirror older than 26 hours, WAL archive service inactive, any standby unit failed, probe blind. Grafana: Operations dashboard, row "Standby backup (ubuntu2)". Alerting is not wired to a pager; failure is visible on the dashboard and on the Prometheus alerts page.

## Open items

- Off-site encrypted copy of the backup archive (owner decision).
- The restore drill is manual. Its age shows on the dashboard but has no threshold or alert rule; add one if the drill moves to a timer.
