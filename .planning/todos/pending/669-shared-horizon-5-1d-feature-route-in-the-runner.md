---
status: pending
priority: P1
filed: 2026-11-24
source: indicagent-3d family-order note (docs/plans/2026-11-24-family-order-after-1d-corpus.md), lead ruling 2026-11-24
---

# A horizon-5 1d stored-feature route in the research runner, with new persistent battery cells

## What

No corpus family can run as registered. The runner admits feature input members only at horizon 1, equal weight, in one family and never beside residual-return members (`runner._check_supported_subset`, `_check_input_mix`; todo 588 item m3). The certified routes are feature 1h to 1d, feature 15m to 1d and `rk_high_dist` 126 1d to 1d, all at horizon 1 (`null_battery_persistent._REPORT_PASSING`). No stored 1d to 1d feature route is certified, and every family since E23 is at horizon 5. Every corpus family (H-B low risk, `corpus_family`, market-residual reversion, regime variants) therefore waits on one shared build.

## Scope

One route: stored 1d feature members at horizon 5 through the runner, with new persistent battery cells (E17) bound by `bind_battery_pass.py`. No new family and no counted look. Gates: this edits `src/intelligence/research`, so `repro_frozen` must report bit-identical (or a recorded methodology-change entry), the existing battery pass records are rebound in the same commit if their code key moves, an independent review, and the suite by exit code.

## Sequence

Behind the four family 10 counted runs and the StepM read on 16 series. It lands after the corpus pilot and before the pin of any counted corpus test. It edits research code, so it never runs while a counted run is live (a live run imports it; `code_content_key`).

## Design ruling 2026-11-24 (lead, indicagent-ef) and the read behind it (indicagent-fb)

Ruling: design B. The statistic is fixed first (the book-arm HAC lag scales with weight persistence and with the target overlap together), with a methodology-change-ledger entry, `repro_frozen` bit-identical or recorded, and every battery pass record rebound; the horizon-5 1d feature certificate and its cells follow on the fixed statistic. Design A (a narrow certificate with a memory cap) only if the member check below shows short memory is enough; it does not (see the table), so A is not planned.

One item, not three: the HAC-lag work of todos 547 (horizon-tied lag for overlapping targets, the part still open there) and 586 (lag that does not scale with weight persistence; the ten failing gating cells) is part of this item. 547 keeps its separate owner decision on the reversal members and the S1-drift hold; 586 closes when its ten cells hold under the fixed statistic. They stay as their own files for history and their gates, and this todo carries the build.

Read (runner.py, `null_battery_persistent.py`, no corpus compute):
- `runner._check_supported_subset` (line 516) refuses `horizon != 1`, any combiner but equal weight and any horizon rule; `_check_input_mix` (line 582) is todo 588 m3 and separate. Admission is `null_battery_persistent.admit` against `PASSING_CERTIFICATES`, matched on every discrete field including `horizon`; the only passing routes are feature 1h to 1d, feature 15m to 1d and `rk_high_dist` 126 1d to 1d, all horizon 1.
- No stored 1d feature to 1d book route passes at horizon 1 either: `f1d_tau60`, `f1d_tau200`, `f1d_static_tau200` fail, and `f1d_s5_tau200` fails (70 of 1,000 at 0.05 against a bound of 67), so smoothing 5 left the passing list (todo 586). Horizon 5 adds target overlap on top, and the cells need `overlap_sessions = horizon - 1` (`null_battery_persistent.py:662`), so the existing cells cannot be reused.
- The daily residual families already run at horizon 5, so the book path handles it; the horizon-1 limit is in the input-member checks and the certificates.

## Member check 2026-11-24 (declared memory in bars, registry under the stored APR config, read-only)

`feature_vectors` has 307 output columns; 282 are stored and applicable at 1d. Declared memory is `registry.effective_memory_bars` (what `_member_memory` verifies and the certificate bounds with `source_memory_bars_max`).

