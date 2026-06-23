# Phase 139: Ensemble + Alpha Emission - Research

**Researched:** 2026-06-23
**Domain:** IC-weighted ensemble construction, Ledoit-Wolf covariance shrinkage, transaction cost modelling, Kafka event emission
**Confidence:** HIGH

---

## Summary

Phase 139 builds on Phase 138's `feature_ic_scores` table to produce three deliverables:
(1) `ensemble_weights` — IC-Sharpe-weighted feature weights with Ledoit-Wolf shrinkage for
feature correlation correction; (2) `ensemble_alpha` — a per-bar composite alpha score built by
running the weights across historical `feature_vectors`; and (3) `AlphaEmitter` — a batch
oneshot that enforces the effective_N gate and publishes qualifying alpha events to the Kafka
topic `alpha.events` in shadow mode.

The math lives in a pure-function `src/intelligence/ensemble/` module (Ring 1). The compute
services are `services/ensemble_builder.py` and `services/alpha_emitter.py` — both extend
`BaseBatch` from `src/core/agent/base_batch.py` (established in Phase 138 P2). DB writes go
to two new hypertables (`ensemble_weights`, `ensemble_alpha`). Kafka publishing uses the
established `KafkaProducerClient.publish(msg=...)` pattern with a new `topic_alpha_events()`
key in `stream_keys.py`. All numeric parameters (weights cap, effective-N threshold, emission
threshold, lookahead selection) live in APR under `alpha.ensemble.*` and
`alpha.quant.threshold.*`. Kelly criterion is explicitly out of scope for Phase 139 (Phase D
in the build sequence from `intelligence-alphaengine.md`).

**Primary recommendation:** Split into three plans — P1: DB schema + APR seeds + pure math
library + unit tests; P2: EnsembleBuilder batch service (feature selection → covariance →
weights → ensemble_alpha rows); P3: AlphaEmitter batch service + Kafka emission + IC discovery
report. Run P1 then P2 then P3 in strict order. Do not attempt to merge ensemble weight
construction and alpha emission into a single service — the SoC invariant and testability both
demand separation.

---

## Standard Stack

### Core

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `sklearn.covariance.LedoitWolf` | scikit-learn 1.x (already in requirements) | Shrinkage covariance estimator for feature correlation correction | Canonical Ledoit-Wolf implementation; O. Ledoit and M. Wolf 2004. Input: `X` shape `[n_samples, n_features]`. Output: `.covariance_` shape `[n_features, n_features]`. No separate install needed. |
| `numpy` | already pinned | Matrix operations, z-scoring, CI propagation | All IC math already uses numpy. |
| `scipy.stats.rankdata` | already pinned | Rank transformation for Spearman IC | Already in ic_engine.py. |
| `psycopg2` + `psycopg2.extras.execute_batch` | already installed | Sync DB writes, batch INSERT | Pattern established in ic_engine.py. |
| `asyncpg` (via `BaseBatch._setup_pool`) | already pinned | Async pool for BaseBatch subclasses that prefer asyncpg | ic_engine.py uses psycopg2 directly; ensemble_builder can do the same for consistency. |
| `structlog` | already pinned | Structured logging | Consistent with all Phase 138 services. |

### Supporting

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `statsmodels.stats.multitest.multipletests` | already installed | BH-FDR, not needed in 139 but already present | Already used in ic_engine.py; not needed for ensemble. |
| `KafkaProducerClient` from `src/core/kafka/producer.py` | internal | Kafka publishing | Use `await producer.publish(msg=...)` — note async, note `msg=` kwarg. |
| `src/core/stream_keys.py` | internal | Topic key construction | New `topic_alpha_events(env_name)` function to add. |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| `sklearn.covariance.LedoitWolf` | Oracle approximating shrinkage (OAS) from sklearn | LW is analytically closed-form, no iteration. OAS slightly better for very small N but immaterial here. Use LW. |
| per-feature IC Sharpe weights | equal weights | Equal weights ignores measured predictive stability; defeats the purpose of IC measurement. Discard. |
| numpy linear algebra for covariance inversion | scipy.linalg.inv | scipy.linalg handles near-singular matrices more robustly. Prefer `scipy.linalg.inv(lw.covariance_)` if inversion is needed. But for weight derivation (see Architecture Patterns) we use eigendecomposition, not raw matrix inversion. |

**Installation:** No new packages needed. sklearn, numpy, scipy all already in requirements.txt.

---

## Architecture Patterns

### Recommended Project Structure

