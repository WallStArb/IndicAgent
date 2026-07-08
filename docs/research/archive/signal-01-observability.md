# Signal Measurement Quality

**Version:** 1.0
**Status:** draft
**Priority:** medium
**Milestone:** future (post-v2.8)
**Last Updated:** 2026-05-30
**Tags:** signals, observability, traceability, metrics, shadow-governance, lifecycle, measurement

---

## Context

The system measures the market rigorously — 132 plugins, tiered feature vectors, regime detection, GARCH volatility, HMM state. It measures its own signals less rigorously. Outcome data exists but the granularity is coarse: we know a signal won or lost, but not whether the selection decision was confident or marginal, whether the edge is decaying, whether the active book is correlated, or whether our significance gates account for how many hypotheses we're testing simultaneously.

Medallion's institutional advantage came partly from measurement discipline — tracking what worked, what didn't, and why, at every level of granularity, and treating failed signals as data rather than noise to discard. That principle applied to the signal lifecycle is the frame for this doc.

These ideas are independent and additive. None requires the others.

---

## Ideas

### 1. Selection Provenance

**Gap:** `was_selected=TRUE` records the winning signal but discards the selection context. We don't know how many candidates competed, what the winning margin was, or whether the selection was dominant or marginal. A signal that won with CIS 0.82 vs next-best 0.41 is a structurally different quality of decision than one that won 0.62 vs 0.59.

**Proposal:** At selection time in `signal_processor.py`, write a selection snapshot alongside the winner:

```sql
-- New table or JSONB column on signal_ledger
selection_context JSONB  -- {candidate_count, winner_cis, runner_up_cis, winner_margin, selection_ts}
```

This makes the selection decision auditable. Downstream analysis: do dominant selections (`winner_margin > 0.3`) produce better outcomes than marginal ones? Does winner margin predict activation rate? Currently unanswerable.

**Implementation surface:** `signal_processor.py` already builds the ranked list — capture it before discarding. `SignalWriterAgent` writes the context column alongside the signal. No lifecycle changes needed.

---

### 2. Direction-Level Performance Tracking

**Gap:** Performance is tracked per-plugin via `shadow_registry` and `setup_performance`. There is no first-class metric at the *strategy direction* level — "momentum + confluence in trending regime" as a class, regardless of which plugin fired it. A direction that fails across three plugins is stronger evidence of structural failure than one plugin that underperformed.

**Proposal:** A `signal_direction_performance` materialized view or table, grouping outcomes by direction cluster (e.g., `setup_type + regime_at_fire + entry_type`) and computing the same metrics as `setup_performance`:

```sql
CREATE MATERIALIZED VIEW signal_direction_performance AS
SELECT
    setup_type,
    hmm_regime_at_fire,
    entry_type,
    COUNT(*)                                    AS n,
    AVG(pnl_r)                                  AS mean_pnl_r,
    percentile_cont(0.5) WITHIN GROUP (ORDER BY pnl_r) AS median_pnl_r,
    SUM(CASE WHEN pnl_r > 0 THEN 1 ELSE 0 END)::float / COUNT(*) AS win_rate,
    STDDEV(pnl_r)                               AS pnl_r_stddev
FROM signal_ledger_full
WHERE outcome IS NOT NULL AND signal_schema_version = 'v1'
GROUP BY setup_type, hmm_regime_at_fire, entry_type;
```

Refreshed by `SignalMetricsComputeAgent` on the same cadence as `setup_performance`. The shadow promotion gate could optionally consult direction-level performance as a second signal — if a plugin is trying to graduate but its entire direction cluster has negative EV, that is relevant evidence.

---

### 3. Performance Decay Curves

**Gap:** `setup_performance` tracks rolling 30d stats. There is no structured view of how performance changes over time. A plugin whose rolling 30d Sharpe has dropped 40% from its all-time average is signaling edge decay — currently invisible.

**Proposal:** `SignalMetricsComputeAgent` writes a time-series snapshot of rolling performance to a `setup_performance_history` table on each run:

```sql
CREATE TABLE setup_performance_history (
    snapshot_ts   TIMESTAMPTZ NOT NULL,
    setup_type    TEXT NOT NULL,
    window_days   INTEGER NOT NULL,     -- 30, 90, 365, all-time
    n             INTEGER NOT NULL,
    mean_pnl_r    FLOAT,
    win_rate      FLOAT,
    sharpe        FLOAT,
    PRIMARY KEY (snapshot_ts, setup_type, window_days)
);
```

Four window sizes per setup per snapshot — 30d, 90d, 365d, all-time. The delta between 30d and all-time is the decay signal. A Grafana panel showing rolling vs all-time per setup makes this visible at a glance. Shadow governance could use the 30d/90d delta as a soft demotion trigger before the hard bootstrap gate fires.

---

### 4. Active Signal Book Correlation

**Gap:** Multiple signals can be active simultaneously for the same symbol. There is no tracking of portfolio concentration — if 4 of 5 active long signals are in the same zone type under the same regime, the book is correlated, not diversified. This is invisible in the current system.

**Proposal:** `SignalMetricsComputeAgent` computes a book concentration score on each run and exposes it as an OTel gauge:

```python
# Concentration: fraction of active signals sharing the dominant (symbol, direction, setup_type)
# 1.0 = fully concentrated, 0.0 = fully diversified
signal_book_concentration_ratio  # gauge, label: symbol
signal_book_active_count          # gauge, label: symbol
```

No schema changes required — reads from the in-memory active index or a `signal_ledger_full WHERE exit_at IS NULL` query. The Grafana SLO panel could flag concentration > 0.7 as a warning. This doesn't affect execution — purely observational.

