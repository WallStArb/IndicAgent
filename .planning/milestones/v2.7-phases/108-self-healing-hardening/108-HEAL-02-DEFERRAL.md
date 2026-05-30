# HEAL-02 Deferral Record - DB Backup

**Status:** Deferred from Phase 108
**Date:** 2026-05-28
**Decision source:** CONTEXT.md D-28

---

## Original Requirement

From REQUIREMENTS.md (HEAL-02):

> DB backup - `indicagent-db-backup.service` + `.timer` perform nightly `pg_dump` to
> `/var/backups/indicagent/`; `.sql.gz` exists and is < 25h old; retention script prunes
> files older than 7 days automatically.

---

## Deferral Rationale (D-28)

No clear restore scenario has been identified. Nightly backups without a tested restore
workflow are operational theater: they create a false sense of safety while adding
operational overhead (disk space management, backup job monitoring, rotation scripts)
with no validated recovery path.

Specific gaps that make the backup less useful today:

1. No staging database to test restores against - a backup that has never been restored
   is of unknown quality.
2. TimescaleDB hypertables require a compatible `timescaledb-backup` restore procedure,
   not plain `pg_restore`. A plain `pg_dump` backup may not restore cleanly.
3. Raw OHLCV data (the largest table by volume) can be replayed from IBKR historical data.
   Most state loss is recoverable from Kafka topic replay + IBKR backfill.
4. The one-person shop constraint means manual restore steps add risk unless automated
   and tested end-to-end.

---

## Re-evaluation Triggers

HEAL-02 MUST be revisited when any of the following conditions occur:

1. **Disk-loss incident** - any data loss event in test or production that would have
   been mitigated by a backup, however small.
2. **Regulatory or audit requirement** - any external requirement for point-in-time
   recovery, disaster recovery documentation, or data retention compliance.
3. **Non-replayable state introduced** - any new system component whose state cannot
   be reconstructed from Kafka + raw OHLCV replay. Examples: long-lived ML model
   artifacts stored only in DB, manually curated configuration tables, annotated signal
   outcomes that do not flow through any replay path.
4. **Explicit user decision** - operator decides the operational theater tradeoff is
   acceptable and adds HEAL-02 as a quick task with a tested restore procedure.

---

## Implementation Hint (when revisited)

Start smaller than the original requirement scope:

1. Begin with `pg_dump --schema-only` to capture DDL, plus selected user tables:
   `instruments`, `contract_metadata`, `signal_ledger` (recent 90d), `shadow_registry`,
   `setup_performance`.
2. Test restore on a staging TimescaleDB container before adding hypertable data.
3. Use `pg_dump --format=directory` for parallel restore capability.
4. Only extend to full hypertable dump (`market_data_ohlcv`, `intelligence_features`)
   after the selective restore is validated.
5. Add a `backup_health` OTel gauge (1 = last backup < 25h old, 0 = stale) so Grafana
   can alert without manual inspection.

---

## Forward Pointer

This deferral is linked from CLAUDE.md OTel Health Contract section:
"HEAL-02 (DB backup) is deferred - see `.planning/phases/108-self-healing-hardening/108-HEAL-02-DEFERRAL.md`."

---

*Phase: 108-self-healing-hardening*
*Deferred: 2026-05-28*
