---
status: pending
priority: P1
filed: 2026-10-13
source: independent review of phase 191 plans 01-03 (fresh-context Claude reviewer; AGY and Codex out of quota)
owner: phase 191
---

# Raw bar table review findings that plan 191-04 does not close

Full report: scratchpad `review_claude_01-03.md` of the 2026-10-13 session (the findings below are
self-contained). Findings 1 to 3 of the review (per-route venue kinds, delta update-on-difference,
archive value kept with the canonical value as a revision) went to the 191-04 executor.

## Open

1. A refusal does not last. `write_raw` replaces raw current with the refused values, and selection
   reads current raw plus policy, so the next unchanged overlapping fetch or the plan 07 rebuild
   writes them into canonical. Design (owner direction pending objection): raw stays faithful; a
   refusal is a held span (vendor, kind, series, span) that selection skips until explicitly
   accepted. Plan 07 already names a `refused_self_restatement` class (slots of a series whose raw write was refused are excluded from selection, via the ohlcv_load outcome), so this is probably built there: verify plan 07 makes the exclusion durable across reruns before adding a table.
2. A slot with no winner, or a winner with NULL volume, leaves the old canonical row
   (`bar_selection.py:124-134`), so canonical depends on history. Use `removal_scope`, fall to the
   next candidate on NULL volume. Do not wire `apply_raw_contract` before plan 07 seeds the Alpaca
   spans (live 5m policy is IBKR-only; 220M canonical 5m rows are Alpaca).
3. Reconstructed revision loads carry today's `loaded_at` for restatements back to 2005;
   `ops_data_bar_check.py` uses `MAX(loaded_at)`, so known-answer keys can flip from replaced to
   open (inferred, not run). `old_source='ibkr'` on `smart_trades`/`venue` rows reads as `generic`
   in migrations 472/475.
4. Policy spans match by UTC calendar date, not session date (`selection.py:107`); Alpaca AAPL 5m
   has 8,331 post-market bars after 00:00 UTC. Harmless until dated spans are seeded. Kind
   `sip_rth` holds post-market bars, contradicting its description.
5. Low: `--check` subtracts canonical diffs by count, not by row (`ops_raw_backfill.py:781`);
   no advisory lock between read and upsert in `write_raw`; canonical-only kind `fallback` would
   enter raw; a chunk with the same key twice drops the earlier value; request-writer buffer is
   handed over by reference; `ohlcv_revision.load_id` ON DELETE CASCADE removes revision evidence
   when Tradier loads are deleted (plan 20); a deferrable `ohlcv_revision` FK would let
   `preview_series` go; `bar_derivation_writer` holds INSERT and UPDATE on `ohlcv_raw`.

## Status after plan 191-05 (2026-10-13)

- Item 1 (refusal does not last): done in 191-05, no new table. A refused series writes no raw row;
  its offered values that differ from the stored rows are `ohlcv_revision` rows of origin `pending`
  (migration 477, applied live at the window resume step); the stored rows stay current. Tests: unit
  (refuse, unchanged re-offer, raw and selection untouched) and integration under the real role.
  Plan 07's `refused_self_restatement` class should now count zero (amendment appended to plan 07);
  a release command is not built (a waived write releases).
- Item 5, advisory lock per series: done (`write_raw`, `preview_series`). Same key twice with different
  values in one chunk: raises. Request-writer buffer: swapped, restored on failure. `fallback` into
  raw: closed in 191-04.
- Item 5, deferrable FK: decided against. A refused series must be classified before any write, so
  `preview_series` stays whatever the FK does; the advisory lock now makes preview and write agree
  by construction.
- Still open: items 2, 3, 4 and the `bar_derivation_writer` grant on `ohlcv_raw`; the CASCADE on
  `ohlcv_revision.load_id` (plan 25 Tradier retire).

## Status after plan 191-07 code (2026-10-14)

- Item 4 (spans by UTC date): done. Selection matches `bar_source_policy` spans by the NYSE session date;
  kind `sip_rth` is a candidate only on the regular-hours grid (Alpaca's extended-hours bars stay in raw
  and never reach canonical; D-191-L).
