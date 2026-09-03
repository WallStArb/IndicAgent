# Phase 171 Requirement 1: APR Verification

**Verdict: REQ-1 required no new implementation.** Migration 292 (commit `1300ec8d`,
2026-08-05) already seeded all 8 tf-calibrated `alpha.hmm.walk_forward.*` keys with the
exact values ROADMAP.md's Requirement 1 specifies. No migration was written by this task.
No config value was changed by this task. This file exists so that verdict is backed by an
executed query's captured output, not asserted from `171-RESEARCH.md`'s summary (D-00: no
verification-by-inspection).

## Verbatim query

```sql
SELECT s.config_key, s.config_value, sch.description
FROM config_state s
JOIN config_schema sch USING (config_key)
WHERE s.config_key LIKE 'alpha.hmm.walk_forward%'
   OR s.config_key IN ('alpha.hmm.n_restarts', 'alpha.hmm.random_state')
ORDER BY s.config_key;
```

Run via:
```
PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -c "SELECT s.config_key, s.config_value, sch.description FROM config_state s JOIN config_schema sch USING (config_key) WHERE s.config_key LIKE 'alpha.hmm.walk_forward%' OR s.config_key IN ('alpha.hmm.n_restarts','alpha.hmm.random_state') ORDER BY s.config_key"
```

## Verbatim output (captured 2026-08-08)

```
                   config_key                   | config_value |                                                                                                                                                                                                                                                                                                                                                        description
------------------------------------------------+--------------+----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
 alpha.hmm.n_restarts                           | 1            | [initial_estimate] Number of GaussianHMM fits attempted in regime_writer.py, one per seed derived deterministically as alpha.hmm.random_state + i for i in range(n_restarts) — the converged fit with the highest log-likelihood is kept. GaussianHMM's EM objective is non-convex, so a single seed can land in a worse local optimum than a different seed would find. Changing this away from 1 changes which local optimum regime_writer.py lands on and therefore invalidates all downstream regime labels in feature_vectors — same caution class as alpha.hmm.random_state. Not an ML learning target. Default 1 reproduces the prior single-seed-fit behavior exactly (one seed, one same-seed convergence retry).
 alpha.hmm.random_state                         | 42           | [conventional] numpy random seed for GaussianHMM fitting in regime_writer. CHANGING THIS INVALIDATES all regime labels in feature_vectors and requires full regime_writer + ic_engine re-run.
 alpha.hmm.walk_forward.enabled                 | false        | [user_preference] Gate for todo 248's walk-forward HMM parameter-lookahead fix in services/regime_writer.py's _compute_symbol_tf_walk_forward. Default false: landing the code must not itself change any existing feature_vectors.regime value. Flipping this true, then running regime_writer.py --refit, is a deliberate, separate deployment decision -- see _compute_symbol_tf_walk_forward's docstring for the precondition (only run against a freshly-recomputed corpus, never a partial re-run over rows the single-fit path already populated). Not an ML learning target.
 alpha.hmm.walk_forward.initial_warmup_bars.15m | 13200        | [rca_analysis] todo 248: bars of history required before the first walk-forward HMM fit at 15m (~2yr at 15m density). Same pilot confirmation as refit_every_bars.15m. Not an ML learning target.
 alpha.hmm.walk_forward.initial_warmup_bars.1d  | 504          | [initial_estimate] todo 248: bars of history required before the first walk-forward HMM fit at 1d (~2 trading years at daily density). Same unpiloted-estimate caveat as refit_every_bars.1d. Not an ML learning target.
 alpha.hmm.walk_forward.initial_warmup_bars.1h  | 3300         | [rca_analysis] todo 248: bars of history required before the first walk-forward HMM fit at 1h (~2 trading years). Same pilot as refit_every_bars.1h. Not an ML learning target.
 alpha.hmm.walk_forward.initial_warmup_bars.5m  | 39600        | [initial_estimate] todo 248: bars of history required before the first walk-forward HMM fit at 5m (~2yr at 5m density). See migration 292 header. Not an ML learning target.
 alpha.hmm.walk_forward.refit_every_bars.15m    | 6600         | [rca_analysis] todo 248: bars between walk-forward HMM refits at 15m. Independently re-piloted and confirmed (SPY/15m: 56.8% label agreement vs 22.1% chance baseline, +34.8 points above chance, 0 sign flips) -- see docs/analysis/hmm-parameter-lookahead-pilot-spy-1h.md. Not an ML learning target.
 alpha.hmm.walk_forward.refit_every_bars.1d     | 252          | [initial_estimate] todo 248: bars between walk-forward HMM refits at 1d (~1 trading year at daily density). Fresh, UNPILOTED estimate -- no broadened-pilot measurement exists at this tf, the least-certain of the four calibrated tfs. See migration 292 header. Not an ML learning target.
 alpha.hmm.walk_forward.refit_every_bars.1h     | 1650         | [rca_analysis] todo 248: bars between walk-forward HMM refits at 1h (~1 trading year). Directly measured by the Gate 4 pilot (SPY/1h, TLT/1h): full-history-vs-walk-forward label agreement 24.9% vs 21.7% chance baseline -- see docs/analysis/hmm-parameter-lookahead-pilot-spy-1h.md. Not an ML learning target.
 alpha.hmm.walk_forward.refit_every_bars.5m     | 19800        | [initial_estimate] todo 248: bars between walk-forward HMM refits at 5m. Scaled from the 1h pilot's directly-measured value by 5m's bar-density ratio (12x), following the same scaling logic 15m's value independently confirmed -- NOT itself re-piloted at 5m. See migration 292 header. Not an ML learning target (calibrates measurement methodology, not a model parameter).
(11 rows)
```

