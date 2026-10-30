---
gsd_state_version: 1.0
milestone: v3.5
milestone_name: Unified Research Pipeline
status: in_progress
last_updated: "2026-10-29T12:00:00.000Z"
progress:
  total_phases: 9
  completed_phases: 2
  total_plans: 148
  completed_plans: 128
  percent: 22
---

# Project State

Current position only. History: git, `.planning/MILESTONES.md`, and the archived state at v3.4
close (`.planning/milestones/v3.4-STATE.md`). Don't stack dated narrative here; replace stale
bullets with current facts.

## Strategic plan (read this first)

- **The design:** `docs/plans/2026-09-26-unified-research-to-production-design.md`, ADOPTED
  2026-09-26 with methodology-change-ledger E18. It owns the sequence (section 16). One pipeline
  from data to a frozen book; the old ensemble chain is deleted; costs never enter a test
  statistic but promotion needs positive net expectation; every look at the vintage is counted and
  selection is by Romano-Wolf StepM; each book gets its own forward span (feature books never
  before 2026-08-08, after 7 recorded holdout looks); raw data is permanent, derived data is cache.

- **Milestone v3.5 Unified Research Pipeline, phases 183-188** (ROADMAP.md). Goal (owner
  2026-10-27): start testing families with new features, factors and regimes as soon as the data
  allows. Build first (2026-09-27) is lifted at plan 191-20's 1d re-derive. From then on, family
  2's one evidence run and the daily price-only families (441 + 423, then 440) run while the
  rebuild runs. Order: 191 (data settled) -> 186 rebuild; 184 planned now and run on the rebuilt
  table; 187 selection core (08-15) now, governance (16-18) after the first feature family;
  then feature and regime families; 188 waits on a candidate book.

- **Evidence rules:** E15 (book as the unit), E16 and E17 (timing statistic), E18 (counting,
  selection, promotion, per-book span). Until phase 187 lands, the phase 183 runner's M = 30
  accounting stays in force for any book test.

- **Research record:** `docs/research/construction-verdict-ledger.md` until phase 187 generates it
  from UCR (fully reconciled 2026-10-08). Check it before recommending a candidate.

## Current position (2026-10-26)