```
services/
├── ensemble_builder.py      # BaseBatch: feature_ic_scores → ensemble_weights + ensemble_alpha
├── alpha_emitter.py         # BaseBatch: ensemble_alpha → alpha_events (Kafka + DB)
src/intelligence/ensemble/
├── __init__.py
├── feature_selector.py      # Pure fn: filter ic_scores → passing features per (symbol,tf,regime)
├── covariance.py            # Pure fn: LedoitWolf wrapper + effective_N computation
├── weights.py               # Pure fn: IC Sharpe → weights vector (cap, renorm)
├── alpha_score.py           # Pure fn: feature_vectors × weights → composite z-score + CI
tests/unit/
├── test_ensemble_math.py    # Pure function unit tests (no DB)
production/migrations/
├── 168_ensemble_tables.sql  # ensemble_weights + ensemble_alpha DDL + APR seeds
```

### Pattern 1: Ledoit-Wolf Shrinkage for Feature Correlation Correction

**What:** Features in the ensemble are correlated. Raw IC Sharpe weights give concentrated exposure to the dominant factor cluster (momentum features all move together). Ledoit-Wolf shrinks the sample covariance toward a target — produces a well-conditioned covariance estimate even when N (number of observations) is only 3-10x the feature count.

**When to use:** Once per (symbol, tf, regime) after feature selection. The input matrix is the feature value matrix from `feature_vectors` for that stratum.

**How effective_N is computed:** The standard HHI-based effective N from the IC weight vector:

```
effective_N = 1 / sum(w_i^2)
```

where `w_i` are the normalized ensemble weights. This is the inverse Herfindahl-Hirschman Index applied to weights. An ensemble with 10 equal-weight features has effective_N = 10. An ensemble where one feature has weight 0.80 and nine others share 0.20 total has effective_N ≈ 1.47. The gate `effective_N >= 3.0` ensures no single feature dominates.

**Important:** LedoitWolf input shape is `[n_obs, n_features]` — samples are rows, features are columns. This is the natural shape of the feature matrix already used in ic_engine.py (`X_sub` shape `[n_independent, n_features]`).

```python
# Source: sklearn.covariance.LedoitWolf docs (Context7 verified)
from sklearn.covariance import LedoitWolf
import numpy as np

def compute_shrinkage_covariance(
    X: np.ndarray,  # shape [n_obs, n_features]
) -> tuple[np.ndarray, float]:
    """Returns (shrunk_covariance, shrinkage_coefficient).
    X must be shape [n_obs, n_features]. LW centers the data internally.
    """
    lw = LedoitWolf(store_precision=False, assume_centered=False)
    lw.fit(X)  # X: n_samples x n_features
    return lw.covariance_, lw.shrinkage_
```

### Pattern 2: IC Sharpe Weight Derivation with Per-Feature Cap

**What:** Each passing feature's IC Sharpe becomes its raw weight. Negative IC Sharpe features are zeroed (not included — they destroy alpha). Weights are normalized to sum to 1.0. A per-feature cap (`alpha.ensemble.max_feature_weight`, default 0.20) prevents any single feature from dominating.

```python
def derive_weights(
    ic_sharpes: np.ndarray,  # shape [n_features]; NaN for excluded features
    max_weight: float = 0.20,
) -> np.ndarray:
    """IC Sharpe → normalized weight vector with cap.
    Returns zero vector if no positive IC Sharpe features.
    """
    w = np.where(np.isfinite(ic_sharpes) & (ic_sharpes > 0), ic_sharpes, 0.0)
    total = w.sum()
    if total < 1e-10:
        return np.zeros_like(ic_sharpes)
    w = w / total
    # Apply per-feature cap, then renormalize (iterate until stable or max 100 iters)
    for _ in range(100):
        clipped = np.minimum(w, max_weight)
        excess = w.sum() - clipped.sum()
        if excess < 1e-10:
            w = clipped
            break
        # Redistribute excess proportionally to uncapped features
        uncapped_mask = w < max_weight
        if uncapped_mask.sum() == 0:
            w = clipped
            break
        w = clipped.copy()
        w[uncapped_mask] += excess * (w[uncapped_mask] / w[uncapped_mask].sum())
    return w / w.sum()  # final renorm for floating point safety
```

### Pattern 3: Composite Alpha Score with CI Propagation

**What:** The alpha score per bar is a weighted linear combination of z-scored feature values. CI propagation is analytic (linear combination of independent normal uncertainties, which is conservative since features are correlated but the correlation correction via LW is already in the weights).

```
alpha_score = sum(w_i * z_i)
where z_i = normalized feature value (already z-scored in feature_vectors)
```

CI propagation for a linear combination where each feature has IC-derived variance:

```
alpha_ci_variance = sum(w_i^2 * ic_ci_variance_i)
alpha_ci_lower = alpha_score - 1.96 * sqrt(alpha_ci_variance)
alpha_ci_upper = alpha_score + 1.96 * sqrt(alpha_ci_variance)
where ic_ci_variance_i = ((ic_ci_upper_i - ic_ci_lower_i) / 3.92)^2
```

