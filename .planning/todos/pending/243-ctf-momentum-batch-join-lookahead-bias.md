---
status: pending
priority: P0
filed: 2026-08-03
source: code-reviewer subagent review of todo 241's live-path fix, mechanism
  independently verified against source before filing
---

# `ctf_momentum`'s batch/corpus join selects the still-forming HTF bar, not the last
# completed one -- real lookahead in every published IC number at 5m/15m/1h

## What

Higher-timeframe bars are stamped by **period start**, not close
(`src/core/service_utils.py:76`: *"For all higher TFs ts is the period start; close = ts +
duration"*; confirmed independently in `src/core/bar_accumulator.py:158`,
`_floor_to_period`).

`backfill_feature_factory.py`'s `_build_ctf_series()` builds a `{htf_bar_ts: (ctf_momentum,
ctf_vwap_align, ctf_regime_align)}` dict from HTF bars. The join back onto LTF rows
(`feature_factory.py:6925`) is:

```python
_idx = bisect.bisect_right(ctf_ts_list, bar_ts) - 1
```

For a 5m bar at `bar_ts=10:05`, with 1h bars stamped `[09:00, 10:00, 11:00, ...]`:
`bisect_right([...,10:00,11:00,...], 10:05) - 1` lands on the `10:00` HTF bar -- the bar
covering 10:00-11:00, which has **not closed yet** as of 10:05 (closes at 11:00). But
`_build_ctf_series` computes Wilder RSI from `closes = np.array([b["close"] for b in
htf_bars])` -- the `10:00` bar's `close` value used in that RSI is only known once the bar
actually finishes forming, at 11:00. Using it to characterize the moment at 10:05 is
lookahead: at that exact wall-clock instant in a real trading scenario, that closing price
does not exist yet.

Same shape at every affected tf:

| LTF | HTF | Lookahead window |
|---|---|---|
| 5m | 1h | up to 55 minutes |
| 15m | 1h | up to 55 minutes |
| 1h | 1d | up to a full trading day |
| 1d | 1d (self-referential) | **none -- this case is fine** |

The `1d` case is genuinely safe: batch only ever processes historical, already-fully-closed
daily bars (backfill runs after the fact), so `bisect_right` selecting "the current bar
itself" is valid there -- exactly what `_build_ctf_series`'s own comment claims ("bisect_right
selects the current bar's CTF which is valid since the bar has closed at computation time").
That comment is true for 1d only; it does not hold for the cross-timeframe cases, where the
selected HTF bar is a *different, still-open* bar relative to the LTF row's own timestamp.

This affects all three CTF fields sharing this join (`ctf_momentum`, `ctf_vwap_align`,
`ctf_regime_align`), not just `ctf_momentum`.

## How this was found

Discovered as a code-review finding on todo 241 (ctf_momentum live/batch divergence fix).
Todo 241's live-path replacement (`feature_vector_pipeline.py`'s
`_update_ctf_cache_from_htf_bar`) only ever reads fully-closed bars from `self._bar_history`
(bars are appended to that buffer only after the bar closes) -- it is therefore genuinely
causal, and as a direct consequence **cannot** and does not reproduce batch's current
(lookahead-contaminated) values for 5m/15m/1h. Todo 241's own regression test was corrected
to state this honestly rather than claim false parity
(`tests/unit/services/test_ctf_momentum_live_batch_parity.py`'s module docstring).

## Why this matters

`services/cross_sectional_spread_tracker.py` ranks directly on `ctf_momentum`
(`_FEATURE = "ctf_momentum"`) -- the sole ranking signal for Phase 167's
`cross_sectional_relative_value` construction, **the first and only construction in this
project to pass both live Validation Gates**. Since live IBKR ingestion is intentionally
stopped, essentially every `ctf_momentum` value in `feature_vectors` today originated from
this lookahead-contaminated batch path. Phase 167's validated result was measured, at least
in part, against a feature containing real future information -- a live-path integrity gap in
this project's single most consequential proof to date, and exactly the kind of "silent wrong
answer" CLAUDE.md's north star treats as unacceptable.

**Not yet quantified.** The mechanism is confirmed and mechanically airtight (traced through
actual `bisect` semantics against actual bar-stamping code, not inferred). The *magnitude* --
how much this moves `ctf_momentum`'s measured IC, and whether it's enough to flip Phase 167's
Gate 1/Gate 2 verdicts -- is unmeasured. Do not assume it invalidates Phase 167 without
measuring; also do not dismiss it as immaterial without measuring. This is the explicit
project mandate: "earn promotion through proof," which cuts both ways here.

## Fix (not yet applied -- deliberately, pending measurement)

Two candidate approaches, not yet chosen:

1. **Shift the batch join back one HTF bar** -- key the CTF dict by HTF *close* time
   (`ts + TF_DURATIONS[htf_tf]`) instead of period-start `ts`, keeping `bisect_right`
   semantics, so the selected bar is always the last one that had genuinely closed by
   `bar_ts`. Simplest, most surgical fix; makes batch match what live's causal
   implementation already does.
2. Alternatively, `bisect_left(ctf_ts_list, bar_ts) - 1` against the existing period-start
   keys achieves the same effective shift without touching the dict's key semantics --
   needs careful verification against the 1d self-referential case (must stay
   "current bar is valid" there, not regress to "yesterday's bar" for 1d).

Whichever is chosen, keep the `1d -> 1d` self-referential case on its current, correct
same-bar semantics -- do not change it.

## Next step (per user direction 2026-08-03: measure before touching)

1. **Read-only measurement first.** Quantify how much the join fix changes `ctf_momentum`'s
   measured per-symbol/cross-sectional IC at 5m/15m/1h -- rerun (or diff against) the existing
   `ic_engine`/nonlinear_interaction_combiner-style measurement scripts with a corrected join
   applied to a scoped sample, without touching the live `feature_vectors` corpus.
2. Based on that measurement, decide: (a) is a corpus-wide recompute of `ctf_momentum`
   (and `ctf_vwap_align`/`ctf_regime_align`) warranted, and (b) does Phase 167's Gate 1/Gate 2
   verdict need re-running under corrected values. Both are real, expensive, load-bearing
   decisions -- explicitly the user's call, not something to trigger unilaterally.
3. Only after 1-2: apply the join fix to `feature_factory.py`, re-run affected IC/gate
   measurements for real, update `docs/research/data-edge-source-thesis.md` and Phase 167's
   verdict record with the corrected numbers.

## Cross-refs

- [todo 241](241-ctf-momentum-live-batch-compute-divergence.md) -- the live-path fix that
  surfaced this via code review; live's implementation is correct and does not need to change
  for this todo
- [todo 189](../completed/189-ctf-momentum-1d-self-referential-htf-not-cross-timeframe.md) --
  documents the 1d self-referential case, unaffected by this bug
- `docs/research/data-edge-source-thesis.md` -- cites `ctf_momentum` as "the strongest, most
  cross-regime-consistent-sign symbol-varying signal" for `cross_sectional_relative_value`;
  needs a caveat pointing here until measured
