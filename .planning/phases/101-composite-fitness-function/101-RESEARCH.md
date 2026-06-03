# Phase 101: Composite Fitness Function - Research

**Researched:** 2026-06-02
**Domain:** Multi-dimensional agent fitness evaluation + shadow governance integration
**Confidence:** HIGH

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

- **D-01:** `agent_fitness` is a TimescaleDB hypertable. One row per `(agent_id, evaluated_at)`. Full history preserved. Chunk interval: 7 days, compression after 7 days. `DISTINCT ON (agent_id) ORDER BY evaluated_at DESC` gives current state.
- **D-02:** Columns: `agent_id TEXT`, `evaluated_at TIMESTAMPTZ`, `accuracy_score DOUBLE PRECISION`, `novelty_score DOUBLE PRECISION`, `calibration_score DOUBLE PRECISION`, `regime_score DOUBLE PRECISION`, `efficiency_score DOUBLE PRECISION`, `composite_score DOUBLE PRECISION`, `n_resolved INTEGER`, `promotion_ready BOOLEAN`, `dimensions_jsonb JSONB`. All dimension scores nullable.
- **D-03:** FIT-06 variance gate uses `stddev(composite_score)` across most recent row per live agent. Population minimum: 5 agents with valid composite. Fewer than 5 = `insufficient_population`.
- **D-04:** Geometric mean formula: `composite = (accuracy × novelty × calibration × regime × efficiency)^(1/5)`. Zero in any dimension collapses composite to 0. No compensation logic.
- **D-05:** Composite not emitted until all 5 dimensions clear minimum N. `composite_score = NULL` means not yet evaluable.
- **D-06:** Per-dimension minimum N as `FITNESS_*` constants in `Settings`. Defaults: `FITNESS_ACCURACY_MIN_N = 50`, `FITNESS_CALIBRATION_MIN_N = 30`, `FITNESS_REGIME_MIN_N_PER_REGIME = 10`, `FITNESS_REGIME_MIN_REGIMES = 2`, `FITNESS_EFFICIENCY_MIN_N = 20`.
- **D-07:** Separate `fitness_auditor.py` oneshot script. `fitness_auditor` reads `signal_ledger + signal_outcomes + llm_calls`, writes `agent_fitness`. `shadow_auditor.py` reads `agent_fitness` for gate decisions.
- **D-08:** `PromotionGate` and `DemotionGate` as pure stateless classes in `src/intelligence/ai/fitness/gates.py`. No DB access. Return `(bool, str | None)`.
- **D-09:** Staleness check: if latest `agent_fitness.evaluated_at` is older than `FITNESS_STALENESS_THRESHOLD_HOURS = 4`, `shadow_auditor` skips that agent and logs a warning.
- **D-10:** `fitness_auditor` runs every 60 minutes. `shadow_auditor` remains 30 minutes.
- **D-11:** Novelty = Pearson r on pairwise `pnl_r` vectors across overlapping resolved `signal_id`s. Score = `1 - max(|r|)` across all live agent pairs.
- **D-12:** Minimum 20 overlapping resolved signals for meaningful Pearson r. Below 20: r treated as 0 (benefit of doubt). Population = 1: `novelty_score = 1.0`.
- **D-13:** Novelty computed at `fitness_auditor` level as a second pass after per-agent dimensions.
- **D-14: PromotionGate** — ALL criteria must pass: (1) `composite_score IS NOT NULL`, (2) `composite_score > 0.05` in every evaluated regime, (3) `n_resolved >= FITNESS_ACCURACY_MIN_N`, (4) `stddev(composite_score) < 0.02` across last 3 audit cycles, (5) `novelty_score > 0.15`, (6) sets `shadow_registry.promotion_ready = TRUE` + emits metric. No auto-promotion.
- **D-15: DemotionGate** — ANY trigger fires: (1) `composite_score < promotion_baseline * 0.80`, (2) `novelty_score < 0.15` for 2 consecutive cycles, (3) `regime_score = 0.0` in newly dominant regime for 2 consecutive cycles, (4) parse failure rate < 0.80 over rolling 50 calls.

### Claude's Discretion

