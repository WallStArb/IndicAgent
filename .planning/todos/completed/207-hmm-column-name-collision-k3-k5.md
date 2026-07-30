---
status: completed
priority: P2
filed: 2026-07-30
closed: 2026-07-30
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

## Resolution (2026-07-30) — option (b) executed

Investigated whether anything reads the K=3 model's live value under any name before choosing
between (a) rename vs (b) stop persisting, per the fork above. Traced every consumer of
`cache.hmm_regime_prob`/`hmm_entropy`/`hmm_duration` and `FeatureVector.hmm_regime_prob`/
`hmm_entropy`/`hmm_duration` repo-wide: the only reads were the 3
`FeatureFactory.compute()`/`compute_batch()` call sites that echoed the cache value into the
constructed `FeatureVector` (now removed) and `ensemble_trainer.py`'s blind
`information_schema.columns`-based feature discovery (doesn't care about provenance, just wants
*a* numeric value — which is exactly the contamination risk, not a reason to keep two writers).
No other live code — not even the archived-adjacent I7/narrative/SMC-context modules checked
along the way — reads a "fast/real-time" K=3 semantic under any name. Per this project's Musk-5-step
mandate ("delete before adding, don't add features for hypothetical future requirements"),
renaming (option a) would have preserved unused optionality nobody asked for; deleting is the
ruthless, correct call.

**Executed:**
1. `src/intelligence/feature_factory.py`: all 3 `FeatureVector` construction sites (`compute()`,
   `compute_batch()`'s main per-bar loop, and its cold-start `_cold_start_vector` fallback) now
   pass `hmm_regime_prob=None`/`hmm_entropy=None`/`hmm_duration=None` unconditionally, matching
   how `regime` was already always `None`. `_build_feature_vector`'s parameter types and
   `FeatureVector`'s dataclass field types (`src/intelligence/schemas.py`) updated from `float`
   to `float | None` to match reality (previously a type lie — always None in practice, declared
   non-Optional).
2. `src/intelligence/feature_cache.py`: deleted the now-fully-dead K=3 forward-pass compute
   itself from `refresh_regime()` — `_hmm_forward_2d` (a Python-loop forward-algorithm pass over
   the entire close series on every `regime_cache_refresh_bars` cycle, part of todo 197's ~30%
   compute-cost finding) and `_hmm_entropy`, confirmed zero remaining callers repo-wide before
   removal. `hurst`/`shannon`/`garch_ratio`/`hma_slope_z`/`adx` (the function's other outputs,
   genuinely live) untouched.
3. **Caught mid-fix, real near-miss:** an initial repo-wide-assumed-but-actually-file-scoped grep
   missed that `services/backfill_feature_factory.py` imports `_hmm_forward_step`/`_HMM_K`
   directly for a *different*, genuinely live computation (`ctf_regime_align`, a cross-timeframe
   regime-alignment feature, distinct from `hmm_regime_prob`/etc.) — reusing the same low-level
   forward-algorithm step on higher-timeframe bars. Caught by the full test suite (4 collection
   `ImportError`s), not by review — restored `_hmm_forward_step`/`_HMM_A`/`_HMM_MEANS_2D`/
   `_HMM_VARS_2D`/`_HMM_K` (confirmed via full repo-wide grep this time), keeping only the
   genuinely-orphaned `_hmm_forward_2d`/`_hmm_entropy` removed.
4. Updated 3 test files: `test_feature_factory.py`'s two `_from_cache` tests (which had asserted
   the leak itself as correct behavior) rewritten as `_never_leaks_cache_value` tests, forcing a
   confident cache value and asserting `None` regardless; added cold-start and `compute_batch()`
   coverage (neither existed before); `test_refresh_regime_updates_cache` updated to assert the
   5 still-live fields update while `hmm_regime_prob` stays at its dataclass default.
5. `feature_vector_persistence.py`'s `_EXTERNALLY_OWNED_COLUMN_NAMES` comment updated — no
   longer describes a "two models racing" tiebreaker, now correctly states `regime_writer.py` is
   unconditionally the sole writer of all 5 excluded columns.

**Deliberately left in place:** `FeatureCache.hmm_regime_prob`/`hmm_entropy`/`hmm_duration`/
`_hmm_regime_label` dataclass field *declarations* remain (permanently inert, always at
defaults) — removing them outright is a larger structural change (risk of breaking
introspection/serialization call sites not fully audited in this pass) than the actual goal
(eliminate the wasted compute) required. Noted in `refresh_regime()`'s comment as safe to
delete in a future cleanup.

Full unit suite green (4845 passed, 2 pre-existing skips), ruff/black clean on every touched
file.
