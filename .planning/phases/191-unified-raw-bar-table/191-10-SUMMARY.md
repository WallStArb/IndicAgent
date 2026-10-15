---
phase: 191-unified-raw-bar-table
plan: 10
subsystem: bars / evidence readers
tags: [ohlcv_raw, ohlcv_revision, split-detection, dividends, listing-venue, alpaca, data-quality]
requires: [191-07 last-wins raw (D-191-N), 191-08 daily stage over raw]
provides:
  - split, listing-venue, bar-hold and dividend evidence read from ohlcv_raw and ohlcv_revision only
  - D-191-D pairing in the dividend writer (pair_d1_series)
  - Alpaca artifact answer-time stamp and plausibility bound (migration 487)
  - IBKR 4h series deleted as a written data-quality delete (migration 488)
affects: [ohlcv_history_fetcher (split judging after a 1d run), ops_split_detect, ops_bar_load, alpaca pull, ops_d1_bootstrap]
key-files:
  modified:
    - services/split_detection.py
    - services/listing_venue_writer.py
    - services/bar_hold.py
    - services/dividend_event_writer.py
    - src/intelligence/bars/vendor_ingress.py
    - scripts/ops/bars/ops_bar_load.py
    - scripts/research/alpaca_depth_scratch_pull.py
    - scripts/ops/bars/ops_d1_bootstrap.py
  created:
    - production/migrations/487_alpaca_artifact_answer_lag.sql
    - production/migrations/488_delete_ibkr_4h_raw.sql
    - .planning/phases/191-unified-raw-bar-table/191-10-SPLIT-BASELINE-DIFF.json
decisions:
  - "Split overlap pairs are built in Python from the run's requests and every recorded answer (raw row or revision value), ordered by ohlcv_request.answered_at; only names the run changed are read"
  - "Dividend pairing reads TRADES through the revision log: the run's own answer, else the TRADES value stored at the adjusted serve; a row restated after the adjusted serve never pairs"
  - "Forming 1d bars never pair (adjusted bar answered on its own UTC date, earlier split answer of an incomplete session)"
  - "Alpaca answer time lives in the parquet schema metadata; ops_bar_load refuses a stamp not after the newest bar or more than 120 h after it (APR)"
metrics:
  completed: 2026-10-15
  tasks: 2 plus fold-ins
---

# Phase 191 Plan 10: evidence readers over raw summary

Split detection, listing venue inference, bar holds and the IBKR dividend derivation now read
`ohlcv_raw` plus the `ohlcv_revision` log, never `ohlcv_observation`. Each was checked against
a baseline from the old code, and every baseline matches; the differences are listed and
explained below.

## Commits

| Commit | What |
|---|---|
| 9c524c71a | split_detection over raw and revision, pair_answers, baseline diff file |
| 64563cdd1 | listing_venue_writer and bar_hold over raw |
| d0b7713ce | dividend writer: pair_d1_series (D-191-D), CVR input check |
| a0f2c131b | Alpaca answer-time metadata and plausibility bound, migration 487 (review of 08, M2) |
| e9e96b2f9 | d1 legacy import stamped at the earliest possible answer (review of 08, L1) |
| fffa2cd10 | IBKR 4h written data-quality delete, migration 488; todo 512 record; todo 535 items 36 to 38 |

## Baselines

- Split detection: all 37 1d SMART TRADES fetch runs judged with the old code
  (`logs/split_baseline_20261015T113603Z.json`, 13 detections: 12 CTVA unclassified rescales
  and the ETHA 2026-09-30 1/3 split) and with the new code: the same 13, plus one unexplained
  HYG 2007-06-12..09-25 difference (median 1.0031) in run c9b625b5. `ohlcv_revision` holds 30
  HYG 2007 values served 2026-09-30 that this run displaced (ratios 0.9936 to 1.0010, not
  constant). The vendor really did restate them, and the old code missed it because it paired
  against a different observation. It is reported as unexplained, never as a split.
  Changed-pair counts are lower on five runs, because the plan 04 backfill kept no revision of
  observation values that were not the latest for their key. None of those pairs produced a
  detection (todo 535 item 38). Detail: `191-10-SPLIT-BASELINE-DIFF.json`.
- Listing venue: inputs, inferred spans and evidence identical on all 1,502 1d names
  (`logs/listing_venue_baseline_20261015T165347Z.json`).
- bar_hold vendor ratios: identical on 30 names (`logs/bar_hold_baseline_*.json`).
- Dividend events (IBKR): 39 names (the 28 with the most events plus 12 split names, one
  overlapping). Events, downward-step and unstable-step counts are identical to the old
  derivation, and the stored events match (`logs/dividend_baseline_*.json`). The examined
  span ends one session earlier (2026-09-24, not 09-25): the bootstrap served its 2026-09-30
  adjusted bar while the session was still forming, and that bar no longer pairs (D-191-J).

## Deviations from plan

1. [Plan predates D-191-N] Split detection now builds its pairs in Python over three queries
   instead of one SQL statement. The first SQL version scanned full-history windows on the
   hypertable and timed out; now only names the run changed are read, and judging all 37 runs
   takes about 1 minute. An unchanged re-serve writes nothing under last-wins, so dates inside
   the run's windows pair with the earlier answer (ratio 1). This keeps the seam runs and the
   overlap verdict's median on the same overlap the observation store gave.
