---
status: completed
priority: P0
filed: 2026-07-30
closed: 2026-07-30
source: consistency gate on the todo 202 pipeline relaunch found feature_vectors.regime NULL
  across all 36.8M rows after a Tier 0 --refresh recompute — root-caused and fixed same-day
  rather than deferred to "if it recurs"
---

## Resolution (2026-07-30)

**Root cause confirmed**, not inferred. `FEATURE_VECTOR_UPSERT_SQL`
(`src/intelligence/features/feature_vector_persistence.py`) is the `--refresh`/recompute escape
hatch: `ON CONFLICT (symbol, tf, bar_ts) DO UPDATE SET` over every column not in the 3-column
PK, generated generically from `_ALL_COLUMN_NAMES` so it can't drift from the INSERT variant's
column list. That genericity was the bug: `regime` and `regime_label_source` are not computed
by whichever caller builds the row (`backfill_feature_factory.py`'s `--refresh` path,
`_vector_to_params` at line 1225, always passes `regime=None` — it isn't backfill_feature_factory's
job to compute regime). Those two columns are instead owned by `regime_writer.py`, which
populates them afterward via its own `UPDATE feature_vectors SET regime = ... WHERE regime IS
NULL` pass, restart-safe by construction. Because the generic UPSERT included them in `DO
UPDATE SET`, every `--refresh` run silently overwrote every already-labeled row's `regime`
with `EXCLUDED.regime` — i.e. `None` — discarding regime_writer's prior work corpus-wide. This
is exactly what happened: the Tier 0 (Phase 164/165) combined `--refresh` recompute nulled
`feature_vectors.regime` across all 36.8M rows, caught only because `ic_engine`'s downstream
consistency gate happened to check for it.

