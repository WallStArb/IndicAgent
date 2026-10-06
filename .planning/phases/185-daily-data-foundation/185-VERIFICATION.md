---
phase: 185-daily-data-foundation
verified: 2026-10-06T08:53:03Z
status: gaps_found
score: 9/18 must-haves verified (2 by override)
overrides_applied: 2
overrides:
  - must_have: "D1 is an append-only 1d observation store (D-05)"
    reason: "Owner decision 2026-10-03 recorded in 185-CONTEXT.md (Decisions after 2026-10-03) and migration 438: D1 is mutable so Tradier and IBKR answers sit side by side. The store itself exists and holds every route and request type."
    accepted_by: "owner (185-CONTEXT.md, decisions after 2026-10-03)"
    accepted_at: "2026-10-03T00:00:00Z"
  - must_have: "D2 derived 1d bars written to market_data_ohlcv by the derivation alone (D-06)"
    reason: "Owner decision 2026-10-03: Tradier is the primary 1d source and D2's daily stage skips Tradier-owned names, so the Tradier loader is a second, allow-listed 1d writer (tests/unit/test_market_data_ohlcv_writer_boundary.py). The override covers the second writer only; the lineage, digest and scrub consequences are separate gaps below."
    accepted_by: "owner (185-CONTEXT.md, decisions after 2026-10-03)"
    accepted_at: "2026-10-03T00:00:00Z"
