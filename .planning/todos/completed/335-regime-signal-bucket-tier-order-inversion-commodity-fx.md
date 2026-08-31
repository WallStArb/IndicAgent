---
status: closed
priority: P0
filed: 2026-08-19
closed: 2026-08-31
source: investigating why commodity/5m/up_primary_contango was large enough to breach alpha.ic.max_cell_rows (migration 259, then 319)
fix_landed: 2026-08-20, commits db98ac0a3 (code fix + migrations 319/320) and 36f2554f3 (unrelated docs)
recompute_status: complete 2026-08-31 -- see "Closure" section below
---

# `_bucket()`'s ascending-sort contract is violated by 2 of 4 regime_signals modules — commodity and fx tier1/tier2 labels are wrong, confirmed live in market_regimes

## What's broken

`services/cross_sectional_regime_model.py::_bucket()` requires its `tiers` argument sorted
**ascending** by upper_bound, with the last tuple's bound ignored (only its name used as the
catch-all default) — this is stated explicitly in `_bucket`'s own docstring. Two of the four
`REGISTRY` modules violate this:

**`commodity_momentum_ts.build_tiers()`** (`src/intelligence/regime_signals/commodity_momentum_ts.py:111`):
```python
tiers1 = [("up_primary", primary), ("up_secondary", 0.0), ("down_secondary", -primary)]
```
Sorted **descending** (primary=0.75 > 0.0 > -0.75). Fed through `_bucket()`, this produces:
`momentum_z < 0.75` → `"up_primary"` (swallows neutral AND all negative/down momentum),
`momentum_z >= 0.75` → `"down_secondary"` (only fires for strongly POSITIVE momentum — backwards).
`"up_secondary"` is mathematically unreachable — the last-applied `where()` clause (for
`up_primary`, upper=0.75) unconditionally overwrites it since 0.0 < 0.75. The module's own
docstring claims a 4th label `"down_primary"`, which doesn't exist anywhere in the actual
`tiers1` list — docstring and code have already diverged.

**`fx_dollar_carry.build_tiers()`** (`src/intelligence/regime_signals/fx_dollar_carry.py`):
```python
tiers1 = [("strong_dollar", dollar_thresh), ("weak_dollar", -dollar_thresh)]  # dollar_thresh=0.5
tiers2 = [("risk_on", carry_thresh)]  # carry_thresh=0.0, single entry
```
Same inversion on tiers1: `dollar_z < 0.5` → `"strong_dollar"` (backwards), `dollar_z >= 0.5` →
`"weak_dollar"` (backwards). tiers2 has only ONE tuple, so `tiers[:-1]` is empty, the loop never
executes, and `_bucket()` returns `tiers[-1][0] = "risk_on"` for literally every row regardless
of `carry_z` — `"risk_off"` is unreachable, not just rare.

## Confirmed empirically, not just by code-reading

Full historical `market_regimes` table, all timeframes, both groups:

```
commodity: only up_primary_* and down_secondary_* ever appear. Zero up_secondary rows.
           Zero down_primary rows. Ever. Any timeframe.
fx:        only *_risk_on ever appears. Zero *_risk_off rows. Ever. Any timeframe.
```
This is not "these states are rare" — a semantic simulation of `_bucket()` at the real APR
threshold values (`primary_threshold=0.75`, `dollar_strong_threshold=0.5`,
`carry_risk_on_threshold=0.0`) reproduces exactly this label space and no other, confirming the
code-level diagnosis rather than a coincidental data pattern.

**`breadth_vol` (equity) and `curve_credit` (rates) are NOT affected** — both modules' tier
lists are correctly ascending-sorted; equity's real 9-way and rates' real 6-way label
distributions both match their intended full vocabularies.

## Why this matters (and how it was found)

Directly implicated in the 2026-08-19 `alpha.ic.max_cell_rows` breach (see migration 319):
`commodity/5m/up_primary_contango` hit 4,687,380 rows — by far the largest cell in the entire
4-group corpus run — because it's a mislabeled catch-all swallowing most of the true momentum
distribution (up AND down), not a genuine minority-regime cell. The oversized-cell symptom is
downstream of this labeling bug, not an independent sizing issue.

