# 336 - Verify whether flagged zero-scan indexes are actually unused before considering a drop

**Filed:** 2026-08-20
**Source:** `/supabase:supabase-postgres-best-practices` read-only DB audit, run while `ic_engine.py`
was mid-run on the corpus pipeline (step 5/8, ~162/231 symbols).

## Finding

A `pg_stat_user_indexes` query against per-chunk stats surfaced several indexes with `idx_scan = 0`
on their largest chunk, sized large enough to be worth reclaiming if genuinely dead:

- `idx_market_data_ohlcv_price_sanity_unaudited` -- ~500MB combined across 2 chunks
  (`_hyper_30_63932_chunk` 387MB, `_hyper_30_73682_chunk` 110MB)
- `feature_ic_scores_history_cell_idx` -- 808MB (`_hyper_103_73684_chunk`)
- `idx_market_data_ohlcv_base` -- ~116MB combined across 2 chunks
- `feature_ic_scores_history_archived_at_id` -- 43MB
- `ensemble_alpha_symbol_tf_idx` -- 15MB

**Not conclusive as-is.** TimescaleDB tracks `idx_scan` per chunk, not aggregated per logical
hypertable index -- a single chunk reading 0 doesn't mean the index is unused overall, especially
for indexes that might only get hit by queries scoped to older/different chunks, or by planner
choices that vary chunk-to-chunk. Before considering dropping any of these:

1. Aggregate `idx_scan` across **all** chunks for each of these index names, not just the one
   chunk sampled here.
2. Check `pg_stat_user_indexes` reset history (`pg_stat_reset` calls) -- a recent stats reset
   would make `idx_scan=0` meaningless regardless of real usage.
3. Grep `src/`/`services/` for query patterns that would use each index's columns, to sanity-check
   against the stats before trusting them alone (an index can be structurally necessary for a
   rarely-hit code path stats haven't captured yet).

## Why this isn't urgent

None of this blocks or was prompted by an active problem -- DB health check came back clean
overall (connections 6/200, no seq-scan-dominated large tables, only `market_regimes` showing
mild dead-tuple bloat at 11.2%, all 5 uncompressed hypertables trivially small). This is a
"worth a look sometime" cleanup candidate, not corruption or performance degradation.

## Closed 2026-08-21: verified, mixed verdict per index -- not a blanket drop-everything call

Ran the exact 3-step verification this todo specified against the live DB (read-only,
alongside the still-running `ic_engine.py` corpus job -- negligible query cost, confirmed
safe). Fixed a real methodology trap along the way: the naive exact-name query against
`pg_stat_user_indexes` silently undercounted because TimescaleDB per-chunk index names
(`_hyper_N_chunkid_chunk_<basename>`) get **truncated at Postgres's 63-byte identifier
limit** for long base names -- `idx_market_data_ohlcv_price_sanity_unaudited` truncates to
`..._unaudi`, so an exact-name match missed 501MB of the 509MB total. Used
`indexrelname ILIKE '%<distinctive substring>%'` plus a `regexp_replace` to strip the
`_hyper_N_chunkid_chunk_` prefix for correct cross-chunk aggregation instead.

**1. `pg_stat_reset` check: clean.** `pg_stat_database.stats_reset` is NULL for this DB --
no reset has ever fired, so 0-scan findings aren't reset-masked artifacts.

**2. Cross-chunk aggregated `idx_scan` (all confirmed genuinely 0 corpus-wide, not just the
one originally-sampled chunk):**

| Index | Total size | Chunks | Total scans |
|---|---|---|---|
| `idx_market_data_ohlcv_price_sanity_unaudited` | 501 MB | 257 | 0 |
| `feature_ic_scores_history_cell_idx` | 811 MB | 2 | 0 |
| `idx_market_data_ohlcv_base` | 119 MB | 258 | 0 |
| `feature_ic_scores_history_archived_at_idx` | ~43 MB | 2 | 0 |
| `ensemble_alpha_symbol_tf_idx` | 16 MB | 82 | 0 |

**3. Code-consumer cross-check -- three distinct verdicts, not one:**

- **Confidently dead, real drop candidates (~973MB combined):**
  `feature_ic_scores_history_cell_idx` + `feature_ic_scores_history_archived_at_idx` --
  `feature_ic_scores_history`'s ONLY code reference anywhere in `services/`/`src/`/`scripts/`
  is `ic_engine.py`'s own `INSERT` statements (lines 1452/1489). No `SELECT` consumer
  exists at all -- a pure append-only archive table nobody reads.
  `idx_market_data_ohlcv_base` -- despite its own migration (057)'s comment claiming
  "critical for roll detection," no code anywhere filters `market_data_ohlcv WHERE base =`;
  `ops_roll_batch.py`'s `base=` hits are unrelated Python kwargs (structlog fields), not
  SQL. `roll-batch`'s systemd timer is also confirmed disabled (CLAUDE.md).
- **NOT simply dead -- a real design bug, more valuable than a drop candidate:**
  `idx_market_data_ohlcv_price_sanity_unaudited` (501MB, the biggest one). Its real
  consumer (`bar_auditor.py`'s price-sanity candidate query) exists and matches the
  index's `WHERE price_sanity_status IS NULL` predicate, but the index's leading columns
  (`symbol`, `timeframe`) can't serve the query's actual shape (`ORDER BY timestamp`
  with no symbol/tf filter) -- the index was built with the wrong column order for its
  own intended consumer, not simply unused. Filed as its own todo:
  [347](347-price-sanity-index-column-order-mismatch-bar-auditor-query.md), which also
  cross-references todo 155's ~4.1-year backlog-clear estimate as a possible downstream
  consequence.
- **Genuinely ambiguous, not resolved here:** `ensemble_alpha_symbol_tf_idx` (16MB). A
  real consumer (`ops_oos_gate1_signal_eval.py`) matches its exact `(symbol, tf, bar_ts)`
  shape, and `ensemble_alpha` is NOT a small table (`SELECT count(*)` returned
  **29,991,805 rows**, confirmed live) -- so "table too small for the planner to bother"
  doesn't explain the 0 scans the way it plausibly could for the small archive-table
  indexes. Most likely explanation: the script simply hasn't been run against production
  yet (Gate 1 evaluation may not have executed), but this wasn't confirmed either way --
  left open, not dropped, not fixed.

**Not executed: no `DROP INDEX` run.** DDL on live hypertables during an active corpus
run, without a scoped review of blast radius, isn't a call to make unilaterally in an
audit pass -- matches this session's standing discipline (regime_writer.py/ic_engine.py
left untouched while the run is live) and this project's "operator sign-off before
deploying a live infra change" precedent (todo 169's closing note). Recommend the
~973MB of confidently-dead index space be dropped in a follow-up session once the
current corpus run finishes, as its own small, reviewed change.
