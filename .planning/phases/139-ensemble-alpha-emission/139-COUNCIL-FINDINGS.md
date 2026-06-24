---
phase: 139
type: council-review
status: pending — apply via /gsd-plan-phase 139 --reviews or manual edit before execute
reviewed_at: 2026-06-23
---

# Renaissance Council Findings — Phase 139

Seven findings from first-principles review. Items 1–3 are correctness/performance
blockers. Items 4–5 are design honesty and APR compliance. Items 6–7 are medium/low.

Apply all before running `/gsd-execute-phase 139`.

---

## Finding 1 — BLOCKER: EnsembleBuilder scoring loop must be vectorized (P2 Task 1)

**Problem:** Plan says "for each bar, compute_alpha_score(feature_values, ...)". Python
for-loop over 8–12M corpus rows is O(n × features) with interpreter overhead. Will run
hours, not minutes.

**Fix:** Weights and IC signs are constant per stratum. Scoring is a single matmul:

```
X = feature_values matrix [n_bars, n_features]  — one bulk SELECT per stratum
signed_weights = weights * ic_signs              — [n_features], computed once
alpha_scores = X @ signed_weights                — [n_bars], single matmul, replaces loop
margin = 1.96 * sqrt(dot(weights**2, ((ic_ci_upper - ic_ci_lower) / 3.92)**2))  — constant per stratum
```

Write ensemble_alpha via `conn.executemany()` or COPY, not row-by-row INSERT.

**Plan location:** P2 Task 1 action, step 6 — replace per-bar Python loop with matrix
multiply + bulk insert.

---

## Finding 2 — BLOCKER: Regime filter missing in EnsembleBuilder scoring (P2 Task 1)

**Problem:** Plan says "Score ensemble_alpha for every feature_vectors bar in that
stratum (symbol, tf, regime)." But feature_vectors has a `regime_label` column — the
plan's query doesn't filter by it. Applying weights trained on regime=R to bars where
`regime_label != R` corrupts ensemble_alpha with cross-regime signal. Hidden bias.

**Fix:** Add `WHERE regime_label = $regime` to the feature_vectors SELECT in step 6:

```sql
SELECT <feature_cols> FROM feature_vectors
WHERE symbol = $1 AND tf = $2 AND regime_label = $3
ORDER BY bar_ts
```

This ensures IC → weights → scoring are all on the same regime partition.

**Plan location:** P2 Task 1 action, step 6 — add regime_label filter to feature_vectors
query.

---

## Finding 3 — HIGH: AlphaEmitter N+1 query for top_features (P2 Task 2)

**Problem:** "Query ensemble_weights for that stratum/weight_version" is inside the
per-row emission loop. 100K emitted events = 100K round-trip queries, all returning
the same rows (weights are constant per stratum).

**Fix:** Preload all ensemble_weights rows for the active weight_version at the start of
`execute()` into a dict keyed by (symbol, tf, regime):

```python
weights_cache: dict[tuple, list[dict]] = {}
# SELECT * FROM ensemble_weights WHERE weight_version = $weight_version
# group into weights_cache by (symbol, tf, regime)
```

Emission loop does `weights_cache[(symbol, tf, regime)]` — zero additional queries.

**Plan location:** P2 Task 2 action — add weights_cache preload before emission loop;
replace per-row ensemble_weights query with cache lookup.

---

## Finding 4 — HIGH: Ledoit-Wolf is computed but never used — resolve before execution (P1 Task 2, P2 Task 1)

**Problem:** Phase goal says "Ledoit-Wolf shrinkage covariance → ensemble_weights" but
weights are derived from IC Sharpe only. LW is logged to an OTel gauge and discarded.
Computing LW per stratum (O(n_features^3)) for a diagnostic gauge wastes compute and
misrepresents the architecture.

**Choose one path before executing:**

**Path A — Use LW (correct):** After IC Sharpe weights, apply cluster deflation.
Features with pairwise correlation > `alpha.ensemble.max_cluster_correlation` (new APR
key, default 0.80) share weight within the cluster: cap total cluster weight at
`alpha.ensemble.max_cluster_weight` (new APR key, default 0.40). This is the actual
quant use case for LW in ensemble construction.

