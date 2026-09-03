# 172-06 IC Engine Cutover: Adjacent Regime Machinery Audit

Written evidence for the three pieces of regime machinery adjacent to the Task 1/Task 2
cutover (`_assert_prerequisites`'s startup gate, `_compute_symbol_tf`'s per-symbol feature
matrix) that this plan's objective states must NOT change: `alpha.regime.groups` routing,
`dual_write_symbol_hmm`, and `_POOLED_REGIME_SENTINEL`. Also records the decision not to add
a fourth `feature_ic_scores.regime_scope` value, with the disjointness evidence that decision
depends on. Expected outcome going in: nothing here needs editing. This document is the
evidence for that, not an assertion of it.

## alpha.regime.groups routing

`alpha.regime.groups` is a JSON-typed APR key (`config_state`, namespace `alpha.*`) consumed
exclusively by `services/cross_sectional_regime_model.py`'s `_parse_group_configs()` and
`services/ic_engine.py`'s `main()` (loaded at `ic_engine.py:5062-5066` via
`ICEngineConfig.from_apr()`'s `regime_groups_json` field, `ic_engine.py:610-618,682-687`).
Each array entry configures one peer group for the **cross-sectional** `market_regimes`
system: `name` (the `regime_group` value), `tag_filter` (a list of `instrument_tags` prefix
patterns used by `_build_symbol_regime_class`, `ic_engine.py:259-339`, to route a symbol to
at most one enabled group), `signal_type` (which regime-model module computes labels for that
group -- `breadth_vol`, `curve_credit`, `commodity_momentum_ts`, `fx_dollar_carry`),
`params_prefix` (the APR namespace that signal type reads its own parameters from), `enabled`,
and `dual_write_symbol_hmm` (see next section).

Live value, queried during this task
(`SELECT config_value FROM config_state WHERE config_key = 'alpha.regime.groups'`):

```json
[
  {"name": "equity", "tag_filter": ["eq_*", "intl_*"], "signal_type": "breadth_vol",
   "params_prefix": "alpha.equity_regime", "enabled": true, "dual_write_symbol_hmm": true},
  {"name": "rates", "tag_filter": ["fi_*"], "signal_type": "curve_credit",
   "params_prefix": "alpha.rates_regime", "enabled": true, "dual_write_symbol_hmm": true},
  {"name": "commodity", "tag_filter": ["commodity_energy_crude", "commodity_energy_natgas",
   "commodity_energy_pipeline", "commodity_metals_precious", "commodity_metals_industrial",
   "commodity_agri", "commodity_broad"], "signal_type": "commodity_momentum_ts",
   "params_prefix": "alpha.commodity_regime", "enabled": true, "dual_write_symbol_hmm": true,
   "exclude_symbols": ["AMLP", "GDX", "OIH", "XLE", "XOP"]},
  {"name": "fx", "tag_filter": ["fx_*", "crypto"], "signal_type": "fx_dollar_carry",
   "params_prefix": "alpha.fx_regime", "enabled": true, "dual_write_symbol_hmm": true}
]
```

All 4 groups (`equity`, `rates`, `commodity`, `fx`) are `enabled: true` today.

