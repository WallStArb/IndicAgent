# Phase 114: Occam's Razor - Context

**Gathered:** 2026-06-03
**Status:** Ready for planning

<domain>
## Phase Boundary

Implement complexity-aware model selection for all shadow ML agents. The Occam's Razor Evaluator (ORE) builds simple baselines (linear/logistic/rule-based), runs both complex and baseline models on identical data, and applies a statistical test with complexity penalty. Fail-closed: reject if baseline wins or ties.

**In scope:**
- `BaselineBuilder` protocol and concrete implementations (`LinearBaseline`, `RuleBaseline`, `RandomBaseline`)
- `_BASELINES` registry mapping agent prefixes to appropriate builders
- `OccamRazorEvaluator` — shadow-only AI agent that runs statistical tests
- `ModelScore` dataclass — performance metrics (sharpe, win_rate, pnl_r, complexity_score, n)
- `OccamResult` dataclass — comparison result with winner and recommendation
- Bootstrap CI implementation for statistical significance testing
- Complexity score computation (params × latency × train_time, log-transformed)
- Adjusted delta calculation (raw_sharpe_delta - penalty_weight × complexity_penalty)
- Shadow registry enhancement: `rejection_reason`, `complexity_score`, `last_occam_check` columns
- Automatic rejection flow: UPDATE `shadow_registry.is_shadow = TRUE` on baseline win/tie
- OTel metrics: evaluations, rejections, complexity_ratio, sharpe_delta
- Integration into `config/agents.yaml` as `alpha` group agent

**Out of scope:**
- Multi-baseline comparison (single baseline per agent type for Phase 114)
- Parameter budgeting across agents (future extension)
- Online adaptation of penalty_weight (tunable via config, not adaptive)
- Plugin-level Occam testing (technical indicators excluded in Phase 114)
- Production signal blocking (ORE is shadow-only, never affects live signals)

</domain>

<decisions>
## Implementation Decisions

### D-01: Baseline Selection — Agent Prefix Mapping
**Mechanism:** `_BASELINES` dict maps agent_id prefixes to `BaselineBuilder` instances.
- `ml_*` → `LinearBaseline` (logistic regression with L2)
- `correlation_*` → `RuleBaseline` (correlation threshold)
- `regime_*` → `RandomBaseline` (tests if regime adds value)
- `counterfactual_*` → `NullBaseline` (no adjustment)

**Rationale:** Prefix-based mapping is simple, deterministic, and covers all current ML agents. New agents add one entry to registry.

**Fallback:** If no mapping found, skip agent with warning (don't fail entire evaluation).

### D-02: Complexity Score — Log-Transformed Product
**Formula:** `complexity_score = log(params + 1) × (1 + latency_ms / 1000) × (1 + train_time_ms / 60000)`

**Rationale:**
- Log transform prevents exponential penalty on parameter count (1000 params ≠ 1000× worse than 1 param)
- Normalized latency/train time prevents runaway scores
- Additive terms (1 + ...) prevent zero-division

**Source:** All metrics from existing shadow registry and model metadata.

### D-03: Statistical Test — Bootstrap CI
**Mechanism:** Paired bootstrap on timestamp-aligned return deltas: `delta_t = complex_return_t - baseline_return_t`. 1000 resamples, recompute sharpe_delta for each, extract 2.5/97.5 percentiles. Always paired — never independent bootstraps.

**Decision rule (complexity-penalized):**
- `penalized_delta = sharpe_delta - lambda * log1p(complexity_ratio)`
- `ci_lower > 0` → complex wins
- `ci_upper < 0` → baseline wins
- CI spans 0 → tie (prefer simpler → reject complex)

**Rationale:** Paired bootstrap eliminates noise from non-stationary returns by differencing out common market effects. Non-parametric, handles non-normal return distributions, and provides interpretable CI width for confidence metric.

**No t-test fallback:** Paired bootstrap is always used. If bootstrap fails (exception), evaluation is skipped with EVAL_STATE_INSUFFICIENT_DATA — no fallback to a weaker statistical test that could produce false approvals.

### D-04: Penalty Weight — Tunable via Config, Default 0.5
**Location:** `OccamRazorEvaluator._penalty_weight` attribute, settable via constructor or environment variable `OCCAM_PENALTY_WEIGHT`.

**Rationale:** 0.5 balances performance and complexity. Operator can tune based on empirical results (high rejection rate → lower weight).

### D-05: Shadow Registry Enhancement — Rejection Tracking
**New columns:**
```sql
ALTER TABLE shadow_registry ADD COLUMN rejection_reason TEXT;
ALTER TABLE shadow_registry ADD COLUMN complexity_score FLOAT;
ALTER TABLE shadow_registry ADD COLUMN last_occam_check TIMESTAMPTZ;
```

**Update flow:**
```sql
UPDATE shadow_registry
SET is_shadow = TRUE,
    rejection_reason = $1,
    complexity_score = $2,
    last_occam_check = NOW()
WHERE component_name = $3;
```

**Rationale:** Audit trail for Occam rejections, complexity tracking over time.

### D-06: Fail-Closed — Missing Data Raises
**Rule:** If `complexity_score` is NULL or missing for any agent, raise `RuntimeError` before evaluation begins.

**Rationale:** Cannot compute penalty without complexity data. Defaulting to "low complexity" would incorrectly favor complex models.

### D-07: Evaluation Window — Last 30 Days of Shadow Signals
**Source:** `signal_ledger` WHERE `timestamp > NOW() - INTERVAL '30 days'` AND `agent_id = $1` AND outcome IS NOT NULL.

**Minimum sample size:** `n >= 30` signals required. If fewer, skip evaluation with warning.

**Rationale:** 30 days balances recency and sufficient sample size for statistical power.

### Claude's Discretion
- Whether `OccamRazorEvaluator` lives in `src/intelligence/ai/evaluators/` or `src/intelligence/ai/occam/` (recommend `evaluators/` for consistency with other evaluators)
- Whether bootstrap CI uses 1000 or 2000 resamples (1000 is sufficient for 95% CI)
- Whether penalty_weight is float or int (float for finer tuning)

</decisions>

<open>
## Open Questions

### Q-01: Should ORE evaluate all ML agents or only newly added ones?
**Options:**
1. All ML agents on every run (comprehensive but expensive)
2. Only agents with `last_occam_check IS NULL` or `last_occam_check < NOW() - INTERVAL '7 days'` (incremental)

**Recommendation:** Option 2 — incremental re-evaluation. Full re-evaluation on demand.

### Q-02: Should ORE run as a separate service or inside AlphaSwarm?
**Options:**
1. Separate systemd service (`indicagent-ai-occam-razor`)
2. Periodic job inside AlphaSwarm `_graduation_loop`

**Recommendation:** Option 2 initially — ORE runs as part of AlphaSwarm's existing evaluation loop. Can extract to separate service in Phase 101 if load warrants.

### Q-03: How should ORE handle agents without sufficient shadow signals (n < 30)?
**Options:**
1. Skip evaluation, log warning
2. Wait until sufficient data accumulated
3. Use historical backfill data for bootstrap

**Recommendation:** Option 1 — skip with warning. Don't block evaluation for other agents.

</open>
