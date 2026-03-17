# Pipeline Reset Design

**Date:** 2026-03-06
**Status:** Shipped — production/scripts/pipeline_reset.py
**Context:** Data integrity infrastructure — reusable capability to regenerate canonical dataset from raw OHLCV

## Problem

The current signal_ledger and intelligence_features contain contaminated data:
- Schema mismatch window (Mar 5): `I3Structure.extra="forbid"` rejected `asian_session_high/low`, silently dropping all bars for ~20 hours
- Service restart gaps (multiple restarts Mar 5 due to port conflicts, restores from Phase 16 work)
- New timing fields (`bar_close_ts`, indicator completion timestamp) missing from historical data
- `technical_indicators` table orphaned (4 rows, never written by active services)

Renaissance principle: **data quality over model complexity**. No ML model, signal quality score, or alpha claim is valid until the training dataset is clean, gap-free, and correctly timestamped.

## Solution

`production/scripts/pipeline_reset.py` — a permanent, reusable script that produces a clean, canonical, fully-instrumented dataset from raw OHLCV. Run it whenever signals change, schema changes, or data integrity is in question.

## Flags

```
--keep-ohlcv      Skip IBKR re-fetch; replay from existing market_data_ohlcv
--symbols SYM,..  Comma-separated subset (default: all active contracts)
--days N          Override 1m fetch depth (default: 35 days)
--clear-llm       Also truncate llm_calls and llm_model_scores
--dry-run         Print what would be cleared; exit without touching anything
--yes             Skip confirmation prompt
```

## Stages

### 1. Preflight
Print a summary of what will be cleared with current row counts. Require explicit confirmation unless `--yes` is passed.

```
Pipeline Reset — DRY RUN
========================
Will clear:
  signal_ledger         41,765 rows  (2026-03-04 → 2026-03-05)
  intelligence_features  N rows
  market_data_ohlcv      N rows      (skipped with --keep-ohlcv)
  technical_indicators   4 rows
Redis streams:
  development:indicators:*   N keys
  development:intelligence:* N keys
  development:signals:*      N keys
  development:narratives:*   N keys

This cannot be undone. Type YES to continue:
```

### 2. Service Stop (manual pause)
Script cannot call `sudo` (sudo-rs TTY requirement). Prints exact commands and waits for Enter:

```
Stop pipeline services before continuing:

  sudo systemctl stop indicagent-signal-generator
  sudo systemctl stop indicagent-signal-lifecycle
  sudo systemctl stop indicagent-market-analysis
  sudo systemctl stop indicagent-feature-writer
  sudo systemctl stop indicagent-ai-narrative

Keep running: indicagent-tws, indicagent-indicator

Press Enter when services are stopped...
```

### 3. Clear Redis Streams
Delete all keys matching:
- `{env_prefix}:indicators:*`
- `{env_prefix}:intelligence:*`
- `{env_prefix}:signals:*`
- `{env_prefix}:narratives:*`

Consumer groups are destroyed with their streams and recreated cleanly on service restart.

### 4. Truncate DB Tables

Always:
- `TRUNCATE signal_ledger CASCADE`
- `TRUNCATE intelligence_features`
- `TRUNCATE technical_indicators`

If not `--keep-ohlcv`:
- `TRUNCATE market_data_ohlcv`

If `--clear-llm`:
- `TRUNCATE llm_calls`
- `TRUNCATE llm_model_scores`

Never touched: `cis_weights`, `instruments`

### 5. Fetch OHLCV (skipped if `--keep-ohlcv`)
Reuses existing fetch logic from `historical_backfill.py`. Fetches per-symbol, per-TF from IBKR. Default: 35 days of 1m (enough to cascade through all TFs including 1h warmup).

### 6. Replay Pipeline
Reuses `replay_symbol()` from `historical_backfill.py`. Processes all active contracts, all timeframes, in order (1m → 5m → 15m → 1h). Writes to `intelligence_features` and `signal_ledger`.

### 7. Verify
Assert and print:
- Row counts per table (fail if 0)
- Date range per symbol/TF
- Signal counts per symbol/TF
- Flag obvious gaps (missing timeframes, suspiciously low counts)

### 8. Service Restart (manual pause)
Prints restart commands, waits for Enter:

```
Restart pipeline services:

  sudo systemctl start indicagent-market-analysis
  sudo systemctl start indicagent-feature-writer
  sudo systemctl start indicagent-signal-generator
  sudo systemctl start indicagent-signal-lifecycle
  sudo systemctl start indicagent-ai-narrative

Press Enter when services are restarted...
```

### 9. Summary
```
Pipeline Reset Complete
=======================
intelligence_features:  N rows  (2026-02-28 → 2026-03-06)
signal_ledger:         N rows  (2026-02-28 → 2026-03-06)
  ESH6:  1m=N  5m=N  15m=N  1h=N
  NQH6:  1m=N  5m=N  15m=N  1h=N
  ...
Elapsed: Xm Ys
```

## What This Does NOT Do
- Does not modify any code or schema
- Does not restart services autonomously (sudo-rs constraint)
- Does not touch `cis_weights` or `instruments`
- Does not produce `bar_close_ts` timing data for historical bars (live-pipeline-only feature; historical replay uses nominal bar timestamps)

## Reuse Pattern
This script is designed to be run again. Common invocations:

```bash
# Full reset (re-fetch from IBKR + replay)
.venv/bin/python production/scripts/pipeline_reset.py

# Fast reset (keep OHLCV, just re-replay through updated signal logic)
.venv/bin/python production/scripts/pipeline_reset.py --keep-ohlcv

# Specific symbols only
.venv/bin/python production/scripts/pipeline_reset.py --keep-ohlcv --symbols ESH6,NQH6

# See what would happen without touching anything
.venv/bin/python production/scripts/pipeline_reset.py --dry-run
```