gaps:
  - truth: "Every 1d bar research reads traces to its observations and the rule version that produced it (spec success criterion 1, D-06, D-07)"
    status: failed
    reason: "The Tradier loader upserts canonical 1d bars directly and writes no canonical_bar_lineage and no bar_content_digest rows. 523 Tradier-owned names (3,088,305 real 1d bars) have no lineage and no 1d digest. The other 743 Tradier-owned names keep lineage rows (3,179,486 bars) that claim d2-v1 derivation from IBKR SMART observations whose values differ from the stored Tradier bar (AAPL 2010-03-01 stored close 7.4639 vol 550M, lineage observation close 7.46 vol 518M), and every one of their 1d digests was computed before the Tradier overwrite (computed 2026-10-03 12:25, Tradier load 19:49-20:56). Phase 186's check_d2_landed passes those 743 names on existence alone and ic_measure trusts stored digests, so revision detection is silently blind for them."
    artifacts:
      - path: "scripts/infrastructure/backfill/infrastructure_run_tradier_daily.py"
        issue: "_record_load upserts market_data_ohlcv with no lineage, digest or rule version"
      - path: "services/bar_derivation.py"
        issue: "_run_daily_symbol returns 'tradier_owned' before lineage, scrub and _write_daily_digests"
      - path: "services/rebuild_preconditions.py"
        issue: "check_d2_landed tests row existence, not that lineage/digest describe the stored values"
    missing:
      - "A versioned Tradier canonical rule (or D2 rule branch) that records canonical_bar_lineage pointing at the TRADIER D1 observation for every Tradier bar"
      - "Supersede the 3,179,486 stale IBKR lineage rows on Tradier-owned names"
      - "Recompute 1d bar_content_digest for all 1,266 Tradier-owned names after every Tradier write"
      - "A live check that lineage observation values equal the stored bar (test_d2_single_writer_live.py is red on exactly this)"
  - truth: "Every 1d bar carries a scrub flag from validated rules on every write path, historical and nightly (spec success criterion 2, D-12)"
    status: partial
    reason: "The current corpus was scrubbed after the Tradier load (scrub batches 2026-10-03 20:49 over 523 names and 20:58 over 743), quarantine hides flagged bars and every IBKR-sourced known answer is quarantined. But the nightly Tradier leg writes changed bars with no scrub (the daily stage that runs bar_scrub returns early for Tradier-owned names), so the first nightly will land unscrubbed canonical bars. 11 of the 15 legacy_price_sanity_status flags now hide clean Tradier bars (e.g. SPY 2007-04-02 high 142.46 close 142.16)."
    artifacts:
      - path: "scripts/infrastructure/backfill/infrastructure_nightly_backfill.py"
        issue: "No scrub step for Tradier-owned names after _run_tradier_leg"
      - path: "bar_quality_flag (rule legacy_price_sanity_status)"
        issue: "Flags keyed to replaced IBKR values still quarantine Tradier bars"
    missing:
      - "Run bar_scrub over every symbol the Tradier leg changed, in the same nightly"
      - "Retire legacy flags whose bar was replaced by a different source"
  - truth: "Every attempt carries D0's data-quality labels and every research snapshot records the D2 rule version (spec success criteria 1 and 3, D-04, D-07)"
    status: failed
    reason: "src/intelligence/bars/labels.py and label_inputs.py exist and are tested, but nothing outside tests imports load_label_inputs or build_labels. snapshot.py and runner.py contain no d2_rule_version, bar_content_digests or data_quality key. 185-S0-HANDOFF.md says D-04 is met only when the lane owner applies it; no todo, plan or later-phase criterion tracks that application."
    artifacts:
      - path: "src/intelligence/research/snapshot.py"
        issue: "build_panel manifest lacks d2_rule_version and bar_content_digests"
      - path: "src/intelligence/research/runner.py"
        issue: "evidence lacks the data_quality block"
    missing:
      - "Apply 185-S0-HANDOFF.md (two files plus four tests), then repro_frozen bit-identical"
      - "File a todo with a PRIORITIES row if it is not applied in this phase"
  - truth: "No ohlcv_empty_history row exists that every route has not confirmed (spec success criterion 4, D-20)"
    status: failed
    reason: "D7's unconfirmed_empty check (2026-10-06) reports 6 1d rows (CYRX, IBEX, KURA, MARA, ODFL, POWI). All 6 spans contain stored Tradier bars (ODFL claims empty 2006-10-05 to 2024-05-06 over 4,424 stored bars)."
    artifacts:
      - path: "ohlcv_empty_history (6 1d rows)"
        issue: "Unconfirmed and contradicted by stored bars"
    missing:
      - "Reconcile or delete the 6 rows; teach the reconcile that a Tradier-owned span with stored bars is not empty"
  - truth: "Every symbol with tradeable 5m bars has only derived 15m and 1h rows (D-15, D2b)"
    status: partial
    reason: "233 of 240 symbols with 5m are derived. A, AAP, ABBV, ACRS, ACVA, ADBE and ADP keep 27,317 IBKR 15m/1h rows because the grid stage's archive verify refuses twice-observed bars (todo 490); the last ten grid batches through 2026-10-03 ended failed. test_derived_grid_live.py is also red on 1h-vs-1d volume (LMT 2009-07-23, 7.45% deficit) because 1d volume is now Tradier's consolidated volume while 5m is IBKR's."
    artifacts:
      - path: "services/intraday_raw_archive.py / services/bar_derivation.py grid stage"
        issue: "First-write-wins archive cannot hold a second observation (todo 490)"
      - path: "tests/integration/test_derived_grid_live.py"
        issue: "Volume identity assumes one vendor across 1d and 5m"
    missing:
      - "Todo 490 decision and fix (archive as observation history, recommended)"
      - "Restate the 1h-vs-1d volume identity per vendor or limit it to IBKR-owned names"
  - truth: "The D-28 minimum data bar check passes (ops_data_bar_check.py exits 0)"
    status: failed
    reason: "Run 2026-10-06 (read-only): 4/7 pass, exit 1. scrub_pass_complete fails 28/72 because 44 known-answer keys now hold clean Tradier values (all 13 IBKR-sourced keys are quarantined), so the check is stale against the Tradier decision. no_pre_move_bars_visible fails with 91,059 pre-move bars on 32 names, all Tradier consolidated bars, also stale (and ohlcv_venue_head counts TRADIER as a venue route). late_name_dispositions is a real failure: 8 unresolved (BLBD, DAL, FRHC, IDR, KN, OGS, SGHC, UUUU)."
    artifacts:
      - path: "scripts/ops/bars/ops_data_bar_check.py"
        issue: "Conditions 1 and 4 not updated for Tradier-sourced bars"
    missing:
      - "Make conditions 1 and 4 source-aware"
      - "Resolve the 8 unresolved late names (re-ask or Tradier load)"
  - truth: "Phase 185's own live integration tests pass"
    status: failed
    reason: "test_d2_single_writer_live.py fails 3 of its tests (source 'tradier' not canonical; VWO derived-but-not-stored mismatches; stale TLT exception) and test_derived_grid_live.py fails 1; neither failure is tracked (todo 496 names two other tests)."
    artifacts:
      - path: "tests/integration/test_d2_single_writer_live.py"
        issue: "Still asserts IBKR-only canonical 1d"
    missing:
      - "Update both tests to the Tradier-primary design once the lineage gap is closed; drop the stale TLT exception"
