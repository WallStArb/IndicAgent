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
   - Status 2026-10-28, third review: built (dc961d149 RED, d724430d9 GREEN; migration 527
     applied). A pre-IBKR span over 20 sessions needs Tradier agreement (90%) or a gap of at most
     `threshold.bar_integrity.arbitration_gap_max_daily_moves` (4) daily moves; SW and GRNT are
     held. Re-run 06:50Z: 90 IBKR rows (24 interim holds), 285 quarantine sessions, all 154 live
     symbol rows retire (21 replaced, 133 superseded_by_default). Owner: the holds, and CRH
     (admitted on the gap while Tradier contradicts Alpaca).
   - Status 2026-10-28, decisions (data lane, owner via indicagent-c3): the Tradier veto
     (e2de94c0c, 9afb353c0): where Tradier answered inside a long pre-IBKR span its agreement
     alone decides, the gap test only without Tradier; re-run 11:34Z holds CRH and, under 300 bp,
     MDU, MSGS, ONTO, TPL and ZWS; the other 300 bp spans are unchanged; 30 interim holds.
     Migration 528 (applied) adds `vendor_disagreement` to `threshold.bar_scrub.quarantine_rules`
     (config_history by data_lane; a no-op until the apply writes a flag). The 30 interim holds,
     DHC and SW included, stay interim IBKR rows as the decided state: IBKR serves, no bar where
     IBKR is missing (NaN under no_fill); the owner overrides any by a row in a future plan.
     No Alpaca 1d split re-ask is built now (todo 557, P2).
   - Pre-apply items (c3 review, 2026-10-28): the arbitration writes a gzip copy of the plan to
     `.planning/phases/191-unified-raw-bar-table/evidence/d191q_1d_plan_<date>.json.gz` (about
     130 KB) with its sha256 in the report, since the decisions without a policy row exist only
     there once Tradier is deleted; build_plan reports instead of writing a row or hold whose
     IBKR row would end after the window end, and `--plan` refuses one (0 such rows in the 11:34Z
     run).
   - Spin-offs (2026-10-27): where IBKR and Tradier agree on a spin-off-adjusted history and
     Alpaca does not, the arbitration emits an IBKR-primary row for the pre-spin span (correct
     returns, NULL volume); where Alpaca and Tradier agree, Alpaca serves.
   - Open: D7 digests stale until a re-derive. Details:
     `.planning/phases/191-unified-raw-bar-table/191-D191Q-DAILY-RULE-BUILD.md`.
4. Policy rows via `ops_source_policy.py --plan` (dry run, then apply): 1d default Alpaca primary
   with IBKR fallback from 2016-01-04, IBKR before; reconcile the 154 1d symbol rows (143 names).
   - Ready 2026-10-28: `ops_source_policy.py --plan data/policy_plans/d191q_1d_plan_20261028.json`
     (dry run first). Under a table lock it refuses when the 2 pinned default ids or the 1d raw
     fingerprint (rows and last serve per series through 2026-10-06) changed: IBKR re-serves old
     1d sessions (last serve 2026-10-28 01:09Z), so re-run the arbitration right before the
     apply with the fetchers idle. `vendor_disagreement` is in
     `threshold.bar_scrub.quarantine_rules` (migration 528); the flags go through
     `bar_scrub.write_flags` under one
     `scrub` batch, replacing the rule globally (bar_scrub's stale prune exempts it).
   - Order (third review M2): the final arbitration re-run and this apply happen before plan 20
     deletes Tradier. The arbitration refuses to run without Tradier's 1d rows, and no other
     source can arbitrate the 2016-2026-10-06 spans afterwards. The coordinator runs the final
     window with the fetcher stopped; commit its report and evidence copy with the apply.
5a. BLOCKER: D7 Alpaca-against-IBKR basis check (second review M3). `vendor_basis_run` compares
   Tradier with IBKR and goes empty without Tradier; its successor
   (`services/bar_reconciliation_audit.py`, `integrity_checks`) flags an Alpaca/IBKR level run
   after 2026-10-06 for a dated row. D7's acceptance of the re-derived canonical 1d (step 5) and
   the research notice that 1d is Alpaca-primary both wait on it. The judge for a future
   spin-off is a recorded corporate action (a spin-off factor in `corporate_action`, beside the
   splits it holds today), not a third vendor: after Tradier is gone no vendor arbitrates, and
   a recorded factor says which side of the run is the adjusted history.
   - Built 2026-10-28 (c39f24de2 RED, 43237be90 GREEN): `alpaca_basis_run` in
     `integrity_checks.CHECKS_1D` and the verdict gate's required 1d checks; it fails a name on a
     run of at least `vendor_ratio_run_min_sessions` (5) sessions after 2026-10-06 where the
     Alpaca and IBKR 1d closes differ beyond `fallback_basis_tolerance_bp` (10), unless a
     corporate action inside or ending the run, or an IBKR symbol row over it, explains it. Would
     fail today (read-only, live policy): 0 of 1,502 compute_1d names. `vendor_basis_run` stays
     until Tradier is deleted; plan 25 retires it.
5. Plan 20 Task 3 re-derives 1d once under d2-v4; D7 judges it (acceptance waits on 5a); the 2016
   volume seam is recorded for the research lane.
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

## Paused 2026-10-28 ~17:05Z, before the apply (resume runbook)

The owner approved plan 191-20 in the data lane's session ("approved", 2026-10-28; recorded in
`191-20-OWNER-DECISION.md`, no names held back). Every step so far is code or read-only; no policy
row, backup, flag or delete has been written. The fourth review passed (no HIGH); its M1 is fixed
(6aa15642d: `--plan` refuses a plan listing window-end spans).

