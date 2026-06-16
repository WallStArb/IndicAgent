---
created: 2026-06-16
priority: high
phase_target: post-130
tags: [signal-architecture, ml-training, data-completeness, renaissance]
---

# Near-Miss Signal Capture

## What

Capture signals that fired all the way through I7 plugin logic but fell below the ICC threshold — the "almost fired" population. Currently invisible in the data.

## Why It Matters (Renaissance Lens)

Renaissance mines the **full distribution** around decision boundaries, not just threshold crossings. The ICC threshold is an arbitrary line. A signal at 0.49 ICC vs the 0.50 threshold is not categorically different from one at 0.51 — but one appears in `signal_events` and the other vanishes. This creates a biased training corpus: the ML model sees only right-tail events, learns their features, but has no negative examples from the same plugin generating near-identical setups. The result is a classifier that overfits to threshold proximity rather than learning genuine edge.

Near-misses also surface calibration issues. If plugin X generates 80% of its signals in the 0.48-0.52 ICC band, that's a sign the threshold is poorly set for that plugin — but you can't see it without the near-miss distribution.

## Technical Approach Options

### Option A: Flag-on-emission (recommended)

Lower the effective ICC emission threshold per-plugin to `threshold * 0.85` (configurable via APR). Emit all signals above this lower bound. Add `is_near_miss bool DEFAULT false` and `near_miss_reason text` to `signal_events`. Signals below the original threshold get `is_near_miss = true`.

**Pros:** Single pipeline path. Near-misses stored in `signal_events` with full ECL annotations. No new topic, no new table, no new writer. ML training query just adds `AND NOT is_near_miss` to production queries or includes near-misses as negative examples.

**Cons:** Increases `signal_events` volume by ~3-10x depending on plugin. Compression helps. Requires APR parameter `signal.<plugin>.near_miss_threshold_pct` per plugin (or global default).

### Option B: Separate near-miss topic + table

I7 plugins emit a second event on a `market.signals.near_miss` topic. Separate `signal_near_misses` table mirrors `signal_events` schema but without `trade_frames` / `trade_executions` children (near-misses never become trade candidates by definition).

**Pros:** Zero impact on existing `signal_events` volume or consumers.

**Cons:** Doubles the writer infrastructure. No shared FK structure. ML training must JOIN two tables.

### Option C: Histogram per bar (analytics-only)

After each bar, record a compact ICC distribution vector in `intelligence_features` — `signal_icc_histogram jsonb` with bins [0.0-0.1, 0.1-0.2, ..., 0.9-1.0] per plugin. No new signal rows.

**Pros:** Tiny storage. Reveals distribution shape.

**Cons:** Loses all ECL annotations (no factor_scores, no context_features per near-miss). Can't do per-near-miss attribution. Useful for threshold calibration only, not ML training.

## Recommended Path

**Option A.** APR-controlled per-plugin near_miss_threshold_pct (default: 0.85 of plugin's ICC threshold). Two new columns on `signal_events`. No architectural additions.

## Schema Changes Needed

```sql
-- Add to signal_events in a future migration:
ALTER TABLE signal_events
    ADD COLUMN is_near_miss  bool    NOT NULL DEFAULT false,
    ADD COLUMN near_miss_gap float8;  -- distance below threshold: threshold - raw_confidence; null if not near-miss

-- Index for ML training queries that exclude near-misses:
CREATE INDEX idx_signal_events_not_near_miss
    ON signal_events (ts DESC)
    WHERE is_near_miss = false;
```

## APR Parameters Needed

```
signal.near_miss.enabled               bool    false     [user_preference] Global on/off toggle
signal.near_miss.threshold_pct         float   0.85      [initial_estimate] Fraction of ICC threshold to use as lower bound
```

## Pipeline Changes Needed

1. I7 plugin base class (`BaseSetupPlugin` or equivalent): after ICC computation, check if `raw_confidence >= near_miss_threshold` (not full threshold). Emit with `is_near_miss=True` flag in payload if below full threshold.
2. `SignalWriter` / `signal_events` writer: populate `is_near_miss` and `near_miss_gap` from payload.
3. `CounterfactualTracker`: skip near-miss signals — no `trade_frames` rows generated.
4. `SignalRanker`: exclude near-misses from ranking and activation.

## Volume Estimate

With ~5-15% of setups near the threshold per plugin, 138 plugins, and current ~50-200 signal fires/day: expect 3-10x volume increase in `signal_events`. At current compression ratio (7-day chunks, segmentby symbol+tf): manageable. Monitor with `SELECT count(*), is_near_miss FROM signal_events GROUP BY is_near_miss`.

## Prerequisites

- Phase 130 writers complete (so near-miss writer changes layer on top of stable writer architecture)
- APR parameter store stable (Phase 125+ complete — ✓)
- Option A schema columns added in a migration (138 or later)

## References

- ADR: `docs/signals/signal-trade-separation-ADR.md` — schema context
- APR spec: `docs/foundation/adaptive-parameter-registry.md`
- Principle: "never drop data that could contain signal" — `docs/foundation/principles.md`
- Phase 128 UAT gap discussion: 2026-06-16 session
