---
**Created:** 2026-06-28
**Area:** intelligence
**Type:** new_feature
**Priority:** P3
**Effort:** 5-7 days
**Benefit:** LLM-scored context features (earnings sentiment, macro summaries) join feature_vectors
**Risk:** medium (I8 AI system integration)
**Gate:** I8 LLM evaluation stable
---

# 020 — Context Features Cluster (Phase B milestone)

**Priority: Phase B+ — gated on 007 (tf-agnostic table design) and IC engine live.**
**All four providers implement against the same `context_features` table. Design once, build four.**

---

## Provider A — I8 LLM-Scored Features (earnings sentiment, macro summaries)

v2.x I8 plugin infrastructure is archived. The underlying value reframes as daily
LLM-scored features joining `feature_vectors` by date at IC computation time.

Three extensions (independent, not sequential):

1. **Counterfactual Insight Generator** — for every generated signal, produce companion
   analysis ("What needs to be true to validate/invalidate this setup?")
   Output to `context_features` alongside main narrative.

2. **Regime Change Explainer / Daily Brief** — on HMM regime transitions, LLM-authored
   explanation of the shift. Daily digest at session open: cross-instrument regime
   summary, links symbol-level context to macro narrative.

3. **Anomaly Triage Assistant** — ops LLM that reads metrics/logs and explains pipeline
   anomalies. Uses existing LLM chain + OTel observability.

Gate: `context_features` table in 007 designed and migrated.

---

## Provider B — Earnings Provider Lane

IBKR Fundamental Data (already available via existing TWS connection — no new subscription).

1. **EarningsProviderAgent** — fetches quarterly EPS, consensus, surprise %, report timing
   via `src/providers/ibkr.py` extension. Publishes to `topic_ctx_earnings_raw()`.
2. **EarningsComputeAgent** — normalizes: `days_to_next`, `last_surprise_pct`,
   `surprise_zscore`, `last_direction`. Publishes to `context_features` as event-driven rows
   (`feature_date = earnings_date`, symbol-scoped).

---

## Provider C — Macro Event Provider Lane

Calendar events (FOMC, CPI, NFP) are the largest single-day vol catalysts.

1. **MacroEventProviderAgent** — ingests economic calendar via FRED API (free).
   Events: FOMC, CPI, NFP, PMI, GDP. Publishes to `topic_ctx_macro_raw()`.
2. **MacroEventComputeAgent** — normalizes: `fomc_days_away`, `cpi_days_away`,
   `current_regime` (hiking/pausing/cutting), `vix_term_structure_slope`.
   Writes to `context_features` as global rows (`symbol=NULL`).

Sources: FRED API, IBKR calendar, or Trading Economics (paid).

---

## Provider D — News Sentiment Provider Lane (Phase C+, ships last)

Lowest priority. Ships after A/B/C proven on deterministic data.

NLP quality concerns, provider bias, and continuous latency make this harder than
earnings/macro. Needs NLP quality validation before IC measurement.

1. **NewsProviderAgent** — fetches headlines per instrument via RSS/API
2. **NewsSentimentComputeAgent** — sentiment_1d, sentiment_7d, event_count_1d,
   high_impact_flag via LLM pipeline or FinBERT
3. Writes to `context_features` as intraday/daily NLP scores

Gate: API subscription (AlphaVantage, Polygon, or similar) + NLP model selected +
deterministic context path from A/B/C proven.

---

## Sequence

```
007 (context_features table) → B+C together (deterministic, parallel) → A (LLM) → D (NLP, Phase C+)
```

B and C implement the same write pattern against `context_features` — build together.
A adds LLM complexity but same table. D trails as Phase C+ after signal quality validated.
