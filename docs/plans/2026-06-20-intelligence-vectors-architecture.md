# Intelligence Vectors Architecture

**Date:** 2026-06-20  
**Status:** Active — strategic foundation  
**Role:** Conceptual "why": core thesis, V1-V4 rationale, Quant Vector seed features, phasing A-E. Read alongside `docs/plans/2026-06-20-v30-reference-architecture.md` (the technical "how").  
**Milestone:** v3.0

---

## The Core Thesis

The current indicator→signal pipeline is excellent **feature engineering** but has a structural flaw at the signal layer: Signal plugins use **hand-crafted logic** to decide when a feature combination constitutes a tradeable edge. A human encodes the belief that "RSI divergence + volume confirmation + CTF alignment = signal." This introduces researcher bias at exactly the wrong layer and produces a signal set where most plugins respond to the same underlying phenomenon — correlated signals that don't multiply information.

Renaissance's insight: **you don't need complex signals. You need many simple, uncorrelated ones with positive measured IC, combined empirically.**

The shift required is architectural:

```
Current:  Indicators → Confluence → Signal plugin logic → Binary signal → Ledger
Target:   Indicators → Confluence → Signal plugin score → IC Engine → Ensemble alpha → Ledger
```

Signals stop being "a plugin decided it has an edge." Signals become "the ensemble of scored predictors crossed a regime-adjusted threshold that empirically produces positive EV."

---

## Intelligence Vectors

The system produces alpha by aggregating independent views of the same market. Each view is a **vector** — an orthogonal source of scored prediction. The existing indicator pipeline becomes Vector 1.

```
Vector 1: Quant          — mathematical indicators, composites, signal plugin scores
Vector 2: Microstructure — order flow, CVD, trade size distribution, bid-ask dynamics
Vector 3: Macro          — cross-asset relationships, VIX term structure, yield curve
Vector 4: Calendar       — day-of-week, month-end, options expiry, index rebalance
```

Each vector independently produces a **score per bar per symbol per timeframe** in [-1, +1]. The IC Engine measures each score's predictive power against forward returns. The Ensemble weights scores by IC × orthogonality. HMM regime determines which weight set applies.

The key property: vectors must be **orthogonal by design**. Quant signals respond to price patterns. Microstructure responds to who is trading. Calendar responds to time. Cross-asset responds to macro flow. These are genuinely uncorrelated sources of information — combining them multiplies edge rather than amplifying noise.

---

## The IC Engine

The Information Coefficient (IC) is the Spearman rank correlation between a predictor score and the subsequent N-bar return. IC = 0.05 is meaningful. IC = 0.10 is exceptional. The IC engine is the empirical arbiter of which predictors carry signal.

### What it measures

For each plugin score `s` observed at time `t`, measure:

```
IC(plugin, tf, regime, lookahead_bars) = Spearman(s_t, return_{t, t+N})
```

Stratified by:
- Timeframe (1m/5m/15m/1h/4h/1d)
- HMM regime at fire time
- Lookahead window (1, 5, 10, 20 bars)
- Asset class (equity ETF, futures, FX)

IC is computed on a rolling window (last 500 observations minimum) and bootstrapped for confidence intervals. A plugin with `bootstrap_CI_lower > 0.0` at `n >= 100` has demonstrated positive predictive power with statistical significance.

**The IC engine is `shadow_registry` extended.** Shadow mode measures signal P&L after emission — it tells you whether a signal that fired produced a good outcome. The IC engine measures raw predictor score validity *before* emission — it tells you whether a feature value predicts future returns at all, regardless of whether a signal was ever emitted. Shadow is outcome attribution. IC is predictive validity. Both are necessary; neither replaces the other.

### What this tells us

After Phase 133 rebuilds the corpus (~737+ signals across 35+ plugins over the full bar history):
- Which of the 138 plugins actually predict future returns
- In which regimes each plugin's IC is positive (and in which it is zero or negative)
- Which plugins are correlated with each other (IC for their combined score vs IC for each alone)
- The optimal lookahead window for each plugin's predictive power

This is the empirical foundation that replaces researcher intuition.

---

## Implementation Phasing

### Phase A: IC Measurement (prerequisite: Phase 133 corpus complete)

**What:** Run IC discovery against the rebuilt signal corpus. No pipeline changes.