| Declared memory (bars) | Columns |
|---|---|
| path dependent: refused for members (no finite memory) | 45 |
| 0 and genuinely memoryless (calendar 20, bar shape 5, canaries 5, range_to_close 1) | 31 |
| 0 but a builder-windowed pass-through (see below) | 21 |
| 1 to 20 | 24 |
| 21 to 63 | 44 |
| 64 to 126 | 6 |
| above 126 | 111 |

At or under 20 bars: 55 columns, of which only 24 have a finite positive memory, and the 31 memoryless ones are calendar, bar-shape and canary columns, not hypothesis members. Above 20: 161 columns (44 + 6 + 111) plus the 21 pass-through ones. So most of the 1d family is long memory: the narrow certificate (design A) would admit only the short-memory minority.

The named stage 2 members:

| Family | Column | Declared memory | True builder window |
|---|---|---|---|
| H-B low risk | `max_daily_return` | 0 (distribution_pass_through) | 21 (`feature.max_daily_return.window`) |
| H-B low risk | `idiosyncratic_volatility` | 0 (market_residual_pass_through) | 21 |
| H-B low risk | `equity_beta_z` | 0 (macro_pass_through) | beta window 60 and z window 252 |
| market-residual reversion | `market_residual_z` | 0 | 252 |
| market-residual reversion | `market_residual_lag1_acf` | 0 | 63 |
| size | `size_proxy` | 63 | 63 |
| momentum | `momentum_z_mid`, `momentum_z_slow` | 272, 312 | same |
| `corpus_family` | every guard-passing column | the table above | |

Two findings for the build:
1. None of the eight named members is at or under 20 bars by true window: the two shortest, `max_daily_return` and `idiosyncratic_volatility`, are 21, and the rest are 60 to 312. A tau-20 cap excludes the whole named set.
2. The declared-memory gate is blind to the builder-windowed columns: 21 stored columns (`max_daily_return`, `idiosyncratic_volatility`, `equity_beta_z`, `market_residual_z`, `market_residual_lag1_acf`, `rate_beta_z`, `vix_z` and others of the pass-through kernels) declare memory 0 because their windowing is the builder's own NaN-until-full discipline. A certificate bounded by `source_memory_bars_max` would admit them as memoryless although they have windows of 21 to 252. Whichever design lands must take their true window (or refuse them) before any certificate is minted; this is a defect of the memory proxy, separate from the HAC lag.

Sequence unchanged: after the corpus pilot and the family 10 counted runs and StepM read, before the pin of any counted corpus test, never beside a live counted run.


## Plan 2026-11-25 (indicagent-22, requested by the lead; read-only, no look charged)

### Musk step 1: which parts of the requirement survive

The todo bundles five things. Evidence for each is in this file, todos 547, 586 and 674, and `docs/plans/2026-11-24-family-order-after-1d-corpus.md`.

| Part | Verdict | Reason |
|---|---|---|
| Fixed statistic (HAC lag tied to horizon overlap and weight persistence) | survives | 586: the 1d source, 1d book route fails at horizon 1 (`f1d_tau60`, `f1d_tau200`, `f1d_static_tau200`); horizon 5 adds overlap. A certificate minted on today's statistic would be a silent wrong answer |
| True member window (todo 674) | survives, not owned here | the certificate's `source_memory_bars_max` is blind to 21 pass-through columns; H-B's three members are among them. Lands first, in the 674 R1 and R2 branches |
| Horizon-5 1d to 1d route for equal-weight members in one family | survives, minimum scope | needed by H-B (6 series, rank 1) and by nothing else that is ready |
| Certificates for any other horizon, source timeframe, smoothing or book timeframe | deleted | no ranked family needs them; the 1h and 5m cells in 586 stay refused |
| Multi-input book certificate for `corpus_family` (rank 2) and the regime slot cells (rank 4) | deleted from this item | each is its own build, priced after the H-B read; both are costed in the family-order note and would double the battery block |