This uses the width of the feature's IC 95% CI as a proxy for the alpha score's uncertainty contribution. Conservative — does not account for cross-feature CI covariance. Acceptable for a shadow-mode gate.

```python
def compute_alpha_score(
    feature_values: np.ndarray,  # shape [n_features]
    weights: np.ndarray,         # shape [n_features]
    ic_ci_lower: np.ndarray,     # shape [n_features]
    ic_ci_upper: np.ndarray,     # shape [n_features]
) -> tuple[float, float, float]:
    """Returns (alpha_score, ci_lower, ci_upper).
    feature_values must be z-scored (as stored in feature_vectors).
    NaN feature values are treated as 0 (no contribution).
    """
    safe_vals = np.where(np.isfinite(feature_values), feature_values, 0.0)
    alpha = float(np.dot(weights, safe_vals))
    ci_widths = np.where(
        np.isfinite(ic_ci_lower) & np.isfinite(ic_ci_upper),
        ic_ci_upper - ic_ci_lower,
        0.0,
    )
    ci_variances = (ci_widths / 3.92) ** 2
    alpha_var = float(np.dot(weights ** 2, ci_variances))
    margin = 1.96 * np.sqrt(alpha_var)
    return alpha, alpha - margin, alpha + margin
```

### Pattern 4: Feature Selection from feature_ic_scores

**What:** Phase 139 reads from `feature_ic_scores` WHERE `passes_walkforward = true AND is_pooled = false`. This was locked in the Phase 138 council review: "Phase 139+ ensemble reads exclusively WHERE is_pooled = false."

Per the IC spec's lookahead selection rule: for each (feature, symbol, tf, regime), select the lookahead with the highest IC Sharpe (per `alpha.ensemble.lookahead_selection = 'max_ic_sharpe'`). This produces one row per feature per (symbol, tf, regime) as the input to weight derivation.

**Key SQL pattern:**
```sql
SELECT feature_name, ic_sharpe, ic_ci_lower, ic_ci_upper, lookahead_bars
FROM feature_ic_scores
WHERE symbol = $1
  AND tf = $2
  AND regime = $3
  AND is_pooled = false
  AND passes_walkforward = true
  AND reliable = true
  AND ic_sharpe IS NOT NULL
ORDER BY ic_sharpe DESC
```

Then group by feature_name and take the row with max ic_sharpe per feature. Do not average across lookaheads.

### Pattern 5: AlphaEmitter — Shadow Mode Kafka Publishing

**What:** `alpha_emitter.py` is a BaseBatch that reads `ensemble_alpha` rows exceeding the emission threshold, enforces `effective_N >= 3.0`, and publishes to Kafka topic `alpha.events` as JSON. Shadow mode means no execution — events are published for external platform consumption only.

The Kafka publish pattern from CLAUDE.md is critical:
- `KafkaProducerClient.publish(msg=...)` — kwarg is `msg=`, not `value=`. Wrong kwarg silently fails at flush.
- `await producer.publish(msg=...)` — must await (silently drops if not awaited).

alpha_event schema (Kafka payload):
```python
{
    "event_id": "<sha256_content_key>",
    "symbol": "SPY",
    "tf": "5m",
    "bar_ts": "2024-01-15T14:30:00Z",
    "ensemble_version": "v1.0.0",
    "weight_version": "2024-01-15",
    "alpha_score": 1.24,
    "alpha_ci_lower": 0.38,
    "alpha_ci_upper": 2.10,
    "effective_n": 5.2,
    "regime": "trending_up",
    "n_features_active": 8,
    "feature_contributions": {"momentum_z_fast": 0.31, ...},
    "emitted_at": "2024-01-15T22:00:00Z"
}
```

Content key for `alpha_events` table: `SHA-256(symbol|tf|bar_ts_ns|ensemble_version)[:32]`
as documented in `intelligence-alphaengine.md`.

### Pattern 6: BaseBatch Extension (established pattern from Phase 138)

Both `ensemble_builder.py` and `alpha_emitter.py` extend `BaseBatch`:

```python
# Source: src/core/agent/base_batch.py (Phase 138 P2, confirmed exists)
class EnsembleBuilder(BaseBatch):
    job_name = "ensemble-builder"
    compute_version = "1.0.0"

    def __init__(self, db_dsn: str) -> None:
        super().__init__(db_dsn)
        # load APR keys at init if needed, or load in execute()

    async def execute(self, pool: asyncpg.Pool) -> None:
        # all business logic here
        ...

if __name__ == "__main__":
    import asyncio
    settings = Settings()
    db_dsn = settings.database_url.replace("postgresql+asyncpg://", "postgresql://")
    asyncio.run(EnsembleBuilder(db_dsn=db_dsn).run())
```

