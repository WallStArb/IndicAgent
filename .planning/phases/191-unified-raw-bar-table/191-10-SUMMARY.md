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
