---
status: pending
priority: P2
filed: 2026-07-30
source: found investigating todo 205 (feature_vectors.regime --refresh clobber) — a second,
  narrower dual-writer collision on the same mechanism, already contained but not eliminated
renumbered: from 206 (2026-07-30) -- collided with a concurrent session's todo 206
  (intraday same-session forward-return gate), unrelated topic
---

## What

`feature_vectors.hmm_regime_prob`/`hmm_entropy`/`hmm_duration` are written by two genuinely
different HMMs sharing one column name:

- `regime_writer.py`: per-symbol, BIC-selected K=5, fitted via EM on full history,
  `alpha.hmm.random_state=42` (APR-governed, changing it invalidates `feature_ic_scores`) —
  the model already treated as ground truth for IC/alpha measurement elsewhere in the system.
- `feature_cache.py`'s inline model (used by `FeatureFactory.compute()`/`compute_batch()`):
  fixed-params K=3, forward-filter only, resets to a uniform prior every 30 bars (todo 197) —
  a cost-driven real-time approximation, never validated by BIC or any other criterion.

**Verdict, reached with evidence, not left open:** K=5/`regime_writer` is authoritative.
K=3 has never earned that status empirically (no BIC, no model-selection proof) — it exists
for real-time compute-cost reasons, not measurement accuracy. This is not ambiguous under this
project's own "earn promotion through proof" principle.

**Why this is contained today, not urgent:** `ic_engine.py:345` requires `regime IS NOT NULL`
to stratify for IC measurement, and `regime_writer.py`'s `_bulk_update_by_key` writes `regime`
and the hmm triple in one atomic UPDATE (`set_cols`, `regime_writer.py:695-704`). A row can
never be IC-scored while it still holds the K=3 placeholder — the moment `regime` goes
non-NULL, the hmm triple is settled to K=5 values in the same write. Todo 205's fix
(`_EXTERNALLY_OWNED_COLUMN_NAMES` in `feature_vector_persistence.py`) closed the one real gap:
a `--refresh` recompute could previously re-inject K=3 values into already-settled,
already-scored rows, confirmed live (11% same-model-invariant violation on SPY/1d before the
fix). That can no longer happen.

**What's left, deliberately not fixed now:** `FeatureFactory.compute()`/`compute_batch()`
still computes and writes a placeholder value under a column name it doesn't own. Harmless
under the current gating contract (regime-null rows are never scored), but fragile — it
depends on `ic_engine`'s `regime IS NOT NULL` filter and `regime_writer`'s atomic-write
discipline both staying exactly as they are. If either changes independently (e.g. a future
IC path that doesn't filter on `regime`, or `regime_writer` splitting its UPDATE into separate
per-column passes), the placeholder leaks into measurement silently, with no test today that
would catch it.

**Confirmed live consumer, found in code review closing todo 205 (2026-07-30):**
`ensemble_trainer.py`'s `_get_feature_columns()` discovers feature columns from
`information_schema.columns` minus a `_META_COLS` set that excludes `regime`/
`regime_label_source` but NOT `hmm_regime_prob`/`hmm_entropy`/`hmm_duration` — these three are
fed to ensemble training as ordinary features today. This makes the mixed-provenance risk
concrete rather than hypothetical: any row whose value came from a K=3 write before
`regime_writer` ever reached it is silently indistinguishable, downstream, from a row carrying
the authoritative K=5 value. Todo 205's fix (excluding these columns from `--refresh`'s `DO
UPDATE SET`) is still strictly correct, but note it removes `--refresh`'s prior ability to at
least drive the column to a single uniform (if wrong) K=3 value across a full recompute —
post-fix, a mixed-provenance row's contamination is permanent until `regime_writer` next visits
it. Raises the priority of resolving ownership here from "naming hygiene" to "measurement
integrity with an active consumer" — still not urgent (no evidence yet that it's materially
biasing training), but should not sit indefinitely.

**Minor, also found in the same review:** `feature_vector_pipeline.py`'s live path hardcodes
`regime_label_source="filtered"` on every record even though `regime` is now always `None` at
publish time — the provenance claim is technically inaccurate at insert time (nothing reads
`feature_vectors.regime_label_source` today, and `regime_writer`'s eventual label IS in fact a
causal forward-filter, so the value is accurate by the time anything could read it). Not worth
a standalone fix; note only in case this column gains a consumer later.

## Recommended fix (not executed)

Either: (a) rename the K=3 inline fields to something distinct (e.g.
`hmm_regime_prob_fast`/`hmm_entropy_fast`/`hmm_duration_fast`) if they're meant to be a
persisted, queryable real-time signal in their own right, or (b) stop persisting the K=3
model's values into `feature_vectors` at all if they're purely a live in-memory signal for
I7-style gating and were never meant to be a training feature — check whether anything reads
these fields expecting the K=3 (not K=5) semantics before choosing between (a)/(b). Either way,
add a regression test asserting no code path can write a non-`regime_writer` value into these
three columns when `regime IS NOT NULL` for that row, closing the gap structurally instead of
by gating-contract coincidence.