Note: ic_engine.py uses psycopg2 directly (not BaseBatch) because it predates the BaseBatch
abstract class. `ensemble_builder.py` and `alpha_emitter.py` should use BaseBatch properly
since it exists now.

### Anti-Patterns to Avoid

- **Do not average IC Sharpe across lookaheads.** Select the best lookahead per (feature, symbol, tf, regime). Averaging dilutes the signal.
- **Do not use pooled IC rows (is_pooled=true) in the ensemble.** These are diagnostic artifacts per Phase 138 council review.
- **Do not emit alpha events without the effective_N gate.** An ensemble of 1 effective feature is not diversified ensemble alpha — it is a single-factor bet with ensemble branding.
- **Do not hardcode the emission threshold.** It comes from `alpha.quant.threshold.{tf}` APR keys calibrated from the transaction cost model.
- **Do not use `msg=` positional — use `msg=` as keyword.** `KafkaProducerClient.publish(msg=payload)` only.
- **Do not mix compute and Kafka publishing in one service.** EnsembleBuilder writes to DB. AlphaEmitter reads from DB and publishes to Kafka. This follows the SoC invariant.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Covariance shrinkage | Custom James-Stein or Oracle shrinkage | `sklearn.covariance.LedoitWolf` | Analytical formula, numerically stable, handles near-singular cases. Proven library. |
| Weight cap with redistribution | ad-hoc clip-renormalize | Pattern 2 above (iterative proportional redistribution) | Naive clip-then-renormalize-once can violate the cap on redistribute step. Iterative method guaranteed to converge. |
| DB content key for alpha_events | random UUID | `BaseBatch.content_key(symbol, tf, str(bar_ts_ns), ensemble_version)` | Deterministic, idempotent re-runs, duplicate detection without DB round-trips. Pattern from Phase 138. |
| APR loading in batch service | inline `psycopg2` queries for config | `services/_batch_utils.load_config_service_sync(conn)` then `cfg.get_sync(key, fallback)` | Pattern established in ic_engine.py. |
| CI propagation for linear combination | Monte Carlo CI estimation | Analytic propagation (Pattern 3 above) | Monte Carlo is 100x slower with no meaningful improvement for this use case. |

**Key insight:** The math in Phase 139 looks complex but decomposes into four simple operations (select, weight, dot-product, gate). Each operation should be a pure function with a unit test. The complexity in Phase 138 (bootstrap CI, walk-forward) is not repeated in Phase 139 — that was the measurement phase. Phase 139 is the application phase.

---

## Common Pitfalls

### Pitfall 1: Feature Selection Without Lookahead Disambiguation

**What goes wrong:** A feature has IC Sharpe = 0.8 at the 1-bar lookahead but IC Sharpe = -0.2 at the 60-bar lookahead. If you average across lookaheads, the feature appears weakly positive. If you include both, the negative lookahead dilutes the weight. The correct approach: pick the single best lookahead per feature per (symbol, tf, regime) and use only that row.

**Why it happens:** The query returns multiple rows per feature (one per lookahead). Developer takes them all without filtering.

**How to avoid:** `GROUP BY feature_name` and pick `MAX(ic_sharpe)` with its corresponding row. Do this in Python (fetch all rows, then group by feature and take max_ic_sharpe row) rather than in SQL to keep the query simple.

**Warning signs:** `n_features_active` in alpha_events is higher than expected — you're counting lookahead variants as separate features.

### Pitfall 2: effective_N HHI Applied to Wrong Vector

**What goes wrong:** effective_N = 1/sum(w^2) where w is the normalized weight vector. If you accidentally apply it to the raw IC Sharpe vector (before normalization and capping), you get a misleading number. The gate `effective_N >= 3.0` then passes when it should not.

**Why it happens:** The weight derivation code normalizes weights internally and returns them, but the caller reuses the raw IC Sharpe values to compute effective_N.

**How to avoid:** effective_N is computed from the output of `derive_weights()` — always the post-normalization, post-cap weight vector. `effective_n = 1.0 / float(np.sum(weights ** 2))`.

### Pitfall 3: Alpha Score Z-Scoring the Composite (Double Z-Score)

**What goes wrong:** Feature values in `feature_vectors` are already z-scored (e.g., `momentum_z_fast` is already a z-score). If you z-score the alpha composite again across the bar population, you lose the sign and magnitude relationship to the original IC measurement. The emission threshold becomes meaningless.

**Why it happens:** The success criterion says "composite alpha score (z-scored)". This means the alpha is expressed on a z-score scale because the inputs are z-scored — not that you apply an additional standardization to the composite itself.