- Specific normalization approach for each dimension to [0, 1] (sigmoid, clamp-and-normalize, Brier inversion, etc.)
- Whether `efficiency_score` uses `tokens_est` alone or combines with `latency_ms`
- Systemd unit name and timer interval for `fitness_auditor`

### Deferred Ideas (OUT OF SCOPE)

- Adversarial coevolution (skeptic agents vs. alpha agents)
- Adaptive operator selection (which reproductive operator produces fittest offspring)
- Fitness UI / operator annotation interface
- LLM-directed fitness interpretation
</user_constraints>

---

## Summary

Phase 101 builds a 5-dimensional composite fitness evaluator for swarm AI agents and wires it into the existing shadow governance lifecycle. The existing `shadow_auditor.py` uses a 1D gate (`bootstrap_ci_lower(pnl_r) > 0 AND n >= 100`); this phase replaces it with a 5-axis geometric mean composite and pure `PromotionGate`/`DemotionGate` classes.

The key structural insight from reading the codebase: the `shadow_auditor.py` already handles the oneshot pattern, DB pool, OTel counters, and `job_completed_total` emission correctly. The `fitness_auditor.py` follows this same pattern exactly. The `shadow_auditor.py` integration is a surgical replacement of `_check_promotion` / `_check_demotion` calls with calls into `PromotionGate(fitness_row).can_promote()` and `DemotionGate(fitness_row).should_demote()` after a staleness check.

The `shadow_registry` table currently has `component_type IN ('i7_plugin', 'swarm_agent')`. All swarm agents are skipped in the current audit loop (`ctype == "swarm_agent"` early-continue). Phase 101 changes this: `agent_fitness` is keyed by `agent_id` (not `component_name`), and the gate logic for swarm agents will be via the new fitness path, not the inline bootstrap path. The existing swarm agent skip must be reconciled with the new fitness-based path.

**Primary recommendation:** Build `fitness_auditor.py` as a direct clone of `shadow_auditor.py`'s structure; add `agent_fitness` migration with the exact D-02 column set; implement 5 pure dimension calculator functions in `src/intelligence/ai/fitness/`; then replace the gate logic in `shadow_auditor.py` with `PromotionGate`/`DemotionGate` calls.

---

## Standard Stack

### Core

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `asyncpg` | project-standard | DB reads/writes for `agent_fitness`, `llm_calls`, `signal_ledger_full` | All DB code in this project uses asyncpg; JSONB dict passthrough, no json.dumps |
| `numpy` | project-standard | Pearson r (np.corrcoef), bootstrap resampling, geometric mean | Already used in `stats_utils.py` and throughout intelligence layer |
| `scipy.stats` | project-standard | Brier score computation | Available via requirements.txt; `sklearn.calibration.calibration_curve` also viable |
| `structlog` | project-standard | Logging to `logs/fitness_auditor.log` | Project-wide pattern |
| `opentelemetry` | project-standard | `FITNESS_*` metrics via `src/observability/metrics.py` | Prometheus_client fully removed in Phase 83; OTel only |

### Supporting

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `sklearn.metrics` | project-standard | `brier_score_loss` for calibration dimension | Single function call; avoids hand-rolling |
| `scipy.stats.pearsonr` | project-standard | Pearson r with significance for novelty dimension | Cross-validates numpy corrcoef |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| `sklearn.metrics.brier_score_loss` | Hand-rolled `mean((prob - outcome)^2)` | Sklearn is one import; hand-rolled is acceptable but adds test surface |
| `numpy.corrcoef` | `scipy.stats.pearsonr` | scipy gives p-value; numpy is simpler; either works since we only need r |

**Installation:** No new packages required. All dependencies already in requirements.txt.

---

## Architecture Patterns

### Recommended Project Structure

```
src/intelligence/ai/fitness/
├── __init__.py
├── accuracy.py          # accuracy_score() calculator
├── calibration.py       # calibration_score() calculator
├── regime.py            # regime_score() calculator
├── efficiency.py        # efficiency_score() calculator
├── novelty.py           # novelty_score() per-agent + population pass
├── composite.py         # composite_score() geometric mean + NULL guard
└── gates.py             # PromotionGate, DemotionGate pure classes

services/
└── fitness_auditor.py   # Oneshot: reads signal_ledger + llm_calls, writes agent_fitness

production/migrations/
└── 115_agent_fitness.sql   # agent_fitness hypertable + shadow_registry.promotion_baseline
```

