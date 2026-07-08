---
**Created:** 2026-07-01
**Area:** data-quality / intelligence
**Type:** capability
**Priority:** P2
**Effort:** 1-2 sessions (batch job + report)
**Risk:** low
**Gate:** none — runs against existing market_data_ohlcv
---

# 042 — Adversarial Data-Error Hunt

From the 2026-07-01 Simons-lens review: treat data errors as an alpha-integrity problem (and
occasionally an alpha source), not a hygiene chore. Renaissance lore is specific that hunting
bad prints was itself profitable — uncaught, bad data creates fake IC for us; caught, the
mispricing behind a bad print is sometimes real information.

Current data-quality services are uptime/completeness-flavored. This is different: an
adversarial batch job that actively hunts anomalies in `market_data_ohlcv` and quantifies
their effect on `feature_ic_scores`.

## Checks (batch, per symbol/tf)

1. **Impossible OHLC relationships** — `high < low`, `open/close` outside `[low, high]`,
   zero-range bars with nonzero volume
2. **Stale prints** — N consecutive identical closes at 5m/15m during RTH on liquid symbols
3. **Split/dividend artifacts** — overnight return outliers that coincide with corporate
   actions vs. ones that don't (the latter are either real events or bad data — both worth a
   row in the report)
4. **Volume anomalies** — bars with volume > K × trailing percentile that don't coincide with
   known events; zero-volume RTH bars on liquid symbols
5. **Timestamp alignment** — bar_ts gaps/duplicates vs. the exchange calendar; DST boundary
   artifacts
6. **Cross-source sanity (cheap version)** — daily close vs. a second free source for a sample
   of symbols/dates; systematic disagreement flags a feed problem

## Output

- `docs/analysis/data-error-hunt-<date>.md` — findings ranked by IC impact
- **IC-impact quantification:** for each anomaly class, recompute IC for the most-affected
  (feature, symbol, tf) cells with flagged bars excluded — if a qualifying cell's IC collapses
  without the anomalous bars, that IC was fake and the cell must be flagged in
  `feature_ic_scores` (ties into feature lifecycle / decay machinery)
- Recurrent checks graduate into the existing data-quality service; one-off findings get fixed
  in place with the fix recorded

## References

- `docs/research/edge-source-thesis.md` — data quality as edge context
- `docs/plans/methodology-change-ledger.md` — any exclusion rule added as a result of this
  hunt is a methodology change and gets a ledger entry
