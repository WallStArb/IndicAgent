# Path to the first counted test (lead execution plan)

Author: indicagent-16 (desk lead), 2026-11-03
Informed by: todo 584 manifest (D1-D6, done-when), STATE.md "Decisions waiting on the owner", ROADMAP 186/184, lead brief memory

Status: operative. The lead keeps it current; workers execute the tasks the lead assigns from it.

**Goal:** the first hypothesis test on real data that the research runner counts, on a corpus
that passes the 584 gates, under a written universe and vintage the owner has approved.

**Shape:** a strict chain of four gates (584 landed -> pilot green -> rerun complete -> clean-data
lift) with three side lanes (data gaps, decisions, preregistration) that must be finished by the
gate they feed. Lead plans, rules and verifies; Sonnet worker sessions execute; one worker per
shared file set.

## Global constraints

- One pin move, one rerun: every stored-value change lands before the pin moves; anything found
  after waits for the following rerun (584 Decision).
- Nothing launches on a red gate (D3). Partial K shards are never summarized.
- Every code landing: /simplify, /review, `pytest tests/unit/ -n auto` exit code read from a file,
  golden regen as its own commit first, the 584 row rides the code commit, path-scoped commits, no
  attribution, never amend.
- No real-data hypothesis test until the owner lifts the clean-data rule (owner 2026-10-30).
- Fit validity decides K, never returns (D6). Costs never enter a test statistic (E15-E18).

## Review focus (failure modes no single task's tests catch)

1. Pin moves with an item still open: the rerun stores the old value silently. Gate: the lead
   checks every 584 row reads "landed" and `git log` matches before tagging the pin.
2. 1d rerun launched before todo 566's 71 held names are fixed: those names stay short, nobody
   notices. Gate: 566 closed is a precondition of task 5.
3. The universe drifts between the rerun and the test (new listings, holds released): the test's
   StepM universe no longer matches the data. Gate: task 7 freezes the universe by id list and
   date, and task 9's spec cites it by hash.
4. Looks counted against the wrong vintage: earlier looks inflate the multiple-testing burden or
   are wrongly forgiven. Gate: the owner's vintage ruling is recorded in the methodology-change
   ledger before task 9 runs.
5. A worker edits a shared file another worker owns: lost hunks or a broken suite at HEAD. Gate:
   assignments name file sets; the lead re-verifies `git status` on every landing report.

---

### Task 1: 584 remaining items (worker: indicagent-3a)

Files: `src/intelligence/features/kernels/smc.py`, `feature_factory.py`, `schemas.py`, kernel
modules, `contract/registry.py`, `services/backfill_feature_factory.py`,
`services/feature_vector_pipeline.py`, `production/migrations/`, the 584 row.

- [ ] 1a. /simplify gate debt over item 6 (`1f917b6ed^..47f35b440`).
- [ ] 1b. Item 6c: retire `sweep_detected` (rate 0.997-1.000 at 15m/1h, lead measurement) and drop
      the unneeded `_is_valid_atr` gate in `_compute_liquidity_sweeps`; report other smc kernels
      with the same unneeded gate.
- [ ] 1c. Item 8 add-list wiring, one landing, per the canonical checklist in the 584 row (move
      `_item8_staging/` into `kernels/` first; nine config fields; migration 559; v2 column count
      314 -> 324 minus retired accounting; residual.py F401).
- [ ] 1d. Item 3 after task 2: per-tf `feature.hmm.n_components.<tf>` APR migration with the K the
      rule chose, `hmm_vol_prob_elevated` retired, methodology-change-ledger entry with the table.
- [ ] 1e. Row 4 flipped to landed; done-when 1 checked item by item.

Exit: every 584 row reads landed; full unit suite green at HEAD; the lead has verified each
landing on origin/main.

### Task 2: K rules (lead)

- [ ] When the watcher reports all four lanes done, run `--summarize data/scratch/583-k-sweep-2/*.jsonl`.
- [ ] Report the per-tf refusal-rule K and any |dK| > 1 against BIC to the owner, then append to
      the 583 row. Hand the K table to task 1d.

### Task 3: data gaps that must close before the 1d rerun (worker: indicagent-ab)

- [ ] Todo 566: the 71 held names whose canonical 1d lacks bars raw holds; fixed in selection, not
      by hand, `ops_selection_gate.py --compare` clean.
- [ ] Confirm the 229 D7-hold names and the 16 recent listings enter the rerun from their proven
      span (D4, item 11).

- [ ] Split recovery (2026-11-04 entity audit): pre-2016 IBKR named 1d misses old splits (316 of
      503 pre-2016 jumps sit at a split ratio; `corporate_action` held one row), breaking the stated
      invariant that stored equity bars are split-adjusted. Confirmed splits become `corporate_action`
      rows (witness 1: named vs `smart_adjusted` ratio break; witness 2, independent of IBKR: Yahoo
      split history); the daily rule applies them; raw is untouched; re-derive; D7. The same check
      runs on IBKR 5m pre-2016. This gates the pin: every 1d kernel computes on canonical.
- [ ] Entity continuity: 63 names whose canonical starts before the listed entity existed (ticker
      reuse, shells, OTC pre-listing). Owner rules per class; fixes go through policy rows or excused
      spans, never raw deletion.

Exit: 566 closed, splits recovered and D7 clean on the recovered names, entity spans ruled; the
rerun's name list is generated, not typed.