### Pattern 1: Oneshot Script Structure (clone of shadow_auditor.py)

**What:** Async oneshot, `asyncpg` pool, `_run_audit()`, `main()` with `job_completed_total`
**When to use:** All timer-triggered oneshots in this project follow this pattern

```python
# Source: services/shadow_auditor.py (direct analog)
async def _amain() -> None:
    settings = Settings()
    pool = await create_db_pool(settings.database_url, min_size=2, max_size=5)
    try:
        await _run_audit(pool, settings.env_name)
    finally:
        await pool.close()

def main() -> None:
    try:
        asyncio.run(_amain())
        JOB_COMPLETED_TOTAL.add(1, {"job": "fitness-auditor", "status": "success"})
    except Exception as exc:
        JOB_COMPLETED_TOTAL.add(1, {"job": "fitness-auditor", "status": "failure"})
        raise exc
    finally:
        flush_and_shutdown_metrics()
```

**Critical:** The systemd unit name `%n` suffix (kebab-case) MUST match the `job=` label in `JOB_COMPLETED_TOTAL`. If unit is `indicagent-fitness-auditor.service`, then `job="fitness-auditor"`.

### Pattern 2: Pure Calculator Function Signature

**What:** Dimension calculators are pure functions, no DB, no side effects, directly testable

```python
# Source: design principle from CONTEXT.md D-07 + D-08
def accuracy_score(
    pnl_r_values: list[float],
    outcomes: list[str],
    min_n: int,
) -> float | None:
    """Returns None if n < min_n (not yet computable)."""
    if len(pnl_r_values) < min_n:
        return None
    ...
```

### Pattern 3: PromotionGate / DemotionGate Pure Classes

```python
# Source: CONTEXT.md D-08
class PromotionGate:
    def can_promote(self, fitness_row: dict, history: list[dict]) -> tuple[bool, str | None]:
        """Return (decision, reason). reason is None on pass, string on block."""
        ...

class DemotionGate:
    def should_demote(self, fitness_row: dict, history: list[dict]) -> tuple[bool, str | None]:
        """Return (decision, reason). reason is None if no trigger, string naming trigger."""
        ...
```

### Pattern 4: Geometric Mean with NULL Guard

```python
# CONTEXT.md D-04, D-05
import math

def composite_score(
    accuracy: float | None,
    novelty: float | None,
    calibration: float | None,
    regime: float | None,
    efficiency: float | None,
) -> float | None:
    scores = [accuracy, novelty, calibration, regime, efficiency]
    if any(s is None for s in scores):
        return None  # Not yet evaluable — D-05
    return math.pow(math.prod(scores), 1.0 / 5)
```

### Anti-Patterns to Avoid

- **Inline gate logic in shadow_auditor**: The current `_should_promote` / `_should_demote` functions must be fully replaced by `PromotionGate` / `DemotionGate` — do not leave parallel gate paths.
- **Swarm agent early-continue without fitness check**: The current `if ctype == "swarm_agent": continue` in `_run_audit` must be updated — swarm agents are now the primary fitness evaluation target.
- **`json.dumps()` on JSONB**: Pass Python dicts directly to asyncpg for `dimensions_jsonb`. Never serialize to string first.
- **`datetime.now()` without UTC**: Use `datetime.now(UTC)` everywhere. All timestamps must be timezone-aware.
- **Hardcoded threshold constants**: All `FITNESS_*` thresholds must be `Settings` fields, not module-level constants. The shadow_auditor uses `row["min_n"]` from DB; fitness_auditor reads from `Settings`.
- **`format_iso_ts()` bypass**: Use `format_iso_ts(dt)` from `service_utils.py` for any Kafka/JSON timestamp serialization.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Brier score | Manual `mean((p-o)^2)` loop | `sklearn.metrics.brier_score_loss` | Edge cases: clipping, empty arrays, dtype handling |
| Pearson r | Manual covariance/std calc | `numpy.corrcoef` or `scipy.stats.pearsonr` | Numerical stability for near-zero variance vectors |
| Bootstrap CI | New bootstrap implementation | `src/core/stats_utils.bootstrap_ci_lower` | Already used by shadow_auditor; proven, seeded RNG |
| Geometric mean | `reduce(multiply)` with custom guard | `math.prod()` + `math.pow()` with NULL guard | Cleaner; `math.prod([])` returns 1.0 (handle empty case explicitly) |
| TimescaleDB hypertable | Plain postgres table | `SELECT create_hypertable(...)` | Compression + retention policies require hypertable |