- Item 2, no-winner half: the selection writer counts slots no ranked vendor holds (`unselected`); the
  loader and nightly report them and fail on them. The NULL-volume half needs no change today (no raw row
  of 1m, 5m or 4h has a NULL volume). Canonical rows selection no longer produces are not removed; the
  selection gate reports them as `only_canonical` differences instead.
- Advisory lock per (symbol, timeframe) before `select_and_write`, upsert tail on new rows: done.

## Open items from the plan 191-06 review (2026-10-14), not fixed in the 06 fixes

6. Medium: any single route's `no_data` covers a 1d session. `_d1_gaps.py` (`_ANSWERED_WINDOWS_SQL`
   with `_DAILY_ROUTES`) treats a `no_data` window on SMART or on any one listing-venue route as
   covering the session; the empty-history rule (`confirmed_empty_spans`) requires every required
   route to agree. Live mechanism: SCHW SMART `no_data` 2006-10-05..2010-03-04 over 651 venue
   bars; DAL ISLAND `failed` while SMART/ARCA/AMEX/BATS answered `no_data` in the same run. No
   hole found today (DAL and VRP are genuinely pre-listing), but a failed listing-venue walk under
   a SMART `no_data` window would never be asked again. Fix: for 1d, the confirmed spans (every
   required route `no_data` in one run) become the `no_data` coverage, not per-route windows.
   Recommended placement: plan 191-08 (the daily rule), before the fetcher resumes, with a
   fake-conn test of a SMART `no_data` over a span a venue route failed.
10. Low: a forming 15m or 1h bar is asked, stored and counted as covered. `plan_gaps` caps the
    forming slot at `run_end`; IBKR returns the partial bar; it is stored and counts as a slot.
    5m is re-asked by the update overlap (last-wins), 15m and 1h have no overlap lane, so a
    partial bar stays until a gap-fill restates it. Reach is limited (15m and 1h are parity and
    derived series). Fix: drop intraday slots whose end is after `now` from the horizon, as the 1d
    planner now does for unfinished sessions (`session_complete_at`). Recommended placement: plan
    191-08 with item 6, one planner pass, so the intraday rule and the 1d rule are decided together.

## Open items after the plan 191-07 fixes (2026-10-14, 191-07-FIXES.md)

11. Superseded by item 17: the re-serve list is now `logs/reserve_keys_191_07.json`. The 9
    refused-serve keys belong to loads the re-judgment accepted (raw and canonical hold the whole
    bar); the 17 TMUS truncated bars were restored from the IBKR ledger and stay on the list to be
    verified.
12. Derived 15m/1h over the 2,619 added and 403 replaced 5m slots are stale until bar-derivation
    resumes; re-derive those days when it does.
13. Not built: a check that catches a calendar defect dropping a whole Alpaca day; resetting
    `price_sanity_status` and `base` when selection replaces a canonical row (verify whether they
    go stale first).
14. D-191-M (the one-time catch-up of 2,895 refused_cross_vendor slots): owner acknowledged 2026-10-14.
15. Item 10 (forming 15m/1h bar): the IBKR leaf now drops a bar still forming at the request end
    (eeb0fb7c6); plan 08 confirms whether that closes item 10 or the planner horizon still needs it.

## Second review of the 07 fixes (2026-10-14, 191-07-FIXES-REVIEW.md)

16. Done 2026-10-14 (191-07-FIXES.md, "Second review fixes"): exact-key re-serve evidence,
    load-level re-judgment (53 accepted, 7 held, 15 unjudgeable; D-191-M amendment), session-level
    selection (392 spliced sessions re-selected, 0 left), held keys never selected, complete-bar
    rule in the shared fetch layer. Gate over the 57 series exits 0; idempotence 0/0.

## Open after the second 07 fixes (2026-10-14)

17. Re-serve owed: `ohlcv_history_fetcher.py --reserve-keys logs/reserve_keys_191_07.json` (3,525
    keys, 99 session asks on 35 series) once the fetcher may run, then the gate and idempotence.
    4,652 offered values are held pending. The gate reports them and exits 0 regardless: exit 0
    is canonical equal to the selection, not "nothing owed".
18. Owner acknowledgement of the D-191-M amendment (per-load table in the design doc) before
    plans 08 and 10 rely on it.