**How to avoid:** The alpha score is `sum(w_i * z_i)` where `z_i` are already z-scored features. No additional normalization of the composite. The threshold in `alpha.quant.threshold.*` is expressed in natural units of the composite (e.g., "alpha > 1.5 standard deviations from zero").

### Pitfall 4: Transaction Cost Threshold Calibration — Wrong Direction

**What goes wrong:** The emission threshold is calibrated from transaction cost model. A naive approach sets `threshold = E[transaction_cost] / E[IC]` which produces a threshold in return units, not alpha score units. The alpha score is dimensionless (z-score units of the feature composite) and the transaction cost is in return units.

**Why it happens:** Conflating the alpha score (dimensionless) with the expected return (basis points).

**How to avoid:** The threshold calibration should work in expected return space: first estimate `E[return | alpha_score > threshold]` from historical `ensemble_alpha` joined to `forward_returns`, then set threshold such that `E[return | alpha_score > threshold] > transaction_cost_bps`. For shadow mode, a reasonable seed estimate is threshold = 1.0 (one composite standard deviation from zero), stored as `alpha.quant.threshold.{tf}`. The actual calibration requires running the ensemble against the corpus and joining to forward_returns — this is Phase 139 P2/P3 work.

**Initial APR seeds for threshold:**
- `alpha.quant.threshold.5m = 1.5` (higher bar for short TF — more noise, higher transaction cost per unit time)
- `alpha.quant.threshold.15m = 1.2`
- `alpha.quant.threshold.1h = 1.0`
- `alpha.quant.threshold.1d = 0.8` (lower bar for daily — lower cost, more persistent alpha)

These are `[initial_estimate]` seeds to be updated post-calibration. Document them as such in migration comments.

### Pitfall 5: Kafka publish() Without await in BaseBatch Context

**What goes wrong:** `KafkaProducerClient.publish()` is async. In a BaseBatch `execute()` coroutine, forgetting `await` silently drops all messages. The service appears to succeed (D-06 emits "success"), but zero alpha events appear on the topic.

**Why it happens:** `publish()` returns a coroutine object, not a result. Python does not warn about unawaited coroutines in all contexts.

**How to avoid:** Always `await producer.publish(msg=payload)`. Write a test that asserts the mock producer's `publish` was called and `await`ed. The pattern `mock_producer.publish.assert_awaited_once_with(msg=...)` catches this.

### Pitfall 6: Asyncpg vs Psycopg2 Mismatch in BaseBatch Subclass

**What goes wrong:** `BaseBatch._setup_pool()` creates an asyncpg pool. But if `execute()` tries to use psycopg2 for the heavy batch compute (as ic_engine.py does), the pool is unused and you have two DB connections open simultaneously. The typing is also wrong.

**Why it happens:** ic_engine.py predates BaseBatch and used psycopg2 directly throughout. Developers copy-paste ic_engine.py patterns into a new BaseBatch subclass without noticing the connection type mismatch.

**How to avoid:** In Phase 139, use asyncpg throughout for all batch services that extend BaseBatch. The pool from `execute(pool)` is an asyncpg.Pool. Use `async with pool.acquire() as conn:` for queries. JSONB columns come back as dicts (no json.loads needed — CLAUDE.md rule). The heavy array math (LedoitWolf, numpy) is CPU-bound pure Python — this is fine in an async context as long as you do not call `time.sleep()` in the async path.

---

## Code Examples

Verified patterns from existing codebase:

### APR Loading in Batch Service (from ic_engine.py)

```python
# Source: services/ic_engine.py lines 186-209 (verified in codebase)
from services._batch_utils import load_config_service_sync as _load_config_service

def _load_apr(conn: Any) -> dict[str, Any]:
    cfg = _load_config_service(conn)
    return {
        "max_feature_weight": float(cfg.get_sync("alpha.ensemble.max_feature_weight", 0.20)),
        "effective_n_gate": float(cfg.get_sync("alpha.ensemble.effective_n_gate", 3.0)),
        "weight_version": cfg.get_sync("alpha.ensemble.weight_version", "v1"),
        "threshold_5m": float(cfg.get_sync("alpha.quant.threshold.5m", 1.5)),
        "threshold_15m": float(cfg.get_sync("alpha.quant.threshold.15m", 1.2)),
        "threshold_1h": float(cfg.get_sync("alpha.quant.threshold.1h", 1.0)),
        "threshold_1d": float(cfg.get_sync("alpha.quant.threshold.1d", 0.8)),
    }
```

### Kafka Topic Key (to add to stream_keys.py)

```python
# Source: src/core/stream_keys.py — pattern from existing topic_* functions
def topic_alpha_events(env_name: str) -> str:
    """Kafka topic for alpha emission events from AlphaEngine v3.0."""
    return f"{env_prefix(env_name)}alpha.events"
```

### Content Key for alpha_events (from BaseBatch)

