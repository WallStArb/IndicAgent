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
   session date (Alpaca stamps midnight New York); a zero-volume bar never serves (either
   vendor); exceptions are dated policy rows from the three-vendor arbitration
   (`scripts/ops/bars/ops_d191q_arbitration.py`), never a runtime guard (the first draft's
   agreement guard was rejected in review 2026-10-27: IBKR is wrong on OKE, RJF and others). The nightly's "1d is raw capture only" fence and the
   integrity checks that pin the 1d pairs follow. Fresh-context review.
   - Status 2026-10-27: first build (caab252ce RED, 1cc7bf759 GREEN), code and tests only,
     nothing written live. Canonical kind `(alpaca, sip_rth)` (no CVR migration). Its agreement
     guard was rejected in review and is being replaced by the policy-row arbitration above. d2-v3
     outputs are bit-identical where no policy names Alpaca (fixture goldens; 1,523 live names
     read-only, 0 mismatches).
   - Status 2026-10-27, rework: built (4ab0babc0 RED, e1355c906 rule, 4457a66ef `--plan`,
     c171920c7 + 907c445bf arbitration, 183d11fd1 span minimum = basis window, 61e939bea report).
     The rule has no agreement screen; the IBKR zero-volume fallback guard applies under an Alpaca
     primary (d2-v3 unchanged elsewhere, goldens hold). Arbitration ran read-only over 1,529 names
     (`191-D191Q-ARBITRATION.md`; plan `data/policy_plans/d191q_1d_plan_20261027.json`): 46 IBKR
     rows (72,826 sessions), 194 IBKR-defective names (19,344 sessions, Alpaca serves), 55 holds
     (26 three_way, 2 two_vendor, 27 pre-IBKR history); 136 of 154 live symbol rows retire
     (132 confirmed, 4 replaced), 18 kept.
   - Status 2026-10-28, second review: built (d672e2bcc + 0b99c09c5 M1, 71079481c + 07752ae7b
     arbitration, 6f369cf80 + 1930730a4 `--plan`, 84e63f454 + 4df252223 script). A hold means
     Alpaca does not serve: every hold span carries an interim IBKR row and `--plan` refuses an
     uncovered hold. Inside the Alpaca era an IBKR-served session is `(ibkr, fallback)` (one
     volume basis from 2016; d2-v3 goldens hold). Three-way spans where IBKR and Tradier both
     adjusted get rows; Alpaca before IBKR's first bar serves only when continuous with it.
     Re-run read-only 2026-10-28 01:48Z (`191-D191Q-ARBITRATION.md`; plan
     `data/policy_plans/d191q_1d_plan_20261028.json`, sha256 in the report): 88 IBKR rows (46
     alpaca_differs, 7 three-way adjusted, 13 pre-IBKR no-bar, 22 interim holds), 285 quarantine
     sessions on 215 names, 154 live symbol rows retire (21 replaced, 133 superseded_by_default),
     none kept. DHC fails the log-share test (47 bp against 36) and stays held.
   - Spin-offs (2026-10-27): where IBKR and Tradier agree on a spin-off-adjusted history and
     Alpaca does not, the arbitration emits an IBKR-primary row for the pre-spin span (correct
     returns, NULL volume); where Alpaca and Tradier agree, Alpaca serves.
   - Open: a review of the second rework; the owner's hold list (22 interim rows); D7 digests
     stale until a re-derive; no
     Alpaca 1d split re-ask; D7 `vendor_basis_run` is Tradier-only. Details:
     `.planning/phases/191-unified-raw-bar-table/191-D191Q-DAILY-RULE-BUILD.md`.
4. Policy rows via `ops_source_policy.py --plan` (dry run, then apply): 1d default Alpaca primary
   with IBKR fallback from 2016-01-04, IBKR before; reconcile the 154 1d symbol rows (143 names).
   - Ready 2026-10-28: `ops_source_policy.py --plan data/policy_plans/d191q_1d_plan_20261028.json`
     (dry run first). Under a table lock it refuses when the 2 pinned default ids or the 1d raw
     fingerprint (rows and last serve per series through 2026-10-06) changed: IBKR re-serves old
     1d sessions (last serve 2026-10-28 01:09Z), so re-run the arbitration right before the
     apply with the fetchers idle. Before an apply with the quarantine list:
     `vendor_disagreement` must be added to `threshold.bar_scrub.quarantine_rules` (a migration;
     the apply refuses otherwise); the flags go through `bar_scrub.write_flags` under one
     `scrub` batch.
