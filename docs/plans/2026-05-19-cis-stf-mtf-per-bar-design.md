# CIS STF/MTF Split + Per-Bar Feature Writes — Design

**Date:** 2026-05-19
**Status:** In progress
**Supersedes:** `archive/2026-02-27-composite-intelligence-score-design.md` (original CIS design, shipped)
**See also:** `docs/concepts/cis-scoring.md` (canonical CIS reference)

---

## Background

The CIS scorer (`src/intelligence/trading/cis_scorer.py`) is live and shipping signals. It aggregates 6 buckets into a directional score in [-1.0, +1.0], Kalman-filtered before signal selection.

Two gaps remain:

**Gap 1 — No per-bar CIS record.** CIS is computed inside `SignalProcessor.process()`, which returns early when no I7 signals fire. On no-signal bars the CIS score is never computed and never written. The `intelligence_features` table has no CIS columns. This means:
- We cannot chart CIS over time without signals
- We cannot study CIS behavior during drawdowns or quiet regimes
- The ML training pipeline has no CIS feature to train on

**Gap 2 — No single-timeframe variant.** The current CIS score is multi-timeframe (MTF): its trend and regime buckets consume `ctf_trend_alignment` and `ctf_regime_agreement`, which are derived from cross-timeframe plugin outputs. There is no way to distinguish whether CIS conviction comes from same-bar evidence vs. HTF context, making it harder to evaluate setup quality on short timeframes independently of higher-timeframe state.

---

## Solution Overview

1. **STF CIS variant** — run the scorer a second time with the two CTF inputs zeroed. The result isolates single-timeframe evidence only.
2. **Renamed columns** — `raw_cis_score`/`filtered_cis_score` become `raw_cis_mtf_score`/`filtered_cis_mtf_score` everywhere.
3. **Per-bar writes** — both MTF and STF scores written to `intelligence_features` on every bar regardless of whether signals fire.
4. **signal_ledger** — carries all four scores at signal fire time for post-hoc analysis.
5. **Divergence** — `mtf - stf` derived at query time; no dedicated column needed.

---

## The STF/MTF Distinction

| Variant | CTF inputs | Kalman key | Interpretation |
|---------|-----------|-----------|---------------|
| MTF (current) | `ctf_trend_alignment`, `ctf_regime_agreement` | `(symbol, tf)` | Cross-timeframe confirmed conviction |
| STF (new) | both zeroed to 0.0 | `(symbol, tf, "stf")` | Same-bar evidence only |

The `CISScorer` stays pure — no mode flag. The caller builds a shallow-copied feature dict with the two CTF fields set to `0.0` before the second call. This preserves the scorer's existing test surface.

**Divergence signal:** `mtf - stf > 0` means HTF context is adding conviction beyond what this timeframe shows alone. `mtf - stf < 0` (HTF contradicts intrabar evidence) is a warning signal and can gate or weight-reduce the winner's confidence. Computed at query time; no DB column.

---

## Data Path Changes

### signal_processor.py

Current flow (simplified):
```
raw_signals empty? → early return (CIS never computed)
else:
  cis_result = scorer.score(features, plugin_outputs)    # MTF only
  kalman filter → filtered_cis
  ... pipeline gates ...
  sig["raw_cis_score"] = raw_cis
  sig["filtered_cis_score"] = filtered_cis
```

New flow:
```
# Always compute — before the early-return guard
features = _build_features_from_event(event)
cis_result_mtf = scorer.score(features, plugin_outputs)
raw_cis_mtf, filtered_cis_mtf = kalman_update(cis_result_mtf, key=(symbol, tf))

stf_features = {**features, "ctf_trend_alignment": 0.0, "ctf_regime_agreement": 0.0}
cis_result_stf = scorer.score(stf_features, plugin_outputs)
raw_cis_stf, filtered_cis_stf = kalman_update(cis_result_stf, key=(symbol, tf, "stf"))

if raw_signals empty:
  return SignalProcessorResult(..., cis_scores=CISScores(...))   # scores still returned
else:
  ... pipeline gates ...
  sig["raw_cis_mtf_score"] = raw_cis_mtf
  sig["filtered_cis_mtf_score"] = filtered_cis_mtf
  sig["raw_cis_stf_score"] = raw_cis_stf
  sig["filtered_cis_stf_score"] = filtered_cis_stf
```

`SignalProcessorResult` gains a `cis_scores` field so the orchestrator can pass scores to the feature writer even on no-signal bars.

### BarIntelligenceRecord

Add four nullable float fields:
```python
raw_cis_mtf_score: float | None = None
filtered_cis_mtf_score: float | None = None
raw_cis_stf_score: float | None = None
filtered_cis_stf_score: float | None = None
```

### feature_writer_agent.py

`_record_to_insert_params()` gains four new positional params ($32–$35). `_INSERT_FEATURE_SQL` adds the four column names. `FeatureRepository` SQL template updated to match.

### signal_ledger_repository.py

`LedgerEntry` fields renamed + two new fields:
```python
# was: raw_cis_score, filtered_cis_score
raw_cis_mtf_score: float | None = None    # $55
filtered_cis_mtf_score: float | None = None  # $56
raw_cis_stf_score: float | None = None    # $57
filtered_cis_stf_score: float | None = None  # $58
```

