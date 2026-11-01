# Data-layer redundancy audit: disposition map

**Author:** Claude (research lane, session b0), 2026-11-01, at the owner's request (coordinator
indicagent-af). **Informed by:** todo 533's Tradier retirement, todo 574's retention gate, todo
443's exporter measurements, the 186-26 stage-2 rebuild. **Status:** audit, not a plan; read-only,
no deletions executed. The Tradier cluster (ops_tradier_delete, ops_tradier_residue,
ops_tradier_residue_gate, ops_d191q_arbitration, ops_raw_cutover_window) and ops_tradier_restore
are dispositioned by the coordinator's own lane and excluded here except at the boundary; the
boundary confirms clean: every excluded script's remaining reference outside the cluster is either
todo 574's retention gate or a phase record.

Scope: `scripts/ops/bars/`, `scripts/infrastructure/backfill/`, `services/bar_*.py`,
`src/intelligence/bars/`. Evidence classes: live reference (unit, timer, import), completed plan
that consumed the script, pending todo gating it, or the module's own deletion note.

## Families and dispositions

### The three load/derive/audit core chains — keep, no duplicates

The production DAG is one chain per stage and every member is load-bearing: capture
(ops_bar_nightly -> bar_load -> ohlcv_raw_writer -> ohlcv_request_writer) -> selection
(bar_selection, ops_selection_gate) -> derive (bar_derivation daily+grid, bar_derivation_batch,
daily_rule, bar_scrub/scrub_rules, write_contract, bar_hold) -> audit (bar_reconciliation_audit,
integrity_checks, verdict_gate, digest, restatement, seams) -> support (bar_aggregator,
bar_writer, provider_merger). Each has a live unit or timer. No second implementation of any
stage exists; the overlaps below are check-vs-check, not implementation-vs-implementation.

### scripts/ops/bars/

| Script | Purpose | Duplicate? | Evidence | Disposition |
|---|---|---|---|---|
| ops_bar_nightly.py | Alpaca nightly capture through the load engine | no | live timer | keep |
| ops_bar_load.py | Thin shell over bar_load for one-off loads | overlaps ops_bar_nightly's engine, not its function | named in services/README and canonical-truth-registry | keep (standing tool) |
| ops_selection_gate.py | Canonical selection, D-191-C; re-selects on policy writes | no | live, imported by ops_source_policy's reselect path | keep |
| ops_data_bar_check.py | D-28 gate: scrub/keys/late-name conditions, live DB | see overlap A | live, references the D-28 conditions | keep, but see overlap A |
| ops_capture_completeness.py | ohlcv_load-ledger vs raw completeness (R6) | see overlap A | live reference (SOP/checklist) | keep, see overlap A |
| ops_head_rerun.py | Classifies IBKR-sourced late 1d names, reruns heads | see overlap C | live, feeds classify_head evidence | keep |
| ops_intraday_venue_recovery.py | Recovers moved names' 5m venue history, refuses by default | see overlap C | uses _campaign and _fetcher_lock | keep (standing, campaign-scoped) |
| ops_ibkr_1d_deepening_gate.sh | Gates the 1d deepening stage of the 534 campaign | see overlap C | campaign gate | keep until 534 closes, then capture-as-todo |
| ops_campaign.py (_campaign.py) | Phase 185 campaign pre-flight check | consumed by head_rerun and venue_recovery | live imports | keep while campaigns run; capture-as-todo when 534 closes |
| ops_split_detect.py | Split detection over fetch runs | see overlap B | live, called by the fetcher's judge | keep |
| ops_restatement_review.py | Human review surface for restatement findings | no | imported by _history_fetch_item and the ingress contract | keep |
| ops_scrub_historical_pass.py | One-time historical scrub pass | bar_scrub holds the rules | named by bar_scrub; pass-shaped (a completed sweep) | capture-as-todo: confirm the pass completed, then delete |
| ops_export_known_answer_fixtures.py | Exports known-answer fixtures | no other producer | no references outside itself | capture-as-todo: one-shot-done; confirm fixtures are frozen in git, delete |
| ops_session_choice_backfill.py | Migration 480's session-choice backfill | no | migration-companion; the backfill ran | delete now (one-shot-done; migration 480 is the record) |
| ops_truncated_bar_scan.py | Scans IBKR 5m requests that ended mid-bar | no | todo 535 item 19 dispositioned it as built and P3 | keep (standing scan) or capture-as-todo for a scheduled run; owner call |
| ops_hold_slot_coverage_gaps.py | Holds names the nightly slot_coverage verdict fails (565a) | no, it consumes the audit's verdict | migration 552, recorded_by | keep |
| ops_old_store_backup.py | Dumps old-store tables to CSV for rollback | no | todo 574's retention gate | delete with todo 574 on 2026-11-12 |
| ops_d191p_followon.sh | One-shot re-selection of the D-191-P follow-on names | no | plan 191-07 record | delete now (one-shot-done) |
| ops_source_policy.py | Writes bar_source_policy rows (--add/--close/--plan) | no | live; sweep arm retired in 191-25 | keep |

### scripts/infrastructure/backfill/

| Module | Purpose | Duplicate? | Disposition |
|---|---|---|---|
| ohlcv_history_fetcher.py, _history_fetch.py, _history_fetch_item.py, _fetch_queue.py, _fetcher_lock.py, _intraday_persist.py, _derivation_stage.py | The consolidated fetcher (queue, item driver, persistence, lock) | no; ops_head_rerun and ops_intraday_venue_recovery consume pieces rather than reimplement | keep |
| _d1_gaps.py | plan_gaps-driven D1 gap planning | see overlap C | keep |
| _empty_history.py | Empty-history evidence (answered-empty spans) | see overlap C | keep |
| infrastructure_ibkr_chunk_and_rate_limit_probe.py | Measures IBKR chunk/rate limits | no; referenced by src/providers/CLAUDE.md and ibkr.py docs | capture-as-todo: one-shot-done for the 191-02 calibration; keep as a re-probe tool or delete with its numbers recorded |