Row count confirmation:
```
$ PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -tAc "SELECT count(*) FROM config_state WHERE config_key LIKE 'alpha.hmm.walk_forward%'"
9
```
9 = 8 tf-calibrated keys + `alpha.hmm.walk_forward.enabled`, matching the acceptance criterion exactly.

## Per-key table: value + tf calibration match

| Key | `refit_every_bars` | `initial_warmup_bars` | Matches ROADMAP spec? |
|-----|---------------------|-------------------------|------------------------|
| 1h  | 1650 | 3300  | Yes |
| 15m | 6600 | 13200 | Yes |
| 5m  | 19800 | 39600 | Yes |
| 1d  | 252  | 504   | Yes |

All 8 literal values (1650, 6600, 19800, 252, 3300, 13200, 39600, 504) are present verbatim
in the captured output above and match the ROADMAP requirement's specified values exactly.

## Provenance disclosure (D-02)

| tf  | `refit_every_bars` provenance | `initial_warmup_bars` provenance |
|-----|-------------------------------|-----------------------------------|
| 1h  | `[rca_analysis]` — directly measured by the Gate 4 pilot | `[rca_analysis]` |
| 15m | `[rca_analysis]` — independently re-piloted, confirmed | `[rca_analysis]` |
| 5m  | `[initial_estimate]` — scaled by bar-density ratio, not re-piloted | `[initial_estimate]` |
| 1d  | `[initial_estimate]` — fresh, unpiloted density-scaled estimate | `[initial_estimate]` |

Per D-02, **1d's two keys are explicitly disclosed as `[initial_estimate]`, not
`[rca_analysis]`.** The migration 292 header states 1d's values were derived by
density-scaling the same "~1 trading year refit / ~2 year warmup" heuristic already used
for 5m/15m at ~252 bars/year, not pilot-measured directly — matching this project's
"disclose limitations, don't gate on them" precedent (Phase 166 D-05) rather than blocking
this phase's whole rollout on a dedicated 1d pilot. The captured `description` column above
shows the literal `[initial_estimate]` tag on both 1d rows and both 5m rows, and the literal
`[rca_analysis]` tag on both 1h rows and both 15m rows — this is asserted from the actual
DB-stored description text, not from the migration source alone.

## Code/config consistency check

`services/regime_writer.py` lines 122-127 (`_WALK_FORWARD_DEFAULT_PARAMS`):

```python
_WALK_FORWARD_DEFAULT_PARAMS: dict[str, tuple[int, int]] = {
    "5m": (19800, 39600),
    "15m": (6600, 13200),
    "1h": (1650, 3300),
    "1d": (252, 504),
}
```

These in-code fallback defaults match the seeded `config_state` values exactly, tf-for-tf,
value-for-value. If an APR read ever fails at runtime, `regime_writer.py` degrades to the
same numbers currently live in `config_state`, not silently different ones.

## Baseline values for D-03's pilot arm

- `alpha.hmm.n_restarts` = `1` (`[initial_estimate]`) — current baseline; D-03's pilot
  compares `n_restarts=1` against `n_restarts>1` as two separate comparison arms, not a
  blind default switch.
- `alpha.hmm.random_state` = `42` (`[conventional]`) — unchanged; changing this invalidates
  all downstream `feature_ic_scores` and requires a full regime_writer + ic_engine re-run.

## No migration, no config change

```
$ git status --short production/migrations/
```
(empty — no migration was added or modified by this task)

No `config_state`/`config_schema` row was inserted, updated, or deleted by this task. This
file is a read-only evidence capture.
