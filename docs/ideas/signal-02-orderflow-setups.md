# Orderflow-Based Setups (Research)

**Version:** 1.0.0
**Status:** draft
**Priority:** low
**Milestone:** future (post-v2.8)
**Last Updated:** 2026-02-27
**Tags:** orderflow, delta, signals, setups, ibkr, tick-data, absorption

**Source:** `.planning/IDEAS.md`

---

## Overview

Three setup ideas that depend on orderflow data (buy/sell volume, delta, absorption). Not implementable until the platform has orderflow integration (e.g. IBKR `reqTickByTickData` with bid/ask flagging or equivalent).

---

## 1. Delta Divergence Setup

**Concept:** Price makes a new high but delta (buy volume minus sell volume) diverges — i.e. delta does not confirm the high. Interpret as a reversal signal.

**Dependency:** Orderflow integration (delta series per bar or per level).

---

## 2. Imbalance Continuation Setup

**Concept:** Strong delta imbalance (e.g. >70% one-sided) suggests momentum continuation in that direction rather than reversal.

**Dependency:** Orderflow integration (delta or buy/sell volume breakdown).

---

## 3. Absorption Detection

**Concept:** Large volume at a price level with little or no price movement indicates hidden supply or demand (absorption). Useful for SMC-style levels and breakout failure.

**Dependency:** Orderflow integration (volume at price, or delta at level).

---

## Implementation Path

1. Add orderflow data source (e.g. tick-by-tick bid/ask, or exchange-provided delta/volume-at-price).
2. Store or stream orderflow-derived series (delta, volume at price, imbalance) for the same symbols/timeframes as existing bars.
3. Implement the three setups above as I7-style plugins consuming orderflow features alongside existing intelligence.
