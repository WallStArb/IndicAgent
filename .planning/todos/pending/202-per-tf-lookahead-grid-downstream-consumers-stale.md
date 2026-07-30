---
status: pending
priority: P0
filed: 2026-07-29
source: /code-review of todo 146's per-tf IC lookahead grid landing (commits
  876f40ee..96ea5200)
---

# todo 146's per-tf lookahead grid landed in the 3 primary config surfaces, but
# forward_returns rebuild + 7 downstream measurement/validation scripts still assume the
# old global 1/5/20/60 grid -- next full-corpus run risks silently mismatched IC scores

## Correction (2026-07-30)

[208](208-intraday-same-session-forward-return-gate-inconsistent-with-trade-construction.md)
found that the same-ET-session completeness gate this todo's Item 1 rebuild sequence would
apply to `forward_returns` for 5m/15m/1h is itself under active reconsideration -- Invariant
1 does not require session-boundedness, and 1h's live completeness under the current gate is
as low as 53.5% at the `mid` tier. Before running Item 1's truncate-and-rebuild step, check
208's Step 1 (`ops_lookahead_horizon_response.py --allow-overnight`) status: if 208's Step 2
lands first (removing the session gate for intraday tfs), rebuilding `forward_returns` now
under the still-session-gated `_build_forward_return_sql` produces a second rebuild almost
immediately after, once the gate changes. Sequence this todo's rebuild after 208's empirical
Step 1 resolves, not in parallel with it, for 5m/15m/1h. `1d` is unaffected either way (no
session gate applies to it), so nothing here blocks a 1d-only rebuild.

## What

