---
phase: 185-daily-data-foundation
plan: 17
subsystem: bars
tags: [d2, canonical-1d, derivation, lineage, dry-run]
requires: [185-10, 185-11, 185-15]
provides:
  - derive_daily pure rule (d2-v1) with split, venue and legacy precedence
  - bar_derivation --stage daily (upsert writer, lineage, flags, scrub rerun, digests, --report)
  - canonical_bar_lineage side table live (migration 402) with writer-role DML
  - pre_split_unrefetched in the quarantine rules (D-21)
  - measured dry run over all 931 1d-eligible names (docs/research/d2-derivation-dry-run.md)
affects: [185-16, 185-18, 185-21, 185-23]
key-files:
  created:
    - src/intelligence/bars/derivation.py
    - production/migrations/402_canonical_bar_lineage.sql
    - tests/unit/bars/test_derivation.py
    - tests/unit/services/test_bar_derivation_daily.py
    - docs/research/d2-derivation-dry-run.md
  modified:
    - services/bar_derivation.py
decisions:
  - Migration number 402 used as planned (re-checked free on disk before create and before psql -f).
  - Observation carries what_to_show (default TRADES) so the ADJUSTED_LAST ValueError in the contract is enforceable; the loader filters in SQL and the rule is the backstop.
  - Daily reads ohlcv_observation directly (it carries route/what_to_show/fetched_at); the interface's join to ohlcv_request would add nothing because observation rows exist only for bars answers.
  - D2a rerun is one scrub_symbols call over the run's symbols after the write loop (cross-symbol corroboration, D-11), not a per-symbol call inside it.
  - volume-only differences split into their own report reason (volume_differs) after the live dry run showed IBKR daily volume drifts across fetches; prices stay bit-exact.
  - base is NULL across market_data_ohlcv (the grid stage writes NULL too); the daily upsert carries the stored value or NULL rather than failing the symbol.
metrics:
  tasks: 2
  completed: 2026-10-02
---

# Phase 185 Plan 17: D2 1d derivation rule and stage Summary

The D2 rule, the lineage side table and the daily writer stage exist and are
tested; a full dry run over all 931 1d-eligible names measured exactly what an
apply would change before any write. No apply ran (no stage='daily' batch row,
no canonical_bar_lineage row, zero market_data_ohlcv writes), so
`d2_rule_version` in label_inputs is still None until 185-18's first apply,
as its contract expects.

## Results

- Rule (task 1, TDD): `src/intelligence/bars/derivation.py`, 21 tests. Latest
  real SMART fetch wins per date, legacy fallback only; split staleness
  threshold = the latest recorded_at among splits whose effective date is
  after the bar date, `pre_split_unrefetched` when no post-recording fetch
  exists, legacy always pre-split; venue route = the single max-volume route
  over the pre-head span (ties alphabetical), never used on/after the SMART
  head and gated by the caller's APR flag; sorted deterministic output,
  `no_provider_volume` flag, ADJUSTED_LAST rejected.
- Migration 402 applied live and committed in the same step: canonical_bar_lineage
  (plain table, PK symbol/timeframe/timestamp, DML to bar_derivation_writer),
  `infra.bar_derivation.daily_symbol_batch` int 25,
  `infra.bar_derivation.daily_write_method` text upsert [rca_analysis],
  `pre_split_unrefetched` appended to `threshold.bar_scrub.quarantine_rules`
  (config_history changed_by migration_402). market_data_ohlcv still 11 columns.
- Stage (task 2, TDD): `services/bar_derivation.py --stage daily`, 9 tests.
  Upsert of differing/missing rows only (185-01 measurement b), lineage for
  EVERY canonical bar, flags through bar_scrub.write_flags, scrub rerun,
  digests for months whose digest differs from bar_content_digest_current,
  `--report`, `--changed-only` (observations/corporate actions after the last
  completed daily batch). Dry run writes nothing and opens no batch.
  compute_version now reports `grid-v1,d2-v1`.
- Dry run (2026-10-02): 931/931 derived, 0 failed. 3,877,335 canonical bars
  vs 3,874,063 stored rows; 5,733 changed bars = 3,542 missing + 312 price
  diffs + 1,879 volume-only; 0 split flags (corporate_action is empty), 0
  venue bars (gate false). Full detail and the reading in
  docs/research/d2-derivation-dry-run.md.
- Full unit suite green after both tasks (`pytest tests/unit/ -q`, rc=0).

