---
phase: 138-ic-engine-forward-returns
plan: 05
status: complete
completed: 2026-06-23
commit: f9442ad3
---

# 138-P5 Summary

## What Was Built

**Task 0: Migration 162 + regime_writer HMM probability vector**
- Migration 162 applied: `feature_vectors` gained `hmm_prob_trending_up`, `hmm_prob_ranging`, `hmm_prob_trending_down` columns
- `_causal_decode()` now returns `(states, alpha_history)` tuple (was `states` only)
- Generator in `_label_symbol_tf()` replaced with explicit loop -- required for index-based alpha_history access and stateful duration tracking simultaneously
- UPDATE SQL expanded to write all 6 enrichment columns per bar: `regime`, `hmm_prob_trending_up`, `hmm_prob_ranging`, `hmm_prob_trending_down`, `hmm_regime_prob`, `hmm_entropy`, `hmm_duration`
- `hmm_direction_score` NOT stored -- trivially derivable as `p_up - p_down` at query time
- 18 unit tests updated for tuple return type; full suite green

**Task 1: forward_return_writer OTel metrics**
- Added `FORWARD_RETURN_WRITER_ROWS_WRITTEN_TOTAL`, `FORWARD_RETURN_WRITER_RUN_LATENCY_SECONDS`, `OUTCOME_LABELS_COVERAGE` to `src/observability/metrics.py`

**Task 2: services/forward_return_writer.py**
- Causal LEAD()-based forward returns: `ln(open[T+N+1] / open[T+1])` -- entry at T+1 open, exit at T+N+1 open
- `TRAINING_WINDOW_END = MAX(bar_ts) FROM feature_vectors` gate explicit in WHERE clause (not a comment)
- JOIN gate: only rows with a matching `feature_vectors.bar_ts` written
- `complete_Nbar` flags: false for last N bars of each series
- Idempotent: `ON CONFLICT (symbol, tf, bar_ts) DO NOTHING`
- Smoke test against VUG 1h validated causal formula against raw LEAD()
- D-06 + 3 OTel metrics + 2 spans wired; APR-compliant

## Decisions Made

- Full HMM alpha vector (`hmm_prob_*` raw components) stored as typed columns, not JSONB -- makes them direct IC features without decoding overhead
- `hmm_direction_score` excluded from schema (derivable)
- Corpus runs (regime_writer + forward_return_writer full pass) extracted to P8 -- they require `backfill_feature_factory` to complete the full corpus first

## Key Numbers (VUG 1h smoke test)
- forward_returns rows for VUG 1h: ~62,000 (matching feature_vectors exactly)
- Completeness: >99% for 1-bar, >99% for 5-bar (last 5 rows incomplete), ~99% for 60-bar
- regime labels (VUG 1h post-Task 0 smoke run): 3 regimes present, probs sum to 1.0

## Status
Tasks 0-2 complete. Corpus runs deferred to P8 (need full backfill_feature_factory corpus).