More importantly: every `feature_ic_scores` row currently stratified by a `commodity` or `fx`
`regime_label`, and any `ensemble_weights`/`ensemble_alpha` trained from those regime-conditional
IC scores, has been measuring predictive power conditional on a **mislabeled** regime for as
long as these two groups have been enabled. This corrupts the "segment by regime" principle
specifically for these two groups — equity and rates are unaffected.

## Fix

1. Sort `tiers1`/`tiers2` ascending by upper_bound in both modules, matching `_bucket()`'s
   documented contract (`commodity`: `[("down_primary", -primary), ("down_secondary", 0.0),
   ("up_secondary", primary), ("up_primary", inf)]`-shaped, i.e. 4 real tiers, not 3; `fx`
   tiers2 needs a real second threshold to produce an actual `risk_off` state, not a
   single-entry list).
2. Reconcile `commodity_momentum_ts`'s docstring (claims 4 tier1 states) against the actual
   code (currently 3 tuples) once fixed — pick one, make them agree.
3. Once fixed, `commodity` and `fx` regime history needs a full recompute
   (`cross_sectional_regime_model.py`, both groups, all tfs) — old rows carry the wrong label.
4. Every `feature_ic_scores` row and `ensemble_weights`/`ensemble_alpha` row keyed to a
   `commodity`/`fx` `regime_label` is invalid and needs recomputing under corrected labels
   (mirrors the todo 092/183 precedent: a regime relabeling invalidates downstream IC measured
   under the old labels).
5. Add a startup-time or CI assertion that every `REGISTRY` module's `build_tiers()` output is
   ascending-sorted, so a 3rd module can't silently repeat this (the code has no automated check
   today — this was only caught by hand-tracing `_bucket()` against real data).

## Recompute status (2026-08-20)

