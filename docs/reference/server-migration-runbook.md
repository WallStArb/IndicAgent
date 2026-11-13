# Server migration runbook

**Version:** 1.0
**Status:** cutover done 2026-11-12 (Phases 0-3 executed; Phase 4 soak running; Phase 5 pending). Deviations are in the Cutover record below.
**Last Updated:** 2026-11-11

Moves the platform from the current server (call it OLD: 24 threads, 29 GB RAM, 914 GB disk) to a new mini PC (call it NEW: Ryzen AI 9 HX 370, 64 GB RAM, 2 TB NVMe), then turns OLD into the backup and read-only research box. Written by a Claude Code session at the owner's request. Treat every command as unverified until the first run, and correct this doc where reality differs.

Decision (owner 2026-11-11): NEW becomes the main server because it has the memory and disk; OLD is reformatted after NEW is proven and becomes backup, standby and research compute.

## Inventory (measured 2026-11-11 on OLD)

| Item | Value |
|------|-------|
| Postgres | PG 18.4 in the `timescaledb` container, image built from `production/Dockerfile.timescaledb` (`timescale/timescaledb:latest-pg18` plus pgvector v0.8.2), TimescaleDB extension 2.27.1 |
| Postgres data | Docker volume `production_timescale-data`, mounted at `/var/lib/postgresql`, data directory `/var/lib/postgresql/18/docker`; database 73 GB; `wal_level=replica`, `max_wal_senders=10` |
| Tuning | `production/docker-compose.yml` command block: `shared_buffers=7GB`, `work_mem=128MB`, `max_connections=200`, `max_locks_per_transaction=16384`, `shm_size 13g` (decision D-38, sized for 29 GB) |
| Other containers | redpanda (6 GB limit, transport only), ib-gateway, otel-collector, prometheus, grafana, loki, tempo, alertmanager, node-exporter, two postgres-exporters; sibling project `ssfi-timescaledb` with its own volume |
| Host services | 53 unit files in `/etc/systemd/system` copied from `production/systemd/` (57 files); enabled timers: alpaca-nightly, bar-derivation-daily, bar-derivation-grid, bar-reconciliation-audit, borrow-capture, dividend-event-writer-yahoo, gateway-auth-probe, regime-coverage-auditor |
| Repo state outside git | `.env` (holds IB credentials; never print or commit), `.venv`, `data/` (85 GB `massive`, 3.9 GB `backups`, small others), `cache/`, `research/`, `logs/` (1.4 GB) |
| Paths | units and configs use `/home/bg/dev/indicagent` and user `bg`; NEW uses the same user and path so no unit file changes |
| Privileged steps | OLD requires a sudo password; every step marked (root) is run by the owner, for example with `! sudo ...` in the session |

## Principles for this move

1. Physical replication, never `pg_dump`. Hypertable chunks do not restore from dumps (`docs/operations/operations-database.md`, Backups); a streaming copy is exact, keeps OLD running, and makes the cutover a short window.
2. One writer at all times. Exactly one box runs the services, timers, IB Gateway and Postgres in read-write mode. The second box is read-only until the instant of promotion.
3. OLD stays untouched and bootable until NEW has passed acceptance and a week of soak. That is the rollback.
4. Nothing moves while a fingerprinted batch run or backfill is in flight. Check first; see the cutover preconditions.
5. Copy images, do not rebuild them. `latest-pg18` is a floating tag; rebuilding on NEW could pull a different TimescaleDB, and a replica needs the same binaries as its primary.

## Phase 0: preparation on OLD (no downtime)

1. Record the baseline for acceptance: row counts and max timestamps of the key tables, `ops_pg_settings_baseline.py` output, and the `systemctl list-timers` listing. Save under `data/scratch/migration-baseline/`.
2. Commit anything uncommitted that belongs in git (`git status -sb`). NEW is populated by `git clone`, so uncommitted work does not travel.
3. Confirm disk headroom on OLD for retained WAL while the replication slot exists: at least 100 GB free (646 GB free today).
4. Decide the sibling `ssfi-timescaledb` project: it is outside this runbook. Either leave it on OLD, or move its volume with the stop-and-copy procedure in `docs/operations/operations-database.md` after the main cutover. Do not leave it unplanned.

## Phase 1: build NEW (OLD keeps running)

