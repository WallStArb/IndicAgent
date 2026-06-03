# Phase 101: Composite Fitness Function - Context

**Gathered:** 2026-06-02
**Status:** Ready for planning

<domain>
## Phase Boundary

Build a 5-dimensional composite fitness evaluation system for AI agents and wire it into the shadow governance lifecycle. Delivers: `agent_fitness` TimescaleDB hypertable, five dimension calculators (accuracy, novelty, calibration, regime specificity, efficiency), a geometric-mean composite formula, `PromotionGate` / `DemotionGate` pure classes, a new `fitness_auditor.py` oneshot service, and an updated `shadow_auditor.py` that reads from `agent_fitness` instead of computing inline metrics.

The FIT-06 discriminative power gate — population `stddev(composite_score) >= 0.2` — blocks Phase 102 until the fitness function provably separates agents.

**In scope:**
- `agent_fitness` hypertable (migration) with 5 dimension scores + composite
- Per-dimension calculators in `src/intelligence/ai/fitness/` (pure functions, no DB side-effects)
- `PromotionGate` and `DemotionGate` as pure stateless classes (no DB access)
- `services/fitness_auditor.py` oneshot script (reads `signal_ledger + signal_outcomes + llm_calls`, writes `agent_fitness`)
- `shadow_auditor.py` refactor: read `agent_fitness` for gate decisions; current inline `bootstrap_ci_lower` promotion logic replaced by `PromotionGate`
- FIT-06 variance gate implementation and blocking check
- Unit tests for all 5 calculators, gates, and composite formula

**Out of scope:**
- Agent genome serialization (Phase 102)
- Reproductive operators (Phase 103)
- Memory integration (Phase 097)
- Any changes to how agents analyze signals — fitness is read-only evaluation of existing data
- Manual promotion/demotion UI (future)

</domain>

<decisions>
## Implementation Decisions

### agent_fitness Table Architecture
- **D-01: TimescaleDB hypertable.** One row per `(agent_id, evaluated_at)`. Full history of every audit cycle. Never delete — fitness trajectories are signal for gene extraction in Phase 102. Chunk interval: 7 days, compression after 7 days. `DISTINCT ON (agent_id) ORDER BY evaluated_at DESC` gives current state — no separate snapshot table needed.
- **D-02: Columns.** `agent_id TEXT NOT NULL`, `evaluated_at TIMESTAMPTZ NOT NULL`, `accuracy_score DOUBLE PRECISION`, `novelty_score DOUBLE PRECISION`, `calibration_score DOUBLE PRECISION`, `regime_score DOUBLE PRECISION`, `efficiency_score DOUBLE PRECISION`, `composite_score DOUBLE PRECISION`, `n_resolved INTEGER`, `promotion_ready BOOLEAN`, `dimensions_jsonb JSONB` (raw sub-metrics: per-regime counts, bootstrap CIs, pairwise r values, token medians — for audit and debugging). All dimension scores nullable (NULL = not yet computable for this agent).
- **D-03: Variance gate uses latest scores.** FIT-06 computes `stddev(composite_score)` across all live agents using their most recent row. Population minimum: 5 agents with valid composite scores required before gate is computable. Fewer than 5 agents → gate status = `insufficient_population`, not blocked/passed.

### Composite Formula
- **D-04: Geometric mean of 5 dimensions.** `composite = (accuracy × novelty × calibration × regime × efficiency)^(1/5)`. A zero in any dimension collapses the composite to 0 — structural weaknesses cannot be hidden by strength in other dimensions. No special-case compensation logic.
- **D-05: Composite not emitted until all 5 dimensions are computable.** Agent stays in shadow with NULL composite until each dimension clears its minimum N. `composite_score = NULL` means "not yet evaluable" — `shadow_auditor.py` skips promotion for agents with NULL composite.
- **D-06: Per-dimension minimum N (stored as `FITNESS_*` constants in `Settings`, not hardcoded).** Defaults: `FITNESS_ACCURACY_MIN_N = 50`, `FITNESS_CALIBRATION_MIN_N = 30`, `FITNESS_REGIME_MIN_N_PER_REGIME = 10` with `FITNESS_REGIME_MIN_REGIMES = 2` (at least 2 distinct `hmm_regime` values seen), `FITNESS_EFFICIENCY_MIN_N = 20`. Novelty is population-level, no per-agent N.