19. Truncated IBKR bars outside the 57 series: 22 IBKR 2026-10-09 14:10 bars under a fifth of
    Alpaca's volume (a request ended about 14:12 UTC). Canonical holds the truncated bar for BLK
    and XTL; all 22 are on the re-serve list. Retired-path fetches left no request rows, so the
    universe-wide count is unknown. Build a detector (a vendor's bar far below the other vendor's
    and its own session median at a stamp where a fetch of that day ended) before plan 10's
    evidence readers trust intraday volume.
20. Complete-bar rule gaps: `scripts/ops/bars/ops_bar_load.py` loads artifacts that carry no
    answer time, so it cannot judge a forming bar (any next Alpaca campaign must record the pull
    time per artifact, a lower bound on the answer); `services/backfill_feature_factory.py` calls
    `store_bars` without `asked_at` (judged at call time, seconds late) because editing it renames
    every feature unit it writes. Fix the factory call when its code key next changes anyway.
21. Alpaca 2026-10-09: the one-time depth pull ran during the session, so each name's serve ends
    at its pull time. Selection now takes those sessions whole from IBKR, or leaves them empty for
    the six held series. Re-pull the day through the nightly runner when Alpaca capture reopens.
22. Not built: `ops_selection_gate --apply-spans` has no staleness guard (refuse a spans file
    older than the series' last load). Nothing runs it today.
23. Derived 15m/1h are stale over every 5m session changed by the second fixes (23,750 re-selected
    rows, 1,331 replaced, 446 retracted, 17 TMUS) on top of item 12; re-derive when bar-derivation
    resumes.

## Third review of the 07 fixes and the last-wins decision (2026-10-14, D-191-N)

Owner decision 2026-10-14 (D-191-N): a vendor's re-serve always overwrites its raw value
last-wins, the old value is logged, nothing is held and no load is refused; a restatement
detector reports instead. Fixes recorded in `191-07-FIXES.md` ("Third review fixes and last-wins
decision").

- Item 1 (refusal durability) and item 16: superseded by D-191-N; holds released
  (`ops_pending_release.py`: 4,572 written, 80 superseded), migration 482 drops the pending
  origin.
- Item 11 and item 17: superseded by the regenerated `logs/reserve_keys_191_07.json` (4,569 keys,
  103 session asks on 38 series): 58 IBKR sessions lost under the 2026-10-10 refusals on AGG,
  AVGO, BAC, BKNG, CAT, CCJ, CRWD, EDV, EMLC (the planner now asks them too), 22 truncated
  2026-10-09 14:10 bars, 17 TMUS 19:05 verifications, 6 partial-only keys still missing from raw.
  Still owed once the fetcher may run.
- Item 18 (owner acknowledgement of the D-191-M amendment): moot, superseded by D-191-N.
- Item 19: the truncated-bar scan is built (`ops_truncated_bar_scan.py`, APR
  `threshold.bar_integrity.truncated_bar_volume_ratio`, migration 483). Open, see item 27.

## Open after the third review fixes (2026-10-14)

24. GE 5m 2021-11-08 to 2021-11-24: 1,014 IBKR bars now hold the two-decimal values of the
    refused d2adcf51 serve (latest answer, D-191-N) inside four-decimal history. Nothing to fix
    by hand (owner 2026-10-14); a later IBKR re-serve of that span overwrites them last-wins.
    The restatement detector would flag such a serve going forward only by share, not by
    signature (rounding is no constant ratio).
25. The fetcher's `waived` parameter chain (`_history_fetch_item`, `ohlcv_history_fetcher`
    escalation) no longer changes any write; it only decides whether an overlap breach is
    re-fetched at full depth. Delete or rename it the next time the fetcher changes.
26. `services/bar_derivation.py` keeps its own answered-window read (`_SELECT_ANSWERED_WINDOWS_SQL`)
    and does not exclude refused windows as the gap planner now does (finding 3). Check whether
    the grid stage can treat a refused 5m window as answered; fix with plan 08.
27. Truncated-bar scan: BLK and XTL alone give about 100 candidates each over history at the
    0.2 threshold, most of them older than the request ledger. Calibrate the threshold (or add a
    request-end condition) and run it over the universe before plan 10's evidence readers trust
    intraday volume; only then add its keys to the re-serve list.
28. Derived 15m/1h are stale over every session the release re-selected (4,572 raw writes on
    ADM, AEP, AMT, AMZN, ASML, BA, GE) on top of items 12 and 23.
29. `--apply-spans` staleness guard (item 22) is still not built.

## Status after plan 191-08 (2026-10-15)

- Item 10 and item 15: closed. The IBKR leaf's forming-bar drop (eeb0fb7c6) did not close item
  10 alone: an ask whose window ran past `now` still recorded the dropped slot as answered.
  `detect_gaps_from_record` now drops every slot whose bar has not ended by `now` (85dd6537b),
  so no planner ask covers a forming bar.
- Item 26: closed. The grid stage's answered-window read corroborates a `bars` answer on the
  answering vendor's raw rows and excludes a window whose load was refused, the gap planner's
  rule (03ab0a4a6). Its partial-slot handling (`live_partials`) is not ported: a missing slot an
  answer served partial only loses its `partial_constituents` flag, which is a flag, not a bar.
- Item 6: closed with a narrower rule than recommended, on measurement. 1d coverage stays every
  route's no_data window, less any span where that route's latest answer was a transport
  failure (a timeout, or a failure the provider raised with error text) not answered later by
  the same route (`_d1_gaps.daily_no_data_coverage`). Measured 2026-10-15 over the 518 names
  with an IBKR 1d no_data answer: the recommended all-routes rule would add 346,491 gap
  sessions and withdrawing coverage on every failure 101,615 on 64 names, nearly all pre-listing
  heads, because ISLAND fails structurally for non-NASDAQ names and SMART on pre-listing
  windows (no error text, recurring on every ask). The transport-failure rule adds 2,467
  sessions on one name, KNSL, whose ISLAND, AMEX and BATS walks over 2006-10-09..2016-07-28 were
  lost to `ConnectionError: Not connected` under SMART and ARCA no_data: the hole the item
  describes, asked once more on resume.

30. Found by plan 191-08's live grid check (`test_derived_grid_live`, sessions whose canonical
    5m is IBKR's own): the derived 1h volume against IBKR's 1d smart_trades volume has a
    per-name median deficit beyond 0.005 on CTVA (held, bar_hold), ETHA and MDGL. ETHA's ratio
    is exactly 3.000 over 557 sessions (2024-07-23 to 2026-10-09; the 1d values were served
    2026-10-08 to 10-11): the 1d and 5m volumes are on different share bases, a corporate
    action one of the two series reflects. Aggregate rates pass. Decide with the corporate
    action evidence (split_detection) before plan 10's readers trust ETHA volume; the test stays
    strict until then.

## Acceptance

Each item is fixed in the plan that owns it, or deleted with a reason here. Findings 1 and 2 land
before plan 191-07.

## Fourth review of the 07 fixes (2026-10-15, 191-07-FIXES3-REVIEW.md)

Done: finding 1 (raw last-wins by serve time, superseded origin; ce723eab8), finding 2 (basis
flags partial, gate class, review CLI, D7 gauge; edb793e79), finding 3 (detector v2; 7c9fe3bf4,
APR in migration 485, 99f8c5c8b), the release tool deleted (finding 8 part). Open (scope cut):

30. Finding 4: rewrite tests/integration/test_ingress_write_contract.py for last-wins, the
    revision log and serve-time ordering against the real DB (it still passes `waived`).
31. Finding 5: selection judges a session with no stamp on the calendar grid on an empty set
    (166 bar_session_choice rows, 2006-12-27 and two others); judge on the vendor's slots, record
    n_grid_slots NULL (migration 485 documents it), reclassify through record_session_choices.
32. Finding 6: run the detector retroactively over the GE 2021-11 release load (via
    ohlcv_ingress_contract.record_flag) so the review queue starts complete.
33. Finding 7: batch record_session_choices into one multi-row upsert and clear all-off-grid
    sessions (pass every session date of the window).
34. Finding 8 rest: delete the inert `waived` chain (_history_fetch_item, ohlcv_history_fetcher).
35. Not run after this round: full unit suite and the selection gate --compare over the 57 series.

## Plan 191-10 (2026-10-15)

36. M1 of the 08 review (open, not cheap): an unchanged re-serve does not advance served_at, so
    replaying an artifact fetched between a change and a later confirm replaces the confirmed
    value. Fix with a separate `confirmed_at` column (advanced on an unchanged offer whose answer
    is later, no revision row); served_at stays the change time so the 1d changed-since probe
    does not re-trigger nightly. Until then replays are safe only for artifacts older than the
    oldest unconfirmed serve. M2 (Alpaca answer-time stamp and plausibility bound, migration
    487) and L1 (legacy import stamp) are closed in 191-10.
37. Deletion rule for IBKR intraday vendor 15m/1h (owner 2026-10-15): per name, delete the IBKR
    vendor 15m and 1h raw rows once IBKR 5m raw covers the same span and the 15m/1h derived from
    it match the vendor's 15m/1h within the parity tolerance (todo 524). Each deleted value is
    logged to ohlcv_revision first, as a written data-quality delete under todo 512's record
    (template: migration 488). Until then vendor 15m/1h is the only pre-2016 intraday history
    and stays.
38. Revision gap seen in 191-10: the plan 04 backfill kept no revision of observation values that
    were not the latest per key, so five 1d fetch runs (430e66e5, 9115da48, c2646a23, b81f9f2e,
    f29214a1) can no longer be re-judged for restatements they saw (none produced a detection;
    191-10-SPLIT-BASELINE-DIFF.json). Forward runs are complete: every displacement is logged.
39. Review of 191-10, finding 3 (LOW, note only): the Alpaca answer-time guard bounds the stamp
    against the newest bar only, so a re-stamped or copied old artifact whose newest bar is
    under 120 h old passes, and its older bars inherit the stamp. The stamp is plain parquet
    metadata: a mistake guard, not tamper-proof. Tighten only if artifacts are ever copied.
    Finding 1 of the same review is closed: the 931 legacy-import requests and their 10,098
    current raw rows are re-stamped to 2026-09-29 (ops_legacy_restamp.py, no value changed);
    the 212 keys it listed hold values from the same run's SMART TRADES fetch (real IBKR answers
    of 2026-09-30, later than the displaced serves), which last-wins keeps by design. 0 keys
    hold a d1-bootstrap value over a later-answered serve. feature_vectors and market_regimes
    hold no 4h rows (tf column), so migration 488 left nothing derived behind.