**Key insight:** The calibration and accuracy dimensions share data sources but measure different things. Accuracy uses `pnl_r` (outcome quality); calibration uses `confidence` vs `outcome` binary (stated probability quality). Don't conflate them.

---

## Common Pitfalls

### Pitfall 1: swarm_agent vs i7_plugin in shadow_registry

**What goes wrong:** The current `shadow_auditor._run_audit()` has an early-continue for `ctype == "swarm_agent"`. Swarm agents (skeptic_v1, etc.) are enrolled in `shadow_registry` but skipped for fitness evaluation. Phase 101 introduces `agent_fitness` keyed by `agent_id` — this is a different key than `component_name` in `shadow_registry`.
**Why it happens:** The current 1D gate is designed for I7 plugins that generate `signal_ledger` rows by `setup_plugin`. Swarm agents don't generate signal rows directly — they generate `llm_calls` rows.
**How to avoid:** In Phase 101, the `shadow_auditor.py` refactor must distinguish between `i7_plugin` components (use old signal-ledger path or new fitness path) and `swarm_agent` components (use new fitness path exclusively). The `component_type = 'ai_agent'` may need to be added to shadow_registry CHECK constraint to separate swarm agents from I7 plugins.
**Warning signs:** Fitness auditor skips swarm agents because no `signal_ledger` rows match — this is expected and correct. The fitness auditor reads `llm_calls` for efficiency + parse failure, not signal_ledger, for swarm agents.

### Pitfall 2: agent_id key mismatch

**What goes wrong:** `signal_ledger.setup_plugin` = `"trad_BullishEngulfing"` but `llm_calls.agent_id` = `"skeptic_v1"`. The two tables use different agent identification. Fitness is computed per `agent_id` but signal data is keyed by `setup_plugin`.
**Why it happens:** I7 plugins don't have `agent_id`; LLM swarm agents don't have `setup_plugin` rows. Fitness for I7 plugins reads from `signal_ledger_full WHERE setup_plugin = ?`; fitness for swarm agents reads from `llm_calls WHERE agent_id = ?`.
**How to avoid:** The fitness auditor must handle two query paths based on `component_type`. For I7 plugins: `signal_ledger_full` is the source. For swarm agents: `llm_calls` is the primary source for efficiency/parse failure; `pnl_r` from `llm_calls` is used for accuracy/novelty if `outcome IS NOT NULL`.
**Warning signs:** An agent has n_resolved=0 despite being active — check whether query uses wrong key.

### Pitfall 3: hmm_regime_at_fire integer encoding

**What goes wrong:** `signal_ledger.hmm_regime_at_fire` is an `integer`, not a text regime label. The regime_score dimension must group by this integer value, not a string like `"trending"`.
**Why it happens:** The HMM state is encoded as 0/1/2/... not as named regimes. The mapping to named regimes is not stored in signal_ledger.
**How to avoid:** For regime_score, group by `hmm_regime_at_fire` integer value directly. The requirement is `>= FITNESS_REGIME_MIN_REGIMES` distinct integer values with `>= FITNESS_REGIME_MIN_N_PER_REGIME` signals each.
**Warning signs:** All signals show `hmm_regime_at_fire = NULL` — this means the signal predates the column or was written by a code path that didn't populate it.

### Pitfall 4: Novelty second-pass requires full population snapshot