deferred:
  - truth: "The 185 daily chain (Tradier leg, split detection, daily and grid stages, D7 audit) runs every night, so a split is caught within a day (spec success criterion 6, operational part)"
    addressed_in: "Phase 189"
    evidence: "Phase 189 goal: the fetcher 'replaces the nightly timer, lane scripts and two-tier lease'; 189-06 installs the fetcher timer; commit e947b553a amends 189-06/07 with the 185-26 nightly legs. Today indicagent-nightly-backfill.timer has been inactive since 2026-10-02, so ETHA's 1-for-3 split (effective 2026-10-02) is still unrecorded in corporate_action."
human_verification:
  - test: "Confirm the deletion of 3,850,642 LEGACY_IMPORT rows from ohlcv_observation was intended"
    expected: "A recorded decision (e.g. dedup against identical SMART observations); 931 legacy requests claim 3,862,849 bars, 12,207 remain, pg_stat n_tup_del = 3,850,642; no summary or commit documents it"
    why_human: "D1 is mutable by owner decision, so intent cannot be read from the code"
  - test: "Spec success criterion 8: reopened ideas re-evaluated on canonical bars"
    expected: "Owner confirms this is an obligation on the first reopened idea, not a phase 185 deliverable (research attempts are paused, build first)"
    why_human: "No reopened idea has run since canonical bars exist"
  - test: "Decide whether to restart the nightly timer before 189-06 lands"
    expected: "Either restart it (ETHA's split gets recorded, the Tradier leg's first real night is measured) or accept staleness until the fetcher cutover"
    why_human: "Operational choice that interacts with the running HTF lane"
---

# Phase 185: Daily data foundation verification report

**Phase goal:** Every daily bar research reads traces to raw observations and a versioned derivation rule, and no data defect reaches a verdict unmeasured (stages D0-D7 of `docs/plans/2026-09-26-daily-data-foundation.md`, revised by the 2026-10-03 owner decisions: Tradier primary for 1d, D1 mutable).
**Verified:** 2026-10-06T08:53:03Z
**Status:** gaps_found
**Re-verification:** No, initial verification

ROADMAP phase 185 has no success-criteria array, so the contract is the spec's eight success criteria (`docs/plans/2026-09-26-daily-data-foundation.md` lines 323-336) plus the goal's stage clauses D0-D7, D2a and D2b, and the D-28 gate the phase built. Plan frontmatter truths were checked where they bear on these. Everything below was read from the codebase and the live DB with read-only queries; no writes, no service changes.

## Goal achievement