2. [Rule 1] An earlier split answer of an incomplete session no longer counts as a partner
   (plan amendment of the 04-05 review).
3. [Rule 1] The SMART head in listing_venue_writer counts only raw rows a SMART request
   served. A legacy import row is no route evidence, and without this filter 464 heads moved
   earlier.
4. [D-191-D refined] D-191-D accepted the current TRADES row only when no revision came after
   the adjusted serve. Its literal form left 1 to 4 dates per name unpaired, where a
   volume-only restatement left a revision row with an equal close. The writer now takes the
   run's own answer, else the TRADES value stored when the adjusted answer was served (current
   or displaced). That is the value-as-of-serve reading of the same rule. The two named tests
   are `test_trades_restated_after_the_adjusted_serve_never_pairs_by_ordering` and
   `test_trades_unchanged_for_the_date_pairs_by_ordering_although_the_name_split_later`.
5. Todo 504: only the input part is done (vendor and kinds checked against CVR at run start).
   The source registry and the per-symbol failure policy stay in todo 504.
6. ops_bar_nightly needed no edit: plan 07 already moved it to the raw contract (no archive or
   observation call; the done-criterion grep is empty).
7. [Hard rule] No held unit was cleared or resumed. The orchestrator clears
   `indicagent-dividend-event-writer-yahoo.timer` and the others after review, with the
   baseline files above as evidence.
8. Owner items: (a) the IBKR 4h series (LLY 432, MSFT 1,752 raw rows) is deleted by migration
   488. Each value went to `ohlcv_revision` first, the canonical copies (equal on all 2,184
   keys) and the 2 coverage rows went with it, the 4h policy is closed, and the delete is
   recorded in todo 512. (b) The IBKR 15m/1h deletion rule is todo 535 item 37.
9. M1 of the 08 review (`confirmed_at`) is not cheap and is todo 535 item 36.

## Deferred issues

- `tests/unit/test_table_and_apr_key_readers.py` fails on `infra.ohlcv_raw.compress_after_days`
  (migration 486, a58af0a75, a concurrent session's commit; no Python reader). It is not part
  of this plan, so I did not fix it. The rest of the full unit suite passes.

## Threat model

T-191-29 is mitigated by the split baseline. T-191-30 is mitigated by `pair_d1_series` and its
restated-TRADES test. T-191-31 is open by instruction: units are resumed by the orchestrator
after review.

## Self-Check: PASSED

The commits above exist on main. Migrations 487 and 488 were applied live and committed.

## Review fixes and resume (2026-10-15, 191-10-REVIEW.md)

- Finding 1: re-stamped the 931 d1 legacy-import requests and the 10,098 current raw rows they
  wrote to 2026-09-29 00:00 UTC, the midnight after their last bar. `scripts/ops/bars/ops_legacy_restamp.py`
  is a logged, idempotent, one-shot script: a re-run moves 0, and the log is
  `logs/legacy_restamp_20261015T174031Z.json`. No value changed (0 keys would flip). The
  review's 212 keys on 80 names did not hold legacy values. They held the same run's SMART
  TRADES fetch: real IBKR answers of 2026-09-30, later than the serves they displaced, which
  last-wins keeps. So no re-resolution was needed, and those requests keep their real times.
  0 keys hold a d1-bootstrap value over a later-answered serve.
- Finding 2: `_run_values` drops superseded offers and reads rows in a fixed order. The new
  test failed on the old code. The 39-name dividend derivation is unchanged.
- Finding 3: todo 535 item 39 (note only).
- IBKR 4h: feature_vectors and market_regimes (column `tf`) hold no 4h rows.
- Resume: the gateway was logged in with the API port open. I cleared bar-derivation (191-08
  evidence), the fetcher pair and the dividend units (191-10 evidence) and resumed them. The
  reconciliation audit, bar_auditor, bar_aggregator and bar_writer stay held for plan 11
  (bar_reconciliation_audit and bar_auditor still read the old stores).
- Re-serve run `--reserve-keys logs/reserve_keys_191_07.json` (fetch run 32c497ca): 38 items,
  all ok, 9,483 bars, 0 flagged, 0 unselected. Its grid stage failed 231 names: bar_derivation
  wrote ohlcv_revision rows without vendor and kind, which have been NOT NULL since plan 04.
  [Rule 1] fixed in 0d9daf04e for both the grid and the daily delta. The grid re-run then
  derived 231 names with 0 failed (1,786 new rows, 13,990 changed, 25 removed).
- Selection gate `--compare` over the 38 re-served 5m series: exit 0. That is 0 real
  differences, 0 mixed-vendor sessions, 0 unrecorded choices, 0 unselected slots and
  0 unreviewed basis flags (`logs/gate_compare_191_10.json`).
- Daily stage (changed only, applied): 1,497 names derived, 27,455 new rows, 132 changed,
  5 removed. Canonical 1d now ends at 2026-10-12, the raw maximum (1,492 names). GYRE is
  refused by the derivation-stage rule: a revision ratio of 0.0283 over 4,665 stored rows,
  with no recorded corporate action. Its canonical equals IBKR raw on all 4,665 shared keys,
  so the rows behind the 2.8% are open (todo 535 item 40). One name is held (bar_hold).
- The fetcher timer is re-enabled because the gate exited 0. Its runs fetch 1d for 2026-10-13
  and 10-14 and continue the deep 5m backfill.
