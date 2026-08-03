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

**Reconciled against shipped/pending 148-family 2026-07-19:** the "corrupt-print" thesis that
motivated this todo (bad IBKR prints fabricating fake IC) is exactly what todos 148 (shipped,
`forward_returns.return_{scale}_suspect`), 149 (pending, bar-ingestion plausibility guard at
`ProviderMerger`), and 151/152 (cleanup + false-positive fix for 148's guard) already cover or
are actively building — but each targets a narrower slice than this todo's 6 checks. Per-check
overlap:

| This todo's check | Status |
|---|---|
| 1. Impossible OHLC relationships (`high<low`, zero-range+volume) | **Covered by 149** once it ships — same "plausibility at ingestion" fix. Drop from this todo's scope, don't duplicate. |
| 2. Stale prints (N identical closes) | **Not covered.** 148/149 are magnitude/relationship checks, not repetition checks. Still this todo's scope. |
| 3. Split/dividend artifacts | **Not covered.** Distinct check class (needs a corporate-actions reference). Still this todo's scope. |
| 4. Volume anomalies | **Partially covered** — 148 guards the *return* computed from a bar, not the bar's volume field directly. A `volume > K × trailing percentile` check with no return-magnitude trigger is still a gap. Still this todo's scope. |
| 5. Timestamp alignment (gaps/dupes/DST) | **Not covered.** Different failure class from all of 148/149/151/152. Still this todo's scope. |
| 6. Cross-source sanity | **Not covered.** No other todo does an external cross-check. Still this todo's scope. |

**Revised scope:** drop check 1 entirely (149 will own it — don't build the same "impossible
OHLC" detector twice against the same table). Keep 2/3/5/6 as originally scoped; narrow 4 to
volume-only anomalies that 148's return-magnitude guard wouldn't catch. The **IC-impact
quantification methodology** below (recompute IC with flagged bars excluded, promote to
`feature_ic_scores` flag if a cell's IC collapses) is still the right general pattern and is
exactly what 152 independently had to build ad hoc for the Flash Crash false-positive case —
worth checking 152's cross-symbol corroboration code before writing this todo's version, in case
it's reusable rather than a fresh build.

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

- `docs/research/data-edge-source-thesis.md` — data quality as edge context
- `docs/plans/methodology-change-ledger.md` — any exclusion rule added as a result of this
  hunt is a methodology change and gets a ledger entry