INSERT SQL gains two columns; param positions shift.

---

## Schema Migrations

All `ADD COLUMN` statements use nullable `double precision` — no default, no `NOT NULL`. In PostgreSQL 11+ this is a metadata-only operation: no table rewrite, no exclusive lock, no ingestion pause. Historical rows will read NULL for the new columns, which is acceptable (pre-migration bars simply have no CIS record).

### signal_ledger

```sql
-- Rename existing columns (instant metadata op)
ALTER TABLE signal_ledger
    RENAME COLUMN raw_cis_score TO raw_cis_mtf_score;
ALTER TABLE signal_ledger
    RENAME COLUMN filtered_cis_score TO filtered_cis_mtf_score;

-- Add STF columns (nullable, no table rewrite)
ALTER TABLE signal_ledger
    ADD COLUMN raw_cis_stf_score double precision,
    ADD COLUMN filtered_cis_stf_score double precision;
```

### intelligence_features

```sql
-- All four nullable — no table rewrite on TimescaleDB hypertable
ALTER TABLE intelligence_features
    ADD COLUMN raw_cis_mtf_score double precision,
    ADD COLUMN filtered_cis_mtf_score double precision,
    ADD COLUMN raw_cis_stf_score double precision,
    ADD COLUMN filtered_cis_stf_score double precision;
```

### ON CONFLICT strategy

The feature INSERT uses `ON CONFLICT (ts, symbol, tf) DO NOTHING`. Since CIS columns are written in the same INSERT as the rest of the bar data, a new bar will always land with all four CIS values populated. The conflict guard only fires if the same (ts, symbol, tf) is inserted twice — in which case the first write wins and the scores are already there. `DO NOTHING` is correct; no `DO UPDATE` needed.

Historical bars (pre-migration) will have NULL CIS columns permanently. This is acceptable — the learning pipeline gates on `IS NOT NULL` already for other optional columns.

### STF Kalman warm-up

The `(symbol, tf, "stf")` state is initialized identically to the MTF key: `x = raw_cis_stf` on first bar, `P = 1.0`. The filter converges within ~5–10 bars, same as MTF. No special treatment needed.

---

## Files Touched

| File | Change |
|------|--------|
| `src/intelligence/pipeline/signal_processor.py` | Lift CIS before early-return; add STF pass; rename sig dict keys; add cis_scores to SignalProcessorResult |
| `src/persistence/repository/signal_ledger_repository.py` | LedgerEntry field rename + 2 new fields; INSERT SQL; param positions |
| `services/feature_writer_agent.py` | _INSERT_FEATURE_SQL + _record_to_insert_params ($32–$35) |
| `src/persistence/repository/feature_repository.py` | SQL template + column count comment |
| `src/core/stream_keys.py` | Update stale comment referencing old column names |
| `tests/unit/intelligence/test_signal_ledger.py` | Param position assertions; field name checks |
| `tests/unit/pipeline_tests/test_signal_processor.py` | Fixture dict keys |
| DB migration script | ALTER TABLE statements above |
| `src/observability/metrics.py` | Add `CIS_MTF_STF_DIVERGENCE` histogram for post-deploy validation |

---

## What Does NOT Change

- `CISScorer` internals — no mode flag, no new public methods
- CIS fire threshold, bucket weights, bucket names
- `cis_score` column on `signal_ledger` (the aggregated MTF score written at signal fire) — stays as-is
- `bucket_scores`, `weights_version`, `cis_attribution` columns — unchanged
- All 36 I7 plugin files
- Dashboard and API — no CIS columns exposed in REST endpoints yet

---

## Divergence Queries (examples)

```sql
-- Bars where HTF context added strong conviction (MTF > STF by > 0.2)
SELECT ts, symbol, tf,
       raw_cis_mtf_score - raw_cis_stf_score AS divergence
FROM intelligence_features
WHERE raw_cis_mtf_score - raw_cis_stf_score > 0.2
ORDER BY ts DESC
LIMIT 50;

-- Signal quality by divergence band
SELECT
    CASE
        WHEN (raw_cis_mtf_score - raw_cis_stf_score) > 0.2 THEN 'htf_amplified'
        WHEN (raw_cis_mtf_score - raw_cis_stf_score) < -0.1 THEN 'htf_contradicts'
        ELSE 'aligned'
    END AS div_band,
    COUNT(*), AVG(pnl_r), AVG(signal_quality)
FROM signal_ledger
WHERE outcome IS NOT NULL
GROUP BY 1;
```

---

## Success Criteria

- All 4 CIS columns present in `intelligence_features` for every bar (signal or no-signal)
- `signal_ledger` MTF columns renamed; STF columns populated on new signals
- `raw_cis_mtf_score - raw_cis_stf_score` computable across full history
- Migration runs without locking ingestion (nullable ADD COLUMN, RENAME COLUMN)
- `CIS_MTF_STF_DIVERGENCE` histogram emitting in production metrics after deploy
- Test suite green, ruff 0 errors
- No regression on existing signal firing behavior
