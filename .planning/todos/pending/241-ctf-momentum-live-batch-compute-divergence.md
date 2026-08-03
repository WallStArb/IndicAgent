---
status: pending
priority: P1
filed: 2026-08-03
source: user question about ctf_momentum's HTF tracking mechanics, mid-session
---

## What

`ctf_momentum` is computed by two genuinely different formulas in the live-serving path vs the
batch/corpus path, sharing one column name with no distinguishing metadata:

- **Batch/corpus** (`services/backfill_feature_factory.py`'s `_build_ctf_series()`, lines
  350-380ish, driven by `_CTF_HIGHER_TF` mapping at line 160: `5m->1h, 15m->1h, 1h->1d,
  1d->1d`): a causal Wilder RSI (period `rsi_mid_period`) computed over the mapped HTF's own
  bars, normalized to `[-1, +1]`. This is what every IC measurement, `nonlinear_interaction_combiner`,
  and Phase 167's live cross_sectional_relative_value construction were validated against.
- **Live serving** (`services/feature_vector_pipeline.py`'s `_update_ctf_cache_from_bar()`,
  lines 1422-1429): `(bar.close - bar.open) / bar.open` on the HTF bar -- a crude same-bar
  intrabar-return proxy, explicitly called "Simple proxy" in its own docstring. Not an RSI, not
  clipped to `[-1,+1]`, not the same statistic at all.