1. Install Ubuntu Server 26.04 LTS on NEW (same release as OLD) with OpenSSH, over ethernet, with LVM. Create user `bg`. Give the root filesystem or the Docker data-root the full 2 TB; keep free space at least twice the largest hypertable before any decompress and recompress migration (the 768 GB incident rule in `CLAUDE.md`).
2. Install Docker Engine and the compose plugin, `uv`, `git`, Python build prerequisites, and a Postgres 18 client (`postgresql-client-18`). Match OLD's versions of Docker and the Postgres client.
3. Add the SSH key from OLD (or a new key) to GitHub as a deploy or user key, then `git clone` the repo to `/home/bg/dev/indicagent`.
4. Rebuild the environment with `uv sync` from `uv.lock`; do not copy `.venv`. Copy `.env` from OLD with `scp` (it carries credentials) and set mode 600.
5. Copy untracked data with `rsync -a --info=progress2` from OLD: `data/`, `cache/`, `research/`, and `logs/` (logs are optional). Re-run the rsync during the cutover window to pick up changes.
6. Copy the images instead of rebuilding. For the Postgres image run, from OLD: `docker save production-timescaledb | ssh bg@NEW docker load`. Pull the pinned third-party images (grafana, prometheus, loki, tempo, otel, alertmanager, redpanda) from the registry; `ib-gateway:stable`, `postgres-exporter:latest` and `node-exporter:latest` float, so also `docker save` those two if exact parity matters.
7. Retune for 64 GB in `production/docker-compose.yml`. Redo the D-38 arithmetic with MemTotal 64 GB: `shared_buffers` 25 percent (16 GB), recompute `work_mem` and `shm_size` with the same formula, keep redpanda at its 6 GB limit. Keep `max_connections` and `max_locks_per_transaction` at or above OLD's values (a standby refuses to start with smaller values than its primary); `shared_buffers` and `work_mem` may differ. Commit this change as its own docs-and-config commit, after NEW is promoted (a standby ignores most of it until then).
8. Install units: copy `production/systemd/*` to `/etc/systemd/system/`, `systemctl daemon-reload`, install `production/indicagent-logrotate.conf`. Do not enable or start anything yet (root).

## Phase 2: replicate OLD to NEW (no downtime)

On OLD:

