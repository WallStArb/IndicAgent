# 075 — Small feature additions: permutation entropy, dollar-bar pilot, sub-bar path summaries

**Status (moved to deferred/, 2026-07-10):** Bundle with todos 066/073/074 -- meant for the v3.15 corpus-rerun batch, not standalone. Revive alongside that batch.


**Source:** `docs/research/fable-2026-07-07-renaissance-layer-refinements.md` §2-3 (L0-1, L0-2,
L1-4). Note: the `ret_div_*` cross-TF divergences L0-2 mentions "building in the same pass" are
**already tracked as todo 066** — don't duplicate, just ride the same cross-TF-read
infrastructure when picked up.
**Priority:** low-medium, genuinely small/cheap items; bundle rather than build separately.
**Gate:** none.

## L1-4 — Permutation entropy (small, disciplined complement to existing complexity features)

`efficiency_ratio` and `variance_ratio` (142.5) measure linear trendiness. One nonlinear
complement worth screening: permutation entropy of the last-N returns (distribution of ordinal
patterns; low entropy = structured/predictable path, high = noise). Cheap (O(N) per bar), bounded
[0,1], no distributional assumptions. Deliberately stop there — mutual-information/transfer-entropy
features are expensive and estimator-fragile at these window sizes; premature before this cheap
member of the family shows anything. One column, standard FDR pool; will cluster with
`efficiency_ratio` and die at zero cost if it adds nothing after LW deflation.

## L0-1 — Dollar-bar shadow clock pilot (information-time sampling)

Time bars sample on a wall-clock grid; dollar bars sample per unit of transacted value,
normalizing for activity bursts (returns closer to IID, less heteroskedastic, thinner tails) —
improves every downstream estimator without changing any of them. The one L0 idea with plausible
direct IC impact rather than hygiene value.

**Pilot:** aggregate existing 5m bars into dollar bars (threshold pre-committed: trailing median
daily dollar volume / 78, one APR key `feature.dollar_bar.divisor`) for a 5-symbol pilot. Compute
the lagged-return and variance-ratio families on the dollar-bar clock, join each dollar-bar
feature to the *next time-bar*, measure against canonical time-bar executable returns. No change
to `forward_returns`, Invariant 1 untouched. Verdict: dollar-clock features must show materially
tighter IC CIs or higher IC Sharpe to earn a fuller build. One-off script + standard `ic_engine`
invocation; no new service.

## L0-2 — Sub-bar path summaries for HTF bars (realized variance from constituent bars)

The corpus holds 5m bars under every 15m/1h/1d bar, and the HTF feature set never looks inside
its own bars — 1h volatility features are OHLC-estimator approximations (Parkinson/GK/YZ) of a
quantity the 5m data measures directly. Realized variance from constituent 5m returns, plus
intrabar return skew and signed path (fraction of intrabar movement in the close's direction),
are strictly more information than any single-bar OHLC estimator. The GK-vs-realized-variance
*gap* is itself a candidate feature (jump/noise decomposition). 3-4 columns, standard FDR pool;
computable in `backfill_feature_factory` where LTF data already streams past — `feature_cache.py`
already supports the cross-TF read (same infra todo 066's `ret_div_*` needs), build both in the
same pass.