40. CLOSED 2026-10-15 (D-191-O, 7ec5f10fe): GYRE's refusal was the derivation stage refusing a
    vendor restatement instead of applying it last-wins. The write contract now flags ratio
    breaches (revision_flagged, non-blocking) and refuses only removals (refuse_removal); one
    refused or failed name no longer fails the batch (per-name isolation, migration 493).
    The 23:24 UTC apply derived 1,500 names (canonical 1d to 2026-10-12 head per name with raw
    to 10-12; AVA then refused alone, see item 42; CTVA held by design, todo 515). GYRE
    canonical equals IBKR raw on every shared key; fresh sessions arrive with the fetcher.
    Original finding (2026-10-15 resume): the derivation-stage rule refused a revision ratio
    of 0.0283 over 4,665 stored rows with no corporate action; the refusal failed the whole
    daily batch (18:31 UTC run derived 1,497 names and 27,455 new rows, wrote none).
41. Old-store migration tooling left by 191-11 (plan 16 owns): `scripts/ops/bars/ops_raw_backfill.py`
    (the plan 03 backfill; its source is the two old stores) and `ops_selection_gate.locate_groups`
    (plan 04's balance diagnostic) still read `ohlcv_observation` and `ohlcv_intraday_raw_archive`
    by design. Plan 16 runs the last balance check with them, then deletes both with the stores.
    The comment in `scripts/infrastructure/backfill/_fetcher_lock.py` (lines 6 and 32) still names
    the deleted ops_d1_bootstrap and ops_venue_study; it was left because the live fetcher imports
    the module; fix it at the next fetcher-module edit. `ops_head_rerun`'s first bar per request
    is now the earliest bar its id names in raw or the revision log (last-wins moves a re-served
    bar's request id; a head re-ask is the only request over its oldest window, so its head is
    unaffected).
42. Tradier 1d back-adjusted history class (2026-10-15, surfaced by the AVA daily refusal):
    tradier consolidated 1d closes are on a back-adjusted basis before 2023-01-03 (all damaged
    spans end 2022-12-30; the two vendors agree exactly from 2023 on). The 185-17/18 full-history
    apply authored those spans into canonical under the global tradier-primary row, so canonical
    1d sits on the adjusted basis for them. Digest-equality checks cannot see basis drift; the
    D-191-O isolation plus the seam gate surfaced it (AVA: seam median 2.806, 2,766 of 5,229
    stored rows would be removed, refused alone while 1,500 names derived).
    Measured: 27 names with median drift >= 1% over >= 60 paired pre-2023 sessions
    (AVA -57%, ELE -100% (decimal shift, tradier serves ELE at 1/10), EWS/EWT -30%, WELL -24%,
    UNIT -22%, STAG -17%, RJF +18%, IJR +60%, MGM +12%, SSP +12%, TIGO +11%, BH -11%, FTV -8%,
    VMRK -5%, APO -5%, CUBI +5%, FTI +4%, OKE +4%, RTX +3%, IP/PFE/LEN/IBM -2%, WBD/O -1%,
    IESC +2%); 1,022 measurable names are clean (< 1%).
    Fixed 2026-10-15 (migration 494): scoped bar_source_policy rows make IBKR primary over
    [1990-01-01, 2026-10-07) for the damaged names whose IBKR raw coverage is >= 98% of stored
    and whose basis is anchored (non-tradier stored values and non-tradier ohlcv_revision old
    values equal today's IBKR raw exactly; IBKR's basis never drifted): AVA, BH, FTV, CUBI,
    FTI, IP, PFE. FTV and IP rows split around the closed 185-47 one-day rows (append-only
    table). The daily stage re-derives them; the write contract applies last-wins with
    revision flags and logs every displaced tradier value.
    Follow-up (owner flow): the remaining damaged names are IBKR-thin (ELE 93.9% coverage,
    IJR 77%, and 18 more at 75% or less: IBM, RTX, O, LEN, WBD, VMRK, OKE, APO, MGM, RJF,
    WELL, EWS, EWT, STAG, TIGO, SSP, IESC); the fetcher's 1d catch-up is deepening their raw.
    Re-run the drift scan after the catch-up completes and add rows for the same class.
    UNIT is excluded either way: IBKR re-served its own 1d history on another scale
    (2026-10-12, plan 08 finding); its 512 track owns it.
43. Plan 191-12 review (2026-10-16, 191-12-REVIEW.md): PASS, no HIGH. M1 (evidence
    accuracy, fixed same day): the committed WINDOW-EVIDENCE source breakdown quoted a
    stale pre-window dry-run snapshot (ibkr_named 99140486, ibkr_fallback 194470, 2,664
    short of 461,198,119) while citing the clean preflight log; corrected in the evidence
    file to the final preflight values (99,142,349 / 195,271). No mapping gap: live
    GROUP BY source gives exactly the five mapped labels summing exactly to the total.
    Carried to plan 14 (executor prompt): L4 - `--swap` must require in code a fresh
    `--prove` pass since the last build (count-equality resume could skip a same-count
    wrong-values window; prove backstops it today, the swap must not rely on that); L2 -
    window close must confirm the two held units sitting in failed state
    (ibkr-history-fetcher.service, dividend-event-writer@yahoo.service) clear on timer
    resume. Recorded only: L1 - the deleted stale window-one record survives as summary
    prose (logs/ is gitignored; the window script has no abort verb); L3 - one migration
    landed where the plan expected two consecutive numbers (harmless, now documented).
44. Plan 13 executor finding (2026-10-16): `indicagent-api.service` is active and serves
    src/api/routes/market_data.py, which plan 13 switched to (vendor, kind). It is not
    among the window's ten held units. The running process serves old in-memory code
    (queries `source`), which is correct against the live table until the swap. Plan 14
    must hold it for the swap (stop before the rename, restart after with the new code);
    a stale-code reader would 500 on every market-data request post-swap. Same list as
    item 43's plan-14 riders (L4 fresh-prove in --swap, L2 failed-units cleanup at close).
45. SOP review of the 191-12/13 arc + simplify pass (2026-10-16, range
    9636711f7~1..dc434a918): verdict FAIL, one P1, all fixed same session.
    P1 (fixed): bar_reconciliation_audit's `_FIRST_1D_BAR_SQL` still read canonical
    `source` and its call site passed `list(CANONICAL_1D_SOURCES)` - a list of tuples
    since plan 13, unbindable to `text[]`, so the held audit unit would have crashed on
    its first post-swap run (and the query was already broken pre-swap). Converted to
    `vendor = ANY($1) AND kind = ANY($2)` with the CANONICAL_1D_VENDORS/KINDS arrays,
    matching every other converted read in the module.
    P2 (fixed): ohlcv_raw_writer inlined the composite token `f"{vendor}/{kind}"`
    instead of `pair_token`; both ohlcv_revision writers now route through the one
    definition in vendor_kind.py.
    P3 (fixed): SwapAborted/SwapRefused renamed to the Error-suffix taxonomy;
    daily_rule's PRIMARY_PAIR/FALLBACK_PAIR made public (imported across modules);
    bar_derivation's stale-delete binds the derived vendor instead of interpolating it;
    the swap script's local format_ts deleted in favor of format_iso_ts.
    P3 (dispositioned): ops_source_policy.py, ops_truncated_bar_scan.py and
    ops_raw_backfill.py read canonical `source` and sat on no plan's file list - all
    three added to 191-15-PLAN.md's files_modified (verified live: ops_raw_backfill's
    `m` really aliases market_data_ohlcv; the archive-side `a.source` joins are by
    design). Clean surfaces: migration 496 + five infra.canonical_swap.* APR keys with
    provenance, Ring rule (Ring 0 change comment-only), writer topology, circularity
    constraint, BarValues positional compat, rename sweeps, glossary, test placement.