1. Create the replication role and slot (use a real password, not the repo's default `postgres`, for this role):
   ```sql
   CREATE ROLE replicator WITH REPLICATION LOGIN PASSWORD '<generated>';
   SELECT pg_create_physical_replication_slot('new_primary', true);
   ALTER SYSTEM SET max_slot_wal_keep_size = '100GB';
   SELECT pg_reload_conf();
   ```
2. Allow NEW in `pg_hba.conf` inside the data directory: `host replication replicator <NEW-ip>/32 scram-sha-256`, then reload. Port 5432 is already published by compose. Confirm the existing `host all all all` rule is the only broader opening and that nothing outside the LAN can reach 5432.

On NEW, with the container not running and the volume empty:

3. Take the base backup into the volume using the copied image so the binaries match:
   ```bash
   docker volume create production_timescale-data
   docker run --rm --network host --user postgres \
     -v production_timescale-data:/var/lib/postgresql \
     -e PGPASSWORD='<replicator password>' production-timescaledb \
     pg_basebackup -h <OLD-ip> -U replicator -D /var/lib/postgresql/18/docker \
       -X stream -S new_primary -R -P
   ```
   Expected time on a 1 GbE link: about 15 minutes for 73 GB. `-R` writes `standby.signal` and `primary_conninfo`.
4. Start the container (`docker compose up -d --no-deps --no-build timescaledb`, from `production/`). It comes up as a standby.
5. Verify: on OLD `SELECT * FROM pg_stat_replication;` shows `streaming`; on NEW `SELECT pg_is_in_recovery();` returns true; replay lag stays near zero after catching up. Run a read-only row-count comparison against the Phase 0 baseline.

The standby can run for days. Watch OLD's WAL retention for the slot (`pg_replication_slots`, `wal_status`); the 100 GB cap makes the slot invalidate before it fills the disk, at the price of re-running step 3.

## Phase 3: cutover

Preconditions, all verified, not assumed:

- No backfill, fetch or batch run in flight: `ps aux | grep -E 'backfill|fetcher|corpus|massive'`, `systemctl list-units --state=running | grep indicagent`, no held `FetcherLock`.
- Todo 600 (Massive admission) is either complete or stopped at a resumable boundary and nothing under `src/` or `services/` is being edited (the `code_content_key` rule: an edit to an imported module while a run is resumable discards its completed cells).
- Replica is within seconds of OLD, and the Phase 0 baseline exists.
- The owner is at hand for IB Gateway two-factor approval.

Steps:

1. On OLD stop the timers and services: `systemctl stop 'indicagent-*.timer'`, then the wave and infrastructure targets in reverse order (wave4 down to wave1), then dashboard and api (root).
2. Stop OLD's IB Gateway container (`docker stop ib-gateway`). Two sessions on one account evict each other.
3. Stop OLD's Postgres cleanly: `docker stop timescaledb`. A clean stop writes the shutdown checkpoint and sends it to the standby. Note the final LSN from `docker run --rm ... pg_controldata` against the OLD volume.
4. On NEW wait until `pg_last_wal_replay_lsn()` equals that final LSN, then promote: `docker exec timescaledb psql -U postgres -c "SELECT pg_promote();"`. Confirm `pg_is_in_recovery()` is false. Clear the leftover primary setting: `ALTER SYSTEM RESET primary_conninfo;` and reload.
5. Leave OLD's Postgres stopped from here on; restart it only for a rollback.
6. Final `rsync` of `data/`, `cache/` and `research/` from OLD to NEW (step 5 of Phase 1 again).
7. Acceptance gate before any writer starts:
   - Row counts and max timestamps match the Phase 0 baseline.
   - `scripts/ops/db/ops_pg_settings_baseline.py` reports no drift against the new `docker-compose.yml`.
   - `.venv/bin/pytest tests/unit/ -n auto` passes on NEW.
   - `.venv/bin/python -m scripts.research.determinism.repro_frozen <scratch_dir> --logs /home/bg/dev/indicagent/logs` reports bit-identical. A different CPU or library build can change floats; a failure here stops the migration until explained.
8. Commit point: start NEW's stack. `systemctl start indicagent-infrastructure.target`, then the waves in order, then the IB Gateway container; the owner approves two-factor; run the gateway probe. After the first writer starts there is no rollback; fix forward.
9. Enable only NEW's timers (`systemctl enable --now` for the eight listed in the inventory). Check `systemctl list-timers` matches the Phase 0 listing.
10. Disable OLD's timers and units so a reboot cannot restart them: `systemctl disable` and `mask` (root).
11. Network identity: either give NEW OLD's reserved IP in the router (OLD powered off first, or re-addressed) or keep both IPs and update `~/.ssh/config` on clients. If NEW takes the old address, run `ssh-keygen -R <ip>` on clients to clear the changed host key warning.

Rollback (valid only before step 8): `docker stop` on NEW, then on OLD `docker start timescaledb`, ib-gateway and the services in wave order. OLD was shut down cleanly and never promoted, so it resumes as it was. Remove NEW's promoted state by re-running Phase 2 later.

## Phase 4: soak (one week)

- Watch the nightly chain on NEW: alpaca-nightly, bar-derivation, dividend event writer, regime coverage auditor. Check Grafana at `:3001` and `service_auditor`.
- Keep OLD powered but with services disabled. Do not delete anything on it.
- After one clean week and one clean nightly cycle, proceed to Phase 5.

## Phase 5: OLD becomes standby, backup and research box

Reformat OLD with the same Ubuntu release, user `bg`, Docker, and the same repo path. Then:

1. Standby: `docker save` the Postgres image from NEW to OLD and repeat Phase 2 in the opposite direction, with a replication slot named for OLD and `hot_standby_feedback = on` on the standby (prevents long research queries being cancelled by replication conflicts; it costs some bloat on the primary, accepted). Standby is read-only; promotion is by hand and never automatic.
2. Point-in-time backups without changing the Postgres image. pgBackRest would need the binary inside the container, which means changing the image; avoid that. Use OLD instead: a systemd service running `pg_receivewal` against a second replication slot (continuous WAL archive), plus a weekly `pg_basebackup -Ft -z --wal-method=none` of NEW, plus a pruning script that keeps the newest N base backups and the WAL they need. Set `max_slot_wal_keep_size` on NEW so a dead OLD cannot fill NEW's disk.
3. A replica is not a backup: a destructive statement replicates at once. The archive in step 2 is the backup.
4. Restore drill (required, recorded here with its measured duration): restore the latest base backup plus WAL into a scratch container on another port, run to a chosen timestamp, and compare row counts with NEW. An untested backup does not count as a backup.
5. Mirror the non-Postgres permanent data to OLD by a pull from OLD (a systemd timer on OLD running `rsync` from NEW; the pull direction means OLD cannot modify NEW): `data/massive`, `data/backups`, raw captures, `logs/`, and `git fetch` of the repo. Raw market data is permanent under the project rules, so it deserves a second copy.
6. Off-site: two boxes in one room do not survive fire or theft. Owner decision pending: an encrypted copy of the backup archive to cloud storage or an external drive, on a schedule.

## Research worker role (later, only when compute is the bottleneck)

OLD runs research against its local standby and returns results to NEW. It never ingests, backfills, captures from any vendor, runs a second IB Gateway session, or commits code.

- Single writer: `research_run` keeps its one writer, the S6 ledger. The worker computes and sends results to NEW through that single writer connection; replication carries the rows back to OLD.
- Determinism: pin the worker to the same git commit and `uv.lock` as NEW, pin each run to a snapshot hash so replica lag cannot change an input, and run `repro_frozen` on the worker before its first counted run.
- Open question to verify in code before building: whether `src/config/Settings` can express one read DSN and one write DSN. If not, that is a todo, not a workaround.
- Trigger: build this when a counted run is waiting on CPU. The corpus rerun (span-major, parallel across chunks) is the first likely consumer. Before then, the standby and backups are the whole job.

## Open items

- Rehearse Phases 1 and 2 on NEW before the cutover window; Phase 3 timing and the exact `pg_basebackup` ownership flags are the least certain steps.
- Decide the `ssfi-timescaledb` sibling project (Phase 0, item 4).
- Update `CLAUDE.md` ("Claude Code runs ON this machine", the IP `192.168.68.60`) and memory after cutover; record the cutover date and any deviations here.

## Cutover record (2026-11-12)

Executed from OLD over SSH, owner approving. Deviations from the plan above:

- Owner decision: NEW runs the latest of everything; on any mismatch OLD is upgraded, never NEW downgraded. The Postgres image was built on NEW from `latest-pg18` (PG 18.6, TimescaleDB 2.32.0, pgvector 0.8.7, llvm21 build deps) instead of copying OLD's image. A newer-minor standby replayed OLD's PG 18.4 / TimescaleDB 2.27.1 stream without trouble; the extension catalogs were updated with `ALTER EXTENSION` after promotion.
- Python: `uv.lock` covers only the dev group; the runtime set is `requirements.txt`. NEW's venv is built from it at the newest versions. scipy 1.18 changed three outputs, fixed in code and gated: `rank_float64` (float32 ranks), local skew and kurtosis in `research/evaluate.py` (d**3 and d**4 moments), regime goldens regenerated with a flip report (no label flips). `repro_frozen` is bit-identical on the new stack.
- The base backup took about six minutes for 88 GB; promotion was at LSN 204D/D84100E8 after OLD's clean shutdown (checkpoint 204D/D8410070). Counts matched the baseline in `data/scratch/migration-baseline/`.
- The IB Gateway first-prompt 2FA expired before approval; a container restart sent a fresh prompt and the probe then reported authenticated.
- The dashboard needed `npm ci` before first start; NEW also needed the Node install.
- OLD's units are disabled and its Postgres and gateway containers set to `restart=no`; OLD's Postgres volume is intact for rollback until the soak ends.
- Network identity: NEW took the old address `192.168.68.60` and OLD moved to `192.168.68.65`, both as fixed addresses in netplan (OLD first, then NEW, each with a rollback script). Router reservations for the two MAC addresses (NEW `38:05:25:30:cb:a3`, OLD `c8:ff:bf:0d:1a:d6`) are still worth adding so the DHCP pool never hands those addresses out. `.61` belongs to another device.
- Cloudflare tunnel (`cloudflared`, remotely managed ingress) and remote SSH through `ssh.indicagent.com` now run from NEW; OLD's tunnel is disabled.

## Phase 5 record (2026-11-12)

`ubuntu2` was reformatted the same day (soak dropped by the owner: still building, not production). Units and scripts: `production/standby/`.

- Standby: slot `ubuntu2_standby`, base backup 92.8 GB in about 6 minutes, streaming with zero replay lag. Settings scaled to 29 GB (`shared_buffers` 7GB, `work_mem` 128MB); `max_connections` and `max_locks_per_transaction` equal the primary's.
- Backup: `pg_receivewal` archive (slot `ubuntu2_archive`) plus weekly base backup (first one 40 GB gzip, verified).
- Restore drill passed: first base backup plus WAL recovered to LSN `204D/E90F2000` in a scratch container; 10 of 10 table counts equal the primary's at that point. Duration 497 s (extract 465 s, recovery 11 s).
- Mirror: `~/dev` pulled daily (87 GB first run). The pull key on `ubuntu1` allows only read-only rsync of `/home/bg/dev`; a write and a shell login were both refused.
- `pg_receivewal` writes mode 600 files, so a restore container running as another uid cannot read them; `restore_drill.sh` makes the archive readable first, and a real restore must do the same.
- Open: off-site copy (owner decision). Failed or stale jobs are visible through `standby_probe.sh` metrics, rules and a Grafana row (2026-11-13); the disaster recovery doc is rewritten to match this design.