```python
# Source: src/core/agent/base_batch.py lines 102-116 (verified in codebase)
# event_id = BaseBatch.content_key(symbol, tf, str(int(bar_ts.timestamp() * 1e9)), ensemble_version)
event_id = BaseBatch.content_key("SPY", "5m", "1719014400000000000", "v1.0.0")
# Returns 32-char hex string — deterministic, idempotent
```

### D-06 Completion in BaseBatch (from base_batch.py)

```python
# Source: src/core/agent/base_batch.py lines 73-96 (verified in codebase)
# Automatically handled by BaseBatch.run() — no manual JOB_COMPLETED_TOTAL.add() needed
# in EnsembleBuilder.execute() or AlphaEmitter.execute().
# BaseBatch.run() wraps execute() and calls _emit_completion(status, elapsed) in finally.
```

### OTel Gauge Pattern for Ensemble Metrics (from observability/metrics.py)

```python
# Source: src/observability/metrics.py lines 1112-1128 (verified in codebase)
# Existing gauges follow: _meter.create_gauge("name", unit="", description="...")
ENSEMBLE_EFFECTIVE_N_GAUGE = _meter.create_gauge(
    "ensemble_effective_n",
    unit="",
    description="Effective N (inverse HHI) of ensemble weights per (symbol, tf, regime)"
)
ENSEMBLE_WEIGHT_VERSION_GAUGE = _meter.create_gauge(
    "ensemble_weight_count",
    unit="",
    description="Number of active features in ensemble per (symbol, tf, regime)"
)
ALPHA_EVENTS_EMITTED_TOTAL = _meter.create_up_down_counter(
    "alpha_events_emitted_total",
    unit="",
    description="Total alpha events emitted per (symbol, tf, regime)"
)
```

---

## DB Schema

### New Tables Required (Migration 168)

**`ensemble_weights`** — stores per-feature weights per (symbol, tf, regime, weight_version):

```sql
CREATE TABLE IF NOT EXISTS ensemble_weights (
    symbol              text             NOT NULL,
    tf                  text             NOT NULL,
    regime              text             NOT NULL,
    weight_version      text             NOT NULL,   -- e.g. '2024-01-15' or 'v1'
    feature_name        text             NOT NULL,
    ic_sharpe           double precision,            -- IC Sharpe used for this weight
    raw_weight          double precision,            -- before cap/renorm
    weight              double precision NOT NULL,   -- after cap + renorm
    lookahead_bars      integer         NOT NULL,    -- which lookahead was selected
    effective_n         double precision,            -- effective N of the full weight vector (stored once per symbol/tf/regime/version)
    computed_at         timestamptz      NOT NULL DEFAULT now(),
    PRIMARY KEY (symbol, tf, regime, weight_version, feature_name)
);
-- NOT a hypertable (dimension is weight_version, not time)
CREATE INDEX IF NOT EXISTS ensemble_weights_lookup_idx
    ON ensemble_weights (symbol, tf, regime, weight_version);
```

**`ensemble_alpha`** — stores per-bar composite alpha scores:

```sql
CREATE TABLE IF NOT EXISTS ensemble_alpha (
    symbol              text             NOT NULL,
    tf                  text             NOT NULL,
    bar_ts              timestamptz      NOT NULL,
    weight_version      text             NOT NULL,
    regime              text,                        -- regime at bar_ts
    alpha_score         double precision NOT NULL,
    alpha_ci_lower      double precision,
    alpha_ci_upper      double precision,
    effective_n         double precision,
    n_features_active   integer,
    computed_at         timestamptz      NOT NULL DEFAULT now(),
    PRIMARY KEY (symbol, tf, bar_ts, weight_version)
);
SELECT create_hypertable('ensemble_alpha', 'bar_ts',
    chunk_time_interval => INTERVAL '3 months', if_not_exists => TRUE);
CREATE INDEX IF NOT EXISTS ensemble_alpha_symbol_tf_idx
    ON ensemble_alpha (symbol, tf, bar_ts DESC);
```

**`alpha_events`** — emission events (alpha crossed threshold):

```sql
CREATE TABLE IF NOT EXISTS alpha_events (
    event_id            text             NOT NULL,   -- SHA-256 content key
    symbol              text             NOT NULL,
    tf                  text             NOT NULL,
    bar_ts              timestamptz      NOT NULL,
    ensemble_version    text             NOT NULL,
    weight_version      text             NOT NULL,
    regime              text,
    alpha_score         double precision NOT NULL,
    alpha_ci_lower      double precision,
    alpha_ci_upper      double precision,
    effective_n         double precision,
    n_features_active   integer,
    emission_threshold  double precision,
    feature_contributions jsonb,                     -- {feature_name: contribution_value}
    emitted_at          timestamptz      NOT NULL DEFAULT now(),
    PRIMARY KEY (event_id)
);
SELECT create_hypertable('alpha_events', 'bar_ts',
    chunk_time_interval => INTERVAL '3 months', if_not_exists => TRUE);
CREATE INDEX IF NOT EXISTS alpha_events_symbol_tf_idx
    ON alpha_events (symbol, tf, bar_ts DESC);
```