5a. D7 Alpaca-against-IBKR basis check (second review M3), before plan 20 deletes Tradier:
   `vendor_basis_run` compares Tradier with IBKR and goes empty without Tradier; its successor
   (`services/bar_reconciliation_audit.py`, `integrity_checks`) flags an Alpaca/IBKR level run
   after 2026-10-06 (a spin-off Alpaca leaves unadjusted) for a dated row. Not built in this
   round: it changes D7's verdict set and the verdict gate.
5. Plan 20 Task 3 re-derives 1d once under d2-v4; D7 judges it; the 2016 volume seam is recorded
   for the research lane.
6. Rules and docs, in the same commit that applies the policy rows (not before, so no doc claims
   a source that is not yet live):
   - Done 2026-10-27 (doc sweep 5c2b5cef3..c6d209290, written as decided, not live): CLAUDE.md,
     the onboarding SOP, the canonical-truth registry, the glossary, gotchas, the cheatsheet and
     the operations docs. At the policy commit only the 'decided' wording flips to 'live'.
   - (was) CLAUDE.md: the pipeline line reads `ingest (IBKR -> market_data_ohlcv)`; it becomes
     `ingest (IBKR + Alpaca -> ohlcv_raw -> market_data_ohlcv selection)`. The IBKR bullet's
     "Every history fetch goes through ohlcv_history_fetcher" becomes "every IBKR history fetch";
     Alpaca's path is `ops_bar_nightly.py` (raw capture under the load engine).
   - `docs/foundation/instrument-onboarding-sop.md` (around line 215): "Alpaca never authors 1d"
     and the 1d source section; a new name's daily history comes from Alpaca SIP from 2016 plus
     IBKR before.
   - `docs/foundation/glossary.md`, the daily source policy entry (around line 2052): the
     D-191-Q span, the agreement guard and the zero-volume rule.
   - Code docstrings still describing the old 1d source or the dropped D1 store (doc sweep
     2026-10-27; edit once no fetch run imports them): `ops_bar_nightly.py:5-8`,
     `ohlcv_history_fetcher.py:36`, `_fetch_queue.py:24`, `daily_rule.py:7`,
     `_history_fetch_item.py:992`, `ops_head_rerun.py:421`, `vendor_kind.py:186`. The APR key
     `infra.ohlcv_observation.copy_batch_rows` keeps the retired store's name (rename needs a
     migration; todo 531 naming pass).
   - No change to the universe rules: never screen names on history or returns, never
     deactivate a dead name, and todo 512's exclude-then-replace-by-fixed-rule stays the only
     replacement path.

## Step 2 results (2026-10-27 20:45Z, full universe, read-only)

Alpaca SIP 1d raw after the backfill: 1,529 names, 3,736,726 rows before 2026-10-01 (backfill
`logs/alpaca_1d_backfill_20261027.log`, 0 errors). Compared with Tradier consolidated 1d over
2016-01-04..2026-10-06, matched by session date (Alpaca in New York time, Tradier in UTC); query
in 3a's scratchpad `cmp545.sql`.

- Common sessions: 3,675,889 on 1,529 names. Only Alpaca: 66,949. Only Tradier: 51,565.
- Open-to-open log-return difference: p50 0 bp, p90 0.003 bp, p99 56 bp; 1.89% of sessions over
  25 bp, 0.58% over 1%. Returns, the quantity research reads, agree closely.
- Opens: p50 0 bp, p90 0.24 bp; 4.97% over 25 bp, 4.35% over 1%. Closes: p50 0, p90 0;
  5.06% over 25 bp, 4.42% over 1%. Nearly all of the level differences are 71 names whose median
  Alpaca/Tradier close ratio is off by more than 1% for the whole span (M 0.416, GE 1.607,
  MDU 2.633, ENOV 1.744, EXC 1.402, FLEX 1.375, BDX 1.304, FDX 1.242, J 1.210, LH 1.165 and
  others): persistent level offsets from spin-off adjustment that one vendor applied and the
  other did not. A level offset does not change returns except on the event date.
- Volume, Alpaca over Tradier: p10 1.000, p50 1.028, p90 1.165. Both are consolidated.
- Zero-volume Alpaca bars: 9,087 on 74 names (the zero-volume guard keeps them out).
- Names whose Alpaca span starts more than 5 sessions before Tradier's: 62 (ticker-reuse
  candidates for the arbitration in step 3).

Reading: the 71 offset names and the 62 early-start names are exactly what the three-vendor
arbitration (step 3 rework: `ops_d191q_arbitration.py`) must classify into dated policy rows
before plan 20 deletes Tradier.
