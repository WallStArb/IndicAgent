# Next counted family after the daily residual run

**Status:** Recommendation, 2026-11-22, for the lead (indicagent-bd). Docs only; no corpus reads, no edits under `src/intelligence/research/` or `statistics/`. No real-data number exists for any family here.
**Outcome (2026-11-22):** the lead accepted the order H-C, family 9, family 10 and confirmed H-C under the E21 lift (ledger). Todo 635 is closed. Family 9's kernel landed unregistered (42f20c330); its spec, battery and close member input are parked as todo 653 because a member receives only S1 residual returns, and the close input edits `runner.member_input` and `_member_fn`, which are inside every battery code key and imported by the live run.
**Decision:** run H-C seasonality next (`research/specs/seasonality_h5.yaml`, then the core spec). It needs no build and its E17 pass is bound. After it, build family 9 (52-week high) as the next new family.

## Scope and rules applied

- Eligible now means a price-derived 1d family that reads canonical 1d and `universe_membership` through the panel. The E21 lift (ledger 2026-11-22) covers exactly that class. Feature-vector and intraday families still need their own gate, so H-B (stored columns), family 10's stored intraday members and the 5m families are out of this ranking.
- Looks are series added to the E18 selection universe: members times horizons times panels. All candidates are h = 5; h = 21 waits on the horizon-tied HAC lag (todo 547).
- Battery cost is the E17 pass a family needs before the runner admits it (`runner.static_gate` with `require_pass`, which calls `battery_pass.require`). A pass binds to `battery_code_key`, the import closure of the battery module, the family module and the S1 entries, plus the runner, snapshot and spec statistic functions. An edit to any module in that closure stales the pass.
- The run in flight (daily_residual_h5, pid 130613) imports the research modules `families/daily_residual`, `families/common`, `portfolio`, `timing` and the runner. Nothing below touches those until it finishes.

## Verified today

Run read-only on `origin/main` at ae309c4cf with `runner.static_gate(spec, require_pass=True)`: all four specs (`daily_residual_h5`, `daily_residual_h5_core`, `seasonality_h5`, `seasonality_h5_core`) return a gate, none is refused. The seasonality record is `research/battery_passes/seasonality_2026-11-21.json` (code key ae9ff30d, rebound after A3 and A4). The PRIORITIES row for todo 635 still says no seasonality battery exists; it is stale; the record has no failures, so the lead can close 635 after checking its own done-when list.

## Ranking

| Rank | Family | Hypothesis | Looks | Build | E17 pass | Code-key coupling |
|---|---|---|---|---|---|---|
| 1 | H-C seasonality | A name's same-calendar-month residual return in the past 5 years predicts this month's (Heston and Sadka 2008; Keloharju, Linnainmaa and Nyberg 2016), plus the other-months contrast with sign -1 | 4 (2 members, 2 panels) | none | bound, 2026-11-21, gate passes | imports `daily_residual` (`_daily`, `_place`) and the daily battery: any edit to either stales it |
| 2 | Family 9, 52-week high | Price near its 252-session high continues (George and Hwang 2004), pinned positive against a seen opposite-sign corpus look | 2 (1 member, 2 panels) | one kernel `high_distance` in a new module, a spec, a battery cell | new pass needed | new modules only; touches nothing existing if the battery is a new module |
| 3 | Family 10, volume shock | Volume shocks orthogonal to the same-session return predict returns (high-volume premium), 50 and 5 session windows | 4 (2 members, 2 panels) | two kernels in a new `volume_shock` module, a spec, a battery | new pass needed | new modules only |
| 4 | Industry momentum (todo 441 remainder) | Industry membership carries information the S1 sector residual removes | 3 at h5 | kernel, classification join, no prereg yet | new pass needed | needs the classification read in the panel, which is shared code |
| 5 | H-A, information discreteness (M3 re-add) | Continuous winners continue, discrete winners reverse (Da, Gurun and Warachka 2014) | 2 | spec and battery edits to the daily residual family | already failed pooled; A4 dropped it | edits the daily residual closure, which stales both the daily residual and seasonality passes |

