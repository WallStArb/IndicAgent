# I7 Phase 1.5: Signal Aggregation & Management — Design

> **Status:** Approved
> **Date:** 2026-02-17
> **Goal:** Build data-first signal aggregation system that collects outcome data for future predictive model calibration

## Problem Statement

5 trading setup plugins fire independently with no coordination. This creates:
- Conflicting signals (TrendFollowing LONG vs MeanReversion SHORT)
- No way to decide which signal to act on
- No outcome tracking (did the signal work?)
- No data to calibrate or improve the system

## Design Principle: Data First

The end goal is a calibrated predictive model for buy/sell decisions. Working backwards:

```
Calibrated scoring model ← Outcome data ← Signal logging + lifecycle tracking ← Aggregation rules (NOW)
```

The aggregation rules we ship today are NOT the final model — they're the data collection mechanism that feeds the real predictive system. The signal ledger is the crown jewel; the rules are replaceable scaffolding.

## Architecture

```
Setup Plugins (5)
    ↓ (raw signals per bar)
Signal Collector
    ↓ dedup + rules-based priority
Signal Aggregator (rules-based, swappable)
    ↓
├─ signals:SYMBOL:TIMEFRAME (aggregated winner → SSE → Dashboard)
├─ Signal Ledger DB (ALL signals — winners, losers, context, outcomes)
└─ Lifecycle Tracker (monitors entry/exit/P&L continuously)
```

## Component 1: Signal Collector

- Reads all 5 plugin outputs per bar
- Deduplicates: max 1 signal per setup type per bar
- Passes signal list to aggregator

## Component 2: Signal Aggregator (Rules-Based)

Interface: `aggregate(signals: list[Signal]) → AggregatedResult`

### Conflict Resolution Rules

**Step 1 — Dedup:** Max 1 signal per setup per bar.

**Step 2 — Direction check:** Group into longs[] vs shorts[].

**Step 3 — Resolve:**

Case A — Only longs OR only shorts:
- Pick by setup priority:
  1. LiquiditySweepReclaim (SMC — rarest, highest conviction)
  2. MTFAlignment (structural — multi-TF agreement)
  3. TrendFollowing (directional — workhorse)
  4. SqueezeExpansion (tactical — volatility event)
  5. MeanReversion (counter-trend — highest risk)
- Merge supporting_factors from agreeing signals
- Boost confidence: min(1.0, winner_confidence + 0.05 × num_agreeing)

Case B — Mixed directions:
- If one side has 2+ signals and other has 1: take majority side's top priority
- If tied: use regime as tiebreaker
  - |trend_regime| > 0.4: take trend-aligned side
  - Else: emit NO SIGNAL (genuinely conflicting)

Case C — No signals: emit "none" type.

**Step 4 — Enrich:** Add aggregation metadata (num_signals_fired, num_agreeing, num_conflicting, resolution_method).

### Setup Priority Rationale

| Rank | Setup | Why |
|------|-------|-----|
| 1 | LiquiditySweepReclaim | Rarest. Requires sweep + reclaim + FVG/OB. High conviction when it fires. |
| 2 | MTFAlignment | Structural. Multiple TFs agreeing is hard to argue with. |
| 3 | TrendFollowing | Reliable in trending markets (~60% of the time). |
| 4 | SqueezeExpansion | Event-driven. Good but tactical. |
| 5 | MeanReversion | Counter-trend by nature. Highest risk. |

Priority order is a hypothesis — will be validated from outcome data.

## Component 3: Signal Ledger (Database)

Every signal logged with full context for future ML training:

```sql
CREATE TABLE signal_ledger (
    signal_id       UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    timestamp       TIMESTAMPTZ NOT NULL,
    symbol          TEXT NOT NULL,
    timeframe       TEXT NOT NULL,
    setup_plugin    TEXT NOT NULL,
    signal_type     TEXT NOT NULL,
    direction       SMALLINT NOT NULL,
    entry_price     DOUBLE PRECISION NOT NULL,
    stop_loss       DOUBLE PRECISION NOT NULL,
    targets         JSONB NOT NULL,
    confidence      DOUBLE PRECISION NOT NULL,
    confluence_score DOUBLE PRECISION NOT NULL,
    regime_context  TEXT NOT NULL,
    supporting_factors JSONB NOT NULL,
    was_selected    BOOLEAN NOT NULL,
    num_signals_bar INTEGER NOT NULL,
    num_agreeing    INTEGER NOT NULL,
    num_conflicting INTEGER NOT NULL,
    resolution_method TEXT NOT NULL,
    composite_rank  SMALLINT NOT NULL,
    market_context  JSONB NOT NULL,
    status          TEXT NOT NULL DEFAULT 'pending',
    activated_at    TIMESTAMPTZ,
    exit_at         TIMESTAMPTZ,
    exit_price      DOUBLE PRECISION,
    exit_reason     TEXT,
    pnl_ticks       DOUBLE PRECISION,
    pnl_r           DOUBLE PRECISION,
    pnl_dollars     DOUBLE PRECISION,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);
```

Key design choices:
- `was_selected` + `pnl_r` = direct training data for scoring model
- `market_context` JSONB = feature vector for ML (trend_regime, vol_regime, atr, volume, etc.)
- Non-selected signals also tracked → enables "what if we'd taken the runner-up?" analysis

## Component 4: Lifecycle Tracker

State machine monitoring active signals against price:

```
pending ──[price crosses entry]──→ active
active  ──[price hits stop]──────→ stopped_out
active  ──[price hits target_N]──→ target_N_hit
active  ──[ttl_bars elapsed]─────→ expired
pending ──[ttl_bars elapsed]─────→ expired (never activated)
```

Reads from `ticks:SYMBOL:live` or `market:SYMBOL:1m` streams. Updates signal_ledger rows with exit data and P&L calculations.

## Component 5: Position Sizing Calculator

Separate concern, applied AFTER signal selection:

```python
contracts = risk_amount / abs(entry_price - stop_loss) / point_value
contracts = min(contracts, max_contracts_per_instrument)
```

Configurable per-instrument limits. Uses point_value from IBKRContract metadata.

## Deferred (Future Phases)

- Numeric scoring model (need ~500+ signals with outcomes first)
- Per-setup weight optimization
- ML calibration (XGBoost, etc.)
- Dashboard signal panel (SSE already wired)

## Calibration Flywheel (Post-Launch)

After ~500+ signals with outcomes (2-4 weeks of running):

```
Signal Ledger → calibrate_weights.py → Calibrated weights → ScoredAggregator → Continue collecting → Recalibrate monthly
```

The rules-based aggregator implements the same interface as the future ScoredAggregator — swap is seamless.