### Integration Architecture (DAG)
- **D-07: Separate `fitness_auditor.py` oneshot script.** Clean DAG: analytics (fitness computation) → lifecycle (shadow governance). `fitness_auditor.py` reads `signal_ledger + signal_outcomes + llm_calls`, computes all 5 dimensions per agent, writes to `agent_fitness`. `shadow_auditor.py` reads `agent_fitness` (latest row per agent) for `PromotionGate`/`DemotionGate` decisions. No reverse coupling.
- **D-08: `PromotionGate` and `DemotionGate` as pure stateless classes in `src/intelligence/ai/fitness/gates.py`.** No DB access. Accept fitness row as input, return `(bool, str | None)` (decision, reason). Replaces the current inline `_should_promote` / `_should_demote` functions in `shadow_auditor.py`. Directly testable without DB.
- **D-09: Staleness check in `shadow_auditor.py`.** If the latest `agent_fitness.evaluated_at` for an agent is older than `FITNESS_STALENESS_THRESHOLD_HOURS = 4` (Settings), `shadow_auditor` skips that agent's promotion/demotion and logs a warning. Prevents acting on stale fitness scores after data gaps.
- **D-10: Timer cadence.** `fitness_auditor` runs every 60 minutes (new timer unit). `shadow_auditor` remains 30 minutes. No ordering guarantee needed — staleness check handles the case where fitness_auditor hasn't run yet.

### Novelty Metric
- **D-11: Pearson r on pairwise `pnl_r` vectors.** Novelty score = `1 - max(|r|)` across all live agent pairs, using the overlapping set of resolved `signal_id`s. This measures actual alpha redundancy, not analytical agreement — two agents can agree on analysis but produce uncorrelated PnL, which IS unique alpha.
- **D-12: Minimum 20 overlapping resolved signals** required to compute a meaningful Pearson r between any pair. Below 20 overlap: that pair's r is treated as 0 (benefit of doubt — not enough data to penalize). Population size = 1: `novelty_score = 1.0` by definition.
- **D-13: Novelty is computed at the `fitness_auditor` level**, not per-agent in isolation. After computing accuracy/calibration/regime/efficiency per agent, novelty is computed as a second pass over the full agent population. Stored per agent in `agent_fitness`.

### Promotion and Demotion Gate Criteria
- **D-14: `PromotionGate` — ALL criteria must pass** (supersedes current `_should_promote` in shadow_auditor):
  1. `composite_score IS NOT NULL` (all 5 dimensions computable)
  2. Regime coverage: `composite_score > 0.05` in every evaluated regime (`regime_score` computed across `>= FITNESS_REGIME_MIN_REGIMES` distinct regimes)
  3. Sample gate: `n_resolved >= FITNESS_ACCURACY_MIN_N` (already required for accuracy dimension)
  4. Stability: `stddev(composite_score) < 0.02` across last 3 audit cycles for this agent (requires 3 rows in `agent_fitness`)
  5. Novelty confirmed: `novelty_score > 0.15` (agent is not a near-duplicate of any live agent)
  6. Triggers human review flag — no auto-promotion to live. Sets `shadow_registry.promotion_ready = TRUE` and emits metric.
- **D-15: `DemotionGate` — ANY trigger fires demotion** (supersedes current `_should_demote`):
  1. Fitness decay: `composite_score < promotion_baseline * 0.80` (20% drop from promotion baseline, stored in `shadow_registry.promotion_baseline`)
  2. Correlation rise: `novelty_score < 0.15` for 2 consecutive cycles (agent has converged toward a live agent)
  3. Regime shift failure: `regime_score = 0.0` in newly dominant regime for 2 consecutive cycles
  4. Parse failure rate: computed from `llm_calls.parse_success` — rate < 0.80 over rolling 50 calls

### Claude's Discretion
- Specific normalization approach for each dimension to [0, 1] — researcher/planner to determine the correct monotonic mapping (e.g., Sharpe → accuracy: sigmoid or clamp-and-normalize, Brier → calibration: `1 - brier_score`, regime variance → regime score)
- Whether `efficiency_score` uses `tokens_est` from `llm_calls` alone or combines with `latency_ms` — both columns exist, planner to decide the composite efficiency formula
- Systemd unit name and timer interval for `fitness_auditor`

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### eAI Research (primary design doc)
- `docs/ideas/ai-03-evolvable-ai-agents.md` — Composite fitness design, agent lifecycle, promotion/demotion criteria, novelty/diversity principles

### Phase Definition
- `.planning/phases/101-composite-fitness-function/README.md` — 6-plan breakdown, PromotionGate/DemotionGate spec, 5-axis descriptions

### Existing Shadow Governance (to understand what is being replaced)
- `services/shadow_auditor.py` — Current 1D gate logic (`_should_promote`, `_should_demote`); this is the primary integration target
- `production/migrations/077_shadow_governance.sql` — `shadow_registry` + `shadow_transition_log` schema
- `src/core/stats_utils.py` — `bootstrap_ci_lower` — reuse for accuracy dimension bootstrap CI