**What goes wrong:** Computing novelty requires all live agents' resolved pnl_r vectors simultaneously. If novelty is computed per-agent independently, the pairwise Pearson r cannot be calculated.
**Why it happens:** Novelty is a population-level metric, not per-agent. It must be computed as a second pass after all per-agent pnl_r vectors are fetched.
**How to avoid:** In `_run_fitness_audit()`, first fetch all agents' `pnl_r` vectors. Then compute accuracy/calibration/regime/efficiency per agent. Then run the pairwise novelty pass across the full population. Store results back per agent.
**Warning signs:** `novelty_score = 1.0` for all agents when population > 1 — indicates pairwise comparison is not running.

### Pitfall 5: Calibration requires confidence values

**What goes wrong:** The Brier score requires `(stated_confidence, binary_outcome)` pairs. `signal_ledger.cis_score` is the raw CIS confidence at fire time; `llm_calls.confidence` is the LLM-stated confidence. For I7 plugins, use `cis_score` from `signal_ledger`. For swarm agents, use `confidence` from `llm_calls`. The binary outcome is `1 if outcome in WIN_OUTCOMES else 0`.
**Why it happens:** Two different confidence sources for two different component types.
**How to avoid:** Explicitly select the right confidence source in the DB query based on `component_type`.
**Warning signs:** Brier score is always 0.25 (random baseline) — indicates confidence values are all 0.5 or NULL.

### Pitfall 6: Geometric mean collapses on zero efficiency

**What goes wrong:** `efficiency_score = 0.0` is mathematically valid (infinite token cost relative to fitness) but collapses the composite to 0. An agent with high accuracy/novelty/calibration/regime but zero efficiency is non-promotable.
**Why it happens:** Geometric mean penalizes structural weaknesses. An agent with no `llm_calls` rows has undefined efficiency — this must return `None`, not 0.0. Only return 0.0 if there IS data but efficiency is genuinely zero.
**How to avoid:** Return `None` from `efficiency_score()` when `n < FITNESS_EFFICIENCY_MIN_N`. Return `0.0` only when data is sufficient but the computed score is genuinely zero.
**Warning signs:** Composite is NULL for an agent with all other dimensions computed — check efficiency MIN_N gate.

### Pitfall 7: DemotionGate promotion_baseline column not yet in shadow_registry

**What goes wrong:** D-15 trigger 1 requires `shadow_registry.promotion_baseline DOUBLE PRECISION` to store the composite score at time of promotion. This column does not exist in migration 077 or any subsequent migration.
**Why it happens:** The current shadow_registry was designed for 1D gate metrics only.
**How to avoid:** Migration 115 (or similar) must `ALTER TABLE shadow_registry ADD COLUMN IF NOT EXISTS promotion_baseline DOUBLE PRECISION`. This is called out in CONTEXT.md code context explicitly.
**Warning signs:** `DemotionGate` trigger 1 cannot be evaluated because `promotion_baseline` is NULL for all live agents on first deploy — this is expected; trigger 1 is a no-op until a promotion occurs under the new system.

---

## Code Examples

### Query: Fetch resolved signals for accuracy/calibration/regime dimensions

```sql
-- Source: signal_ledger_full view (migration 095)
SELECT
    sl.signal_id,
    so.pnl_r,
    so.outcome,
    sl.cis_score,
    sl.hmm_regime_at_fire
FROM signal_ledger sl
JOIN signal_outcomes so ON sl.signal_id = so.signal_id
WHERE sl.setup_plugin = $1          -- agent_id for I7 plugins
  AND so.outcome IS NOT NULL
  AND so.outcome NOT IN ('never_activated', 'ttl_expired_behind')
ORDER BY sl.timestamp DESC
```

### Query: Fetch LLM call data for efficiency + parse failure dimensions

```sql
-- Source: migrations 019 + 087
SELECT
    agent_id,
    latency_ms,
    tokens_est,
    parse_success,
    confidence,
    outcome,
    pnl_r
FROM llm_calls
WHERE agent_id = $1
  AND called_at > NOW() - INTERVAL '90 days'
ORDER BY called_at DESC
LIMIT 200
```

### Query: Write agent_fitness row