If live IBKR ingestion resumes, live-served `ctf_momentum` will silently diverge from the value
every downstream measurement (IC scores, the trained ensemble, Phase 167's tracker) was proven
against -- a live/batch parity violation of the kind this project treats as architecturally
non-negotiable (see todo 221's `vix_z`/`flight_quality`/`yield_slope_z` precedent, and the
Phase 165 close-out note's "vacuous live/batch parity check" fix).

## Why the existing parity guard didn't catch this

`tests/unit/intelligence/test_feature_factory_batch_parity.py` only tests `FeatureFactory.
compute()` vs `compute_batch()` -- the pure math *inside* `feature_factory.py`. Both its
streaming and batch fixtures pass `ctf_momentum=0.0` in as a fixed, already-given `FeatureCache`
value (lines 573/729) and never exercise the two service-layer functions
(`_update_ctf_cache_from_bar()` vs `_build_ctf_series()`) that actually produce it. Those live
one layer above `FeatureFactory`, so the harness proves internal consistency given a value, not
that live and batch compute the same value. Real scope gap, not unique to `ctf_momentum` --
worth keeping in mind for any other cache field populated by service-layer code outside
`FeatureFactory.compute()`/`compute_batch()` (`ctf_vwap_align`/`ctf_regime_align` share the same
`_CTF_HIGHER_TF`-keyed batch construction and are worth checking too, not yet done).

## Recommended fix

Batch's Wilder-RSI version is the correct one (it's what's IC-validated). Wilder RSI is a
recursive/EMA-style update -- an incremental live version is feasible without restructuring:
maintain running avg-gain/avg-loss state per `(symbol, mapped_HTF)` in `FeatureCache`, updated
each time an HTF bar arrives, using the identical formula `_build_ctf_series()` uses. Extract
the RSI-update math into a shared function both paths call, rather than reimplementing it a
third time -- same DRY lesson as todo 214's `ic_engine.py`/`ensemble_ic_engine.py` duplication
finding. Delete the intrabar-return proxy outright once the incremental version lands; don't
keep it as a fallback.

## Scope note

Currently low-blast-radius since live IBKR ingestion is intentionally stopped (see
`project_ingestion_intentionally_paused` memory) -- no live traffic is being silently corrupted
today. P1 rather than P0 because of that, but it's a live-path integrity gap that will bite
silently the moment ingestion resumes, and per this project's "silent wrong answers are worse
than loud crashes" principle it should be fixed before that happens, not discovered after.

## Fix implemented 2026-08-03, pending commit

`_update_ctf_cache_from_htf_bar()` (`feature_vector_pipeline.py`, replaces
`_update_ctf_cache_from_bar()`) now computes ctf_momentum via the shared `_rsi_simple()`
helper (`feature_cache.py`, same function `_build_ctf_series()` uses) over buffered HTF bars
in `self._bar_history` -- the recommended fix above, implemented as a full-recompute on each
HTF bar arrival (negligible cost at 1x/hour or 1x/day per symbol; confirmed via `/simplify`'s
efficiency-angle review) rather than incremental Wilder state, to avoid a second hand-rolled
smoothing recursion. `_CTF_HIGHER_TF` moved to `feature_cache.py` as the single shared source
of truth for both service files (was previously duplicated). Old proxy method deleted, not
kept as a fallback.

Went through `/simplify` (4 parallel review agents: reuse/simplification/efficiency/altitude --
one minor style fix applied, one APR-compliance gap filed separately as
[[242-ctf-higher-tf-mapping-not-apr-governed]]) and an independent code-reviewer subagent pass,
which found and led to fixing 4 more real issues within this fix's own scope:

1. **Cold-start gap** -- ctf_momentum was stuck at the FeatureCache default (0.0) for up to an
   hour (5m/15m) or a full day (1h) after every restart, since the original fix only recomputed
   on live HTF bar arrival, not from already-seeded history. Fixed: `_seed_bar_history_from_db()`
   now calls `_update_ctf_cache_from_htf_bar(..., create_if_missing=True)` for every seeded
   symbol/HTF at setup time (safe -- no concurrent bar processing exists yet at that point).
2. **Warm-up truncation bug** -- `_get_cache()`'s `[:-1]` history-exclusion (correct at its
   original call site, where the excluded bar is "the one currently being processed") would
   have silently dropped one real historical bar's contribution to session-VP/overnight-range/
   session-levels state when the CTF path created a *different* tf's cache for the first time.
   Fixed: `_get_cache()` gained an `exclude_last: bool` param; the live-steady-state CTF call
   site (`create_if_missing=False`, the default) only writes into *already-existing* caches
   instead, avoiding the race entirely rather than risking double-counting.
3. **Silent-zero failure mode** -- an APR override raising `feature.period.rsi.mid` at/above
   `BarHistory`'s 200-bar cap would have made `_wilder_rsi_series` return an all-50.0 series
   (ctf_momentum=0.0) forever, with no error. Fixed: extracted
   `_assert_rsi_mid_period_fits_bar_history()` (plain function, no self/DB, directly
   unit-testable), called at config-load time in `_prewarm_threshold_config()` -- fails loud
   instead (CLAUDE.md: silent wrong answers are worse than loud crashes). `BarHistory` gained a
   public `maxlen` property to support this (was private-only).
4. **Test honesty** -- the original regression test's monotonic-uptrend fixture saturated RSI
   to exactly 100/clipped ctf_momentum to exactly 1.0, so its equality assertion proved less
   than it appeared to. Rewritten with a mixed up/down series landing strictly inside (-1, 1),
   plus new tests for buffer-truncation (>200 HTF bars) and the new RSI-period guard. Test file's
   scope note also corrected to be explicit about what it does NOT prove (see below).

**One finding from the same review was NOT fixed here -- filed as its own, more serious,
separate P0 todo instead:** [[243-ctf-momentum-batch-join-lookahead-bias]]. The reviewer found
that batch's LTF-to-HTF join (`feature_factory.py`'s `bisect_right` against period-start-stamped
HTF bars) selects the *still-forming* HTF bar for 5m/15m/1h, not the last completed one --
real lookahead in every published `ctf_momentum` IC number at those tfs, including what Phase
167's live tracker was validated against. This fix's live implementation is actually causal and
correct; it is batch that has the deeper, pre-existing bug (not introduced by this fix). Per
user direction 2026-08-03: measuring the impact comes before touching the batch join or
triggering any corpus recompute -- see 243 for the full mechanism and next steps.

Verification: 7/7 tests in `tests/unit/services/test_ctf_momentum_live_batch_parity.py` pass;
full `tests/unit/` suite green (no regressions). Not yet committed -- next step per this
project's Done-Coding SOP.