---

### 5. Near-Miss Outcome Class

**Gap:** The 8-class outcome taxonomy collapses "stopped out after reaching +0.8R MFE" and "stopped out immediately" into the same `stopped_in_trade` bucket. These are structurally different: a near-miss indicates a correct directional call with poor exit timing; an immediate stop indicates a failed setup. Both are losses in pnl_r but the diagnostic and training signal are opposite.

**Proposal:** Define a 9th outcome class `near_miss` — derived, not stored:

```sql
-- A near_miss is a stopped_in_trade where the trade was well in profit before reversing
-- Defined as: outcome = 'stopped_in_trade' AND mfe >= 0.5R
```

No schema change: `near_miss` is a query-time classification using existing `outcome` and `mfe` columns. Add it as a named case in `setup_performance` queries and ML training queries. The definition of the MFE threshold (0.5R) is a parameter worth calibrating — start at 0.5R and adjust based on the distribution.

**Why it matters for ML training:** Near-misses are the highest-signal rows for exit timing models. A model trained on `stopped_in_trade` as a single class cannot distinguish "bad entry" from "good entry, bad exit." Near-miss is the label that separates them.

---

### 6. Multiple Testing Correction

**Gap:** The shadow promotion gate (`bootstrap_ci_lower(pnl_r) > 0.0, n >= 100`) evaluates each plugin in isolation. With 36 I7 plugins in shadow simultaneously, some will pass the gate by chance — the expected number of false positives under a 5% significance threshold across 36 simultaneous tests is ~1.8. The gate does not account for this.

**Proposal:** Apply a Bonferroni-corrected significance threshold at the population level. When `GraduationComputeAgent` evaluates promotion candidates, the effective alpha threshold is divided by the number of active shadow candidates:

```python
# Effective alpha for promotion given N simultaneous candidates
effective_alpha = BASE_ALPHA / n_active_shadow_candidates  # BASE_ALPHA = 0.05

# Bootstrap CI uses the corrected alpha instead of fixed 95%
ci_lower = bootstrap_ci_lower(pnl_r, alpha=effective_alpha)
```

Conservative but correct. As the shadow population grows, individual candidates must show stronger evidence to promote. This prevents the promotion gate from becoming a multiple-comparisons lottery as the number of plugins scales.

A less aggressive alternative: Benjamini-Hochberg FDR correction, which controls the false discovery rate rather than the per-comparison error rate. More permissive than Bonferroni at large N; still more rigorous than the current uncorrected gate.

---

### 7. Activation Quality Score

**Gap:** `zone_entry_pct` (where in the zone price entered) and `bars_to_activation` (how long the signal waited) are both stored but never combined. Together they are a leading indicator of outcome quality: proximal entry + fast activation is a strong setup; distal entry + slow activation is structurally weak. This pattern is queryable but not surfaced.

**Proposal:** Write a composite `activation_quality_score` at activation time in `LifecycleWriterAgent`:

```python
# Simple weighted formula — no ML needed
# zone_entry_pct: 0 = proximal (best), 1 = distal (worst)
# bars_to_activation: fewer is better, normalized to [0,1] against TF_TTL_BARS
activation_quality_score = (
    0.6 * (1.0 - zone_entry_pct) +
    0.4 * (1.0 - min(bars_to_activation / ttl_bars, 1.0))
)
```

Written to `signal_outcomes.activation_quality` (new column). Feeds into ML training as a feature — activation quality at the moment of entry is information the model doesn't currently have. Also enables direct queries: do high-quality activations produce better outcomes? Is there a threshold below which activations consistently underperform?

---

## Renaissance Alignment

Medallion's measurement discipline maps directly onto these gaps:

- **Selection provenance** — every decision auditable, not just the outcome
- **Direction-level tracking** — measure edge at the right granularity, not just the instrument
- **Decay curves** — alpha is non-stationary; measure its half-life
- **Book correlation** — portfolio concentration is risk; make it visible
- **Near-miss taxonomy** — failed signals are data, not noise; classify them precisely
- **Multiple testing correction** — significance gates must account for the population they're applied to
- **Activation quality** — measure entry quality at the moment of entry, not retrospectively

The unifying principle: the system should measure itself as rigorously as it measures the market.

---

## Implementation Notes

Rough ordering by effort vs. value:

| Idea | Effort | Schema change | Value |
|---|---|---|---|
| Near-miss outcome class | Low — query-time derived | No | High — immediate ML training benefit |
| Activation quality score | Low — formula at activation | Add one column | High — leading indicator |
| Book correlation metric | Low — OTel gauge only | No | Medium — operational visibility |
| Decay curves | Medium — new history table | New table | High — shadow governance input |
| Direction-level performance | Medium — materialized view | New view | High — research signal |
| Selection provenance | Medium — capture at selection | New JSONB column | High — traceability |
| Multiple testing correction | Low — gate logic change | No | Medium — correctness |

Near-miss and activation quality score are the highest-value, lowest-effort pair. Multiple testing correction is small code change but high correctness value. Everything else is additive.

---

## Related Docs

- `docs/signals/signals-lifecycle.md` — state machine, outcome taxonomy, exit conditions
- `docs/signals/signals-foundation.md` — signal_ledger schema, was_selected vs is_shadow
- `docs/research/ai-11-alpha-search-orchestration.md` — population orchestration and direction-level research agenda
- `src/intelligence/trading/lifecycle_tracker.py` — evaluate_signal(), MAE/MFE tracking
- `services/signal_metrics_compute_agent.py` — setup_performance refresh, natural home for decay curves and book correlation