```python
# asyncpg pattern — dict for JSONB, no json.dumps()
await conn.execute("""
    INSERT INTO agent_fitness (
        agent_id, evaluated_at,
        accuracy_score, novelty_score, calibration_score,
        regime_score, efficiency_score, composite_score,
        n_resolved, promotion_ready, dimensions_jsonb
    ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
""",
    agent_id,
    datetime.now(UTC),
    accuracy, novelty, calibration, regime, efficiency, composite,
    n_resolved, promotion_ready,
    dimensions_dict,  # dict, not json.dumps(dict)
)
```

### Query: FIT-06 variance gate

```sql
-- Compute discriminative power across live agents
WITH latest AS (
    SELECT DISTINCT ON (agent_id) agent_id, composite_score
    FROM agent_fitness
    WHERE composite_score IS NOT NULL
    ORDER BY agent_id, evaluated_at DESC
)
SELECT
    COUNT(*) AS population_size,
    STDDEV(composite_score) AS composite_stddev
FROM latest
```

### Brier Score computation

```python
# Source: sklearn.metrics.brier_score_loss
# outcome_binary: 1 for win (target_1, target_1_2, target_full), 0 for loss
from sklearn.metrics import brier_score_loss

WIN_OUTCOMES = {"target_1", "target_1_2", "target_full"}

def calibration_score(
    confidence_values: list[float],
    outcomes: list[str],
    min_n: int,
) -> float | None:
    if len(confidence_values) < min_n:
        return None
    binary = [1.0 if o in WIN_OUTCOMES else 0.0 for o in outcomes]
    brier = brier_score_loss(binary, confidence_values)
    return 1.0 - brier  # Invert: lower Brier = higher calibration score
```

### Pearson r for novelty

```python
# numpy approach — direct corrcoef
import numpy as np

def _pearson_r(vec_a: list[float], vec_b: list[float]) -> float:
    """Pearson r on aligned pnl_r vectors. Returns 0.0 if insufficient overlap."""
    if len(vec_a) < 20 or len(vec_b) < 20:
        return 0.0
    a = np.array(vec_a)
    b = np.array(vec_b)
    if np.std(a) == 0 or np.std(b) == 0:
        return 0.0
    return float(np.corrcoef(a, b)[0, 1])
```

### Settings constants pattern (existing project pattern)

```python
# Source: src/config/settings.py — Field() with validation_alias
fitness_accuracy_min_n: int = Field(
    default=50,
    validation_alias="FITNESS_ACCURACY_MIN_N",
)
fitness_calibration_min_n: int = Field(
    default=30,
    validation_alias="FITNESS_CALIBRATION_MIN_N",
)
fitness_regime_min_n_per_regime: int = Field(
    default=10,
    validation_alias="FITNESS_REGIME_MIN_N_PER_REGIME",
)
fitness_regime_min_regimes: int = Field(
    default=2,
    validation_alias="FITNESS_REGIME_MIN_REGIMES",
)
fitness_efficiency_min_n: int = Field(
    default=20,
    validation_alias="FITNESS_EFFICIENCY_MIN_N",
)
fitness_staleness_threshold_hours: int = Field(
    default=4,
    validation_alias="FITNESS_STALENESS_THRESHOLD_HOURS",
)
```

---

## Dimension Normalization Recommendations

These fall under "Claude's Discretion" in CONTEXT.md. Recommendations based on domain knowledge and the constraint that all outputs must be in [0, 1]:

### Accuracy: bootstrap_ci_lower mapped to [0, 1]

`bootstrap_ci_lower` returns a float in `(-inf, +inf)`. Recommended: sigmoid normalization centered at 0.

```python
import math

def normalize_accuracy(ci_lower: float) -> float:
    """Sigmoid: ci_lower=0 -> 0.5, ci_lower=+inf -> 1.0, ci_lower=-inf -> 0.0"""
    return 1.0 / (1.0 + math.exp(-ci_lower * 4))  # scale factor 4 = moderate slope
```

Alternative: `clamp(ci_lower, -0.5, +0.5)` then rescale to [0,1]. Sigmoid is preferred because it preserves relative ordering across the full range.

### Calibration: Brier score inversion

Brier score is in [0, 1] where 0 = perfect. `1 - brier_score` maps to [0, 1] where 1 = perfect.

```python
calibration = 1.0 - brier_score_loss(binary_outcomes, confidence_values)
```

No additional normalization needed — already in [0, 1].

