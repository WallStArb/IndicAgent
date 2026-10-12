# 533: one raw bar table for every vendor and timeframe; canonical is a selection from it

Filed: 2026-10-12 (widened the same day from the vendor/kind column split, owner direction)
Owner: pending
Priority: P2; phase-sized (rebuilds the 1d path), plan it as a phase rather than a session

## Owner direction (2026-10-12)

- Raw is one table: every timeframe, every vendor.
- Raw is NOT append-only: a refetch replaces the earlier answer (append-only wastes space when
  we refetch).
- `ohlcv_observation` is unnecessary and complicates a simple process; delete it.

## Target design

- **Raw** (`ohlcv_raw` or similar; glossary first): key (timestamp, symbol, timeframe, vendor,
  kind). `vendor` is the `ohlcv_load` vocabulary (ibkr, alpaca, tradier). `kind` carries what the
  vendor label suffix carries today (named, venue, fallback, and the 1d route SMART vs a former
  listing venue), so two IBKR answers for one date coexist. Every served bar lands here, winners
  included. Upsert last-wins.
- **Revision log on raw:** the raw writer classifies incoming against stored, as the canonical
  ingress contract already does. Unchanged rows cost nothing; a changed row's old values go to
  `ohlcv_revision`. Vendor restatements (IBKR rewrites history after a split) are evidence;
  `services/split_detection.py` reads observation history today for exactly this. Revisions are
  rare, so last-wins keeps the space saving without losing that evidence.
- **Canonical** (`market_data_ohlcv`): a pure selection from raw by `bar_source_policy`
  (first-writer-stays, per-span primary), plus derived rows (the 15m/1h grid from 5m, D2's 1d).
  Rebuildable from raw at any time, which "raw data is permanent, derived data is cache" already
  implies. Today canonical holds the only copy of winning bars, so it is not rebuildable.
- **Fetch ledger:** `ohlcv_request` stays (answered and no_data windows can't be read off bars).
- **Deleted:** `ohlcv_observation` (1d only, append per request, 16M rows / 3.5 GB on
  2026-10-12) and `ohlcv_intraday_raw_archive` (folds into raw).
- **Source column on canonical:** vendor plus kind, same vocabulary as raw;
  `market_data_ohlcv_tradeable` nulls volume by kind (venue and fallback volume is not
  consolidated), not by a suffix in a label.

## Why (evidence, 2026-10-12)

- The bar `source` label mixes vendors (`alpaca`, `tradier`), vendor plus kind (`ibkr_named`,
  `ibkr_fallback`) and a computation (`derived_5m`). `ohlcv_load.source` holds vendors only; the
  mismatch broke every IBKR ingress write from 2026-10-10 15:03 UTC to 2026-10-12 (aaa67e637,
  fixed in 33a177772). `src/intelligence/bars/sources.LABEL_VENDOR` (31e61063c) is the single
  label-to-vendor map until the split.
- Raw today is three places: canonical (winners only), `ohlcv_intraday_raw_archive` (losers,
  refusals, 15m/1h; keyed with source, last-wins), and `ohlcv_observation` (1d, append). The 82M
  Alpaca 5m archive rows came from a one-off archive campaign; canonical holds 220M.
- Archive-timeframe refusals (15m/1h): `_record_refusal`'s `archive_refusal_rows` upserts the
  refused rows into the same archive table, overwriting the stored rows the refusal meant to
  protect (code review, 2026-10-12). Under the target design a refusal is a canonical-selection
  outcome only; raw always takes the answer and the revision log keeps the old values.

## Scope

Readers of `ohlcv_observation` (16 modules on 2026-10-12): `services/bar_derivation.py` (daily
rule), `bar_reconciliation_audit.py` (D7), `split_detection.py`, `listing_venue_writer.py`,
`dividend_event_writer.py`, `bar_load.py`, `bar_hold.py`, `ohlcv_observation_writer.py`,
`scripts/infrastructure/backfill/_d1_gaps.py` and `_history_fetch.py`, ops scripts
(`ops_head_rerun`, `ops_source_policy`, `ops_venue_study`, `ops_d1_bootstrap`) and two research
scripts. Readers of the bar `source` label: the tradeable view, D7, the 1d digest,
`CANONICAL_1D_SOURCES`, the completeness report's `CASE`, `integrity_checks._PRIMARY_LABEL`.
Data movement: about 450M canonical plus archive rows across compressed hypertables (bare
`VACUUM` per the compressed-column migration template). Needs a design doc in `docs/plans/`
and a data-layer integrity design amendment before planning. Pairs with todo 530 (writer-labeled
loads have no bar-label join; the vendor/kind key resolves it).