Todo 146's plan (`docs/superpowers/plans/2026-07-29-per-tf-ic-lookahead-grid.md`) scoped
Tasks 1-4 tightly to the three primary config surfaces (`ICEngineConfig`,
`EnsembleICConfig`, `forward_return_writer.py`'s loader) plus `_run_lifecycle_hook`'s
gate query -- all now landed and unit-tested green. A `/code-review` pass immediately
after landing found the change is **not self-contained**: applying migration 269 without
a coordinated corpus rebuild, and without touching several other readers of the old
global `alpha.ic.lookahead.{scale}` keys, produces silently mismatched or systematically
wrong measurements rather than a clean cutover. Ranked by severity:

### 1. CRITICAL -- `forward_returns` must be truncated and fully rebuilt before the next `ic_engine` run, or scores land horizon-mismatched

`services/forward_return_writer.py`'s `_build_insert_sql` ends in
`ON CONFLICT (symbol, tf, bar_ts) DO NOTHING` and only appends new bars past the existing
high-water mark -- there is no overwrite/refresh path. The live `forward_returns` table
(36.7M rows as of 2026-07-29, all computed 2026-07-09..2026-07-22) is entirely under the
OLD grid. Meanwhile `lookahead_fast/mid/slow/extended` are in `ICEngineConfig`'s
`_COMPUTATIONAL_CONFIG_FIELDS` and feed `_compute_apr_snapshot_key`'s fingerprint, so
migration 269 has ALREADY invalidated every cell's fingerprint -- the next `ic_engine` run
will recompute everything, reading `forward_returns.return_mid` etc. still holding OLD-grid
horizons while writing `lookahead_bars` = the NEW value into `feature_ic_scores`. Every
resulting row is mislabeled: stride/embargo correction sized for the wrong horizon, and
(because `feature_ic_scores`'s ON CONFLICT key includes `lookahead_bars`) new rows land
ALONGSIDE old-grid rows rather than replacing them -- `ensemble_trainer.py`'s per-feature
best-lookahead selection (no `lookahead_bars` filter) then argmaxes over 8 candidate
horizons instead of 4, half of them stale.

There IS existing runbook precedent for this exact class of problem: `services/
forward_return_writer.py`'s runbook comment (`scripts/ops/corpus/
ops_corpus_pipeline_run.sh:311`, "forward_returns must be truncated and re-run after the
ET session-boundary fix") documents an earlier schema-affecting change that required a
manual truncate via `scripts/infrastructure/backfill/infrastructure_truncate_derived_tables.sh`
(confirmed: covers `forward_returns`, `feature_ic_scores`, and 8 other derived tables) --
that script was NOT re-invoked for this change and needs to be, in the correct order,
before the next full corpus pass that's supposed to pick up migration 269's grid. This is
the single highest-priority item here: everything else in this todo is about the
validation/measurement TOOLING being wrong; this one is about the CORPUS DATA itself
silently drifting out of internal consistency.

### 2. HIGH -- `corpus_manifest_verifier.py`'s lookahead check reads a phantom key and will become a broken gate in both directions

`src/observability/corpus_manifest_verifier.py:40,256-261`: `_APR_DEFAULT_LOOKAHEADS =
[1, 5, 20, 60]` is hardcoded and its APR key `alpha.ic.lookaheads` (plural) does not exist
in `config_state` (confirmed) -- the fallback is always used, and the check is unscoped by
`training_window_end`. Today it passes vacuously against the stale old-grid rows. After the
Step 1 rebuild above, it will hard-fail (`RuntimeError: TF 5m missing lookaheads: {5, 20,
60}`) against a fully correct corpus. Needs to become tf-scoped off
`services._batch_utils.LOOKAHEAD_FALLBACKS_BY_TF` (or the 16 real per-tf APR keys) before
the rebuild, not after.

### 3. HIGH -- `ops_ic_shrinkage.py` silently drops nearly every cell post-rebuild

`scripts/ops/alpha/ops_ic_shrinkage.py:235-236,272-275,400-405` builds a GLOBAL
bars-to-scale reverse map from the old flat grid (`{1:fast, 5:mid, 20:slow, 60:extended}`)
and does `scale = bars_to_scale.get(lookahead_bars); if scale is None: continue` -- a
silent skip on a hot path, violating this project's "never drop data that could contain
signal" principle. Post-rebuild, no 5m cell maps at all (6/12/39 not in the map); 15m/1d's
`mid=2`/`extended=10` collide with EACH OTHER's old meaning too. A global int-keyed reverse
map is ill-defined by construction once the same bar count means different scales on
different tfs (`5` is 15m's old slow AND still means nothing consistent post-grid; `10` is
both 15m's and 1d's new extended). E1's out-of-fold `ic_shrunk` gate would silently
evaluate a small biased residue and report a verdict as if it ran on the full corpus. Needs
a tf-scoped rewrite, not a re-seeded literal.

### 4. HIGH -- 6 more scripts read the stale global `alpha.ic.lookahead.{scale}` keys directly

Migration 269's own `UPDATE config_schema` comment says the old 4 flat keys are "no longer
read by ic_engine.py/ensemble_ic_engine.py/forward_return_writer.py after this migration's
code changes land" -- true, but reads as though the keys are fully dead. They are not:

- `scripts/ops/corpus/ops_oos_holdout_eval.py:67-68,253-264,375-378` -- computes OOS IC at
  the OLD `{1,5,20,60}` grid while in-sample counts (no `lookahead_bars` filter) reflect
  whatever the corpus actually holds; `_drop_verdict`'s significant-drop fraction (THE gate
  for whether v3.0 alpha replicates OOS) gets computed across mismatched horizons.
- `scripts/ops/alpha/ops_ensemble_ablation.py:415-418,563` -- `AblationConfig` is a 4th
  independent copy of the scalar lookahead pattern (already flagged out-of-scope by todo
  146's plan itself, Task 5's exclusion #2 -- restated here for completeness, not a new
  finding).
- `scripts/ops/alpha/ops_ic_null_calibration.py:97-100`
- `scripts/ops/alpha/ops_vol_normalized_target_ab.py:102-105`
- `scripts/analysis/ic_sharpe_stride_bias_check.py:51-54`

Each needs either a tf-scoped read off `LOOKAHEAD_FALLBACKS_BY_TF`/the real per-tf APR
keys, or an explicit, loud "this tool is stale relative to todo 146, do not trust its
output until updated" guard -- silent wrong numbers from a validation/calibration tool are
worse than the tool refusing to run.

## Already fixed inline (not part of this todo, noted for provenance)

Two related, cheap, already-landed fixes from the same code-review pass (commit after
96ea5200): `ic_engine.py --tf` now has `choices=_DEFAULT_TFS` (previously unconstrained,
unlike `forward_return_writer.py --tf`, so an invalid tf would `KeyError` deep inside a
`ProcessPoolExecutor` worker instead of failing argument parsing); and a stale comment in
`forward_return_writer.py` referencing the old flat `alpha.ic.lookahead.{scale}` key
format was corrected to `{tf}.{scale}`.

## Sizing

Item 1 (the truncate-and-rebuild sequencing) is an operational step, not code -- fold it
into whichever queued corpus-rebuild run is next (todo 176's sequence per STATE.md/memory:
data catchup -> `--refresh` -> one full-corpus pass) as an explicit pre-step, in the
correct order: apply migration 269 (already done) -> truncate `forward_returns` +
`feature_ic_scores` (+ everything downstream in the truncate script's table list) ->
re-run `forward_return_writer` -> re-run `ic_engine`. Items 2-4 are small, independent,
parallelizable code fixes (7 files, each a self-contained tf-scoping change) -- do NOT
bundle them into one PR; each script's fix is testable in isolation.

## References

- `.planning/todos/pending/146-lookahead-grid-per-tf-recalibration.md` -- the grid's
  empirical derivation and Step 3 rollout note
- `docs/superpowers/plans/2026-07-29-per-tf-ic-lookahead-grid.md` -- the implementation
  plan this todo's landed work followed (Tasks 1-4 complete)
- `production/migrations/269_per_tf_ic_lookahead_grid.sql` -- seeds the 16 new keys,
  supersedes (but does not delete) the 4 old flat keys
- `scripts/infrastructure/backfill/infrastructure_truncate_derived_tables.sh` -- the
  existing truncate mechanism item 1 needs re-invoked
- [208](208-intraday-same-session-forward-return-gate-inconsistent-with-trade-construction.md)
  -- disputes whether the session gate this todo's Item 1 rebuild would apply to 5m/15m/1h
  should exist at all; check its status before sequencing the rebuild