### Regime specificity: variance-based penalty

Compute mean pnl_r per distinct `hmm_regime_at_fire` value. Score = `1 - stddev(per_regime_means) / mean(abs(per_regime_means))` clamped to [0, 1]. A regime-agnostic agent (equal performance across regimes) scores 1.0. An agent that only works in one regime scores low.

Alternative (simpler): require minimum performance in EACH covered regime, score = fraction of regimes where `bootstrap_ci_lower > 0`.

**Recommendation:** Use the fraction approach — it directly measures the "knows its limits" property described in the eAI doc. Score = `n_passing_regimes / n_total_regimes` where a regime passes if `n >= FITNESS_REGIME_MIN_N_PER_REGIME` AND `bootstrap_ci_lower(pnl_r_in_regime) > -0.1`.

### Efficiency: tokens_est + optional latency_ms

**Recommendation:** Use `tokens_est` as the primary efficiency input since it directly measures compute cost. `latency_ms` is a secondary concern (already tracked separately via OTel histograms).

```python
def efficiency_score(
    composite_fitness: float,  # Pass the computed composite before efficiency
    tokens_est_values: list[int],
    min_n: int,
) -> float | None:
    if len(tokens_est_values) < min_n:
        return None
    median_tokens = float(np.median(tokens_est_values))
    if median_tokens <= 0:
        return 1.0  # No token usage = maximum efficiency
    # Score = fitness / normalized_tokens. Normalize tokens relative to 1000-token baseline.
    raw = composite_fitness / (median_tokens / 1000.0)
    return min(1.0, raw)  # Cap at 1.0
```

Note: efficiency_score depends on the other 4 dimensions. This creates a dependency order: compute accuracy/novelty/calibration/regime first, then efficiency uses their composite as numerator. This is architecturally acceptable since composite is called last.

**Simpler alternative**: Normalize median_tokens against a max_tokens ceiling (e.g. 4096), invert: `efficiency = 1.0 - (median_tokens / 4096)`. This is independent of fitness but doesn't measure "fitness per cost" directly.

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| 1D promotion gate: `n>=100 AND bootstrap_ci_lower>0` | 5D composite: accuracy + novelty + calibration + regime + efficiency | Phase 101 | Prevents single-metric gaming; collapses on structural weakness |
| Inline gate logic in shadow_auditor | Pure `PromotionGate`/`DemotionGate` classes | Phase 101 | Directly unit-testable without DB |
| Shadow auditor skips swarm agents | Fitness auditor evaluates swarm agents via llm_calls | Phase 101 | Swarm agents now have measurable fitness |
| No fitness history | agent_fitness hypertable | Phase 101 | Phase 102 gene extraction reads fitness trajectories |

**Deprecated/outdated:**
- `_should_promote(n, ci_lower, min_n, min_ev_r)` in `shadow_auditor.py`: replaced by `PromotionGate.can_promote()`
- `_should_demote(new_count, min_evaluations)` in `shadow_auditor.py`: replaced by `DemotionGate.should_demote()`
- Inline `bootstrap_ci_lower` call in `_check_promotion`: moved to accuracy dimension calculator

---

## Open Questions

1. **component_type for swarm agents in fitness path**
   - What we know: `shadow_registry.component_type` currently has `CHECK (component_type IN ('i7_plugin', 'swarm_agent'))`. Swarm agents need fitness evaluation but their data source is `llm_calls`, not `signal_ledger`.
   - What's unclear: Should `agent_fitness.agent_id` map directly to `shadow_registry.component_name`? Or is there a separate `agent_id` concept? Currently `shadow_registry.component_name = 'skeptic_v1'` and `llm_calls.agent_id = 'skeptic_v1'` — they match.
   - Recommendation: `agent_id` in `agent_fitness` IS `component_name` in `shadow_registry`. The planner should explicitly map these. In `shadow_auditor.py`, replace the `ctype == "swarm_agent"` early-continue with a staleness check against `agent_fitness` for all agents.