### Observable truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | Every 1d bar traces to its observations and rule version (SC1) | FAILED | 1d corpus: 722,186 real IBKR bars with lineage; 3,088,305 real Tradier bars (523 names) with none; 3,179,486 Tradier bars (743 names) whose lineage cites IBKR observations with different values. All 743 names' 1d digests predate the Tradier overwrite. |
| 2 | Every research snapshot records the D2 rule version (SC1) | FAILED | `snapshot.py`/`runner.py` have no `d2_rule_version`; the S0 hand-off was never applied |
| 3 | Every attempt carries D0 labels (SC3, D-04) | FAILED | `labels.py`/`label_inputs.py` exist and are tested but are orphaned (only tests import them) |
| 4 | Every 1d bar scrubbed by validated rules, quarantined not deleted (SC2, D2a) | PARTIAL | Corpus scrubbed 2026-10-03 after the Tradier load; 14,984 Tradier OHLC-invariant bars quarantined on 1,078 names; all 13 IBKR-sourced known answers quarantined. The nightly Tradier path has no scrub; 11 stale legacy flags hide clean Tradier bars. |
| 5 | No unconfirmed `ohlcv_empty_history` row (SC4, D4) | FAILED | D7: 6 unconfirmed 1d rows, each overlapping stored Tradier bars |
| 6 | Moved names chain across the move or the seam is flagged (SC5, D3) | VERIFIED | Study failed both criteria (`config/bars/venue_study_verdict.json`); `venue_bars_1d` false; 0 `ibkr_venue` canonical rows. 32 of 45 moved names have continuous Tradier history; the 15 still truncated (PEP, CSX among them) are reported by D7 `late_heads`; `unexplained_seams` judges 3,331 and finds 2 (FICO, LQDA, Sept 2026). |
| 7 | Split seams found, recorded, re-derived; caught within a day (SC6, D5) | VERIFIED (code); operation deferred | Seam audit over 931 names found 0 seams (`corporate_action` empty, MRNA/ALMS events); overlap detection and Tradier-refetch split inference wired and unit-tested; nightly not running since 2026-10-02 (deferred to 189) |
| 8 | Dividend route validated or reported unusable (SC7) | VERIFIED | `docs/research/ibkr-dividend-route-validation.md` verdict: not usable alone; 45,876 `ibkr_adjusted_last_ratio` rows on 707 names; 26 `dividend_date_dispute` rows |
| 9 | Reopened ideas re-evaluated on canonical bars (SC8) | UNCERTAIN | No reopened idea has run; research paused (human item) |
| 10 | D1 store holds every route and request type, append-only | PASSED (override) | 20.2M observations: TRADIER 11.78M (1,529 names), SMART TRADES 4.12M, ADJUSTED_LAST 3.87M, five venues; mutability is owner-approved. See the legacy-deletion human item. |
| 11 | D2 is the only 1d writer | PASSED (override) | Tradier loader allow-listed as PERMANENT second writer per owner decision |
| 12 | D2b: only derived 15m/1h for every symbol with 5m | PARTIAL | 233/240 derived; 7 todo-490 symbols keep 27,317 IBKR rows; no symbol mixes grids; masked slots 0 |
| 13 | D3 venue bars used only after the study passes | VERIFIED | Same evidence as truth 6; provider never returns venue bars (185-19) |
| 14 | D4 empty history derived from recorded answers | VERIFIED (mechanism) | `_empty_history.py` reconcile from D1; the residue is truth 5 |
| 15 | D5 IBKR dividends from ADJUSTED_LAST vs TRADES in D1 | VERIFIED | As truth 8; the writer reads D1, its fetch is gone (185-21) |
| 16 | D6 point-in-time listing venue | VERIFIED | `listing_venue`: 974 rows, 931 names, 931 open spans, 0 overlaps, append-only triggers present |
| 17 | D7 daily reconciliation into integrity_monitor and Grafana | VERIFIED | 30 `bar_reconciliation` metrics written 2026-10-06; panel in `production/grafana/dashboards/operations.json`; chained as the nightly's last step |
| 18 | D-28 minimum data bar check passes | FAILED | 4/7, exit 1 (two stale conditions, one real: 8 unresolved late names) |

