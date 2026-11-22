---
status: pending
priority: P2
filed: 2026-11-22
source: owner direction 2026-11-22 ("we eventually need the right postgres image, timescale and pgvector")
blocked_on: a planned database rebuild window (no live run, owner call); the 1d corpus runs counted
---

# Move the database to the Debian timescaledb-ha image with pgvector and toolkit, C.UTF-8

## What

Production runs `production-timescaledb`, built by `production/Dockerfile.timescaledb` on `timescale/timescaledb:latest-pg18` (Alpine, musl): PG 18.6, TimescaleDB 2.32.0, pgvector 0.8.7 compiled in, no `timescaledb_toolkit`. The sibling ssfi project already runs `timescale/timescaledb-ha:pg18` (Debian, glibc, with pgvector and toolkit). The base is pinned by digest since 2026-11-22 (`7d7ac1506`). The target is one image family for both: `timescale/timescaledb-ha:pg18` at a pinned tag.

Why: Postgres on musl has weak locale support, the HA image ships pgvector and toolkit with no custom build step, and Timescale maintains it.

The data directory cannot move between libc flavors as is. The database is `en_US.utf8` with the libc provider, which on musl sorts by raw bytes and on glibc sorts linguistically, so every text-keyed index (hypertable chunks included) would be wrong. The new database is created with `C.UTF-8` (bytewise, same as today in practice), and loaded by dump and restore, so no reindex of reordered data is needed.

## Scope

1. Decide the pinned HA tag (PG 18.x, TimescaleDB at or above 2.32.0, pgvector at or above 0.8.7); record `SELECT version()` and `pg_extension` before and after.
2. A rehearsal on ubuntu2 (the standby host) from a base backup: create the `C.UTF-8` database on the HA image, restore, compare row counts per table and a checksum of the keyed text columns, run the integration suite against it.
3. Replication: the ubuntu2 standby, the WAL archive (`pg_receivewal`) and base backups move to the same image in the same window; physical replication needs identical libc and image.
4. Cutover runbook under `docs/operations/` (gate: no batch job, no research run, no timer within 30 minutes), with a rollback to the current image kept until verified.
5. Delete `Dockerfile.timescaledb` (no custom build once the HA image carries pgvector), drop the alpine-only notes in `operations-database.md`, and make the integration harness use the same image (todo for the harness redesign).

## Gates

Owner approves the window. Rehearsal passes with counts and checksums equal. `repro_frozen` bit-identical on the restored database for a frozen verdict replay. No cutover while a fingerprinted run or step window is live.

## Not before

The daily residual and first counted runs finish; not while the corpus run is open (todo 652).
