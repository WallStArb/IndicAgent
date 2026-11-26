# PRIORITIES.md decision log

**What this is:** durable reasoning behind `.planning/todos/PRIORITIES.md` that isn't obvious
from the current tier list alone — active multi-step sequencing decisions, process rules learned
the hard way, and pointers to where folded/superseded content actually lives now. This is not a
full audit trail: closed-todo history, superseded diagnoses, and dated correction narratives with
no forward reference value were pruned 2026-07-14 rather than archived — once a fix has shipped
and the code/commit/completed-todo-file is the record, restating the debugging path here added
weight without adding usable information. Keep this doc itself lean on the same principle: add an
entry only if someone doing future work would actually need it.

---

## Process rules learned this project

**A "Gate:" line written once at filing time rots.** Anything sitting in `deferred/` more than
~2 weeks should have its gate re-checked against live state before being cited as still-blocked,
not trusted at face value (found via todo 020, which cited a gate that had already cleared).

**Never bake a live-progress snapshot (percent complete, symbol count, ETA) into a static
planning doc.** It goes stale within hours and is a recurring source of drift. State only
"in progress" or "complete as of DATE" — point at STATE.md or a live query for current progress.

## The locked sequencing chain — rationale

**Decision (2026-07-10, project owner confirmed; reaffirmed 2026-07-11 twice; full detail:
`docs/plans/archive/2026-07-11-ic-quality-and-sign-symmetry-strategy.md`):** todos 093 → 091 → 097 → 094
→ [E1-vs-E2 A/B re-run] → 096 → 088 must run in this order, not in parallel or reordered by tier.

**Why:** 091, 097, and 094 all read or directly affect `ic_ci_lower`/`ic_ci_upper`, and 094
independently requires a full `ic_engine` re-run — sequencing 091 and 097 first means one corpus
re-run serves all three fixes instead of splitting across multiple, and 094's eligibility redesign
runs against the already-corrected CI and return-target measurement rather than the old one. 096
was inserted after 094 because its stride-bias finding (see below) directly informs 088's
censoring-vs-decay question. This chain is why 097 and 088 sit in P1/P2 tiers by effort despite
being just as blocking as the P0 rows — tier reflects independence/size, not exemption from order.

**096's fix, for reproducibility:** `_compute_ic_rolling_metrics` now uses a fixed subsampled-bar
window (`alpha.ic.sharpe_window_size_subsampled=100`, migration 230) instead of raw-bars÷stride,
removing a `sqrt(window_size_ratio)` deflation at long lookaheads. Threshold rescale shipped same
migration: `alpha.ensemble_ic.decay_threshold` 0.1→0.05, `alpha.ensemble.sharpe_floor` 0.05→0.025,
`alpha.feature_registry.min_ic_sharpe_default` 0.5→0.25. Verify: `python
scripts/analysis/ic_sharpe_stride_bias_check.py`.

**088 and 096 are separately-sequenced steps, not one item** — they were briefly merged in error
once (2026-07-12) and reverted; this is on record because it directly triggered Concept Registry's
build trigger (a governance gap letting distinct work get silently conflated).

## Standing diagnostics (re-run periodically, not one-time)

**Crowding proxy regression** (`scripts/analysis/crowding_proxy_regression.py`, todo 072):
baseline run against pre-143.1-fix `alpha_frames` found max R²=0.2674 at 1d/mid_bull, 0.003-0.09
at the primary 5m/15m strata — no crowding alarm at that baseline. Re-run each future corpus
epoch; see `docs/analysis/crowding-proxy-report.md` for the current number.

## Where folded content actually lives

**Concept Registry / Controlled Vocabulary / Stratification cluster (2026-07-13):** consolidated
from a scatter of 5 separate items (058, 105, 106, 076, 041) to exactly 3 top-level todos — 112
(Concept Registry), 110 (Controlled Vocabulary), 111 (Stratification & Classification). The
deferred/speculative content from 105, 106, 076, and 041 was folded directly into the design docs
they were forward-looking notes on, not kept as separate files:
- `concept-unified-registry.md` — regime_model domain seeding sequence (from 105/106)
- `stratification-dimension-unification.md` — new candidate dimensions + formalization revival
  note (from 076)