### Signal Data Sources (what fitness reads)
- `production/migrations/095_signal_ledger_split.sql` — `signal_ledger` (immutable) + `signal_outcomes` (mutable lifecycle); `pnl_r`, `outcome`, `hmm_regime` columns
- `production/migrations/019_llm_intelligence_layer.sql` + `production/migrations/087_llm_calls_agent_attrs.sql` — `llm_calls` schema; `agent_id`, `latency_ms`, `tokens_est`, `parse_success` columns used for efficiency + parse failure rate

### Project Patterns
- `src/config/settings.py` — `Settings` class; add `FITNESS_*` threshold constants here
- `CLAUDE.md` — Oneshot contract (D-06): emit `job_completed_total{job, status}` at script exit; DAG invariants (no DB access from analytics layer)

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `src/core/stats_utils.bootstrap_ci_lower(pnl_r_values, alpha, n_boot)` — already used by shadow_auditor for accuracy bootstrap CI; reuse directly in `accuracy` dimension calculator
- `shadow_auditor._should_promote` / `_should_demote` — pure gate functions (no DB); refactor into `PromotionGate` / `DemotionGate` in `src/intelligence/ai/fitness/gates.py`
- `src/observability/metrics.py` — use for `SHADOW_*` metrics already defined + new `FITNESS_*` gauge metrics

### Established Patterns
- Oneshot timer-triggered scripts: `services/shadow_auditor.py` is the direct analog — same pattern (asyncpg pool, `_run_audit()`, `job_completed_total` at exit)
- `asyncpg` for all DB: JSONB → dict (no `json.dumps`), timestamps → datetime, `format_iso_ts()` for Kafka/JSON
- `structlog` logging to `logs/<snake_case>.log` via `setup_service_logging()`
- `Settings` constants with `FITNESS_` prefix (aligned with `SHADOW_*` prefix in shadow governance)

### Integration Points
- `shadow_auditor.py:_check_promotion` → replace inline `bootstrap_ci_lower` check with `PromotionGate(fitness_row).can_promote()`
- `shadow_auditor.py:_check_demotion` → replace inline EV[R] check with `DemotionGate(fitness_row).should_demote()`
- New `indicagent-fitness-auditor.timer` + `indicagent-fitness-auditor.service` systemd units (oneshot pattern)
- `shadow_registry` table: add `promotion_baseline DOUBLE PRECISION` column (migration) to support DemotionGate D-15 trigger 1

</code_context>

<specifics>
## Specific Ideas

- **Renaissance rigor principle (explicit constraint):** All 5 dimension scores must independently clear minimum N before composite is emitted. No partial composites. The system must be conservative — a lucky 30-signal run that produces a good composite is a false signal. Incubation is cheap; false promotions are expensive.
- **PromotionGate statistical test (CRITICAL-03 from architecture review 2026-06-03):** `PromotionGate` MUST use a one-sided t-test (p < 0.05, t-stat > 1.96 on pnl_r) as its significance criterion — NOT bootstrap CI lower bound. Bootstrap CI at n=100 with fat-tailed returns nearly always produces a negative lower bound (undersized sample, high variance), making the gate either never-promote or arbitrary. Minimum n for the significance criterion: 200 (not 100 — 100 is insufficient for stable moment estimation on fat-tailed R-multiples). Add `one_sided_ttest_passes(pnl_r_values, min_n=200)` to `src/core/stats_utils.py` and wire it into PromotionGate. `FITNESS_ACCURACY_MIN_N` default must be 200.
- **DemotionGate Sharpe threshold (CRITICAL-03 from architecture review 2026-06-03):** `DemotionGate` MUST use rolling 30-day Sharpe < -0.5 as its decay trigger — NOT consecutive cycle count. Three consecutive bad weekly cycles misses slow-bleed patterns and can hemorrhage capital for weeks. Sharpe captures both magnitude and consistency. Add `rolling_sharpe(pnl_r_values)` to `src/core/stats_utils.py`.
- **Geometric mean is non-negotiable:** The composite formula must be `(accuracy × novelty × calibration × regime × efficiency)^(1/5)`. No weighted linear alternatives. An uncalibrated agent or a redundant agent scores near-zero regardless of accuracy.
- **Historical fitness is permanent:** `agent_fitness` has no retention policy. Fitness trajectories inform Phase 102 gene extraction — we never discard performance history.

</specifics>

<deferred>
## Deferred Ideas

- **Adversarial coevolution** (skeptic agents vs. alpha agents) — described in `ai-03-evolvable-ai-agents.md`; relevant to post-Phase-103 evolution
- **Adaptive operator selection** (tracking which reproductive operator produces fittest offspring) — Phase 103 scope
- **Fitness UI / operator annotation interface** — future phase; operator needs a way to see the fitness breakdown before approving promotion
- **LLM-directed fitness interpretation** — an LLM that reads the 5-axis breakdown and explains WHY an agent is performing well or poorly; future layer on top of this phase

</deferred>

---

*Phase: 101-composite-fitness-function*
*Context gathered: 2026-06-02*