46. Plan 191-14 review (2026-10-17, 8c10d0cc9..0cfb9b825): PASS, no P1/P2; six P3s.
    Two fixed same session (docstring claimed the script runs the bare VACUUM - it is a
    runbook step; SUMMARY said eight L4 tests, there are seven). Deferred to plan 17's
    script-deletion pass (the last consumer of this code): no suite coverage of the
    swap/rollback path itself (only the live run evidences it; --rollback is the untested
    residue); run_rollback neither checks nor reports the api service state truthfully
    and the abort-after-api-stop path leaves it stopped; prove_blockers leniency on a
    hand-corrupted record shape. Recorded only: _API_START_TIMEOUT_S = 60.0 is a
    hard-coded tunable beside four seeded infra.canonical_swap.* siblings - not worth a
    migration for a script retired at 191-17. Deviations 1-5 judged contained; deviation
    4's NOT IN (0, 80) widens a production assertion permanently (noted, accepted).
47. Plan 191-15 review (2026-10-17): PASS, five P3s, all fixed in c176329d2.
48. Plan 191-16 review (2026-10-17): PASS, six P3s - five fixed in b53baec72..be5f01826, P3-6
    deferred to plan 17 D7 (confirm the week-42 parity draw executed end to end before close).
49. Plan 191-17 review (2026-10-22): PASS, one P2 and two P3s, all fixed same session. P2:
    todo 539's premise refuted by the DB (the week-42 parity draw executed end to end
    2026-10-18 19:49Z, destination raw), the todo corrected and closed on that evidence and
    the SUMMARY rider answer fixed by dated addendum. Two P3s fixed in docs: ETHA
    effective-date note (corporate_action says 2026-10-05, the citation said 2026-10-06) and
    the STATE completed_plans recount to 119.
50. Plan 191-18 review (2026-10-22): PASS, three P3 wording nits, all fixed same session:
    PRIORITIES.md and the todo 533 body compressed the close to "D7 exit 0" (the gate passed
    as same known failures or better, not exit 0; fixed in both), STATE.md said "checked plan
    rows 118" where the count is of checked boxes, and the 521 row still described the
    2026-10-10 canonical 5m load as RUNNING though it landed 1,502/1,502 that day.