2. **Efficiency score chicken-and-egg with composite**
   - What we know: D-04 says composite = geometric mean of 5 dimensions. Efficiency is one of the 5. But the recommended efficiency formula uses composite fitness as numerator (fitness per token).
   - What's unclear: Does efficiency use composite (circular) or use a simpler standalone formula?
   - Recommendation: Use the simpler standalone formula: `efficiency = 1.0 - clamp(median_tokens / FITNESS_EFFICIENCY_TOKEN_CEILING, 0, 1)` where `FITNESS_EFFICIENCY_TOKEN_CEILING = 4096` (a Settings constant). This avoids circularity entirely. The "fitness per token" framing is described in the eAI doc but the standalone normalization is mathematically cleaner.

3. **I7 plugins have no llm_calls rows — efficiency undefined**
   - What we know: I7 plugins (`trad_BullishEngulfing`, etc.) don't call LLMs. `llm_calls.agent_id` has no rows for I7 plugin names.
   - What's unclear: How is efficiency computed for I7 plugins?
   - Recommendation: For `component_type = 'i7_plugin'`, efficiency_score = `1.0` by convention (pure computation, no LLM cost). Only swarm agents (LLM callers) have meaningful efficiency metrics. This should be documented in the calculator and tested explicitly.

4. **Regime specificity for swarm agents vs I7 plugins**
   - What we know: `signal_ledger.hmm_regime_at_fire` captures regime for I7 plugins. For swarm agents, regime is `llm_calls.regime` (a TEXT field like 'trending', 'ranging', 'volatile').
   - What's unclear: Are these the same encoding? `hmm_regime_at_fire` is an INTEGER (HMM state index); `llm_calls.regime` is a TEXT label.
   - Recommendation: The regime dimension uses the appropriate field per component type. For I7 plugins: `hmm_regime_at_fire` integer grouping. For swarm agents: `llm_calls.regime` text grouping. Both satisfy the "distinct regimes" requirement.

---

## Sources

### Primary (HIGH confidence)

- `services/shadow_auditor.py` - complete oneshot pattern, gate functions, DB queries, OTel emission; direct template for `fitness_auditor.py`
- `src/core/stats_utils.py` - `bootstrap_ci_lower` implementation; reuse directly in accuracy dimension
- `production/migrations/077_shadow_governance.sql` - `shadow_registry` exact schema; `promotion_baseline` column missing (confirmed)
- `production/migrations/095_signal_ledger_split.sql` - `signal_ledger`, `signal_outcomes`, `signal_ledger_full` view; exact column names
- `production/migrations/019_llm_intelligence_layer.sql` + `087_llm_calls_agent_attrs.sql` - `llm_calls` exact schema: `agent_id`, `latency_ms`, `tokens_est`, `parse_success`, `confidence`, `outcome`, `pnl_r`
- `src/config/settings.py` - `Settings` Field pattern; no `FITNESS_*` constants exist yet (confirmed)
- `src/observability/metrics.py` - `SHADOW_*` metrics pattern; `point_gauge`, `counter`, `gauge` factory functions
- `production/systemd/indicagent-shadow-auditor.service` + `.timer` - exact systemd unit template
- `docs/ideas/ai-03-evolvable-ai-agents.md` - eAI design principles; fitness dimensions described at lines 100-115

### Secondary (MEDIUM confidence)

- `production/migrations/086_validation_results.sql` - confirms `promotion_evidence JSONB` already added to `shadow_registry`; shows existing ALTER TABLE IF NOT EXISTS pattern for safe column additions
- `.planning/phases/101-composite-fitness-function/README.md` - plan breakdown; PromotionGate/DemotionGate criteria; confirmed 6-plan structure

### Tertiary (LOW confidence)

- Normalization approach recommendations (sigmoid for accuracy, fraction for regime) - based on domain knowledge; planner should validate against team preference

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH - all libraries already in project; no new deps required
- Architecture patterns: HIGH - verified against existing oneshot pattern in shadow_auditor.py
- DB schema: HIGH - read all migrations directly; exact column names confirmed
- Dimension normalization: MEDIUM - "Claude's Discretion" area; recommendations are sound but planner may prefer alternatives
- Pitfalls: HIGH - all identified from direct code inspection (not speculation)

**Research date:** 2026-06-02
**Valid until:** 2026-07-02 (stable codebase; schema migrations unlikely to change these tables)