Resume, in one window, from a worktree at origin/main (the shared checkout's local main carries
other sessions' unpushed commits):
1. Stop the timers: ibkr-history-fetcher (and stop its running service by PID), alpaca-nightly,
   bar-derivation-grid, bar-reconciliation-audit, regime-coverage-auditor,
   dividend-event-writer-yahoo. Tell the other sessions.
2. `ops_d191q_arbitration --plan-out data/policy_plans/d191q_1d_plan_<date>_final.json --report
   .planning/phases/191-unified-raw-bar-table/191-D191Q-ARBITRATION.md` (writes the tracked
   evidence gz too). Commit the report and the evidence before anything else.
3. `ops_source_policy --plan <file>` dry run, then `--apply`.
4. `ops_tradier_delete --dump --apply`, then `--verify`; confirm CLBK's Alpaca 1d covers
   2018-04-20 onward.
5. `--trial <symbol> --apply`, then `--delete --apply`, then `--verify --require-complete`.
6. 1d re-derive under d2-v4 for every name, then D7 (digest_fresh needs the re-derive first);
   VACUUM ohlcv_raw, market_data_ohlcv, ohlcv_revision.
7. Restart the timers; send indicagent-5b (or the research lane owner) the notice, listing the
   family 2 universe names with holds or pending spans.

Follow-up (fourth review M2, not blocking): after the Tradier delete, an `alpaca_basis_run`
failure has no fix path. `corporate_action` holds splits only, so a spin-off cannot explain a
run, and a new 1d plan needs a raw fingerprint the arbitration script can no longer produce. A
split inside a run also silences the check while canonical stays unadjusted. Fix: a `--plan` mode
that writes an IBKR row on D7 evidence, and count a corporate action only when its type matches
the event (spin-off records in `corporate_action`, todo 557's lane).

## Progress 2026-10-28, window open (resume point)

Runbook steps 1 to 6 are done except D7 acceptance and VACUUM. Worktree /home/bg/dev/indicagent-545.
- Step 2: final arbitration, report and evidence committed (395035646).
- Step 3: policy plan applied (96 symbol rows, 2 defaults, 285 vendor_disagreement quarantine flags).
- Step 4: backup verified; CLBK Alpaca 1d covers 2018-04-20 to 2026-10-27.
- Step 5: AAPL trial, full delete (7,133,667 raw, 6,695,283 canonical, 155,350 revision rows),
  `--verify --require-complete` ok, zero Tradier rows.
- Step 6: `bar_derivation --stage daily --apply` finished 23:09Z (1,501 derived, 0 failed, 1 held;
  6,415,823 rows new). The service logs to logs/bar_derivation.log, not stdout.
- D7: `python -m services.bar_reconciliation_audit` run from the worktree (the unit would run the
  shared checkout's older code, which lacks alpaca_basis_run); it ignores arguments, so `--help`
  starts a run. Read the verdicts from `integrity_monitor` (monitor_type bar_integrity) before
  accepting.

D7 result after the re-derive and `--rewrite-digests` (42,316 digests, 0 failed), 1,502 names:
alpaca_basis_run and vendor_basis_run pass for all (step 5a blocker cleared); digest_fresh passes;
policy_conformance fails 1 (the held name), freshness_1d 6, unexplained_seam 22, session_coverage
288, canonical_recompute 1,309, lineage_missing 1,501. D7 acceptance and the research notice that
1d is Alpaca-primary wait on the last two.

Cause of lineage_missing (verified): `canonical_bar_lineage` joins a canonical bar to
`ohlcv_raw` JOIN `ohlcv_request`, and no Alpaca raw row has an `ohlcv_request` row (AAPL: 2,720 of
2,720 sip_rth 1d, 610,861 5m for CLBK and AAPL, nightly rows too; the request ids resolve in
neither ohlcv_request, ohlcv_load nor ohlcv_revision). Extending the view to alpaca sip_rth
cannot fix it, and Alpaca stamps 1d raw at the New York session open (04:00 or 05:00 UTC) while
canonical sits at 00:00 UTC, so the view also needs a session_ts mapping (daily_rule.py
RAW_DAILY_SESSION_ZONE). I tried migration 537 for the view, saw no effect, rolled the live view
back to its 491 definition and did not commit it. The fix is where Alpaca raw gets its provenance:
either the Alpaca loader writes an ohlcv_request row per fetch (then the view needs the alpaca
branch and the session_ts mapping), or lineage for Alpaca resolves through another table.
canonical_recompute (1,309) was not diagnosed; check whether it shares this cause first.

Window closed 2026-10-29 ~02:55Z: VACUUM done; all six timers running; peers 47 and 1f told. Left:
the lineage and canonical_recompute fix above (D7 acceptance), then the notice to the research lane
owner listing family 2 universe names with holds or pending spans.
