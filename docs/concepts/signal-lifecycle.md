# Signal Lifecycle

**Last Updated:** 2026-03-11

## Overview

A signal in IndicAgent is not a point-in-time event — it is a lifecycle. From the moment I7 fires a setup to the moment it expires or hits a target, the signal passes through a structured sequence of states tracked by the **Signal Lifecycle Service**.

The lifecycle captures:
- Whether the signal's entry zone was ever touched (activation)
- How far price moved in favor and against the trade (MAE/MFE)
- Which of 8 possible outcomes closed the trade

This data becomes the **labeled training dataset** for the ML scoring model.

---

## Signal Origin: I7 Setup Detection

The I7 tier (17 setup plugins + CISScorer aggregator + SignalAggregator) fires signals when it detects high-confidence trading setups. Each signal is written to `signal_ledger` (TimescaleDB) with:

- `symbol`, `feature_ts`, `feature_tf` — join key back to `intelligence_features`
- `direction` — `long` or `short`
- `entry_low`, `entry_high` — the entry zone (from `TradeFrame.zone_low/zone_high`)
- `stop_loss` — initial stop level
- `target_1`, `target_2`, `target_full` — profit targets
- `ttl_bars` — how many bars until the signal expires if never activated
- `confidence` — CISScorer output (0–1)

Signals start with `status = "pending"`.

---

## Signal States

```
pending           ──► active ──► closed
    └─────────────────────────────────► closed (ttl_expired, never_activated)
regime_suppressed ──► (virtual active) ──► closed (shadow, status never changes)
```

| State | Meaning |
|-------|---------|
| `pending` | Signal fired and regime-eligible; waiting for price to enter entry zone |
| `active` | Price entered the entry zone; trade is live |
| `closed` | Trade exited via stop, target, or TTL expiry |
| `regime_suppressed` | Signal fired but failed the regime gate — not published to the stream. Tracked as a **shadow signal**: the lifecycle service virtually activates it from the signal bar close and records MAE/MFE/outcome without changing its status. This counterfactual data validates and tunes regime gate thresholds empirically. |

`regime_suppressed` signals accumulate as the primary feedback dataset for gate calibration. A regime gate that cannot be validated by its own shadow data has no place in a quant system.

---

## Activation: Zone Entry

The **Signal Lifecycle Service** (`services/signal_lifecycle_service.py`, systemd: `indicagent-signal-lifecycle`) reads 1m market bars via a dedicated consumer group (`signal_lifecycle`).

For every pending signal, each new 1m bar checks whether price entered the entry zone:

```python
if signal.direction == "long":
    activated = bar.low <= signal.entry_high  # price dipped into zone
elif signal.direction == "short":
    activated = bar.high >= signal.entry_low  # price rose into zone
```

On activation, `status` transitions to `active` and `activated_at` is recorded.

---

## MAE / MFE Tracking

Once active, the service tracks **Maximum Adverse Excursion** (MAE) and **Maximum Favorable Excursion** (MFE) in real time:

- **MAE** — worst drawdown against the trade (how far against the position before it closed)
- **MFE** — best peak in favor of the trade (how much the trade could have made)

These are maintained as in-memory dicts keyed by `signal_id` and written to `signal_ledger` when the trade closes:

```python
_mae: dict[str, float]   # signal_id → worst adverse price
_mfe: dict[str, float]   # signal_id → best favorable price
```

MAE/MFE are expressed in price points from the entry zone midpoint.

---

## 8-Class Outcome Classification

Every closed signal receives one of 8 outcomes:

| Outcome | Trigger |
|---------|---------|
| `never_activated` | TTL expired, price never entered the entry zone |
| `stopped_at_entry` | Hit stop before leaving the entry zone (bar 0–2 in trade) |
| `stopped_in_trade` | Hit stop after the trade was moving (bar 3+ in trade, or MFE < threshold) |
| `target_1` | Price reached `target_1` but not `target_2` |
| `target_1_2` | Price reached both `target_1` and `target_2` but not `target_full` |
| `target_full` | Price reached all three targets |
| `ttl_expired_ahead` | TTL expired while trade was in positive territory (MFE > threshold) |
| `ttl_expired_behind` | TTL expired while trade was in negative territory |

The stop outcomes (`stopped_at_entry` / `stopped_in_trade`) are resolved by `_classify_stop_outcome(mfe, bars_in_trade)` — the raw exit only knows a stop was hit, not which class.

---

## Outcome Propagation to LLM Audit

When a signal closes, the lifecycle service publishes the outcome to `llm_outcomes:stream`:
- Signal ID, symbol, timeframe, outcome class, pnl_r, mae, mfe
- `llm_writer_service` consumes this stream and back-fills the outcome onto any `llm_calls` records that generated this signal's narrative
- This closes the feedback loop: every LLM narrative call now knows whether the signal it described was profitable

---

## Database Schema

The `signal_ledger` table (migration `015_signal_lifecycle_fields.sql`) carries 14 lifecycle columns alongside the original I7 signal fields:

```sql
-- Lifecycle state
status          TEXT DEFAULT 'pending'   -- pending|active|closed|regime_suppressed
activated_at    TIMESTAMPTZ
closed_at       TIMESTAMPTZ
bars_in_trade   INTEGER

-- Excursion tracking
mae             FLOAT   -- maximum adverse excursion (points)
mfe             FLOAT   -- maximum favorable excursion (points)

-- Outcome
outcome         TEXT    -- one of 8 outcome classes
exit_price      FLOAT
exit_reason     TEXT    -- stop|target_1|target_1_2|target_full|ttl_expired

-- Zone bounds (resolved at signal creation)
zone_low        FLOAT
zone_high       FLOAT
```

---

## Signal Generator Warmup

After a service restart, `signal_generator_service` needs ~50 live 1m bars (≈50 minutes) to warm up `bar_history` before setup plugins fire. The consumer group is NOT rewound on restart — it picks up from the current stream position. No signals will fire during warmup; this is expected and normal.

---

## Training Data Use Case

The `signal_ledger` table with lifecycle outcomes is the primary labeled dataset for future ML work:

```sql
SELECT
    f.*,                          -- 200+ feature columns from intelligence_features
    s.outcome,                    -- 8-class label
    s.mae, s.mfe,                 -- continuous targets
    s.bars_in_trade
FROM intelligence_features f
JOIN signal_ledger s
  ON f.symbol = s.symbol
 AND f.feature_ts = s.feature_ts
 AND f.feature_tf = s.feature_tf
WHERE s.outcome IS NOT NULL;
```

Every signal outcome tells you: given these market conditions at the time of entry, what happened?

---

## Related Documentation

- [Intelligence Tiers](intelligence-tiers.md) — I7 setup plugins and CISScorer
- [Regime Classification](regime-classification.md) — regime gates that filter I7 signals
- [Data Pipeline](data-pipeline.md) — how signals flow from stream to TimescaleDB
- **Code:** `services/signal_lifecycle_service.py`, `src/intelligence/trading/`
- **Migration:** `production/migrations/015_signal_lifecycle_fields.sql`
