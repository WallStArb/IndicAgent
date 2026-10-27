---
status: pending
priority: P0
filed: 2026-10-27
source: owner decision D-191-Q (2026-10-27) on a measured source review
owner: 2026-10-27
---

# Canonical 1d: Alpaca SIP primary from 2016, IBKR fallback, IBKR before (D-191-Q)

## Why

Plan 191-20 deletes Tradier, which is 92% of canonical 1d today (6.66M of 7.24M rows). On IBKR
alone, canonical 1d would carry a non-consolidated volume basis (IBKR/consolidated 0.41 to 0.91 by
name), lose 494,567 sessions from 2016 on 311 names, and have no fallback for the IBKR nightly 1d
lane (missing about 214 names a day since 2026-10-19). Alpaca SIP 1d matched Tradier on a 21-name
sample (opens p99 5.6 bp, open-to-open returns p90 0.16 bp, volume 1.03x) and filled every hole.
Full record: design doc D-191-Q.

## Steps (order matters: all before plan 20 Task 3's re-derive)

1. Alpaca SIP 1d history 2016+ for all 1,529 names into `ohlcv_raw` (raw capture only):
   `ops_bar_nightly --timeframes 1d --days 3950` in shards of 300
   (`logs/alpaca_1d_backfill_20261027.log`, started 2026-10-27 16:03Z).
2. Full-universe Alpaca vs Tradier 1d comparison while Tradier exists (the last consolidated
   reference): open, close, open-to-open return and volume ratio distributions, sessions present
   in one only, zero-volume bars, ticker-reuse splices; record it here.
3. Daily rule d2-v4 (`src/intelligence/bars/daily_rule.py`, `services/bar_derivation.py`
   `read_daily_inputs`): `(alpaca, sip_rth)` as a raw daily series and policy primary, matched by
   session date (Alpaca stamps midnight New York); a zero-volume Alpaca bar never serves; the
   Alpaca span starts at the name's listing. The nightly's "1d is raw capture only" fence and the
   integrity checks that pin the 1d pairs follow. Fresh-context review.
   - Status 2026-10-27: built (caab252ce RED, 1cc7bf759 GREEN), code and tests only, nothing
     written live. Canonical kind `(alpaca, sip_rth)` (no CVR migration). Listing guard: the
     Alpaca span starts at the first session where IBKR's contract-keyed close agrees (session
     and window median within the basis tolerance); no point-in-time listing table exists. d2-v3
     outputs are bit-identical where no policy names Alpaca (fixture goldens; 1,523 live names
     read-only, 0 mismatches).
   - Spin-offs, decided 2026-10-27 (data lane; owner may override): keep the agreement guard.
     On the 69 names where IBKR's history is spin-off adjusted and Alpaca's is not, 90,484
     pre-spin sessions are served by IBKR (correct returns, NULL volume) instead of Alpaca (a
     false return on every spin ex-date). Serving Alpaca there needs spin-off records, which
     `corporate_action` does not hold yet.
   - Open: the fresh-context review (Codex and AGY out of quota);
     `--plan` cannot express the 1d policy as written; D7 digests stale until a re-derive; no
     Alpaca 1d split re-ask; D7 `vendor_basis_run` is Tradier-only. Details:
     `.planning/phases/191-unified-raw-bar-table/191-D191Q-DAILY-RULE-BUILD.md`.
4. Policy rows via `ops_source_policy.py --plan` (dry run, then apply): 1d default Alpaca primary
   with IBKR fallback from 2016-01-04, IBKR before; reconcile the 154 1d symbol rows (143 names).
5. Plan 20 Task 3 re-derives 1d once under d2-v4; D7 judges it; the 2016 volume seam is recorded
   for the research lane.