**Critical path (reordered 2026-10-27):** phase 191 plan 19 Task 2 -> plan 20 (owner confirms
the Tradier deletion; 1d re-derive; testing unpauses here) -> 191-21 -> 22 -> 23 (decided
2026-10-27: 23 depends on 22, whose integrity_checks changes bar_reconciliation_audit consumes;
21 and 23 are the plans that edit modules the rebuild imports) -> 186-26 feature rebuild (todos 553, 390/555 and 560 land first, before 191-23's summary: 553 and 555 are on origin/main, 560 is on origin/main with its checks open; the 186-26 launch has no owner), with 191-24 and 25 landing alongside -> 186-27 -> 184 feature families.
Research lane in parallel: 184 planned 2026-10-27 (14 plans, 8 waves; wave 1 01-04 new files only, runs on indicagent-5b's go; wiring 06-11 after 187-08/09/10 and 187-15 Task 2, before 187-18), 187 plans 08-15.

- **Phase 191 (unified raw bar table, todo 533): 18 of 25 plans done.** Plans 01 to 18 landed and
  were reviewed (summaries and reviews in the phase dir; the swap landed 2026-10-17, the old stores
  were dropped, todo 530 closed). Canonical is `market_data_ohlcv` keyed by (vendor, kind), a pure
  function of `ohlcv_raw` plus `bar_source_policy`; the selection gate (`ops_selection_gate.py
  --compare`) is the standing proof. Raw is last-wins with a revision log (D-191-N).

- **Plan 19 (Tradier residue readiness): Task 2 done 2026-10-28.** Readiness green 01:30Z
  (1,522 settled, 0 unsettled, 7 frozen: MOD, PSKY, CLBK, BZH by flag; CCO, QRVO, WBD by
  listing_end). `191-TRADIER-RESIDUE.md` (measure, prove, report; the gate's report step now passes
  its inputs). Residue after D-191-Q coverage: 314,522 Tradier-only sessions on 799 names, 90%
  before 2016, much of it predecessor splices under reused tickers. Proof: 1,466 of 1,529 proven;
  62 of 63 unproven are venue-moved (todo 433), plus ETHA. Owner decision summary:
  `191-20-OWNER-DECISION.md`, relayed to indicagent-5b for the owner. Plan 19 SUMMARY and
  completed_plans follow with the plan 20 approval.
- **Plan 20 (Tradier deletion): done 2026-10-29, D7 accepted with 229 named holds.** Policy
  applied, Tradier bar rows deleted (zero remain), 1d re-derived under d2-v4, VACUUM, timers running.
  Migration 537 (25b930e1c) makes canonical_bar_lineage resolve Alpaca bars through ohlcv_load. D7
  on 1,502 names: 1,273 pass every required 1d check; the 229 holds are in
  `191-20-D7-HOLDS.tsv` (CTVA is the held rescale name). Research lane notified. Record: todo 545.
- **Plan 20 approved by the owner 2026-10-28:** delete all Tradier bar rows, no names held back (recorded in
  `191-20-OWNER-DECISION.md`). It runs after todo 545 lands. Review findings for 3a: keep the final
  arbitration plan JSON in a tracked place, refuse a row whose span touches `window_end`, stop the fetcher
  timer for the final re-run and apply. The 30 interim daily holds stay as gaps (todo 557).
- **Research docs, 2026-10-28:** the ledger is condensed (sections 2 and 4 verbatim); the cointegration concept is
  reopened as a spread family (ledger section 2, todo 559, pre-registration before any look); the stat arb
  method map and the pre-rebuild feature pass (todo 558, window closes when 186-26 starts) are unreviewed
  Sonnet drafts that need an Opus or Fable pass.

- **IBKR:** the gateway was wedged 2026-10-18 23:59Z to 2026-10-26 09:00Z (2FA never approved), so
  no IBKR bars landed 2026-10-17 to 2026-10-25; the backlog is catching up. Fixed today: explicit-UTC
  request end (540), an out-of-range client id no longer restarts the gateway (542), and the
  fetcher lock survives `idle_session_timeout` (543; before it, any run over an hour lost its lock).

- **Alpaca nightly (todo 521):** `indicagent-alpaca-nightly.timer` installed 2026-10-26 (04:40
  UTC). It asks SIP with its window end held 20 minutes back (migration 513; the free plan 403s
  only a window ending within about 15 minutes of now). IEX answers are kind `iex_rth`, raw only,
  never selected. A one-time 20-day SIP catch-up is running
  (`logs/alpaca_nightly_catchup_20261026.log`) and fills canonical 5m where IBKR has no session.

- **186-26 rebuild preconditions:** the selection gate exits 0, canonical 1d is current, plans
  191-21 to 191-23 have landed (21 and 23 edit the rebuild's import closure, 23 depends on 22), and canonical 5m is caught up past the 2026-10-17..25 gap (the
  Alpaca catch-up finished, gate exits 0 on 5m). D-32 gates as in `186-26-PLAN.md`; the run tree
  `/home/bg/dev/indicagent-186-26` is kept for it (plan 186-27 removes it).

- **186-26 rebuild stage 1 (1d, 1,273 non-hold names), launched 2026-10-29 22:08Z, completed 22:44Z
  (51 of 51 units, 5,127,577 rows, one kill-and-resume); later stages are resumable and pending:** systemd
  user unit `feature-rebuild-1d`, 12 workers, 25 names per unit, horizon `--data-horizon 2026-10-01`. Run tree
  `/home/bg/dev/indicagent-186-26` pinned at code sha `92e588385` (unit code key `8c3ab364de21`); every
  later stage (the 229 D7 holds on 1d with `--symbols <holds>`, then the intraday tfs) runs from that
  tree, not from main. Logs: `/home/bg/dev/indicagent/logs/feature_rebuild_1d.log` and
  `/home/bg/dev/indicagent-186-26/logs/backfill_feature_factory.log`. Evidence and the resume procedure:
  `.planning/phases/186-old-ensemble-chain-retirement-and-ic-engine-re-scope/evidence/186-26-rebuild-run.json`
  (key `stage1_1d`) and `186-26-stage1-1d-launch.sh`. Freeze: no module the rebuild imports
  (`services/backfill_feature_factory.py`, `services/_batch_utils.py`, `src/intelligence/features/`,
  their imports) may be edited while the run is live or resumable, and later stages are still to
  come, so the import closure stays frozen at `92e588385` until the owner closes the rebuild.
  Todo 420 is not part of stage 1 (the factory does not read `market_regimes`).

- **186-26 rebuild stage 1b (1d, 73 names freed after the 2026-10-30 verdicts), completed 2026-10-30
  (3 units, 296,486 rows; the table now holds 5,424,063 rows over 1,314 names, 54 completed units):**
  unit `feature-rebuild-1d-b`, the same pinned tree, code key and horizon as stage 1; the names are every
  compute_1d name that passes every 1d verdict and was not built (16 recent listings produced zero rows
  for lack of bars). Still to build: the 156 names that fail `session_coverage` in the era (list in
  `191-SESSION-COVERAGE-ERA-FAILS.tsv`) and the other holds as they clear, the 27 names whose 1d history
  grew after the stage 1 input (drift list in todo 566; delete their rows and rebuild at the 186-27 drift
  read), then the intraday tfs once the intraday verdicts pass. The feature table ends 2026-09-30 by the
  horizon; moving it forward is a new run, not a resume.

- **Research, 2026-10-27 (indicagent-5b):** 187 plans 01-07 landed; 08 Tasks 1-2 landed
  (horizon rule, book_memory, ridge and kappa battery cells, 59c6c44fb and 44409aafb), Task 3 waits
  on the 187-08 battery run. Cross-AI review of 187 (Codex and AGY, 187-REVIEWS.md): code fixes
  1e2d26419 and 7d8a14de2, amendments in plans 08-18. StepM: the 1,500-session battery failed two
  cells; at 4,000 sessions both hold; owner decision 2026-10-27: the attestation is a complete
  13-cell run at 4,000 sessions (next run). Plan 09 in-fold signs: trailing (owner 2026-10-27).
  E17 amended: L adds a daily target's reach (`timing.e17_memory`; intraday unchanged). Daily
  residual family (441 + 423) built to its battery (ee8c264df); prereg draft; h = 21 waits on
  todo 547. The 187-03 backfill (8 of 20 replays, then `--apply`) is approved (owner 2026-10-27).
  E17 v2 (owner 2026-10-27, todo 549): fixed-b critical values; the 4,000-session StepM run on v1
  is a pre-v2 baseline only. 2026-10-28: 187-09, 187-10 and 187-11 landed (migration 530 live: typed concept domains, recipes, `concept_research_stage`), and 187-15 Task 2
  (`PanelSpec.fields`, 184-06's dependency). 187-03's `--apply` runs from 11:32Z under
  `indicagent-187-03-apply` (about 4 h; hold other compare-all runs). Todo 549 carries a finding
  that fixed-b may not be needed (step A pooled correlated arms; fresh 4,000-session H0 runs show
  size 4.3 to 4.9%); owner 2026-10-28: rerun step A cluster-robust first (unit `e17-step-a-rerun`, starts when the 187-03 apply ends). `tools/gate.py` runs the mechanical gate and holds the cross-session parity lock.
- **Research lane, 2026-10-29 (indicagent-1f; 187-12 to 187-14 landed, origin f39458854):**
  187-12 (typed-domain registry, `register_idea`, migrations 533 composition and 535 genesis rows,
  todo 459 closed), 187-13 (27 legacy cards are research_run attempts, 47 hand-ledger ideas are
  family candidates, `docs/research/research-ledger.md` generated by
  `scripts/research/render_research_ledger.py`, hand ledger frozen, migration 536; the nightly
  timer is INSTALLED BUT NOT ENABLED because the job commits to the diverged local main), 187-14
  (contribution kernels, migration 538 and 539, `subset_refit` attempts, `run_book` records the
  block). Next: 187-15 Task 1 and 3 (grammar), then 187-16 to 18 after the first feature family.
  E17: step A rerun pooled size 5.02% [4.66, 5.37], so v1 stands and fixed-b is not built (todo 549
  closed). Step B (pre-registered, one fresh 4,000-session StepM run) failed one gating cell,
  `s1_hostile` 89 of 1,000 against 74; pooled 5.34% passes; no selection is attested; todo 561
  (diagnostic 1 on fresh seeds: 5.17%; a 3,000-simulation run, unit `stepm-diag-561b`, is under
  way). `compare-all` on 11e0384a3: 16 equal, 4 pre_e17, exit 0. Todo 547: at the real panel length
  the current lag is fine at h = 5 (5.3% to 5.9%) and fails at h = 21 (11% to 12%); L + 3 (h - 1)
  is the best candidate; an owner-approved E17 amendment and a 1,000-simulation certification are
  next. A book over two or more families cannot run: `check_family_plant` refuses it (todo 562).
  Todos 558 and 559 are specified only in indicagent-47's inbox. Data lane: plan 191-20 done
  2026-10-29 (canonical 1d is Alpaca SIP primary from 2016, Tradier rows deleted, 1d re-derived,
  migration 537 live); D7: 1,273 of 1,502 names pass every required 1d check, the 229 holds are in
  `191-20-D7-HOLDS.tsv`. The family 2 and daily-family notice went to indicagent-47 to relay: those
  runs may start (holds excluded) once a research session picks them up.
- **Research (phase 183 done; 187 next):** todo 501 closed 2026-10-26 (317d61b69): S0 snapshots
  pin d2_rule_version, policy and verdict as-of, bar_integrity verdicts, per-symbol content
  digests and the D0 label inputs; evidence carries data_quality from the snapshot. The 501
  blocker for daily attempts 3/3b/4 is cleared; the build-first pause (owner 2026-09-27) still
  holds. Family 2's evidence run (187's gate) is approved for one run once plan 191-20's 1d re-derive lands (moved up from 191-25 by the owner 2026-10-27; the runner's import closure touches no file in plans 21-25). `build_panel` refuses any end past `alpha.validation.oos_start` (2025-12-24, write-once).

- **Pre-2016 IBKR 5m backfill (todo 534, P0 again, owner 2026-10-28):** 289 of 1,529 names hold any IBKR 5m; of 1,279 listed before 2016, 43 are complete, 217 partial, 1,019 none (about 9,200 name-years). Alpaca SIP covers all names only from 2016-01-01. The fetcher runs near continuously at 76 to 88 requests an hour (73 s median answer); `infra.backfill.fetch_concurrency` is 4 from 2026-10-28 (applies from the run starting about 15:47Z; expect about 175/h). Canonical 1d lags raw (1,317 names to 10-23) until plan 191-20's re-derive; raw 1d is complete through 10-27.
- **Ops, 2026-10-28:** `tools/gate.py` runs the mechanical gate with a cross-session parity lock; rolling service logs cleared (kept evidence under logs/); unit `e17-step-a-rerun` waits on the 187-03 apply; migration 530 (typed concept domains) and 531 (fetch_concurrency type) live; migration 526 breaks the integration baseline replay (3a).

- **Frozen and ended names (todo 519):** WBD, QRVO, CCO ended (merger or buyout); PSKY trades as
  SKYD on NYSE and IBKR re-served its history on a 0.979 scale. Parked as non-critical; the
  rebuild gate already skips stale names.

- **Other phases:** 185 done (53 plans); 186 at 25/29 (17 Task 2, 26, 27, 28 left; 186-14 open);
  189 and 190 are functionally done with stale ROADMAP boxes (189-09, 189-10, 189-11 verification
  items; 190-06/07 landed per their summaries).

- **Universe:** 1,529 active, all intraday scope (owner 2026-10-09); 1,502 `compute_eligible_1d`.
  Never deactivate a name (onboarding SOP rule 6).

- **Data freshness:** features and regimes stale since 2026-08-10 until the 186-26 rebuild; check
  `max(timestamp)` before citing freshness.

## Starting a new session

Read in order: this file -> `ROADMAP.md` (active milestone table) ->
`docs/plans/2026-09-26-unified-research-to-production-design.md` (sections 2, 16 and the section
for your work) -> `.planning/todos/PRIORITIES.md`. Then pick one lane; lanes run in parallel and
coordinate through cross-session messages before touching shared files.

## Paused 2026-10-30 (owner's usage limit; both lanes clean, all work on main)

Resume from `.planning/HANDOFF.json` (remaining_tasks, human_actions_pending). Data lane: the 1d feature
table is built for 1,314 names (186-26 stages 1 and 1b); next is the intraday audit report, then the next
stage from the pinned tree. Research lane: waits on the owner (todos 547 and 562).

Data lane update 2026-10-30 (evening): the full intraday sweep fails coverage_cache for all 1,529 names (todo 570: no writer
creates alpaca 1d ledger rows; a rebuild is queued behind the fetcher lock) and grid_parity for 144 (todo 569: volume
rounding of 1 to 2 shares, prices exact; owner decides the bound). The 229-name 14:30 grid re-derive is complete. No name
builds as the next 186-26 stage until both clear.

## Restart order (2026-10-29; two sessions only)

The server stays up through a reboot of the owner's PC: timers, the 5m backfill and the
`stepm-diag-561b` user unit keep running. Open exactly two sessions. Each works in its own
worktree off origin/main (`git worktree add --detach ../indicagent-<name> origin/main`, symlink
`.venv`, `.env`, `data`); neither commits from the shared checkout.

| Session | Lane | Order |
|---|---|---|
| A: data | phase 191, Alpaca nightly, IBKR fetch; `src/providers/`, `src/intelligence/bars/`, `services/bar_*`, phase 191 files | 1. Check `stepm-diag-561b` has exited, then `git reset --hard origin/main` in the shared checkout (its dirty files and 2 unpushed commits are backed up in `data/backups/worktree-salvage-20261029/` and already on origin). 2. Plan 191-21, then 22, then 23 (21 and 23 edit the rebuild import closure; 23 needs 22). 3. 186-26 launch only after 21 and 23 land and session B reports the 555/560 path-dependent check and review done. 4. Then the spin-off gap (todo 545 follow-up, M2) and the 229 D7 holds name by name (todo 557). |
| B: research | phase 187, 184, E17, family 2; `src/intelligence/research/`, `tests/unit/research/`, `.planning/phases/187-*`, `.planning/phases/184-*`, `research/specs/` | 1. Read the D7 notice and `191-20-D7-HOLDS.tsv`. 2. 555/560 path-dependent check and review (gates 186-26). 3. Todo 561 (step B failed s1_hostile) and 562 (multi-family plant gap). 4. Family 2 one owner-approved run, with the 187-name universe intersected with the D7 holds first. |

Rules for both: never run two backfills at once; the 5m backfill is a systemd timer, do not
start another; kill processes by PID only; do not edit modules a live fingerprinted run imports;
message the other session before touching a shared file. Lanes before 2026-10-29 (3a, 5b, 24,
47) are gone; their work is on origin/main.

Phases 184 and 188 have no directory yet; `gsd-sdk query phase.add` numbers from
`.planning/phases/`, so add or plan them by number, never through `phase.add` (CLAUDE.md).

## Decisions waiting on the owner

- Research lane (2026-10-30): the E17 daily statistic landed (`d2f3ff0b1`, flat-top kernel plus influence
  series; todo 547) and cut the daily battery from 40+ size failures to 3 marginal ones (gaussian
  `reversal_5_skip1` 71 of 1,000 against 67; the two momentum members in s1_hostile, S1 drift). Decide: certify
  the reversal members and book now and hold the rest, or hold the family until S1's drift is decided. The
  StepM attestation is complete (Step B v2 passed), so `select_books.py` is unblocked. Todo 562 (multi-family
  power plant) also waits on the owner.
- Research lane: (1) approve the E17 amendment for todo 547 (a horizon-tied lag, L + c (h - 1) for
  daily targets with h > 5, c = 3 to certify); (2) decide the multi-family power plant (todo 562)
  before the `generated_family` grammar; (3) enable the research-ledger render timer (`sudo systemctl
  enable --now indicagent-research-ledger-render.timer`) once local main is reconciled, or let the
  job commit from a scratch worktree off origin/main and push that one file; (4) todo 561: after the
  3,000-simulation diagnostic, a new pre-registered step B or a written call on the `s1_hostile` cell.
- Plan 20: confirm the Tradier deletion once the residue report exists (it also settles the todo
  537 item 2 basis restore). This is the only open owner call (the research restart was decided 2026-10-27; for E17 v2 the owner chose on 2026-10-28 to rerun step A cluster-robust before building fixed-b). The tooling is
  built ahead of the approval and reviewed twice (Task 2: `scripts/ops/bars/ops_tradier_delete.py`,
  migration 524, scratch-schema integration test; record `191-20-TASK2-BUILD.md`); nothing has
  run live. D-191-Q (owner 2026-10-27, todo 545): canonical 1d becomes Alpaca
  SIP primary from 2016 with IBKR fallback, IBKR before; the Alpaca 1d backfill, a full Alpaca vs
  Tradier comparison, daily rule d2-v4 and the policy rows land before Task 3's re-derive.
  Simplify pass 2026-10-27: every ohlcv_load row stays (lineage,
  like ohlcv_request), so only value rows go and the IBKR revision rows under Tradier loads stay
  by construction; the design doc carries the amendment. Task 3 must stop every
  1d consumer, not only the fetcher and bar_derivation, from the first batch to the 1d re-derive.

D-191-P done 2026-10-27 (migration 520 retirement, ba03e9ff7; plan file
`data/policy_plans/2026-10-26-d191p-5m-alpaca-primary.json`): live 5m policy is two defaults, IBKR
before 2016-01-04 and Alpaca then IBKR from it; 1,641 symbol rows retired. 267 names reselected
(44.5M bars changed) and their grid re-derived in full; the other 1,261 names had their stale
session-choice records rewritten by record-only shards (0 bar changes). Every name's 15m/1h grid
is current through 2026-10-26 (`indicagent-bar-derivation-grid`, 05:45 UTC, --changed-only, now
follows the Alpaca nightly; writing derivation runs serialize on a stage lock, e48ddbfb6). Final
5m selection gate exit 0: 1,529/1,529 series clean, n_canonical == n_selected == 311,503,335,
session_choices_unrecorded 0 (`logs/selection_gate_20261027T072705Z.json`). The research lane
(5b) was told 2026-10-27 about 08:28Z; the 5m snapshot and 186-26 are no longer held on D-191-P. 5b fires the family 2 run on a one-line notice from the data lane when plan 20's 1d re-derive lands; the notice lists, among family 2's 187-name US-session universe, every name with a pending span, a frozen hold or a D-191-Q arbitration hold.

Decided 2026-10-26 and queued for the data lane: D-191-A..L acknowledged (A: refuse a non-split
Alpaca raw write; L: count never-selected-kind slots apart from policy gaps); D-191-P canonical 5m
is Alpaca SIP primary from 2016-01-04, IBKR fallback, IBKR alone before (policy rows plus a
reselect after the Alpaca catch-up, before 186-26); todo 519 listing_end table and PSKY to SKYD;
family 2 gets one evidence run after 191-25 (moved to plan 20's re-derive 2026-10-27); todo 509 deletes the v2.x dashboard signal surface and
the ML batch chain (nothing worth keeping; regime HMM kernel stays). Migrations: this lane takes
518 and up (515-517 reserved by the research lane).

## Open items that are not verdicts

- Dashboard v3.5 cockpit closed 2026-10-27 (owner: a dashboard does not find edge). Six pages
  are served on :3000; Books stays an empty state until phase 188. Unscheduled refinements are
  listed in `docs/plans/2026-10-26-dashboard-v35-cockpit-design.md`.

- The midterm spec was committed 2026-10-01, before the 2026-11-03 election: its forward window
  (to 2027-05-03) is recorded in `docs/ideas/signal-political-policy-regime.md`; todo 483 records
  its result after 2027-05-03.

- Economic series (todo 480, 2026-10-01): `economic_series_observation` holds 10 FRED and 39 NY Fed
  series. Backfilled FRED availability times are assumed, not measured (THREEFYTP10 about a week
  early); todo 482 (deferred, gate: phase 184 B8) reloads them from ALFRED. No reader until B8.
  Owner decided 2026-10-01: long-history index levels are stored as context-only series (migration
  427: Yahoo S&P 500 from 1927 and Nasdaq 100 from 1985, FRED Nasdaq Composite from 1971); Nasdaq 100
  sources disagree on 2003-2005 closes (recorded in todo 480).

- Todo 248 (HMM per-symbol lookahead): walk-forward deployed 2026-08-12. Stored regime columns
  carry the todo 451 gate mask until the 186-26 rebuild; 186-13 made the HMM a registry kernel.
  HMM columns stay out of every family until the rebuild.

- Todo 372 (`Panel.sync_shift_null_p`): finding 1 fixed, lacks independent review; finding 2
  (`volume_z` diurnal detrending) untouched.

- N1 nonlinear combiner: structurally inconclusive; don't cite as pass or fail.
- Survivorship: every universe reads current state; phase 185 D0 bounds past verdicts. Forward
  capture (D8) was descoped by the owner 2026-09-26: few names in this universe delist, and the
  past cannot be fixed from IBKR.

## Delete-after list (disk housekeeping)

Disk is not tight (28% used, 2026-10-29), so none of this is urgent; it is here so safety copies
are removed on schedule and nothing protected is removed by accident. Everything under `data/` and
`logs/` is git-ignored.

| Path | Size | Delete when | Why it is kept until then |
|---|---|---|---|
| `data/backups/185-45` | 5.6 GB | after 2026-11-06 | dumps of the removed v2.x AI stack; `CLAUDE.md` keeps them until about that date (the git tag `archive/v2x-ai-stack-2026-10` stays) |
| `data/backups/191` | 3.2 GB | when the owner closes the Tradier work (plan 191-20 done 2026-10-29; D7 holds, todo 545, still open) | backup taken before the irreversible Tradier bar delete |
| `data/backups/185-38` | 142 MB | unknown: find its phase's retention rule first | an earlier phase's drop backup |
| `data/backups/worktree-salvage-20261029` | 1 MB | about 2026-11-12 | patches and a bundle from the removed 5b-t3, prev3 and shared-checkout work; the shared checkout was stale, its commits are on origin under other hashes |

Never delete: `logs/phase181` and `logs/phase179` (`repro_frozen` replays the frozen verdicts from
them), `logs/research/snapshots` and the step A and B evidence under `logs/research/` (`compare-all`
and the E17 records), `.venv`. Worktrees (`git worktree list`) are extra working folders of this one
repository: sessions create a detached one off `origin/main` to commit without touching other
sessions' uncommitted files, then remove it; `git worktree prune` clears entries whose folder is gone.

## Process pointers

- `.planning/todos/PRIORITIES.md` is the sole todo priority source.
- The research ledger is the sole construction-verdict source.
- Methodology changes go through `docs/plans/methodology-change-ledger.md`.

## Key decisions (load-bearing)

- `HMM_RANDOM_STATE = 42`: changing it invalidates every regime-derived output.
- Executable returns only, open to open: `panel.forward_returns` is the one target definition
  (UD-25); the `forward_returns` table is legacy until phase 186 drops it, and new code never reads it.

- `ON CONFLICT` for partial indexes on TimescaleDB: column list plus WHERE clause, not
  `ON CONSTRAINT`.

- Phase 190 batch history surface (190-01): `HistoryProvider` protocol + HistoryRequest /
  FetchBudget / NoDataVerdict / HistoryPage live in `src/providers/base.py`; DataProvider is
  byte-identical. `IBKRProvider.fetch_ohlcv` returns one caller-driven window plus resume
  point; `adjustment='split'` raises loudly on IBKR (ADJUSTED_LAST is now-anchored). Services/
  scripts/src cannot import a concrete provider leaf outside `src/providers/`
  (tests/unit/test_provider_leaf_boundary.py; at 190-04 the three fetcher-family entries
  stayed, now owned by the registry's ibkr entry rather than a factory seam).

- Phase 190 generalized fetcher (190-04): `_PROVIDER_REGISTRY` in the fetcher maps provider
  name to leaf factory + item-fetch hook + overlay loader; the loop dispatches strictly
  through `entry.fetch` per item's provider (an entry failure is that item's error outcome,
  never an IBKR fallback), budgets come from per-provider ProviderPlan (stall bound, retries,
  inter-item pause), and the dry-run TSV carries the provider column (190-06 parity delta 1).
  Adding a vendor is one registry entry plus a leaf module; multi-plane queueing (one run,
  several providers' candidates) is still future work.

- Phase 190 code-identity rename (190-05): the fetcher is `ohlcv_history_fetcher` /
  `OHLCVHistoryFetcher` in code and tests; every external identity stayed byte-identical
  under FROZEN (phase 190 decision) comments (FETCHER_LOCK_NAME, LOCK_HELD_MESSAGE, JOB,
  status-file path, unit filenames). A compatibility shim at the old
  ibkr_history_fetcher.py path keeps the live unit runnable until 190-06 installs the
  updated unit and deletes it. The log file does not move: BaseBatch derives it from the
  frozen JOB, so logs/ibkr_history_fetcher.log stays.

- Phase 190 two-tier ledger foundation (190-02): migration 464 applied live (ohlcv_coverage.provider,
  ohlcv_provider_head.timeframe nullable; ibkr label is the authoring fetch plane of a stored-state
  row, never a vendor provenance claim). Migration 465 (PK swaps + measured floor seeds) is committed
  UN-APPLIED: 190-06 applies it with the fetcher stopped, in the same shell breath as flipping the
  coverage writer's ON CONFLICT to (symbol, timeframe, provider); the boundary test and the
  conftest _COMMITTED_BUT_UNAPPLIED={465} entry pin that discipline until then.

- Phase 190 per-provider planner (190-03): `_fetch_queue.py` is provider-parameterized with
  ProviderPlan + load_provider_plan reading infra.<provider>.* under the split contract
  (planner inputs raise, leaf-native rate-limit window keeps its logged fallback); the queue's
  candidates, due reasons and visited checks are (provider, symbol, timeframe) triples that
  still accept the legacy pairs, so the unmodified fetcher kept draining through every commit
  boundary (back-to-back dry-run TSVs identical). The bar_source_policy gate authorizes
  primary-OR-fallback (derived rows and no-row pairs fall back to the default plane), which
  keeps the two open tradier-primary 1d rows with the ibkr fallback (MOD, QRVO) fetching via
  IBKR; 190-04 passes the plans and triples the fetcher side, and 190-06 activates
  record_head_per_tf when 465 applies.

- Corpus pipeline: `--compute-only` silently skips every symbol if `backfill_status` is empty;
  seed it first (query in `.planning/milestones/v3.4-STATE.md`, "Corpus Pipeline Gotcha").

## Accumulated Context

### Roadmap Evolution

- Phase 190 added: Provider history plane unification: one multi-provider fetcher, N leaves, two-tier ledger (design: docs/plans/2026-10-09-provider-history-plane-unification-design.md; rides with todo 526)
- Phase 189 edited: edited fields: depends_on
- Phase 189 added: IBKR history fetch consolidation: single fetcher, coverage ledger, priority queue replacing the nightly/bulk lease and lane scripts