Note: The alpha_events table was removed from Phase 138 scope ("alpha_events table not created (removed from scope during replan)" per STATE.md) — Phase 139 creates it.

---

## APR Keys Required (Migration 168, Section 2)

New keys to seed in `config_schema` and `config_state`:

| Key | Type | Seed | Description |
|-----|------|------|-------------|
| `alpha.ensemble.max_feature_weight` | float | 0.20 | Per-feature cap in IC Sharpe weight derivation. [conventional] |
| `alpha.ensemble.effective_n_gate` | float | 3.0 | Minimum effective N (inverse HHI of weights) required before alpha emission. [initial_estimate] |
| `alpha.ensemble.weight_version` | str | 'v1' | Version tag for weight snapshots. Bump to trigger re-solve. [operator_controlled] |
| `alpha.ensemble.lookahead_selection` | str | 'max_ic_sharpe' | Strategy for selecting lookahead per feature. [initial_estimate] |
| `alpha.ensemble.min_passing_features` | int | 3 | Minimum features with passes_walkforward=true to proceed. [initial_estimate] |
| `alpha.quant.threshold.5m` | float | 1.5 | Alpha emission threshold for 5m TF (composite z-score units). [initial_estimate] |
| `alpha.quant.threshold.15m` | float | 1.2 | Alpha emission threshold for 15m TF. [initial_estimate] |
| `alpha.quant.threshold.1h` | float | 1.0 | Alpha emission threshold for 1h TF. [initial_estimate] |
| `alpha.quant.threshold.1d` | float | 0.8 | Alpha emission threshold for 1d TF. [initial_estimate] |

All are APR-exempt-checked: none fall into schema identifiers, mathematical constants, or DAG topology. All are tunable thresholds/parameters. All go in `alpha.*` namespace per APR mandate.

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Equal weights across features | IC Sharpe weighted with LW shrinkage | Phase 139 introduces | Correct for feature correlation; prevents momentum cluster domination |
| Binary signal fired/not fired | Continuous alpha score with CI bounds | v3.0 | Enables probabilistic emission and downstream Kelly sizing |
| Researcher-defined confluence rules | Data-discovered weights via IC measurement | v3.0 Phase 138-139 | Eliminates confirmation bias |
| Plugin registry (138 plugins, ~15 independent views) | 61-feature typed function library + IC-weighted ensemble | Phase 137-139 | Truly independent factor exposure measured empirically |

**Deprecated/outdated:**
- `signal_events` as primary output: replaced by `alpha_events` in v3.0. The `signal_events` table still exists for v2.x operation but is not the output of Phase 139.
- `shadow_registry` binary promotion gates: replaced by continuous IC monitoring. Phase 139 produces alpha_events in shadow mode unconditionally — no binary promotion gate.

---

## Phase Structure Recommendation

Based on dependencies and testability, three plans in strict sequence:

**P1: DB Schema + APR + Pure Math Library + Tests**
- Migration 168 (ensemble_weights, ensemble_alpha, alpha_events DDL + APR keys)
- `src/intelligence/ensemble/` module (pure functions: feature_selector, covariance, weights, alpha_score)
- `topic_alpha_events()` in `stream_keys.py`
- OTel gauges for ensemble metrics in `observability/metrics.py`
- `tests/unit/test_ensemble_math.py` — LedoitWolf correctness, weight cap, effective_N, CI propagation

**P2: EnsembleBuilder Service**
- `services/ensemble_builder.py` (extends BaseBatch)
- Startup gate: feature_ic_scores has sufficient rows (>0 passes_walkforward=true rows)
- Reads `feature_ic_scores WHERE passes_walkforward=true AND is_pooled=false`
- Runs feature selection → covariance → LedoitWolf → weight derivation per (symbol,tf,regime)
- Writes to `ensemble_weights` (idempotent: ON CONFLICT DO NOTHING on PK)
- Computes `ensemble_alpha` for all historical `feature_vectors` bars (batch, vectorized)
- Writes to `ensemble_alpha` (ON CONFLICT DO NOTHING)
- Emits OTel gauges per (symbol, tf, regime)

