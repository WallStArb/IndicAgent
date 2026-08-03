---
status: completed
priority: P3
filed: 2026-08-02
closed: 2026-08-03
source: /simplify altitude review of todo 231's OOM fix
---

## What

Todo 231 fixed `[dict(r) for r in rows]` fed to `pd.DataFrame(...)` OOM-killing
`scripts/analysis/nonlinear_interaction_combiner_lightgbm_check.py` by adding a general-purpose
`_fetch_frame_chunked(db_dsn, sql_tf_query, batch_size)` helper (streams via an asyncpg
server-side cursor, downcasts float64->float32 per chunk, folds periodically to bound peak
memory). The two nonlinear_interaction_combiner replication scripts now import and share it.

The `/simplify` altitude review on that fix found the identical unsafe pattern (`[dict(r) for r
in rows]` -> `pd.DataFrame`) untouched, verbatim, in six other places:

- `scripts/analysis/phase143_1_08_shadow_validation.py:97`
- `scripts/analysis/regime_boundary_churn_check.py:566`
- `scripts/analysis/diagnose166_frame_calibration.py:313`
- `scripts/analysis/score03_gate2_execution_eval.py:490`
- `scripts/analysis/gate166_frame_recalibration_eval.py:605`
- **`services/graduation_analyzer.py:262`** — this one is live production code, not an
  exploratory script.

`_fetch_frame_chunked` has zero nonlinear_interaction_combiner/domain vocabulary (generic `db_dsn`/`sql`/`tf` signature) and
qualifies as Ring 0 portable infrastructure per CLAUDE.md's naming rules, but it currently lives
as a private (`_`-prefixed) symbol inside one specific hypothesis-test script — not discoverable
by any of the six files above. Deliberately NOT fixed in the same session as todo 231: rewiring
`services/graduation_analyzer.py` (production) and five unrelated analysis scripts is well
outside that diff's scope.

## Correction (2026-08-02, same session as 231's follow-on fix) — urgency claim doesn't hold

Checked the actual row-count scale and liveness of all six sites before treating this as a
priority queue, per this project's own [[feedback_check_archived_before_investigating]] and
`docs/foundation/performance-investigation-sop.md` mandate to measure before theorizing:

- **`services/graduation_analyzer.py:262` is NOT live production code — this todo's own
  framing was wrong.** `indicagent-graduation-compute` has no matching systemd unit installed
  on this host (`systemctl list-units --all | grep graduation` returns nothing), and its query
  path (`signal_transform_log` JOIN `signal_ledger`) reads from tables that are (a)
  architecturally ARCHIVED per CLAUDE.md's Architecture section (v2.x Signal Ledger
  Architecture, "no live consumer as of 2026-07-02") and (b) **empty** — `signal_ledger` and
  `signal_transform_log` both `count(*) = 0` live. There is zero live-incident risk here; this
  file is dead code downstream of an archived subsystem, not a production OOM waiting to
  happen.
- **The other four analysis scripts (`phase143_1_08_shadow_validation.py`,
  `regime_boundary_churn_check.py`, `diagnose166_frame_calibration.py`,
  `score03_gate2_execution_eval.py`, `gate166_frame_recalibration_eval.py`) query `alpha_frames`
  via `_OOS_QUERY_SQL` — 5 narrow columns, filtered to one `weight_epoch`, not `feature_vectors`'
  263-column full-corpus scan.** `alpha_frames` is currently `count(*) = 0` (Phase 168 hasn't
  shipped), and even at scale a 5-column trade-frame table is nowhere near the width/row-count
  product that OOM-killed the nonlinear_interaction_combiner scripts. No real risk here either.
- The nonlinear_interaction_combiner-family scripts are also not doing the Ring-0-worthy generic reuse the original framing
  assumed: `gate166_frame_recalibration_eval.py`/`score03_gate2_execution_eval.py` already
  cross-import underscore-prefixed symbols from `phase143_1_08_shadow_validation.py` — the same
  "shared via private cross-import" shape nonlinear_interaction_combiner's three scripts now use, and an established
  (if imperfect) convention in this specific directory already, not a nonlinear_interaction_combiner-specific violation.

**Revised next step, downgraded P2 -> P3:** the only genuine OOM-risk pattern in this codebase
is "full `feature_vectors` corpus x wide column count," which exists solely in the three nonlinear_interaction_combiner
scripts — already fixed and already sharing one implementation. Promoting `_fetch_frame_chunked`
to `src/core/` now would be premature abstraction for consumers that don't exist (CLAUDE.md:
"Don't design for hypothetical future requirements"). The one real, low-cost cleanup still worth
doing: extract `_fetch_frame_chunked`/`_extract_training_arrays`/`_bootstrap_ic_stats`/
`_per_symbol_ic_ci` out of `nonlinear_interaction_combiner_lightgbm_check.py`'s private namespace into a
small `t5`-scoped shared module (not `src/core/`, not `graduation_analyzer.py` — neither needs
it), so the two replication scripts stop importing underscore-prefixed names across a module
boundary. Do this opportunistically, not urgently.

## Closed as moot (2026-08-03)

The extraction this todo's remaining scope asked for already happened
(`scripts/analysis/_nonlinear_interaction_combiner_shared.py`, created 2026-08-02) — but todo 234's
follow-on OOM investigation (2026-08-03) then found the whole `_fetch_frame_chunked` /
`_extract_training_arrays` design was itself the architectural defect (see 234's resolution) and
replaced both with `fetch_training_matrix()`, a different function that never materializes a
wide DataFrame at all. The specific function names this todo named no longer exist. Nothing left
to do here — the shared module exists, the extraction happened, and the functions inside it have
since been superseded by a better design for an unrelated reason (memory, not duplication).