**Path B — Remove LW from Phase 139 (honest):** IC Sharpe weights + 0.20 per-feature
cap already limit concentration. Delete `compute_shrinkage_covariance()` call from
EnsembleBuilder's stratum loop. Keep `covariance.py` in the math library (it will be
used in a future phase) but don't call it here. Update phase goal description: "IC-Sharpe
weighted ensemble with per-feature cap." Add `alpha.ensemble.lw_deflation_enabled bool
false [initial_estimate]` as an APR key — operator can enable when ready.

**Path B is recommended for Phase 139.** It is simpler, honest, and deferral is explicit
via APR rather than silent.

**Plan location:**
- P1 Task 2: remove LW from EnsembleBuilder's core loop OR add cluster deflation logic
- P2 Task 1: update action to match chosen path
- Phase goal description in ROADMAP.md: update to "IC-Sharpe weighted ensemble" if Path B

---

## Finding 5 — HIGH: `top_features_count` missing from APR seeds (P1 Task 1, P2 Task 2)

**Problem:** "Build top_features dict (top contributing features and their weight×value)"
doesn't specify how many. "All 61" vs "top 10" affects JSONB row size, Kafka payload
size, and downstream usability. This is an operator-controlled parameter, not a
mathematical constant.

**Fix:** Add a 10th APR key to migration 168:

```
alpha.ensemble.top_features_count int 10 min 1 max 61 [operator_controlled]
description: "Number of top-contributing features to include in alpha_events.top_features
JSONB. Features ranked by abs(weight × feature_value) descending. Default 10 balances
traceability with payload size."
```

AlphaEmitter reads this key and slices the sorted contribution list before building
the top_features dict.

**Plan location:** P1 Task 1 action section 2 (config_schema INSERT) and section 3
(config_state INSERT); P2 Task 2 action (emit top-N by abs contribution); migration 168
APR key count becomes 10.

---

## Finding 6 — MEDIUM: CI variance propagation assumes feature independence — document it (P1 Task 2)

**Problem:** `var = dot(weights**2, sigma_ic**2)` assumes IC estimation errors are
independent across features. Correlated features (e.g., three momentum z-scores)
have correlated IC estimates. This understates CI width, making the signal appear
more statistically significant than it is — systematic upward bias on confidence.

**Fix (documentation path):** Add to `alpha_score.py` module docstring:

```
CI bounds assume independence of feature IC estimation errors.
For correlated feature clusters, actual CI width is wider than computed.
Threshold calibration via alpha.quant.threshold.* compensates empirically.
This assumption is acknowledged via APR key alpha.ensemble.ci_independence_assumption.
```

Add APR key `alpha.ensemble.ci_independence_assumption str 'acknowledged' [operator_controlled]`
to migration 168 (becomes key 11 if finding 5 is also applied, or key 10 if finding 5 is
skipped). Forces a conscious confirmation that this approximation is intentional.

The full fix (`var = w^T Sigma_IC w` using the full LW covariance matrix) is deferred
until corpus data reveals whether correlation structure materially affects thresholds.

**Plan location:** P1 Task 2 action (alpha_score.py docstring note); P1 Task 1 (optional
APR key).

---

## Finding 7 — LOW: P3 report generator specifies "psycopg2 or asyncpg" — should be asyncpg only (P3 Task 2)

**Problem:** `generate_ic_discovery_report.py` action says "psycopg2 or asyncpg,
read-only queries." Ambiguity could produce a psycopg2 implementation that works but
deviates from the project standard.

**Fix:** Change to "asyncpg, read-only queries" in P3 Task 2 action.

**Plan location:** P3 Task 2 action, first sentence.

---

## Application order when resuming

After `/clear`, run:

```
/gsd-plan-phase 139 --reviews
```

Or manually edit P1 and P2 to apply findings 1–5 directly. The REVIEWS.md in this
directory documents the prior round of review fixes (bugs 1–4 from the Codex review).
These council findings are the second round and are additive — all prior fixes remain.

Priority order for manual application:
1. Finding 2 (regime filter) — one-line SQL fix, high correctness impact
2. Finding 1 (vectorize scoring) — rewrites step 6 of P2 T1, high perf impact
3. Finding 3 (weights_cache) — adds preload block to P2 T2, high perf impact
4. Finding 5 (top_features_count APR key) — adds one key to migration, P2 T2 reference
5. Finding 4 (LW resolution) — design decision required first; Path B recommended
6. Finding 6 (CI documentation) — docstring addition
7. Finding 7 (asyncpg only in P3) — one-word change