**Why repointing the per-symbol label column cannot change this section's behavior:** the
regime labels this system produces live in `market_regimes`, a separate table keyed by
`(regime_group, tf, ts)`, written by `cross_sectional_regime_model.py` from each group's own
`signal_type` module (`breadth_vol.py` etc.) reading market-wide inputs (VIX, breadth,
credit spreads, FX carry) -- none of them read `feature_vectors.regime` or
`feature_vectors.regime_volatility` at all. `_build_symbol_regime_class` routes a symbol to a
group using only `instrument_tags`, not any per-bar feature column. `main()`'s market_regimes
load (`ic_engine.py:5257-5275`, `SELECT ts, regime_label FROM market_regimes WHERE
regime_group=%s AND tf=%s`) and the cross-sectional label discovery
(`ic_engine.py:5377-5383`, `SELECT DISTINCT regime_label FROM market_regimes WHERE
regime_group=%s AND tf=%s`) are both untouched by Task 1/Task 2 -- Task 2's `git diff` (verified
in the Task 2 commit) shows zero changes inside `_compute_cross_sectional_tf`, the `mr_dict`
construction, or the `market_regimes` load block. Task 1's gate change only touches the
`feature_vectors.regime_volatility IS NOT NULL` count check; the separate per-group
`market_regimes` gate (`_assert_prerequisites`'s fourth check, `ic_engine.py:1698-1717`) is
untouched in condition, order, and message, as the plan requires.

**Todo 280 note, as required:** 115/151 (76%) of the 2026-08-05/06 universe-expansion symbols
are unrouted from any enabled `alpha.regime.groups` filter (single-name equities carry the
`single_name_equity` tag, which matches no group's `tag_filter`; see todo 280's 2026-08-08
addendum, merged with todo 283). This plan neither fixes nor worsens that gap: it is entirely a
function of `instrument_tags` and the `tag_filter` config, both untouched here. Unrouted
symbols still receive the pooled IC pass (`_compute_one_regime_cell` with a pooled mask always
runs, regardless of routing) and, since Task 2 repoints the per-symbol fallback, also the
`symbol_hmm` primary pass on `feature_vectors.regime_volatility` when `equity_model_enabled`
is `False` for them or they fall through unrouted -- confirmed by reading
`_compute_symbol_tf`'s `cross_sectional = mr_dict is not None` branch: an unrouted symbol's
`mr_dict_by_tf.get(tf)` entry is `None` (never populated for it in
`mr_dicts_by_group`), so `cross_sectional` is `False` and the per-symbol volatility labels are
used as the primary (not additional dual-write) pass.

## dual_write_symbol_hmm

Every one of the 4 live groups sets `dual_write_symbol_hmm: true` today (see the JSON above).
This per-group field is read at `_resolve_symbol_routing` (`ic_engine.py:1598-1604`):
`dual_write = bool(group_by_name.get(routed_group_name, {}).get("dual_write_symbol_hmm",
False) if routed_group_name else False)`, and consumed by `_build_regime_passes`
(`ic_engine.py:2420-2450`): a symbol routed to an enabled group with `dual_write_symbol_hmm`
true gets a second stratification pass appended --
`regime_passes.append((regime_aligned, distinct_symbol_hmm_regimes, "symbol_hmm"))` -- ON TOP
of its primary `cross_sectional` pass, using `regime_aligned` as the label array (line 2448
in the current file: `distinct_symbol_hmm_regimes = [r for r in set(regime_aligned) if r is
not None]`).

**This is the one place where the routing machinery and the cutover actually meet, stated
plainly rather than filed under "unaffected":** `regime_aligned` is exactly the array Task 2
repointed. Before Task 2, a `dual_write_symbol_hmm`-enabled symbol's second pass wrote
`regime_scope='symbol_hmm'` rows carrying the 5-label trend vocabulary read from
`feature_vectors.regime`. After Task 2, that same code path (unedited itself --
`_build_regime_passes`'s source is unchanged, confirmed by the Task 2 commit's diff, which
touches only `_resolve_regime_scope`'s docstring, comments, and `fv_sql`) now carries the
3-label volatility vocabulary read from `feature_vectors.regime_volatility`, because
`regime_aligned` is populated from the repointed `fv_sql` fetch upstream in
`_compute_symbol_tf`. The pass type string `"symbol_hmm"` is unchanged -- only the vocabulary
flowing through the array it wraps changed, which is the entire point of the cutover and
exactly why plan 172-06's objective states `regime_scope` does not get a new enum value: the
label SOURCE (a per-symbol GaussianHMM, dual-written alongside the group's cross-sectional
pass) is identical before and after; only the observation columns and vocabulary that HMM was
fit on changed, and that changed back in migration 307/plan 172-04, not in this plan.

`cluster_regime_conditioned` (the Phase 151 Plan 02 run-level APR switch,
`alpha.ic.cluster_regime_conditioned` via `ICEngineConfig`, currently seeded `true` per
migration 286) is the second, OR'd gate for the same `symbol_hmm` dual-write pass
(`_build_regime_passes`'s `if cross_sectional and (dual_write_symbol_hmm or
cluster_regime_conditioned):`). Since it defaults true and every group already sets
`dual_write_symbol_hmm=true`, the OR is not currently load-bearing for whether the pass runs,
but is unchanged by this plan either way.

## _POOLED_REGIME_SENTINEL

`_POOLED_REGIME_SENTINEL = "_pooled"` (`ic_engine.py:173`) has exactly two write sites in
`ic_engine.py`, both on the pooled path:

- `ic_engine.py:2725`, the pooled pass in `_compute_symbol_tf`:
  ```python
  pooled_rows, pooled_skipped, pooled_skip_reasons = _compute_one_regime_cell(
      _POOLED_REGIME_SENTINEL,
      True,
      np.ones(len(aligned_idx), dtype=bool),
      _resolve_regime_scope(True, cross_sectional),
      ...
  )
  ```
  The mask argument is `np.ones(len(aligned_idx), dtype=bool)` -- unconditionally all-`True`,
  every aligned row included regardless of any regime label. This pass never reads
  `regime_aligned`, `regime_aligned_market`, or `mr_dict` to build its mask; it runs exactly
  once per `(symbol, tf)` "regardless of how many regime-label sources this (symbol, tf)
  computes" (the function's own comment, `ic_engine.py:2713-2716`).
- `ic_engine.py:2982`, the daily-cadence context-features pooled row (`vix_z` etc.):
  `"regime": _POOLED_REGIME_SENTINEL` paired with `"is_pooled": True` unconditionally,
  same masking-free semantics (this loop iterates once per calendar day, not per regime).

Grep confirms no other write site in this file:
```
$ grep -n "_POOLED_REGIME_SENTINEL" services/ic_engine.py
173:_POOLED_REGIME_SENTINEL = "_pooled"
2725:            _POOLED_REGIME_SENTINEL,
2982:                            "regime": _POOLED_REGIME_SENTINEL,
```

`ensemble_trainer.py`'s eligibility filter reads the literal string, not the constant (it has
no import coupling to `ic_engine.py`'s module-level name):
```
$ grep -n "_pooled" services/ensemble_trainer.py
4:Reads cross-sectional IC scores (symbol='POOLED', is_pooled=true, regime != '_pooled',
124:        "symbol = 'POOLED' AND is_pooled = true AND regime != '_pooled'"
398:    ensemble eligibility filters (symbol='POOLED', is_pooled=true, regime != '_pooled',
496:            f"(symbol='POOLED', is_pooled=true, regime != '_pooled', {significance_desc}, "
```
`ensemble_trainer.py:124`'s actual eligibility WHERE clause is `symbol = 'POOLED' AND
is_pooled = true AND regime != '_pooled'` -- this excludes the group-level cross-sectional
POOLED cell (`is_group_pooled=True` in `ic_engine.py`, a different pooling concept scoped to
`market_regimes` group aggregation, not this sentinel) while including every regime-stratified
row, and is untouched by anything in this plan: neither Task 1 nor Task 2 changed which rows
get `is_pooled=True`, `regime='_pooled'`, or `symbol='POOLED'`.

Because the pooled pass masks all rows unconditionally and never reads either the trend or the
volatility regime column, `_pooled` rows carry no vintage information at all, and
`ensemble_trainer.py`'s `regime != '_pooled'` eligibility filter keeps the exact meaning it
has today: it discriminates pooled-vs-regime-stratified, not vintage. Confirmed, not assumed.

## Vintage separation in feature_ic_scores

Decision (restated from the plan objective, evidence below): `feature_ic_scores.regime_scope`
does not get a fourth enum value for the volatility vintage. `symbol_hmm` continues to name
the label SOURCE (a per-symbol GaussianHMM); the two label vocabularies it can carry --
5-label trend (`trending_down`, `transition_down`, `ranging`, `transition_up`, `trending_up`)
and 3-label volatility (`calm`, `elevated`, `turbulent`) -- are disjoint strings, so the
`regime` column alone identifies which vintage a `symbol_hmm` row belongs to. Adding a fourth
scope value would touch every `AND regime_scope = %(pass_type)s` / `AND regime_scope =
'cross_sectional'` filter the fingerprint-invalidation and archive-before-delete queries bind
(`_FINGERPRINT_INVALIDATE_DELETE_SQL`, `ic_engine.py:1406-1412`;
`_FINGERPRINT_INVALIDATE_DELETE_CROSS_SECTIONAL_SQL`, `ic_engine.py:1419-1426`;
`_ARCHIVE_BEFORE_DELETE_SQL`, `ic_engine.py:1442-1475`;
`_ARCHIVE_BEFORE_DELETE_CROSS_SECTIONAL_SQL`, `ic_engine.py:1479-1513`), for no discriminating
power the label strings do not already provide.

Live grouped-count table, run during this task
(`SELECT regime_scope, regime, count(*) FROM feature_ic_scores GROUP BY 1,2 ORDER BY 1,2`):

```
  regime_scope   |        regime         | count
-----------------+-----------------------+-------
 cross_sectional | flat_tight            | 15184
 cross_sectional | flat_wide             | 15184
 cross_sectional | high_bear             | 58400
 cross_sectional | high_bull             | 58400
 cross_sectional | high_neutral          | 58400
 cross_sectional | inverted_tight        | 15184
 cross_sectional | inverted_wide         | 15184
 cross_sectional | low_bear              | 58400
 cross_sectional | low_bull              | 58400
 cross_sectional | low_neutral           | 58400
 cross_sectional | mid_bear              | 58400
 cross_sectional | mid_bull              | 58400
 cross_sectional | mid_neutral           | 58400
 cross_sectional | steep_tight           | 15184
 cross_sectional | steep_wide            | 15184
 cross_sectional | strong_dollar_risk_on |  7008
 cross_sectional | weak_dollar_risk_on   |  7008
 pooled          | _pooled               | 93440
 symbol_hmm      | ranging               | 67744
 symbol_hmm      | transition_down       | 67744
 symbol_hmm      | transition_up         | 67744
 symbol_hmm      | trending_down         | 67744
 symbol_hmm      | trending_up           | 67744
(23 rows)
```

Every existing `symbol_hmm` row today carries a trend-vocabulary label -- no
`calm`/`elevated`/`turbulent` row has been written yet, because `ic_engine.py --refresh` has
not run since Task 2's cutover (that run is plan 172-07's scope). This table alone does not
prove future disjointness; it only shows the pre-cutover state contains no overlap by
construction (the volatility vocabulary didn't exist yet).

An eyeballed grouped-count table is exactly the check that silently stops being performed once
this table grows past a page. Executed instead, sourcing both sides from the CVR registry
(`controlled_vocabulary`), not a hand-typed list:

**CVR-level check** -- do the two namespaces' code sets intersect at all, independent of any
particular corpus state:
```sql
SELECT coalesce(string_agg(code, ','), 'none')
FROM controlled_vocabulary
WHERE namespace = 'regime_volatility'
  AND code IN (SELECT code FROM controlled_vocabulary WHERE namespace = 'regime_hmm')
```
Result: `none`

**Live-table check** -- does any `feature_ic_scores` row under `regime_scope = 'symbol_hmm'`
carry a `regime` value that is simultaneously a registered code in BOTH namespaces (which
would only be possible if the CVR-level check above had failed):
```sql
SELECT coalesce(string_agg(DISTINCT regime, ','), 'none')
FROM feature_ic_scores
WHERE regime_scope = 'symbol_hmm'
  AND regime IN (SELECT code FROM controlled_vocabulary WHERE namespace = 'regime_volatility')
  AND regime IN (SELECT code FROM controlled_vocabulary WHERE namespace = 'regime_hmm')
```
Result: `none`

For reference, the full registered code sets at time of check:
```
regime_hmm|ranging
regime_hmm|transition_down
regime_hmm|transition_up
regime_hmm|trending_down
regime_hmm|trending_up
regime_volatility|calm
regime_volatility|elevated
regime_volatility|turbulent
```

```
VINTAGE DISJOINT: PASS
```

The `feature_vectors.regime_volatility` side of the same disjointness property is already
asserted mechanically by plan 172-05's coverage verify: its distinct-labels check confirms
`set(distinct_labels) <= {'calm','elevated','turbulent'}` over the live column, so no trend
label can be present there (`evidence/172-05-relabel-coverage.json`'s `distinct_labels` field
records exactly `["calm", "elevated", "turbulent"]`). This section covers the
`feature_ic_scores` side, where -- unlike `feature_vectors`, which has two separate columns --
the two vintages genuinely share one `regime` column under one `regime_scope` value.

**No mixing across a fresh run and a prior vintage:** the fingerprint-invalidation and
archive-before-delete queries quoted above all bind `regime_scope` together with
`training_window_end` (and, for the per-symbol variant, `symbol`/`tf`) in their WHERE clauses
-- never a bare `training_window_end` filter, per the comment at `ic_engine.py:1400-1402`: "a
bare training_window_end filter... would delete valid unrelated cells at the same window
(T-162-03-03)." A fresh `--refresh` run at a given `training_window_end` invalidates and
archives only the specific `(symbol, tf, regime_scope, training_window_end)` cells it is about
to recompute; it cannot touch a different `training_window_end`'s rows, vintage or otherwise.

**No pre-existing row is deleted by this phase.** Task 1 and Task 2 are both pure code/comment
changes plus one comment-only migration; no `DELETE`, `TRUNCATE`, or data-mutating `UPDATE`
against `feature_ic_scores` was issued by this plan. `feature_ic_scores` row count, checked
before Task 3's queries and again after writing this document
(`SELECT count(*) FROM feature_ic_scores`): **1,062,880 both times, unchanged**. Old
trend-vintage rows remain queryable exactly as written, per CLAUDE.md's Renaissance
data-retention rule -- nothing here is a repoint of what already exists, only of what a future
run writes.