Measure Spearman IC for each signal plugin's `factor_scores` (already stored in `signal_events`) against `counterfactual_pnl_r` (already stored in `trade_frames`). Report:
- IC per plugin, per regime, per TF
- Correlation matrix across plugins (identify redundant pairs)
- Bootstrap CI for each IC estimate

Output: `docs/analysis/ic-discovery-report-{date}.md` + DB table `plugin_ic_scores`.

**Why first:** This is pure analysis on existing data. Zero pipeline risk. Immediately shows which plugins carry information and which are noise dressed up as signal. The results gate everything below.

**Schema addition:**

```sql
CREATE TABLE plugin_ic_scores (
    plugin_name     text NOT NULL,
    timeframe       text NOT NULL,
    hmm_regime      text,              -- NULL = all regimes
    lookahead_bars  int NOT NULL,
    ic_value        double precision,
    ic_ci_lower     double precision,
    ic_ci_upper     double precision,
    n_observations  int,
    computed_at     timestamptz NOT NULL,
    PRIMARY KEY (plugin_name, timeframe, lookahead_bars, computed_at)
);
```

---

### Phase B: Plugin Scores (signal plugins emit scores, not just signals)

**What:** Signal plugins emit a continuous score in [-1, +1] alongside the existing binary signal. Score represents the plugin's directional conviction — negative = bearish, positive = bullish, magnitude = strength.

The existing `raw_confidence` (ICC) maps naturally to this: `score = confidence * direction`. The plugin's `factor_scores` dict (already persisted) IS the decomposed score vector.

Changes:
- Add `alpha_score: float` field to `IntelligenceEvent` (the typed bus schema)
- Signal plugins populate it (default: confidence × direction from existing ICC logic)
- `signal_events` stores it in a new `alpha_score` column
- The IC engine uses this as the predictor variable going forward

**Why now:** Zero behavior change to signal emission. Adds one float to the schema. Makes the existing data IC-measurable in a cleaner form than reverse-engineering it from factor_scores.

---

### Phase C: Ensemble Layer

**What:** A deterministic ensemble layer aggregates signal plugin scores into a single **Quant Vector alpha score** per bar. No LLM. No AI. Pure IC-weighted linear combination.

```python
alpha_quant = sum(
    plugin_score[p] * ic_weight[p][regime][tf]
    for p in active_plugins
    if ic_ci_lower[p][regime][tf] > 0.0
)
```

Where `ic_weight` is normalized IC from Phase A, adjusted for correlation (correlated plugins share weight rather than each getting full weight).

The Quant Vector score replaces hand-crafted signal plugin confidence. A signal is emitted when `alpha_quant` crosses the regime-adjusted threshold AND the ensemble CI supports positive EV.

This runs in-process in `IntelligencePipeline`, after the signal tier, consuming the plugin scores from the typed bus. DAG: indicators → composites → structure → context → patterns → confluence → signals(scores) → ensemble → signal_events.

**DB additions:**

```sql
ALTER TABLE signal_events ADD COLUMN alpha_score_quant double precision;
ALTER TABLE signal_events ADD COLUMN ensemble_ci_lower double precision;
```

---

### Phase D: Vector 2 — Microstructure

**What:** A new plugin tier (or structure/context tier additions) that scores each bar on microstructure quality:
- OFI (Order Flow Imbalance): `(buy_vol - sell_vol) / total_vol` — already partially in codebase
- CVD slope: directional volume pressure over N bars
- Trade size distribution: large vs small trade ratio (institutional vs retail signal)
- Spread-adjusted return: price move normalized by bid-ask spread (removes noise)

These produce a `microstructure_score` per bar. IC is measured against forward returns independently of the Quant Vector.

**Key property:** Microstructure scores are orthogonal to technical indicators by construction — OFI responds to who is trading (flow), not what the chart looks like (price pattern). The correlation between OFI score and RSI score is near zero.

---

### Phase E: Vector 3 & 4 — Calendar and Macro

**Calendar Vector (Vector 4 — implement first, trivially orthogonal):**

Purely time-based features — no market data needed beyond the timestamp:
- Day of week (Monday gaps, Friday drift, etc.)
- Month-end window (+/- 2 days of EOM): institutional rebalancing flows
- Options expiry week: gamma exposure suppresses realized vol
- Index reconstitution period: forced buying/selling of additions/deletions
- Earnings blackout periods: reduced institutional activity