**P3: AlphaEmitter Service + IC Discovery Report**
- `services/alpha_emitter.py` (extends BaseBatch)
- Reads `ensemble_alpha WHERE alpha_score > threshold AND effective_n >= gate`
- Enforces effective_N gate
- Writes to `alpha_events` (idempotent: ON CONFLICT DO NOTHING on event_id PK)
- Publishes to Kafka `alpha.events` topic using `KafkaProducerClient.publish(msg=...)`
- Writes `docs/analysis/ic-discovery-report.md` and `docs/analysis/ic-discovery-report.json`
- IC discovery report content: passing features per (symbol, tf, regime), weight vectors, effective_N per stratum, alpha event count, emission rate

Kelly criterion, trade framing, portfolio construction: Phase D in the build sequence. Not Phase 139 scope.

---

## Open Questions

1. **full corpus availability**
   - What we know: feature_vectors has 0 rows (junk data purged 2026-06-23); backfill_feature_factory requires ~20-30h for full 58-symbol run
   - What's unclear: Phase 138 P8 (corpus run) is the prerequisite for Phase 139. Phase 139 cannot produce ensemble_weights or ensemble_alpha without feature_vectors rows. The planner must determine whether to gate Phase 139 plans on P8 completion or whether Phase 139 development can proceed in parallel with P8 execution (likely yes — code development is independent of data availability).
   - Recommendation: Phase 139 P1 and P2 can be written and unit-tested without data. P3 corpus runs require data. Run Phase 138 P8 (backfill + IC engine full run) concurrently with Phase 139 P1/P2 development. Phase 139 P3 is gated on Phase 138 P8 complete.

2. **effective_N gate calibration**
   - What we know: effective_N = 1/sum(w^2) — the inverse HHI. Gate is `>= 3.0`. With 61 features and a 0.20 cap, max effective_N is 5 (since 5 × 0.20 = 1.0). With realistic IC distributions, expect effective_N of 3-8.
   - What's unclear: Whether 3.0 is the right floor for shadow-mode emission. It is a conservative gate.
   - Recommendation: Seed at 3.0 as APR `[initial_estimate]`. Measure empirically once corpus runs complete and adjust.

3. **Kafka topic partitioning for alpha.events**
   - What we know: `stream_keys.py` pattern — one `topic_alpha_events(env_name)` function.
   - What's unclear: Number of partitions needed. AlphaEmitter runs as a batch job, not a streaming service. At most 58 symbols × 4 TFs × 4 regimes = 928 distinct emitter streams. Kafka default of 1 partition is fine for shadow mode.
   - Recommendation: 1 partition, standard retention (Kafka is transport not storage). Add retention.bytes cap matching the pattern in other Phase 104 topics.

---

## Sources

### Primary (HIGH confidence)
- `docs/intelligence/intelligence-alphaengine.md` — AlphaEngine concept doc, vocabulary, build sequence, effective_N definition, content-key inputs for alpha_events
- `services/ic_engine.py` — full implementation verified in codebase; APR loading, OTel patterns, ON CONFLICT pattern, D-06 emission pattern
- `src/core/agent/base_batch.py` — BaseBatch contract, content_key(), _emit_completion()
- `services/_batch_utils.py` — load_config_service_sync pattern
- `production/migrations/161_alpha_ic_apr_keys.sql` — APR seed migration template with doc standards
- `sklearn.covariance.LedoitWolf` docs (Context7: `/websites/scikit-learn_stable`) — confirmed `fit(X)` input shape, `.covariance_`, `.shrinkage_` attributes
- `.planning/STATE.md` — Phase 138 decisions, council review findings, data state
- `CLAUDE.md` — KafkaProducerClient.publish kwarg, asyncpg JSONB rules, OTel metric types, exception naming

### Secondary (MEDIUM confidence)
- `docs/plans/2026-06-20-alphaengine-ic-spec.md` — IC methodology spec, lookahead selection rule, feature universe pre-specification requirement
- `docs/plans/2026-06-20-alphaengine-architecture.md` — three-layer architecture, feature table

### Tertiary (LOW confidence)
- Transaction cost threshold seed values (1.5 / 1.2 / 1.0 / 0.8) — [initial_estimate] based on typical ETF market-impact literature. Not verified against this project's specific corpus. Must be updated post-calibration.

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — sklearn LedoitWolf verified via Context7; all other libraries confirmed present in codebase
- Architecture: HIGH — BaseBatch pattern, APR pattern, stream_keys pattern all verified in existing code
- DB schema: HIGH — follows exact pattern from migration 160 (feature_ic_scores); hypertable and content-key patterns confirmed
- Pitfalls: HIGH — KafkaProducerClient kwarg from CLAUDE.md; effective_N formula from alphaengine.md; double-z-score trap from IC spec
- Transaction cost thresholds: LOW — seed values are conventional estimates; need corpus data to calibrate

**Research date:** 2026-06-23
**Valid until:** 2026-07-23 (sklearn LedoitWolf API stable; internal patterns stable)