**Score:** 9/18 (7 verified, 2 by override; 7 failed or partial; 1 uncertain; truth 7's operational half deferred)

### Deferred items

| # | Item | Addressed in | Evidence |
|---|------|--------------|----------|
| 1 | Nightly execution of the 185 chain (catch a split within a day) | Phase 189 | Goal replaces the nightly timer; 189-06 installs the fetcher timer; e947b553a carries the 185-26 legs into 189-06/07 |

### Required artifacts (spot-checked)

| Artifact | Status | Details |
|----------|--------|---------|
| D1 tables `ohlcv_request`, `ohlcv_observation` | VERIFIED | Live, populated |
| `bar_quality_flag`, `market_data_ohlcv_tradeable` quarantine | VERIFIED | 2.15M flags; quarantine hides bars |
| `canonical_bar_lineage` | HOLLOW for Tradier names | 3.92M rows, all d2-v1, none for Tradier values |
| `bar_content_digest` (1d) | STALE for 743, MISSING for 523 names | 979 symbols covered |
| `corporate_action`, `listing_venue`, `ohlcv_intraday_raw_archive` | VERIFIED | Append-only triggers on the first two |
| `src/intelligence/bars/labels.py`, `label_inputs.py` | ORPHANED | Not imported by research code |
| `services/bar_reconciliation_audit.py` | VERIFIED | Ran 2026-10-06 |
| `scripts/ops/bars/ops_data_bar_check.py` | VERIFIED (runs), result red | See truth 18 |
| `market_data_ohlcv` synthetic fill (185-25) | VERIFIED | 0 `synthetic_fill` rows |

### Key link verification

| From | To | Via | Status |
|------|----|-----|--------|
| Tradier loader | `canonical_bar_lineage` / `bar_content_digest` | none | NOT_WIRED |
| Nightly Tradier leg | `bar_scrub` | none (daily stage returns at `tradier_owned`) | NOT_WIRED |
| `label_inputs` / `labels` | `snapshot.py` / `runner.py` | hand-off doc only | NOT_WIRED |
| `bar_derivation --stage daily` | lineage, digests, scrub | `_run_daily_symbol` | WIRED (IBKR-owned names) |
| Nightly | split detect, daily, grid, D7 | `_run_nightly`, `main` | WIRED in code; timer inactive |
| `rebuild_preconditions.check_d2_landed` | lineage/digest truth | existence only | PARTIAL (false pass for 743 names) |

### Data-flow trace (level 4)

| Artifact | Data | Source | Real data | Status |
|----------|------|--------|-----------|--------|
| 1d `market_data_ohlcv` (Tradier names) | OHLCV | Tradier loader | Yes | FLOWING, untraced |
| 1d lineage (743 names) | request_ids | 2026-10-03 D2 run | Describes overwritten IBKR values | HOLLOW |
| 1d digests (743 names) | digest | 2026-10-03 12:25 | Predates overwrite | STALE |

### Behavioral spot-checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| Pure phase tests and CI boundaries | `pytest tests/unit/bars/ tests/unit/providers/test_ibkr_provider.py` plus four boundary tests | 220 passed | PASS |
| D-28 gate | `python -m scripts.ops.bars.ops_data_bar_check` | 4/7, exit 1 | FAIL |
| D2 single writer live | `pytest tests/integration/test_d2_single_writer_live.py -m integration` | 3 failed | FAIL |
| D2b live grid | `pytest tests/integration/test_derived_grid_live.py -m integration` | 1 failed (volume identity) | FAIL |

The full `tests/unit/` suite was not run: todo 494 records unit tests that write to the live DB.

### Probe execution

Step 7c: no probes declared for this phase.

### Requirements coverage

ROADMAP lists Requirements: TBD; plans carry decision IDs (D-01 to D-31), not REQUIREMENTS.md IDs. Decision coverage is in the truth table.

### Anti-patterns found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| (phase files) | - | TBD/FIXME/XXX | none found | - |
| `infrastructure_run_tradier_daily.py` | 68 | `_VALUE_TOLERANCE = 1e-9` literal | Info | Float epsilon, arguably APR-exempt |
| `ohlcv_venue_head` view | - | Counts TRADIER as a venue route | Warning | Inflates moved-name inputs (492 names "pre_move" on TRADIER) |

### Human verification required

1. Legacy D1 deletion: confirm the 3,850,642 deleted `LEGACY_IMPORT` observations were intended and record why.
2. Success criterion 8: confirm it is an obligation on the first reopened idea, not a 185 deliverable.
3. Nightly timer: restart now or wait for 189-06 (ETHA split unrecorded since 2026-10-02).

### Gaps summary

Two root causes carry most of the gap.

A. The Tradier decision was wired as a bypass of D2 rather than as a source inside it. The loader writes canonical bars directly, so the phase's first promise (every bar traces to observations and a versioned rule) holds for about 723k IBKR bars and fails for about 6.27M Tradier bars. The worst part is silent: 743 names carry lineage and digests that describe IBKR values the table no longer holds, and phase 186's `check_d2_landed` passes them. The same bypass skips scrubbing on the nightly path and leaves the D-28 gate and two live tests asserting the pre-Tradier design. Fixing it means one versioned canonical rule that lineages, scrubs and digests Tradier bars the way D2 does for IBKR, plus superseding the stale rows.

B. D0 never reached research. The label code is done and orphaned; the S0 hand-off is untracked.

Smaller, independent gaps: 6 contradicted empty-history rows, todo 490's 7 grid symbols, 8 unresolved late names.

### Open todos: blocking or later

| Todo | Blocks phase 185? | Reason |
|------|-------------------|--------|
| 490 | Yes, narrowly | D2b (D-15) is incomplete for 7 symbols and the grid stage exits non-zero every run; the fix is in 185's archive write path. Close it, or have the owner accept a 7-symbol exception explicitly. |
| 495 | No | Integration-DB baseline hygiene; no goal truth depends on it |
| 497 | No, belongs to phase 186 | Intraday recovery unlock is set by 186-27 by design (D-19) |
| 433 | No | 1d done (study failed, venue bars stored and unused, Tradier covers 32 moved names, D6 records moves, D7 reports the 15 still truncated); intraday recovery waits on 186 by design |

The real blockers are not in any todo: gaps A and B above, the 6 empty-history rows and the stale D-28 conditions. Each needs a todo with a PRIORITIES.md row, or a gap-closure plan (`/gsd-plan-phase 185 --gaps`).

---

_Verified: 2026-10-06T08:53:03Z_
_Verifier: Claude (gsd-verifier)_
