# Gap-Closure: stopped_at_entry Rate — Corrected Framing

**Created:** 2026-06-18
**Revised:** 2026-06-18 (post-analysis: misdiagnosis corrected)
**Source:** Phase 132 Plan 05 verification gate FAIL
**Priority:** Medium

## Corrected Problem Statement

Phase 132 measured 51.11% stopped_at_entry on a 30-day window, but that sample was 86% GBPUSD
by stop count. GBPUSD had a pathological bar=1 spike (42.52% of its stop exits hit on bar 1),
which was spread-induced — stop distances on GBPUSD 1m were inside the bid-ask noise band. That
contaminated the headline number.

**Equity ETF baseline (SPY, QQQ, IWM — no FX, no futures rolls):**

| Symbol | Total stops | stopped_at_entry | Rate |
|--------|-------------|------------------|------|
| QQQ    | 1,027       | 305              | 29.70% |
| SPY    | 3,059       | 1,060            | 34.65% |
| IWM    | 2,949       | 1,112            | 37.71% |

Bar distribution for ETFs is a normal exponential decay (11.55% bar=1, 7.04% bar=2, 5.03%
bar=3…). No pathological spike. The GBPUSD bar=1 pattern does not exist for ETFs.

## Root Cause: Signal Quality, Not Stop Geometry

For equity ETFs, the stopped_at_entry is dominated by `actual_mfe <= 0.05R` — price never moved
meaningfully in the right direction. Decomposition for QQQ:

- `bars <= 2` only (stopped fast, price DID move in favor): 41 trades (13%)
- `mfe <= 0.05` only (price never moved, stopped slow): 125 trades (41%)
- Both: 139 trades (46%)
- **mfe <= 0.05 share: 86%**

SPY/IWM: mfe <= 0.05 share is 96-97%.

**Implication:** Wider stop floors do not fix this. If price never reaches 0.05R of favorable
movement, a 1.0 ATR floor and a 2.0 ATR floor produce identical outcomes. The entries themselves
are wrong — zones that are firing into immediate reversals.

## What the Original Todo Got Wrong

The original framing ("tune per-class stop floors based on per-source rates") was misdiagnosed.
Stop floor tuning addresses `bars <= 2` failures where price moved in favor but the stop was too
tight. That component is 13% of QQQ stopped_at_entry. Tuning floors for the 87% that are
`mfe <= 0.05` failures accomplishes nothing.

## Corrected Work Items

### 1. Fix the standard verification sample

All future stopped_at_entry measurements use equity ETFs only: **SPY, QQQ, IWM, XLK**.

- No FX (spread-induced stop patterns pollute the analysis)
- No futures (roll artifacts, contract gaps)
- Update `132-VERIFICATION.md` notes and any future phase verification docs to reflect this

### 2. Persist zone_source to context_features (prerequisite for #3)

`trade_framer.py` resolves `zone_source` at zone assignment but it is not written to
`context_features` in `signal_events`. Without it, all zone types look identical.

- Trace: `TradeFrame.zone_source` → signal writer → `signal_events.context_features` INSERT
- Add `zone_source` to the `context_features` dict
- Confirm populated in a test replay before running full analysis

### 3. Segment stopped_at_entry by zone_source (after #2)

Once zone_source is persisted, run the per-source breakdown on equity ETFs:

```sql
SELECT
  se.context_features->>'zone_source' AS zone_source,
  COUNT(*) FILTER (WHERE te.exit_reason='stop_loss') AS total_stops,
  COUNT(*) FILTER (WHERE te.exit_reason='stop_loss'
                   AND (te.actual_mfe<=0.05 OR te.actual_bars<=2)) AS stopped_at_entry,
  ROUND(COUNT(*) FILTER (WHERE te.exit_reason='stop_loss'
                          AND (te.actual_mfe<=0.05 OR te.actual_bars<=2))*100.0
        / NULLIF(COUNT(*) FILTER (WHERE te.exit_reason='stop_loss'),0), 2) AS pct
FROM trade_executions te
JOIN trade_frames tf ON te.frame_id=tf.frame_id
JOIN signal_events se ON tf.signal_id=se.signal_id
WHERE se.symbol IN ('SPY','QQQ','IWM','XLK')
AND se.ts >= '<30d-ago>'
GROUP BY 1 ORDER BY pct DESC;
```

Zone types with high mfe<=0.05 rates are false-positive entry problems. Zone types with high
bars<=2 rates (but positive MFE) are stop-distance problems. These require different fixes.

### 4. For zones with high mfe<=0.05 rate: signal confidence gating

These zones are firing into reversals. The fix is upstream:
- Raise the minimum raw_confidence threshold for the offending zone type
- Or add a zone-type-specific regime gate (only fire demand zones in uptrend regime, etc.)
- This is a shadow governance / signal weighting problem, not a stop geometry problem

### 5. For zones with high bars<=2 rate (and positive MFE): stop floor tuning

These are legitimate stop-distance issues. Use the APR keys from Phase 132 to widen the
relevant buffer per zone type. This is the narrow use case the original todo described.

### 6. Re-evaluate OUTCOME_THRESHOLD_QUICK_STOP_BARS = 2

This threshold in `lifecycle_tracker.py` is not timeframe-aware. On 1m, bars<=2 = 2 minutes;
on 1h, bars<=2 = 2 hours. Consider making it an APR key or scaling it by timeframe before
using it as a universal classification gate.

## Revised Success Criterion

- **Phase 1 (achievable after zone_source + confidence gating):** stopped_at_entry < 25% on
  SPY/QQQ/IWM 30-day replay
- **Phase 2 (signal quality work):** stopped_at_entry < 10% on SPY/QQQ/IWM
- **< 5% is a long-run aspirational target** requiring fundamental signal quality improvements,
  not achievable through stop geometry tuning alone

## What NOT To Do

- Do not test stopped_at_entry on GBPUSD or other FX pairs — spread patterns make the metric
  uninterpretable as a stop geometry signal
- Do not tune stop floors to address mfe<=0.05 failures — wider stops cannot fix wrong entries
- Do not report the aggregate across all asset classes — FX/futures contaminate the equity signal

## References

- `132-VERIFICATION.md` — Phase 132 gate results (note: GBPUSD-contaminated, superseded by
  this analysis)
- `132-A2-MEASUREMENT.md` — original baseline measurement
- `src/intelligence/trading/trade_framer.py` — zone_source assignment (~line 1050)
- `src/intelligence/trading/lifecycle_tracker.py` — `_classify_stop_outcome()`, line 556-564,
  `OUTCOME_THRESHOLD_QUICK_STOP_BARS = 2` (line 24)
- 35 APR keys now in config_state for stop geometry tuning surface