### Task 4: pin move and pilot (worker: 3a after task 1, or a fresh session)

- [ ] Lead tags the pin after the review-focus 1 check.
- [ ] Pilot chunk on the D3 set (~40 names, four timeframes) at the pin; gates G1-G5.
- [ ] Recalibrate from pilot evidence only: the two D3 tolerances (APR, migration 557 keys) and
      `feature.ctf.vwap_window` (6b: per-tf sign-flip rate). Any recalibration is an APR write
      with provenance, not a code edit, so the pin does not move.

Exit: G1-G5 green on every timeframe (done-when 2), report filed in the 584 row.

### Task 5: corpus rerun (worker: same as task 4)

- [ ] 1d first (source-complete; does not wait for todo 534), then intraday stage at the same pin.
      Intraday names with pre-2016 5m still arriving get their history re-derived incrementally
      later; that is not a second pin.
- [ ] Kill-and-resume only with the identical command; never edit an imported module while live.

Exit: 186-26 complete on all timeframes (owner restart condition 1).

### Task 6: swap and stores (worker: same)

- [ ] 186-27 close-out and name swap (D-34), unit-by-unit provenance verification.
- [ ] Todo 571 concept-layer reset through `ConceptRegistryService`, then 186-28 fresh IC writer.

### Task 7: written universe (lead drafts, owner approves)

- [ ] One file: the frozen id list, its as-of date, inclusion rules (proven span, holds, recent
      listings), its sha256. Point-in-time membership rules, not today's list projected back.
- [ ] Survivorship statement: what the universe cannot see (names delisted before capture), and
      which tests that biases.

### Task 8: S0 readiness check (read-only reader, run now)

- [ ] Can a 1d-only family run through S0 -> S8 on the rebuilt table without phase 184 (multi-tf
      S0)? Name the exact blocker if not. This decides whether 184 is on the critical path for the
      first test or only for intraday families.

### Task 9: first research queue preregistration (lead)

- [ ] Draft into the research ledger: the first families (ideas lane order: 4, 9, 11), each with
      hypothesis, spec, target horizon, StepM universe, look count, and the stop rule, frozen
      before the data exists.
- [ ] Vintage recommendation with rationale for the owner (E18).

Answer (2026-11-03, read-only reader, verified by the lead): it depends on what the family
reads. S0 reads prices only (`snapshot.py` from `market_data_ohlcv_tradeable`), and
`PanelSpec.fields` admits only high, low and sector_pit (`spec.py:89`). Nothing in the runner
imports `feature_inputs.py`. A price-derived 1d family (`research/specs/daily_residual_h5.yaml`
pattern) runs today; any family that reads stored feature columns needs task 10.

### Task 10: phase 184 wiring wave (worker: one session, research files only)

The gate (187-08/09/10, 187-15 Task 2) has landed, so this starts now, in parallel with task 1:
no file overlap (`src/intelligence/research/` only). Order: 184-06 -> 05 and 07 -> 08 -> 09 -> 10,
each with `repro_frozen` bit-identical; `tools/gate.py --compare-all` (hours, locked) runs once after
184-10 for the whole wave, not per plan. Executors work in detached worktrees off origin/main.
Landed: 184-06 (c6ac44aa6), 184-07 (37368678d), 184-08 (3295e6902, migration 564). Executors
self-review their own diffs, so after 184-10 one independent /code-review covers the whole wave
(06-10) alongside the compare-all run. A plan-checker pass against today's code comes first
(the plans predate 584; 184-08 still names migration 526), and the lead edits the plans before
execution. 184-12's dry S0 build runs after 186-27.

Landed 2026-11-04: 184-05 (9ceb891b6, battery 6/13 certificates), 184-09 (1e2bd5584), 184-10
(2e2ec9487); wave gate PASSED (logs/gate/20261104T112922Z_e1cca6456): unit suite, repro_frozen
bit-identical, compare-all. compare-all replays completed evidence runs, and `research_run` is empty
since the 10-30 reset, so it replayed zero runs: vacuous until real runs exist; the wave's parity
evidence is the suite plus repro_frozen. The independent wave review found admission holes: todo
588 (refuse first, then earn admission back by battery cells; 184-12's dry build is its part C).

Exit: a spec with a stored feature member runs through S0 -> S8 on a synthetic panel, and the
frozen verdicts reproduce bit-identically.

### Owner decisions (lead brings each with a recommendation)

- Price-only families before the feature corpus: restart condition 1 (186-26 complete) concerns
  features, which a price-derived family never reads. Lead recommendation: lift the clean-data
  rule for price-derived 1d families once conditions 2-4 hold (1d gaps per 566, written universe,
  vintage). That puts a counted test ahead of the rerun. Its looks count in the same vintage.

- Vintage question (E18), before task 9 is frozen.
- Clean-data lift, after task 6 and task 7.
- E17 horizon-tied lag amendment (todo 547) and the multi-family plant (todo 562), before the
  family that needs them.

## Critical path

Feature families: task 1 -> pin -> task 4 -> task 5 (needs task 3) -> task 6 -> owner lift (needs
task 7) -> counted test (needs tasks 9 and 10). Price-derived 1d family, if the owner takes the
recommendation: task 3 (566) + task 7 + vintage -> counted test, with no wait on the rerun.
Tasks 2, 3, 7, 9 and 10 run now, in parallel with task 1.
