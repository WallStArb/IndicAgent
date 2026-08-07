# Jump/Diffusion Decomposition — Idea (Edge Source Thesis jump_diffusion_decomposition)

**Status:** Pre-registered 2026-08-07, not yet run. Ready to execute — zero remaining
methodology debt, pilot scope is a single symbol (SPY), all data dependencies verified live.
**Author:** Claude (Sonnet 5), interactive session, 2026-08-07 — not a Fable dispatch.
**Origin:** Post-mortem of Phase 167's retraction (`ctf_momentum`'s batch-join lookahead leak,
todo 243). Part of the fork-resolution discovery track: back to Signal-Extraction candidates,
not construction, until one independently proves edge. Refined in a working session applying
this project's own "council of senior engineers / what would Jim Simons demand" design
discipline — the two design constraints below exist because that review specifically asked
"what fails silently or introduces hidden bias" before any code was written, not after.
**Companion to:** `docs/research/data-edge-source-thesis.md` (this is candidate thesis
**jump_diffusion_decomposition**, one of five Signal-Extraction candidates added 2026-08-03).

---

## The core point

All existing volatility features (`garch_ratio`, `hurst`, both in `feature_vectors`) treat price
movement as one undifferentiated process. Realized-variance theory splits it into two
economically distinct components: a continuous diffusion part (steady drift/trend) and a jump
part (discontinuous, news-driven gaps) — separable via bipower variation vs. total realized
variance (Barndorff-Nielsen/Shephard). **Why we might win:** a symbol whose recent volatility is
jump-dominated (news risk) plausibly behaves differently going forward than one whose volatility
is diffusion-dominated (trend continuation) — if the existing undifferentiated vol features blend
these, they may be averaging away a real distinction. Same "the combiner/feature is blind to
structure that exists" pattern as `regime_conditional_persistence`/`nonlinear_interaction_combiner`, applied to feature
*construction* instead of *combination*.

## Formula

Barndorff-Nielsen/Shephard bipower variation, computed from genuine sub-bar returns — **never**
a rolling window of already-aggregated bars of the same timeframe being labelled:

```
For a labeled bar [t, t+Δ) at tf=15m, using its constituent 1m returns r_1...r_n:
  RV  = Σ r_i²                                    (realized variance)
  BV  = (π/2) · Σ |r_i| · |r_{i-1}|                (bipower variation — the diffusion part)
  jump_ratio = max(0, RV - BV) / RV                (bounded [0,1]; 0 = pure diffusion)
```

## Non-negotiable construction guardrails (locked before any code runs)

Both getting these wrong produces a feature that measures the wrong thing while still looking
plausible — exactly the silent-wrong-answer failure mode this project's own principles rank
above a loud crash.

1. **Sub-bar returns come from `market_data_ohlcv_tradeable` only.** The raw `market_data_ohlcv`
   table's synthetic-fill/carry-forward placeholder rows would register as zero-return
   "diffusion," silently biasing every symbol with a data gap toward `jump_ratio=0`.
2. **At `tf=1d`, the overnight gap is excluded from the jump term entirely** — compute
   `jump_ratio` from intraday returns only. Under Invariant 1 (executable returns), the overnight
   gap sits inside the entry price and is not tradeable; a naive jump measure at 1d would be
   dominated by exactly the component the executable-return definition excludes. `overnight_gap_z`
   already exists as a separate, correctly-scoped feature — don't fold the gap into this one.
3. **Pre-specified now, not decided after seeing the pooled number:** test incremental IC both
   pooled and regime-conditional (existing per-symbol HMM `regime` column). Deciding this after
   looking at the pooled result would be regime-slicing p-hacking with extra steps.

## Falsification bar

Does `jump_ratio` add incremental IC on `forward_returns.executable_open_to_open` **beyond**
`garch_ratio`+`hurst` — not whether it's predictive alone (a feature that only duplicates
existing information isn't evidence of anything). Test via partial Spearman IC
(`ic_math.py::partial_spearman_ic`, already exists — controls for both existing features in one
call), CI via `ic_math.py::_circular_block_bootstrap_ic` (the production day-clustered bootstrap,
already fixed a subtle re-ranking bug — reuse it, don't reimplement). If the partial IC's CI
crosses zero at both pooled and every regime, dead.

## Reuse plan — what's new code vs. existing primitives

| Need | Source |
|---|---|
| Fetch OHLCV bars | `services/backfill_feature_factory.py::_fetch_bars_from_db`, `_connect_db` (established cross-module-import pattern — `scripts/ops/corpus/ops_ctf_columns_recompute_15m.py` already does exactly this) |
| Partial IC controlling for existing features | `src/intelligence/statistics/ic_math.py::partial_spearman_ic` |
| Day-clustered bootstrap CI | `src/intelligence/statistics/ic_math.py::_circular_block_bootstrap_ic` |
| BH-FDR across the pooled+per-regime grid | `src/intelligence/statistics/ic_math.py::apply_bh_fdr` |
| Bipower variation formula | **New** — no existing implementation, ~10 lines |

## Pilot scope

SPY, tf=15m, full available history. Promotion to a wider symbol set only after the SPY pilot
clears the falsification bar above.

## Data verified live, 2026-08-07

`market_data_ohlcv_tradeable` and `feature_vectors` at every relevant tf are solid — deep
history, fresh through 2026-07-28 (the ~10-day staleness is the known-paused ingestion chain, not
a gap). `forward_returns.executable_open_to_open` populated with matching row counts. This
candidate touches none of the tables affected by the concurrent CTF-fix corpus work
(`feature_ic_scores`, `construction_spreads`) — it reads raw OHLCV and existing GARCH/Hurst
values directly, computing its own IC from scratch via a standalone diagnostic script, the same
pattern used throughout the CTF-leak investigation (SPY single-symbol pilots before any
corpus-wide claim).

## Promotion boundary

A PASS here does not auto-promote to a live construction — that is a separate, later decision,
same discipline that kept `nonlinear_interaction_combiner`'s real residual from being mistaken
for a tradeable signal.

## References

- `docs/research/data-edge-source-thesis.md` — hub doc, thesis summary
- `src/intelligence/statistics/ic_math.py` — reused statistical primitives
- `docs/foundation/performance-investigation-sop.md` — the general "measure before theorizing"
  discipline this design follows