Each feature produces a signed score. IC measurement against forward returns stratified by asset class and regime. These are trivially uncorrelated with technical signals.

**Macro Vector (Vector 3 — already partially built in the context tier):**

Cross-asset relationships already computed (`flight_to_quality`, `yield_curve`, `vix_regime`). The shift is:
- Produce a continuous macro score per bar (not a binary regime flag)
- Measure IC of macro score against forward returns
- Feed into ensemble as independent vector

---

## Simple Price Action Feature Library (Quant Vector seed)

Simons was explicit: simple features with positive IC beat complex ones with higher IC because they're more robust — complex features overfit. The following are the seed candidates for the Quant Vector, each with documented statistical properties and near-zero correlation with each other:

| Feature | Computation | Known property |
|---------|-------------|----------------|
| Short-term momentum | 1/3/5-bar return | Behavioral persistence (under-reaction) |
| Range position | (close - N-bar low) / (N-bar high - N-bar low) | Mean reversion signal; known reversal predictor at extremes |
| Gap fill rate | % of overnight gap closed intraday | Structural: gaps created by order imbalance tend to fill |
| Open-to-close decomposition | (close - open) vs (open - prev_close) | Separates informed (overnight) from uninformed (intraday) flow |
| Volatility-normalized return | bar_return / ATR | Removes regime noise; makes returns comparable across vol states |
| Bar close position | (close - low) / (high - low) | Buying/selling pressure within bar; complements candle patterns |
| Volume deviation | volume / N-bar avg volume | Attention and conviction proxy; high vol = informed participation |

None of these alone is tradeable. All of them in an IC-weighted ensemble — that's the edge. These slot into the existing indicator tier as additional plugins and feed into the Quant Vector ensemble.

---

## Alpha Decay Monitoring

Edges erode. A plugin that had IC = 0.06 two years ago may have IC = 0.01 today as the market adapts. The IC engine must run on a rolling window, not a static backtest, and trigger down-weighting automatically when a plugin's rolling IC falls below threshold.

- Rolling IC window: last 500 observations (or 90 days, whichever is larger)
- Alert threshold: rolling IC drops below 0.02 or CI_lower crosses zero
- Action: plugin weight in ensemble reduced to zero automatically via APR; human review flagged
- Recovery: plugin weight restored if rolling IC recovers above threshold with n >= 100

This is the continuous discovery loop — the system self-corrects as market regimes shift, without requiring manual intervention. It mirrors the shadow mode promotion/demotion cycle but operates on raw predictor scores before signal emission.

---

## Where to Start Right Now

**Today:** Phase 133 corpus rebuild. This is the prerequisite for everything. The IC engine runs on the rebuilt corpus.

**After Phase 133:** Phase A — IC measurement. Write a one-shot script that:
1. Reads `signal_events.factor_scores` joined with `trade_frames.counterfactual_pnl_r`
2. Computes Spearman IC per plugin, regime, TF, lookahead
3. Produces `plugin_ic_scores` table + markdown report

The report will immediately show which of the 138 plugins carry information. That finding determines the scope of Phase B and C — we may find that 30 plugins have positive IC and 108 are noise, which dramatically simplifies the ensemble.

---

## What This Doesn't Change

- The indicator-through-confluence pipeline is unchanged — it produces the features the ensemble consumes
- Signal ledger schema is additive only (new columns, not new tables)
- HMM regime detection remains the regime-conditioning mechanism
- APR governs all thresholds and weights
- Shadow mode governs promotion

The architecture doesn't discard the current work. It adds the empirical layer that was always the missing piece: **a mechanism to measure whether the signals we generate actually predict what we think they predict.**

---

## Success Criteria

| Milestone | Signal |
|-----------|--------|
| Phase A complete | IC report shows at least 10 plugins with IC > 0.03 and CI_lower > 0.0 |
| Phase B complete | `alpha_score` populated in `signal_events`; IC measurable on continuous scores |
| Phase C complete | Ensemble alpha beats any single plugin's IC on held-out test period |
| Phase D complete | Microstructure vector IC is statistically independent of Quant Vector IC |
| Full V1 (A-D) | Sharpe of ensemble signal > Sharpe of best single-plugin signal on corpus |
