# 072 — Crowding proxy: alpha overlap with public-factor signals

**Source:** `docs/research/fable-2026-07-07-renaissance-layer-refinements.md` §10 (L7-3).
**Priority:** medium — runs against data that exists *today*, no dependency on the corpus rerun
or Phase 142B.
**Gate:** none.

## Proposal

Regress `alpha_score` (per stratum, per epoch) on 2-3 canonical public signals computed from the
same bars: 12-1 momentum, 5-day reversal, low-vol tilt. High R² doesn't invalidate the edge, but
it prices its decay risk — alpha explainable by the most public factors in existence is alpha the
crowd already trades, and its half-life should be assumed short. Report R² per epoch as a
standing manifest metric; a rising trend is a crowding alarm no IC decay monitor would catch
until later.

## Mechanics

One script; factor signals are trivial derivations of existing columns. The regression is the
measurement — the falsifiable claim is "our alpha is not just public factors," and the number
says so or doesn't. Diagnostic only, no gate change.

## Resolution (2026-07-12)

Built `scripts/analysis/crowding_proxy_regression.py`. Factors computed independently from raw
daily bars (`market_data_ohlcv`, `timeframe='1d'`) rather than reused from `feature_vectors`'
`momentum_z_slow`/`momentum_reversal_z` — those house columns turned out not to be academic
12-1/5-day definitions (see todo 103, found while scoping this), and regressing house features
against a house-feature-derived `alpha_score` would have been circular. No-lookahead as-of join:
each observation gets the factor value from strictly the prior trading day's close.

First run against the live (pre-143.1-fix) `alpha_frames` backfill: 16/18 strata fit (2 skipped,
n<30). Highest R² = 0.2674 (1d/mid_bull, n=9342) — some public-factor overlap at daily grain, but
below the 0.3 alarm line. The two primary tradeable strata (5m, 15m) show R² of 0.003-0.09 —
alpha there is NOT well explained by public momentum/reversal/vol factors, a clean result. Full
table: `docs/analysis/crowding-proxy-report.md`. Manifest:
`.planning/corpus_manifests/crowding_proxy_regression.json`.

**Not a one-time close** — this is a standing diagnostic. Re-run after Phase 143.1's corpus
re-run + `alpha_frames` backfill land (composition of eligible features is changing under 143.1),
and again each future corpus epoch, to watch for a *rising* R² trend (the actual crowding
alarm — a single snapshot can't show a trend). No code changes needed to re-run; just invoke the
script again once the next `alpha_frames` backfill completes.