- `stratification-instrument-tag-calibrator.md` — tag taxonomy open question (from 041)

058 (Concept Registry MVP) stays in `completed/` as a frozen historical record only — it
duplicated 112's scope and was closed as a dedup, not because the work shipped (it hasn't).

## 2026-11-24: todo consolidation pass (batches 1 to 4 verified against live code)

Method: an independent read-only verifier per batch of 13 or 14 rows, each claim cited by commit or file and line; the lead's spot-check of every batch before applying; owner ideas are closed only with evidence of completion; rows touching the rebuild code key (`rebuild_code_key()`, 61 writer modules and the 13 kernel modules) are marked to land after the corpus rerun pin. Batches 1 to 3 landed (a3b351177, ea0dcba05, 53821d330) with 554 (2eedb8187), 309 (8706eeb31), 608 (cf7fa4a67, ce98761c3), 470 merged into 668 and 471 rewritten (1555239cb).

Batch 4 verdicts (P2 rows 460 456 457 560 437 516 498 454 589 597 606 568 598 443); applied 2026-11-24 for 498, 454, 460, 560, 516, 456, 568 and 457's merged text (443 and 606 rewrites left unapplied on the lead's instruction):
- Close: 498 (the `job_name` rename landed in 729870eda; Prometheus shows `job_completed_total` series), 454 (stage 2 adopted a $1M median dollar-volume floor in `docs/plans/2026-11-13-stage2-universe-preregistration.md`, so RCAT's thin era is excluded).
- Merge: 460 into 457 (its step 1 compared against IBKR's auction prints; the auction-print check moves into 457 on a Massive source); 560 into 588 item (e) (the NULL-volume path is deleted, 17cfe233b; the only open item is S0 supplying `volume_basis`).
- Rewrite: 516 (item 3 fixed in fe47d2f0a, item 2 obsolete; open: CTVA is held with no 1d bars or membership, a `spin_off` action type and a research-layer distribution event are needed before release), 456 (owner review of 445; part A moot because `name_set_5m` is read by no code and Alpaca commission is zero; open: part B multi-day horizons, an `ic_measure` question after todos 667 and 668), 568 (owner 2026-10-30; done except the reset follow-ups that wait on the owner's freeze lift; fix the stale `test_spec_hashes_pinned` docstring), 443 (exporter half done; open: cut the idle-in-transaction timeout to 10 minutes after the corpus rerun ends), 606 (item 0 done in 8f16538be; open: a CI reconciliation test of stored columns against concept rows, test-only to avoid the closure).
- Keep: 457 (P3, blocked: no slot-subset mask or keep gate in the runner), 437 (P2; a P1 candidate the moment a book is certified, because promotion needs positive net expectation and no spread-cost code exists: Corwin-Schultz and Roll kernels exist, Abdi-Ranaldo does not), 589 (P3; edits `bulk_load.py`, inside the closure, so after the rerun), 597 (P2; the grid derivation does not scrub the new 5m and derived bars, due before the first intraday forward span), 598 (P3; the nightly does not call `setup_service_logging`).
- Leftovers to fix: CLAUDE.md line 117 says `job_completed_total{job, status}` and should say `job_name`; the `indicagent-alpaca-nightly.timer` description still names the deleted IBKR backfill; CTVA (an S&P 500 name) is absent from 1d canonical and from membership and should be disclosed with the rerun.

Batch 5 (P2: 612 038 039 420 504 513 646) applied 2026-11-24: 612 and 646 closed, 039 merged into 038, 038, 420, 504 and 513 rewritten (513 to P2); 512, 520 and 522 are report only and untouched.

Deferred todos: all 19 files re-checked 2026-11-24 (D1 c4ed345d8, D2 afc1c966a, D3 b6ec0a299). Kept: 020 026 135 246 263 344 380 414 415 480 482 527 565 567 596 (527, 565, 567 and 596 wait on the corpus rerun; 596 is P2 now). Closed: 452 497 525 535 (535 item 52 is todo 672). Still to do: a proposed P0 and P1 ordering for the lead.

Handoff 2026-11-24 (indicagent-3d): done and pushed: consolidation batches 1 to 5, todos 554, 309, 608, 661, 662, 666 and 513 closed or landed, 667 to 671 filed, the guarded launchers (`scripts/ops/`), the family order note (`docs/plans/2026-11-24-family-order-after-1d-corpus.md`) and the compute lane review (`docs/plans/archive/2026-11-24-compute-lane-review.md`). Next step for the next session: verify the remaining deferred todos (the first 13 were applied in c4ed345d8; the list is in `PRIORITIES.md`) (`.planning/todos/deferred/`, gates re-checked against live state, one read-only Opus verifier per batch of about 13, spot-check, one docs commit per batch, same guardrails as the memory note `project_todo_consolidation_pass_2026_11_24`), then propose a P0 and P1 ordering to the lead. The lead (indicagent-ee) owns the heavy-slot order: block 2 rerun to IDENTICAL, corpus pilot, family 10 counted runs, stage_1d `--through feature_complete`; the 32,194 stale feature_vectors rows from run a4f6ad40 are cleared by the lead before `--new-run`.

P0 and P1 ordering 2026-11-24 (indicagent-94, for the lead): the order is 584 (pilot, four family 10 runs, `stage_1d`), then the unit install for 649 (before the Massive lapse about 2026-12-10), the owner call on 600, 669 (research route, after the family 10 runs and before the pin of any counted corpus test), 588 part C and item (e), then 636 and 471. Everything that reads rebuilt columns (558, 461, 466, 583, 571, 435, 441, 423, 440, 601, 603, 439 part 2) waits for the rerun; 614's module splits wait for `stage_1d`. Proposals to the lead, not applied: raise 670 and 671 to P1 (IC waits on them); move 609 into 584 (only the rerun is left); demote 615, 622, 624, 601, 603 and 442 to P2 or P3 (materiality rule 2026-11-20; no blocker on the counted path); mark 631 (P3) and 627 and 634 (P2) as such in their tables, since they sit under the P1 headings. Recommended assignments for idle sessions: the 649 timer install, the docs-only 461 and 466 annotations, and the 571 and 583 preparation (backup and measurement queries, no writes) for the day the rerun lands.

Rulings applied 2026-11-24 (lead): 670 and 671 raised to P1 (IC waits on them; behind 669); 609 folded into 584; 615, 622, 624 and 601 demoted to P3 under the 2026-11-20 materiality rule; 603 and 442 stay (owner-originated, tier changes only with the owner); 631 moved under P3 and 627 and 634 under P2. The 649 timer install stays an owner step.

Specs for todos 670 and 671 written 2026-11-24 (indicagent-94, design only). 670 is a script (`scripts/research/stepm_sweep_scale_check.py`) that runs the shipped `stepm` unchanged on the recorded series plus about 1,108 mean-zero, overlap-structured, factor-correlated null cells at three effective breadths (8, 50, all independent), 8 replicates each, and reports whether `reversal_21` stays selected; estimated 0.7 to 2.3 hours at 4 workers, no `repro_frozen` gate unless a vectorized draw path in `stepm.py` is later wanted. 671 is a pure per-session rank-IC function in `src/intelligence/measure/` plus one S6 method (`record_sweep_block`) on `PostgresLedger` that writes each cell as a `research_run` evidence attempt with its series in one transaction per (tf, horizon) block, called by a new oneshot `ic_sweep_recorder`; the ledger edit needs `repro_frozen` bit-identical and a methodology-ledger line. Open for the lead: the feature-domain concept lookup in the ledger, the sign convention of a cell's series, and whether `n_looks` is a go or no-go on batch size.

2026-11-26 Musk step 1 pass over the pending todos (indicagent-26, ruled by the lead, indicagent-17): 477 (pivot detection repeated per row across the structure kernels, about 10 percent of `compute_batch` time; fix would be a shared derived input in `contract/derived_inputs.py`, bit-identical; source plan 186-15 review) and 321 (one shared `FeatureFactoryConfig` test builder; do it with the next field-adding change; source a `/simplify` review) deleted; 309 and 465 merged into 601; 582 moved to deferred (gate: before any feed reactivation); 324 kept because its source is a user question; 331, 394, 504, 509 and 531 are small P3 rows with their verified facts in the row; 443 keeps its live state (idle-in-transaction timeout still 1h). 383 (GSD upstream feedback) and 509's `shadow_registry` call wait on the owner (owner-action-sheet item 8).

2026-11-26 IC-measure readiness memo for the first 1d IC run (indicagent-26, read-only, no IC or return read; the lead decides). Requirement first (Musk step 1): the next step on the critical path after the pilot and `stage_1d` is the 1d IC measure at the scope-1d pin, so only what that run needs is decided now.
- 666 (price-only targets) is decided and its file is closed: ledger 2026-11-24e keeps price-only targets as a screening measure with three disclosures (the straddle table of 1, 2, 5 and 10 percent of rows at h 1, 2, 5 and 10; `dividend_yield`, `size_proxy` and linked columns flagged as read on price-only targets; any family a cell prompts declares `panel.total_return`), and 2026-11-24f withdraws its "not a counted look" sentence in favour of E21. Both later memos (2026-11-24 and 2026-11-25) recommend A, no code, and reopen to C only on a mechanical trigger (a yield-linked column survives StepM, or the first report's straddle share exceeds the table). Nothing is left to decide on 666; the run's report carries the disclosures (`docs/operations/corpus-first-run-disclosures.md` item 3.4).
- 471 settings: `alpha.ic.feature_block_columns` = 16 (already live) and `ic_tfs` = 1d only. Arithmetic check: 5,609 sessions x 12,857 names x 16 x 8 bytes is 9.2 GB for a feature block, plus 2.3 GB of targets and about 3 GB of long form, so about 15 GB on 59 GiB. No 1h, 15m or 5m. The 471 Done-when dry run (25 pilot names at widths 4, 8, 16, 32, peak RSS) is a confirmation of an arithmetic ruling, not a gate: recommend running width 16 only (32 if the heavy slot is free), after `stage_1d`, with no heavy job live. The pilot is DB-heavy (0.1 GiB headroom), so nothing from this memo runs before it ends.
- 667 (time chunks): not needed. At 1d the strided gather is 4.1 M rows (stride 5) and 0.5 GB at width 16 (2.1 M rows, 0.3 GB at h 10), so the dense 1d stack fits. It stays a prerequisite of the scope-all pin only; the P2 row is correct.
- 668 (checkpoint grain): already built and closed (cell spool, `services/ic_measure_spool.py`, closure 2026-11-24 by indicagent-fb); a kill resumes from finished cells. Nothing to do.
- Wall time (estimate, not measured at this universe): the only record is a 7-minute, 925-name 1d run (2026-09-30) with the digest pass about 40 percent of it; by the linear scaling in todo 668 the digest pass alone is about 1.5 hours at 12,857 names, so expect roughly 2 to 3 hours for the 1d unit (the pooled rank IC and bootstrap scale with the strided N of 4.1 M, not linearly with names). Run it as one guarded heavy job at 4 workers with the DIMM watchdog.
- Before the run is created (the item this memo adds): ledger 2026-11-24f says a first IC pass is ledgered with its cell count before it runs, and it says the `ic_measure`, `d19_bound` and `canary` steps wait for todos 670 and 671. Both are now on main (639c244b1), so `stage_1d` through `feature_complete` stays the pilot's stop point and the IC pass needs its own ledger entry (cell count 2 attempts x measured cells x 4 horizons, with the correction of 2026-11-24i, and the three disclosures) before the chain step is released. The lead writes it; the todos 670 and 671 close after the 2026-11-25c ledger confirmation.
Recommendation: no code before the first 1d IC run; write the ledger entry with the cell count, run the unit once, then decide the scope-all pin from measured numbers (667 only then).