Compounding factor: `test_upsert_updates_every_non_pk_column_exactly_once`
(`tests/unit/test_feature_vector_persistence_completeness.py`, added 2026-07-27 closing todo
176) actively asserted every non-PK column must appear in `DO UPDATE SET` — a correct guard in
general (that's what makes `--refresh` useful at all) but blind to the fact that not every
column in the table is owned by the writer calling this SQL. The test enforced the bug's
precondition without anyone noticing `regime` doesn't belong in that set.

**Fix:** added `_EXTERNALLY_OWNED_COLUMN_NAMES = frozenset({"regime", "regime_label_source"})`
alongside `_PK_COLUMN_NAMES`, excluded from `_UPDATE_SET_SQL`'s generation. Updated the
2026-07-27 test to exclude the same set from its `expected` list, and added
`test_upsert_never_overwrites_externally_owned_columns` as a permanent regression guard —
fails loud if `regime`/`regime_label_source` are ever reintroduced into `DO UPDATE SET`. All
10 tests in `test_feature_vector_persistence_completeness.py` pass; adjacent persistence/writer
tests (`test_feature_vector_writer_column_mapping.py`, `test_feature_factory_p7.py`,
`test_context_writer.py`) unaffected.

**Scope check performed:** `regime`/`regime_label_source` are the only two columns in
`_STRUCTURAL_PREFIX_COLUMN_NAMES` not computed by `FeatureFactory.compute()`/`compute_batch()`
itself — `hmm_regime_prob`/`hmm_entropy`/`hmm_duration` are a *different*, inline K=3
forward-filter HMM computed fresh by FeatureCache every run (see todo 197), not
regime_writer's separate fitted K=5 HMM, so those are correctly included in the refresh UPSERT.
No other externally-owned columns found.

**Not done here:** the *current* NULL state (36.8M rows, from the Tier 0 refresh that already
ran) is being repaired by the in-flight `regime_writer.py` relaunch (see
[[project_todo202_regime_wipe_pipeline_relaunch]] in memory) — that data recovery is orthogonal
to this code fix and already in progress in a concurrent session. This fix only prevents
recurrence on the *next* `--refresh` run.

## Extended scope (same session, same day)

A `/simplify` altitude-angle review on this fix found a second, narrower instance of the exact
same collision class: `hmm_regime_prob`/`hmm_entropy`/`hmm_duration` are *also* in
`regime_writer.py`'s `set_cols` (`services/regime_writer.py:695-704`, its per-symbol BIC-selected
K=5 fitted HMM) but were still in the refresh UPSERT's `DO UPDATE SET` — because
`FeatureFactory.compute()`/`compute_batch()` (a *different*, fixed-params K=3 forward-filter
HMM, `feature_cache.py:220`) also populates those same field names on every `FeatureVector`.
Confirmed live before the fix: 11% of SPY/1d rows carrying `regime_writer`'s K=5 probability
triple violated the same-model invariant `hmm_regime_prob <= max(p_up, p_ranging, p_down)` —
the two models' outputs were already mixed in that column. Extended
`_EXTERNALLY_OWNED_COLUMN_NAMES` to cover all three. Verdict reached (not left open): K=5 is
authoritative — BIC-selected, APR-governed (`alpha.hmm.random_state=42`), already treated as
ground truth for `feature_ic_scores` elsewhere; K=3 was never validated by any criterion and
exists for real-time compute-cost reasons. Confirmed the collision was already harmless for
actual IC measurement (`ic_engine.py:345` requires `regime IS NOT NULL` to stratify, and
`regime_writer` writes `regime` + the hmm triple atomically in one UPDATE, so a row is never
IC-scored while still holding the K=3 placeholder) — the refresh-time overwrite this fix closes
was the only real exposure. Residual naming-collision fragility (not a live integrity gap)
filed as [todo 207](../pending/207-hmm-column-name-collision-k3-k5.md), P2 (renumbered from
206 -- collided with a concurrent session's unrelated todo 206).

## Second, more serious finding from the same investigation (same day)

Chasing todo 207's naming collision down to its actual live-path behavior surfaced a live
single-writer-invariant violation, not just fragility: `services/feature_vector_pipeline.py`'s
`_process_bar_compute` (the streaming/live path, Kafka -> `feature_vector_writer.py`) derived
a heuristic `regime` label directly from `cache.hmm_regime_prob`/`cache.hmm_entropy`
(FeatureCache's K=3 model) -- `"ranging"` if `hmm_prob >= 0.6` and `entropy < 0.5`, `"ranging"`
again if `hmm_prob` in `[0.4, 0.6)`, else `None`. This directly contradicted this fix's own
stated premise ("callers always pass regime=None") -- true for `backfill_feature_factory.py`
but false for the live path.

Confirmed via code + grep, not assumed: no downstream consumer of `topic_feature_vectors`
needed this heuristic (`feature_vector_writer.py` is the sole Kafka consumer and just persists
via `FEATURE_VECTOR_INSERT_SQL`'s `DO NOTHING`; every real regime consumer --
`alpha_frame_writer.py`, `counterfactual_tracker.py`, `llm_writer.py` -- reads the
already-persisted `regime` column later, expecting `regime_writer`'s authoritative K=5 label).
Because `regime_writer.py`'s discovery (`SELECT DISTINCT symbol FROM feature_vectors WHERE
regime IS NULL`) is symbol-level and restart-safe by design, a live bar published with this
heuristic's non-NULL value would never be revisited by `regime_writer` again -- a **silent,
permanent** corruption of a measurement-critical, IC-active column, worse than the `--refresh`
clobber this todo was originally about (that one was at least visible/correctable on the next
`regime_writer` pass; this one is invisible and permanent by construction). Also structurally
wrong on its own terms: the heuristic could only ever produce `"ranging"`/`"trending_up"`,
never `"trending_down"` -- a 2-bucket approximation of a 3-label canonical set.

**Fix:** removed the heuristic entirely; `_process_bar_compute` now always publishes
`regime=None`, exactly matching `backfill_feature_factory.py`'s pattern -- establishing
`regime_writer.py` as the true sole writer, consistent with this codebase's existing DAG
Invariant pattern (`ProviderMerger` sole writer to `market.bars`, `alpha_publisher` sole writer
to `alpha_events`). New regression test
(`tests/unit/services/test_feature_vector_pipeline_regime_none.py`) forces
`cache.hmm_regime_prob=0.95`/`hmm_entropy=0.1` (the old heuristic's most-confident branch) and
asserts the published Kafka message still carries `regime=None`; verified failing against the
pre-fix code (`regime='ranging'`) before confirming it passes post-fix. Full unit suite green,
ruff/black clean.

**Currently non-firing in practice, still worth fixing now:** live IBKR ingestion is
intentionally paused (see memory: ingestion-intentionally-paused), so `_process_bar_compute`
isn't processing real bars today -- but this is live, always-on infrastructure that resumes the
moment ingestion does, and per this project's "instrument everything, never drop data that
could contain signal" principles this class of bug (silent, permanent, measurement-critical)
does not get to wait for a recurrence to be worth fixing.

## Third pass: structural fix for the ownership list itself (same day, code-review-driven)

A `pr-review-toolkit:code-reviewer` pass on the branch (correctness-focused, complementary to
the earlier `/simplify` pass) found the `_EXTERNALLY_OWNED_COLUMN_NAMES` exclusion list itself
was a **third independent hand-typed copy** of the same 8-column ownership fact --
`regime_writer.py`'s `set_cols` literal (services/regime_writer.py) and this module's exclusion
set were maintained by hand in two separate files with nothing checking they agreed. That is
exactly the failure mode `feature_vector_persistence.py`'s own docstring already documents for
FeatureVector fields (2026-07-08, todo 176): a column added to one list and not the other fails
silently, and the reviewer noted the existing `test_upsert_updates_every_non_pk_column_exactly_once`
test would *actively enforce* a reintroduced version of this exact bug if a new regime_writer
column were added to `FeatureVector` without remembering to also add it to the exclusion set.

**Fixed structurally, not just re-tested:** promoted the ownership list to a public
`REGIME_WRITER_OWNED_COLUMN_NAMES` tuple in `feature_vector_persistence.py` (Ring 1) and changed
`services/regime_writer.py` (Ring 2, legal import direction) to import and use it directly for
`set_cols`, instead of hand-typing its own copy. The two lists are now the same Python object,
not independently-maintained duplicates -- drift is structurally impossible, not merely tested
for. Added `test_regime_writer_set_cols_is_the_canonical_tuple_not_a_copy` (identity check, not
value-equality) to `test_feature_vector_persistence_completeness.py`, catching a future revert
to a hand-typed literal even if its values still happened to match at the time.

Also recorded in the source comment, per the review's second finding: `hmm_regime_prob`/
`hmm_entropy`/`hmm_duration` are live ML input -- `ensemble_trainer.py`'s `_get_feature_columns()`
excludes `regime`/`regime_label_source` via `_META_COLS` but not these three, so a row's mixed
K=3-vs-K=5 provenance is silently indistinguishable to ensemble training. This doesn't change
the fix (excluding them from `--refresh` is still strictly correct), but makes todo 207's
"unresolved design question" concrete rather than vague, and confirms `--refresh` can no longer
self-heal a mixed-provenance row post-fix (pre-fix it could at least drive the column to a
uniform, if wrong, K=3 value).

Full unit suite green (0 failures, 2 pre-existing unrelated skips), ruff/black clean on all 5
touched files (`feature_vector_pipeline.py`, `feature_vector_persistence.py`, `regime_writer.py`,
`test_feature_vector_persistence_completeness.py`, new
`test_feature_vector_pipeline_regime_none.py`).