### services/bar_*.py

| Service | Purpose | Disposition |
|---|---|---|
| bar_derivation, bar_derivation_batch, bar_selection, bar_scrub, bar_hold, bar_load, bar_reconciliation_audit | Production stages | keep |
| bar_auditor.py | Streaming-era auditor agent: audits canonical completeness and publishes gap requests (Phase 053, the v2.x signal path) | see overlap A; unit exists but disabled; its gap-request publication duplicates gap detection shapes 2-4 below |
| bar_replay_provider.py | Replays tradeable-view bars into the live topics (dormant streaming feed) | the streaming path is dormant while the live feed is down; unit disabled | capture-as-todo: owner call on the dormant streaming path (auditor, replay, and the topic consumers) as one block, not file-by-file |
| bar_writer.py | Streaming bar persistence (BarWriter batch) | dormant with the streaming path; same owner call |
| bar_aggregator.py | Live 5m->15m/1h aggregation (streaming) | dormant with the streaming path; same owner call |

### src/intelligence/bars/ — pure library, all load-bearing

No dead modules. vendor_basis and vendor_arbitration are load-bearing beyond their Tradier
history: integrity_checks imports ARBITRATED_THROUGH and find_basis_runs for the live
alpaca_basis_run check, and daily_rule imports BP. vendor_ingress, verdict_gate, write_contract,
labels/label_inputs, session_grid, sessions, selection, seams, restatement, digest, gap_plan,
scrub_rules, corporate_actions, complete_bars, venue_study (D-17 statistics the record cites),
daily_rule, derivation, sources, vendor_kind: each has live importers. source_admission stays
until todo 574 (2026-11-12). venue_study is the only capture-as-todo candidate: the D-17 study is
closed, the module's statistics are cited by the record; keep unless the owner wants the history
trimmed.

## Overlap analysis (the four gap-detection shapes; normalization; fetch)

**A. Gap/completeness detection, four shapes plus the streaming fifth.** They answer different
questions on different planes and are NOT implementations of one another:
1. bar_auditor (streaming, disabled): canonical completeness pct per (symbol, tf) against the
   live feed; publishes gap requests. Superseded in practice by the nightly audit while the feed
   is dormant.
2. bar_reconciliation_audit + integrity_checks + verdict_gate (nightly): the nine 1d checks and
   slot/freshness/coverage with holds. The canonical gap authority.
3. ops_capture_completeness: ledger-vs-raw completeness of the CAPTURE plane (did a load's
   promised rows land in ohlcv_raw), which the audit does not check.
4. todo 565's slot_coverage evidence: a coverage-evidence DEFINITION inside the nightly audit's
   verdict set, not a separate tool.
Disposition: merge nothing. Capture-as-todo: retire the dormant bar_auditor with the streaming
block (owner call), and fold ops_capture_completeness's R6 condition into the nightly audit's
condition list only if a second plane-wide sweep ever justifies it — until then its ledger-side
view stays distinct.

**B. Normalization: vendor_basis, vendor_arbitration, daily_rule, scrub_rules (D2a), ops_split_detect.**
One pipeline, not duplicates: daily_rule decides which vendor serves a date; vendor_basis
measures agreement (basis runs); vendor_arbitration classifies disagreements into policy actions
(one-shot record writer, inert, self-refusing; its library stays load-bearing for the audit);
scrub_rules quarantine bad bars; ops_split_detect classifies overlap splits that feed the
split-adjustment decisions. No merge candidates. The only residue: ops_data_bar_check's D-28
conditions and the nightly audit both name late-name/known-answer evidence from different planes
(D-28 is capture-plane; the audit is canonical-plane), which is overlap A's answer applied here.

**C. Fetch: the consolidated fetcher vs four named side doors.** _d1_gaps (plan output consumed
by the fetcher), _empty_history (evidence consumed by the fetcher and the audit) are modules OF
the fetcher, not alternatives. ops_head_rerun, ops_intraday_venue_recovery and
ops_ibkr_1d_deepening_gate are campaign/repair doors that hold FetcherLock and go through the
same persistence; they exist because each carries a distinct safety posture (refuse-by-default,
classify-then-act, gate). No merge; each is standing while the 534 campaign runs. After 534
closes, audit the three doors' remaining call volumes (capture-as-todo).

## Proposed todos

1. **Dormant streaming bars block** (owner decision): bar_auditor, bar_replay_provider,
   bar_writer, bar_aggregator units are disabled; decide retire-with-the-archive vs keep-for-the-
   live-feed-return. One todo, four files plus their units and the topic consumers.
2. **One-shot-done sweep**: delete ops_session_choice_backfill.py and ops_d191p_followon.sh now
   (migration 480 and the plan record are the evidence); confirm-and-delete
   ops_export_known_answer_fixtures.py and ops_scrub_historical_pass.py after their outputs are
   confirmed frozen in git.
3. **Post-534 campaign-doors audit**: when todo 534 closes, re-measure ops_head_rerun,
   ops_intraday_venue_recovery, ops_ibkr_1d_deepening_gate, _campaign.py and
   ops_truncated_bar_scan for continued standing.
4. **Existing gates, unchanged**: todo 574 (ops_old_store_backup with the Tradier restore
   toolchain, 2026-11-12); the 443 timeout sequence; venue_study and
   infrastructure_ibkr_chunk_and_rate_limit_probe stay unless the owner wants history trimmed.