Steps 1-2 (tier fix + docstring reconcile) and step 5 (guard, hardened past a code
review — moved into `_bucket()` itself, not just `main()`'s two call sites) are
DONE — commit `db98ac0a3`. Steps 3-4 (regime history + downstream IC/ensemble
recompute) had NOT run as of the fix landing, and could not run immediately: a
different corpus pipeline invocation (`bash ops_corpus_pipeline_run.sh --from-step
5`, PID 1887017, log `logs/corpus_pipeline_resume_regimefix_20260819.log`) was
already in flight, on step 5/8 (`ic_engine`) since 2026-08-19 — that run was
launched with `--from-step 5`, which **skips step 4** (`cross_sectional_regime_model.py`,
the writer of `market_regimes`), so it is consuming pre-fix, still-mislabeled
`commodity`/`fx` rows and will not self-correct. Interrupting a run with ~3 days
of sunk CPU time wasn't warranted just to fold the fix in sooner, so it was left
to finish.

**Queued instead of run immediately.** A detached watcher (`nohup`+`disown`, PID
2737924, log `logs/todo335_recompute_watcher.log`) polls for PID 1887017's exit,
checks `logs/corpus_pipeline_resume_regimefix_20260819.log`'s tail for the
`Pipeline complete` banner, and — only on confirmed success — launches
`bash scripts/ops/corpus/ops_corpus_pipeline_run.sh --from-step 4` (also detached),
logging to `logs/corpus_pipeline_todo335_recompute_<timestamp>.log`. This is
exactly steps 3-4 above: `--from-step 4` regenerates `market_regimes` for all
four groups (equity/rates redundantly, harmlessly, since `cross_sectional_regime_model.py`
has no per-group scoping flag) and then re-runs `ic_engine`/`ic_shrinkage`/
`ensemble_trainer`/`alpha_publisher` for the full symbol universe against the
corrected labels. If the in-flight run instead fails, the watcher does NOT
auto-launch the recompute and logs the failure tail for manual review instead.

Check `logs/todo335_recompute_watcher.log` and `ps aux | grep ops_corpus_pipeline_run`
for current status if picking this up in a new session.

**Update 2026-08-21: original watcher (PID 2737924) found dead.** Confirmed via `ps` (not
present) and its log (0 bytes, mtime 2026-08-20 12:43 — never wrote a single line). `disown`
alone apparently didn't survive whatever ended that terminal/session; the exact cause wasn't
investigated further, not worth the time against a one-line fix. Also found
`logs/corpus_pipeline_resume_regimefix_20260819.log` (the file the dead watcher's design was
going to tail for the `Pipeline complete` banner) itself truncated to 0 bytes with a recent
mtime — same unexpected-log-rotation shape as todo 315's `regime_writer.log` finding, would
have broken the banner-detection approach even if the watcher had survived.

Relaunched: `scripts/ops/corpus/watch_todo335_recompute.sh` (new file, `setsid`-detached this
time, PID 3892989), polls `kill -0` on wrapper PID 1887017 every 5 min instead of a log tail,
and gates the `--from-step 4` launch on `alpha_ensemble_ic` having fresh rows (DB-visible
success signal) instead of a log banner — avoids the same rotation trap. If PID 3892989 is
also gone when this is next checked, don't relaunch blindly a third time; check whether the
underlying run (1887017) already finished and just recompute manually instead. **Confirmed
still alive 2026-08-21 (later same day), PID 3892989 watching PID 1887017, which is still on
step 5 (`ic_engine`, cross-sectional stratification sub-phase, 5m timeframe as of this check).**

**This todo doesn't close on its own** — [306](306-corpus-pipeline-recovery-after-disk-full-incident.md),
[285](285-phase172-full-scope-ic-engine-verification-after-volatility-cutover.md), and
[287](287-legacy-regime-probability-columns-leak-into-ensemble-training-matrix.md) all bottom
out on the same `--from-step 4` recompute this watcher will launch; check all four once it
completes rather than closing this one in isolation.

## References

- `services/cross_sectional_regime_model.py:196-244` — `_bucket()`, `_assign_labels()`
- `src/intelligence/regime_signals/commodity_momentum_ts.py:98-113`
- `src/intelligence/regime_signals/fx_dollar_carry.py:69-80`
- `production/migrations/319_ic_max_cell_rows_recalibration_universe_growth.sql` — the symptom
  this bug produced (oversized cell), fixed tactically there but root cause is here

## Closure (2026-08-31)

Steps 3-4's recompute (`--from-step 4` full chain: `cross_sectional_regime_model` ->
`ic_engine` -> `ic_shrinkage` -> `ensemble_trainer` -> `alpha_publisher`) launched
2026-08-27 11:29 UTC, completed 2026-08-31 12:16 UTC (`ic_engine` alone ran 66.1hr;
`alpha_publisher`'s own final step needed a separate bug fix along the way, see todo
351). Verified live against the corrected corpus:

**`market_regimes`, `commodity` group -- all 4 tiers now populated** (previously only
`up_primary_*`/`down_secondary_*` ever appeared): `down_primary_*` 9,248 rows,
`down_secondary_*` 277,263, `up_secondary_*` 271,047, `up_primary_*` 6,560 across
contango/backwardation/neutral sub-labels. `up_secondary` and `down_primary` -- the two
states the bug made mathematically unreachable -- are both live.

**`market_regimes`, `fx` group -- both risk states now populated** (previously only
`*_risk_on` ever appeared): `strong_dollar_risk_off` 11,648 / `strong_dollar_risk_on`
8,099 / `weak_dollar_risk_off` 253,976 / `weak_dollar_risk_on` 225,662. `risk_off` --
the unreachable state -- is live for both dollar-strength tiers.

**Propagated all the way through `feature_ic_scores`**, not just `market_regimes`:
queried `regime` values where `regime_label_source='forward_filter'` (the per-symbol
path) and confirmed the same full commodity 12-label / fx 4-label vocabularies are
present in the IC-measurement layer, not just the upstream regime table.

Every `feature_ic_scores`/`ensemble_weights`/`ensemble_alpha` row now reflects the
corrected commodity/fx labels -- the "measuring predictive power conditional on a
mislabeled regime" corruption this todo described is resolved corpus-wide.