### 1. H-C seasonality

- Panel: `universe_membership` and `universe_membership_core`, S1 vintage 1 residuals, total-return prices, scored from 2009-03-02 under the 1d lift scope. Reads the daily panels only.
- Cost: no battery work. Launch effort is the same command as the daily run (`scripts/research/run_spec.py`), twice (primary, then core), each counted at start. Run time is not measured here; it is a one-heavy-job slot, so it waits for pid 130613.
- Open before launch: the lift names the daily residual run, "then later families of the same kind". The lead confirms in one ledger line that H-C is of the same kind and spends 4 looks (E23 declared them). That is the only gate item.
- Seen-data disclosure: calendar-month effects overlap the other calendar families (5 and 6) only as disclosure; no recorded null.
- Why first: zero build, the shortest path to a counted test, the only item whose full gate list is already green.

### 2. Family 9, 52-week high

- Panel: 1d with `panel.total_return`. Prereg: `docs/plans/2026-11-15-family9-52week-high-prereg-draft.md`, adopted as E26.
- Cost: one pure kernel with unit tests (sign, window edge, 240-of-252 rule, split-rescale invariance, causality probe), one spec, one battery cell set with the B2 size check. The pooled replication on two seed bases is hours of heavy compute, as the daily residual family needed.
- Open: todo 610, the 2003 to 2007 close convention, touches the first 252-session windows. The prereg allows reporting with and without those windows if the witness is unresolved.
- Looks: 2. The smallest add of any new family, and StepM prices its overlap with residual momentum.
- Effort to launch: correction after the build started: the kernel is a new module, but the member needs a close input, so the runner and spec change after the counted runs (todo 653). This is the work to start while the daily run occupies the heavy slot, in a detached worktree.

### 3. Family 10, volume shock

- Panel: 1d price and share volume. Prereg: `docs/plans/2026-11-15-family10-volume-shock-prereg-draft.md`, adopted as E24.
- Cost: two kernels, a spec, a battery. Extra gate: no NULL volume in the tradeable view over the span (todo 563, expected cleared by step 7, to verify) and the volume basis guard (todo 560). Massive is the only volume source inside the discovery span, so no window crosses the vendor seam.
- Looks: 4. More looks and more gates than family 9 for a weaker prior, so it follows it.

### 4. Industry momentum

- Needs the point-in-time classification joined to dead names, which the stage 2 docs do not state. It has no adopted prereg or spec, so it needs a registration, a kernel, a battery and a classification check before any launch. Looks: 3. Its sector lead-lag leg is the 5m or 15m family 3 and stays out.

### 5. H-A re-add

- Dropped by A4 after failing the pooled battery. Re-adding it edits the daily residual family and its battery, which stales the daily residual and seasonality records and would void the run in progress. Not before the daily run and H-C are counted; parked, not retired.

### Not ranked here

- H-B low-risk (MAX, residual volatility, beta): reads stored feature columns from the corpus rerun, so it is a feature family and stays gated.
- Dividend month premium: monthly horizon waits on todo 547 and covered names only.
- Survivorship measured: a disclosure that rides on the first family; adds no selection look.
- `reversal_21` replication: retired as a phrase (ledger 2026-11-23b). R-1 is a non-gating sub-period disclosure of the recorded runs and R-2 is the forward confirmation at book freeze; neither is a new family.

## Recommendation

Run H-C seasonality after the daily residual run frees the heavy slot. While the slot is busy, build family 9 in a detached worktree off `origin/main`, with its kernel and battery in new modules only, so no existing record goes stale. Start family 10 after family 9's pass is bound. Hold H-A and industry momentum.

Order: (1) lead ledger line confirming H-C under the lift, (2) H-C primary then core, (3) family 9 build and battery, (4) family 9 run, (5) family 10.

## Fixes this surfaced

- Todo 635 is closed (c360327c1).
- Todo 634 (session dates in the book and power paths) does not gate H-C's family run, only a book containing an H-C member.
