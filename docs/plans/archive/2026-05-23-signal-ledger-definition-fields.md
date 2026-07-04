# Signal Ledger Definition Fields — Design Spec

**Version:** 1.0
**Status:** archived
**Last Updated:** 2026-05-23

## Problem

Migration 093 (Phase 104) slimmed `signal_ledger` by dropping ~45 columns. The intent
was correct: remove contextual metadata blobs (confidence, cis_score, market_context,
supporting_factors, etc.) that duplicated data already in `intelligence_features.trading_signals`
JSONB.

However, it also dropped five fields that are not contextual metadata — they are the
**signal's definition**: `entry_price`, `stop_loss`, `targets`, `entry_zone_low`,
`entry_zone_high`. Without them, `signal_ledger` is an incomplete record.

The signal tracker bootstrap now JOINs the `intelligence_features` hypertable to
reconstruct what the signal is. This JOIN spills 3 GB to disk under the default planner
and requires `SET enable_mergejoin = off` to force a hash join (~5 s). This is a planner
hint papering over a modeling error.

A secondary problem: three fields (`garch_sigma_at_fire`, `hmm_regime_at_fire`,
`market_entry_price`) are already columns in `signal_ledger` but the bootstrap still
reads them from the JSONB JOIN unnecessarily.

A third problem: four repository SELECT methods reference ~40 dropped columns and would
error if called.

## Design Principle

`signal_ledger` is the authoritative record of every signal generated. A signal's
definition (entry, stop, targets, zone) is part of what the signal IS — immutable at
fire time, required for live tracking (R calculation, stop exit detection, target exits,
zone tracking). These fields belong in `signal_ledger`. They are not duplicates of
`intelligence_features`; that table is a feature-vector snapshot. The JSONB there is a
secondary record.

## Changes

### 1. Migration 095 — restore signal definition fields

```sql
ALTER TABLE signal_ledger
  ADD COLUMN IF NOT EXISTS entry_price       NUMERIC,
  ADD COLUMN IF NOT EXISTS stop_loss         NUMERIC,
  ADD COLUMN IF NOT EXISTS targets           JSONB,
  ADD COLUMN IF NOT EXISTS entry_zone_low    NUMERIC,
  ADD COLUMN IF NOT EXISTS entry_zone_high   NUMERIC;
```

No index needed — these are read-at-bootstrap only, not filtered on.

### 2. LedgerEntry dataclass

Add five fields:

```python
entry_price: float | None = None
stop_loss: float | None = None
targets: list[float] | None = None
entry_zone_low: float | None = None
entry_zone_high: float | None = None
```

Update `_to_row()` to append them and update `_INSERT_SQL` to include them.

### 3. signal_writer_agent — populate at write time

In `_payload_to_ledger_entries`, extract from each signal dict:

```python
entry_price=sig.get("entry_price"),
stop_loss=sig.get("stop_loss"),
targets=sig.get("targets") or [],
entry_zone_low=sig.get("entry_zone_low"),
entry_zone_high=sig.get("entry_zone_high"),
```

All five are present in every I7 signal payload. asyncpg accepts a Python list for a
JSONB column — no `json.dumps()`.

### 4. Bootstrap query — drop the JOIN

Replace the current query with a direct SELECT from `signal_ledger`:

```sql
SELECT sl.signal_id, sl.symbol, sl.timeframe, sl.timestamp, sl.status, sl.direction,
       sl.activated_at, sl.ttl_bars, sl.signal_schema_version, sl.is_backfill,
       COALESCE(sl.entry_price, sl.activation_price) AS entry_price,
       sl.stop_loss,
       sl.targets,
       sl.entry_zone_low,
       sl.entry_zone_high,
       sl.market_entry_price,
       sl.garch_sigma_at_fire,
       sl.hmm_regime_at_fire
FROM signal_ledger sl
WHERE sl.exit_at IS NULL
  AND sl.status IN ('pending', 'active')
  AND sl.timestamp > NOW() - INTERVAL '7 days'
```

Remove:
- The `LEFT JOIN intelligence_features` and `LEFT JOIN LATERAL jsonb_array_elements`
- `SET enable_mergejoin = off`
- The 8-day restriction on `f.ts` (was only needed to constrain the hypertable scan)

The COALESCE on `entry_price` handles old signals (pre-095) that have NULL there.

### 5. Repository SELECT queries — fix stale column references

Four methods reference dropped columns: `_SELECT_ACTIVE_SQL`, `_SELECT_ACTIVE_BY_SYMBOL_SQL`,
`fetch_active_signals`, `fetch_pending_signals`. Rewrite each to select only columns that
exist in the current schema plus the five restored definition fields.

## What Is NOT Changed

- The bulk of 093's drops (confidence, cis_score, market_context, supporting_factors,
  features_snapshot, etc.) remain dropped. Those were correctly removed.
- `intelligence_features.trading_signals` JSONB is untouched — it remains the full
  feature-vector snapshot.
- No other services are affected; signal_tracker and signal_writer are the only
  consumers of the changed fields.

## Testing

- Unit tests for `_payload_to_ledger_entries` verify the five fields are populated.
- Unit tests for `_load_signal` verify bootstrap path handles NULL definition fields
  (old signals) via COALESCE fallback.
- Bootstrap test: mock DB returns row with NULL entry_price — verify fallback to
  activation_price.
- `pytest tests/unit/ -q` must be green.

## Migration Sequencing

095 must be applied before deploying the updated signal_writer or signal_tracker. The
columns are nullable so existing rows are unaffected. New signals will populate them
immediately on deploy.