## Deviations from plan

**1. [Rule 1 - bug] base gate failed every symbol on the first live run**
- The first dry run returned 931 x "no base currency": base is NULL across
  market_data_ohlcv (every timeframe, the grid stage writes NULL too), so the
  "fail the symbol when no base" gate was wrong for this table's actual state.
- Fix: carry the symbol's stored base or the fallback lookup's value (NULL
  today); no failure. services/bar_derivation.py, same task, commit 3304642c4.

**2. [Rule 2 - correctness] volume_differs split out of d1_value_differs**
- The live dry run flagged bars whose prices were bit-equal and only volume
  differed (IBKR daily volume is not stable across fetches; AAPL 2026-07-29
  stored 35,047,270 vs fresh 35,047,269). Reporting those as "D1 fresh value
  differs" would have buried the 312 real price diffs (the seam audit's
  unexplained set) under 1,879 volume wobbles.
- Fix: exact comparison unchanged, but volume-only diffs get their own reason
  and the report sample table names the differing fields. Still written on
  apply. services/bar_derivation.py, commit 3304642c4.

**3. [Contract shape] Observation gained a what_to_show field**
- The interfaces block lists Observation fields without what_to_show while the
  behavior requires "ADJUSTED_LAST observations passed in raise ValueError";
  the dataclass could not detect it. Added `what_to_show: str = "TRADES"`
  (defaulted, so the documented constructor shape still works).
- src/intelligence/bars/derivation.py, task 1.

**4. Synthetic-fill interpretation (documented, no code conflict)**
- "synthetic_fill rows are never touched" is implemented as: they never enter
  the comparison (comparison reads only ibkr_named/ibkr_venue), and the stage
  never archives or deletes them. A canonical bar whose key holds a synthetic
  placeholder is "missing" and the upsert's ON CONFLICT arm replaces the
  placeholder with the real observation, which is the D-06 outcome (real beats
  filler); no such case exists in today's dry-run data for PLTR (its missing
  dates have no stored row at all).

**5. Two more APR keys than the interface list**
- `infra.bar_derivation.daily_write_method` (mirrors grid_write_method, gates
  the measured method) seeded in 402; `threshold.bar_scrub.quarantine_rules`
  update is per the interface. daily_symbol_batch seeded as specified.

## Notes for 185-18 and 185-21

- 185-18's first `--apply` run: expect ~5,733 bar writes (plus whatever the
  nightly fetch adds), lineage for 3.88M bars, a full scrub pass over 931
  names, and a bar_content_digest row for every 1d month (first run has no
  current digests). The write itself is minutes at 185-01's measured rate;
  the scrub pass is the slow part (~1 min per 50 symbols at plan 10's rates).
- The 312 price diffs are the seam audit's unexplained set (226 bars
  2006-2008 ETF days, 73 on 2026-08-06, 13 scattered). The rule takes the
  fresh value; plan 23's daily-versus-intraday check settles which side is
  right, and a later re-fetch can flip them again (volume wobbles already
  show the provider rewrites small parts of history).
- PLTR's 1,004 pre-move bars (2020-09-30 to 2024-09-24) come in as ibkr_named
  SMART data; the listing-venue gotcha does not apply to it on the current
  provider state. Worth one D-28-style eyeball after the apply.
- The missing 2026 sessions are the stored-corpus lag (931 names missing
  2026-09-29 while the nightly holds, todo 488), not a D1 gap: the fresh fetch
  has the bars, so the apply run closes the lag without any IBKR traffic.
- 185-21 (dividends) does not interact: D2 reads TRADES only, and the D-28
  dividend condition reads dividend_event_coverage source='yahoo'.
- The daily stage reads ohlcv_observation and corporate_action_current on the
  login connection; only writes run under SET LOCAL ROLE bar_derivation_writer.

## Commits

- 89401a48b test(185-17): failing tests for the derive_daily canonical 1d rule (RED)
- ed77f0b60 feat(185-17): derive_daily canonical 1d rule (D-06, D-21) (GREEN)
- b80a54036 test(185-17): failing tests for the bar_derivation daily stage (RED)
- 5e9327ed5 feat(185-17): migration 402 canonical_bar_lineage and the daily derivation stage (GREEN)
- 3304642c4 feat(185-17): dry-run report and honest volume_differs taxonomy

## Self-Check: PASSED

Files and commits re-verified on disk and in git log after writing.