The item is therefore: fix the statistic, then certify one route (feature, 1d source, 1d book, horizon 5, equal weight, `overlap_sessions` 4) at the memory bound the six H-B series need.

### End state

`runner._check_supported_subset` admits horizon 5 for that one route; `null_battery_persistent` carries persistent cells for it that pass on the fixed statistic (seed bases declared before the run, E17); every existing battery pass record is rebound or shown unmoved; the H-B family (`docs/plans/2026-11-15-published-prior-top3-prereg-drafts.md`) is runnable as registered. No counted look, no new family.

### Scope (checkable)

1. Member check on the true windows of the six H-B series (21, 21, 60 with z 252, per the table above, after 674): fix the memory bound the cells must cover. Output: one line per series.
2. Statistic fix: the horizon-tied, persistence-aware lag, with a methodology-change-ledger entry; `repro_frozen` bit-identical or the ledger entry records the move. It edits `RUNNER_STATISTIC_FUNCTIONS`, so every bound battery pass goes stale and is rebound in the same commit (`bind_battery_pass.py`), including the family 10 and daily residual records.
3. Route widening in `_check_supported_subset` (outside `RUNNER_STATISTIC_FUNCTIONS`, so by itself it stales nothing) and the new cells in `null_battery_persistent.py` (check whether `battery_pass` hashes that module; if it does, it belongs to the rebind in item 2).
4. Counted battery block for the new cells at 4 workers, seed bases declared in the ledger first, then `bind_battery_pass.py`.
5. Close 547 (the horizon-tied lag part) and 586 (the ten cells hold) in the landing commit; 547 keeps its owner decision on the reversal members.

### Gates

`/simplify`, independent review, `tests/unit` exit code, `repro_frozen` bit-identical or the recorded ledger entry, `runner.static_gate` passes for every bound record after the rebind, and the preflight in `family10_launch.sh` still passes for the recorded family 10 specs.

### Sequencing and conflicts

- After the four family 10 runs are recorded and the StepM read on 16 series; never beside a live counted run (a live run imports the research code).
- After the single re-pin (652, 674 R1 and R2, 670 and 671). 674 R2 edits `runner.py`, `feature_inputs.py` and `snapshot.py`, the same files as item 3: this item rebases on R2 and does not start before R2 lands, or the two collide on the member check.
- The code can be written and reviewed in a detached worktree while `stage_1d` runs, but it does not land until `stage_1d` ends unless the import closure of the fingerprinted writers is shown to exclude the edited modules (`code_content_key`). The counted battery block (item 4) is a heavy job and waits for `stage_1d` to finish: one heavy job at a time.
- Order of heavy slots after family 10: single re-pin, new pilot, `stage_1d` (about 7 hours extrapolated), then this battery block, then the H-B counted run.

### Open risk

If the fixed statistic still fails the 1d source cells at horizon 5, the route stays refused and H-B waits; the failure is recorded (ledger entry) and the next step is the owner's call on whether persistent members are in scope at all. Do not weaken the cell bound.

## Status 2026-11-25 (lead, after a worker read)

The 674 R2 sequencing blocker is cleared: R1, R2, 652 and 670/671 landed together at 639c244b1 (rebuild pin 0f593f92f8b4). Two blockers remain before any build. (1) The owner ruling on todo 586: the persistence statistic exists on the held branch `wip/586-persistence-statistic` (design note `docs/plans/2026-11-17-persistence-robust-e17-statistic-design.md`), and 669's statistic work starts from it, not from scratch. (2) The 1d source, 1d book, unsmoothed route fails the full battery under that statistic on `f1d_tau200` (20 against a bound of 18 at 0.01); the design note says the only fair second look is a rerun on other seeds. Next step after the corpus pilot, in the heavy slot: that rerun with seed bases declared in the ledger beforehand. If it holds, build 669 on the 586 branch; if it fails again, the route stays refused and whether persistent members are in scope is the owner's call.
