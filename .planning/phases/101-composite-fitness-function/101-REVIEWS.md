---
phase: 101
reviewers: [gemini, codex, ollama]
reviewed_at: 2026-06-03T12:00:00Z
plans_reviewed: [101-01-PLAN.md, 101-02-PLAN.md, 101-03-PLAN.md, 101-04-PLAN.md, 101-05-PLAN.md, 101-06-PLAN.md]
---

# Cross-AI Plan Review — Phase 101: Composite Fitness Function

---

## Gemini Review

### 1. Summary

The plan is highly structured, architecturally sound, and adheres strictly to IndicAgent's established patterns (in-process calculators, stateless gates, clear DB/Service separation). By decomposing the fitness function into pure functional units with TDD, the plan minimizes the risk of logical errors in the complex fitness calculation. The approach to the FIT-06 gate and the segregation of concerns between the new `fitness_auditor` (computation) and `shadow_auditor` (decision-making) aligns well with existing lifecycle management.

### 2. Strengths

- **Strong Modularization**: Separation of pure calculators from DB-accessing services makes the complex fitness logic testable and maintainable.
- **Adherence to Invariants**: Strict compliance with `asyncpg` patterns, no `json` dumps in code (JSONB passthrough), and clear `_DAG_ORDER` updates.
- **Robust Diagnostic Visibility**: Extensive inclusion of diagnostic metrics in `dimensions_jsonb` and OTel will be invaluable for debugging "Composite = 0" or "Staleness" issues in production.
- **Clear Gate Logic**: `PromotionGate` and `DemotionGate` as stateless, threshold-injected classes provide a clean, auditable interface for lifecycle state transitions.
- **Cold-Start Awareness**: Explicit handling of `min_n` requirements ensures the system gracefully handles agents with insufficient data before calculating composite scores.

### 3. Concerns

- **HIGH: Performance** — An hourly scan of `signal_ledger_full` and `llm_calls` over a 90-day lookback for all active agents is compute and I/O intensive. If the agent population grows large, this might exceed the 1-hour window.
- **MEDIUM: Cold-Start/Data Skew** — The plan assumes agents emit signals at a steady rate. If an agent is "stale" due to market conditions (not logic errors), the `FITNESS_STALENESS_THRESHOLD_HOURS=4` might cause premature demotion if not carefully managed.
- **MEDIUM: FIT-06 Edge Case** — D-03 requires a minimum of 5 agents to compute FIT-06. If a deployment starts with 3-4 agents, the gate will stay in `insufficient_population` status. The plan needs to ensure this state doesn't inadvertently block or break downstream logic.
- **LOW: Historical Data Growth** — Phase 101 mentions D-01: NO retention policy for `agent_fitness`. Over time, this table will grow linearly. While Phase 102/103 need this data, an eventual retention strategy or archiving process (not in scope, but needs a future note) should be considered.

### 4. Suggestions

- **Optimization**: Ensure `signal_ledger_full` and `llm_calls` queries are indexed by `(agent_id, created_at)` to support the 90-day lookback efficiently.
- **Diagnostics**: Add a "Data Freshness" check in `fitness_auditor` that alerts if an agent has no new signals in the last 24h, distinct from the fitness staleness check.
- **FIT-06 Status Handling**: Clearly define in `fitness_auditor` how `insufficient_population` status is communicated via OTel metrics to prevent false-negative alerts in the dashboard.
- **Demotion Thresholds**: Ensure the `parse failure rate` check (D-15) is resilient to transient network glitches (e.g., using a weighted moving average rather than a simple 50-call window if appropriate).

### 5. Risk Assessment: LOW

The design is technically robust. The primary risk is the performance overhead of the historical scan, which can be mitigated by ensuring strict SQL index support on the queried tables. The stateless nature of the gates and pure calculators significantly reduces the risk of side-effect-induced bugs.

---

## Codex Review

### Summary

The six-plan structure is coherent and mostly respects the project invariants: pure in-process calculators, DB access isolated to auditor wiring, OTel-only metrics, and a separate oneshot `fitness_auditor.py`. The wave ordering is sensible: schema/settings first, pure calculators and gates second, system integration last. The biggest risks are not architectural but statistical and operational: the 90-day hourly scan may become expensive, several dimension formulas may compress scores too tightly or too loosely, cold-start behavior needs sharper definition, and FIT-06 may fail in ways that are hard to diagnose unless null/insufficient agents are explicitly surfaced.

### Strengths

- Clear separation between pure fitness math and DB-owning auditor code.
- Good adherence to locked decisions, especially geometric mean, NULL composite until all dimensions clear minimum N, and population-level novelty.
- TDD coverage is planned for every pure calculator and gate before integration.
- `fitness_auditor.py` as a separate oneshot preserves the clean analytics-to-lifecycle DAG.
- Promotion and demotion logic moving into pure stateless classes is a strong testability improvement.
- Novelty diagnostics are well-chosen; they address the "benefit of doubt" edge case where low overlap produces artificially high novelty.
- Explicit staleness handling in `shadow_auditor` prevents stale fitness rows from driving promotion decisions.
- FIT-06 uses `statistics.pstdev` and minimum population, matching D-03.

### Concerns

- **HIGH: FIT-06 discriminative power** — FIT-06 may not be meaningfully achievable with the proposed dimension formulas. Geometric mean plus many bounded `[0,1]` scores can compress composites, especially if efficiency is mostly near 1.0 and novelty defaults high during sparse overlap. The plan gates on `stddev >= 0.2`, but does not include a validation step showing the scoring distribution can actually reach that spread across live agents.
- **HIGH: Hourly 90-day scan cost** — The hourly 90-day scan over `signal_ledger_full` and `llm_calls` could be expensive. Plan 06 says reads are bounded by `FITNESS_LOOKBACK_DAYS`, but does not specify indexing, query shape, batching, materialization, or whether it reads all agents' raw records every hour.
- **HIGH: NULL composite cold-start behavior** — `fitness_auditor.py` "writes one `agent_fitness` row per agent" while many composites may be NULL during cold start. FIT-06 must exclude NULL composites and report `insufficient_population` if fewer than 5 latest non-NULL live-agent composites exist — this should be made explicit in Plan 06.
- **MEDIUM: Naming confusion `FITNESS_VARIANCE_GATE_THRESHOLD`** — The diagnostic variance gauge alongside a threshold named `VARIANCE` but measuring `stddev` is a likely operator/developer footgun.
- **MEDIUM: Accuracy transform underspecified** — "Maps bootstrap CI lower bound on `pnl_r` to `[0,1]`" needs an exact transform. Different mappings can drastically change score spread and FIT-06 behavior.
- **MEDIUM: Per-regime accuracy floor undefined** — Regime scoring says "fraction of covered regimes passing per-regime accuracy floor," but the per-regime accuracy floor is not defined. PromotionGate criterion 2 requires `composite_score > 0.05 per evaluated regime`, which implies a per-regime composite stored in `dimensions_jsonb` — this field must be defined and populated.
- **MEDIUM: Calibration weak discriminability** — `1 - Brier` is bounded and simple but may be weakly discriminative if confidence values cluster. Reliability diagram storage is listed in success criteria but Plan 02 only stores Brier-derived score.
- **MEDIUM: Novelty alignment keys underspecified** — Pearson correlation on pairwise pnl_r vectors needs deterministic alignment semantics. Overlap keys (probably resolved signal_id) need explicit definition to prevent accidental vector misalignment.
- **MEDIUM: Efficiency omits latency and quality** — FIT-05 requirement wording says "output quality / latency * tokens" but the plan only penalizes median token usage. If latency and quality coupling are intentionally deferred, say so.
- **MEDIUM: Parse failure semantics** — "parse failure rate < 0.80" needs clarification: is this "success rate" or "failure rate"?
- **LOW: PromotionGate history row exclusion** — Plan 05 says "last 3 prior history rows" (excluding current). D-14 says "last 3 audit cycles." Intent should be made explicit.
- **LOW: promotion_ready ownership** — Plan 05/06 should state exactly where `shadow_auditor` updates `promotion_ready` to TRUE.
- **LOW: First-deploy ordering** — Systemd timer cadence drift between `fitness_auditor` (60 min) and `shadow_auditor` (30 min) should be documented for first deploy.

### Suggestions

- Add a Wave 3 validation test or dry-run mode computing composite distribution on recent historical data (dimension histograms, composite histogram, NULL counts, FIT-06 status).
- Make FIT-06 behavior explicit: use latest row per live agent, exclude NULL composites, require at least 5 non-NULL, emit status labels `pass` / `fail_low_stddev` / `insufficient_population` / `no_live_agents`.
- Define the exact accuracy transform from CI lower bound to `[0,1]`. Include tests for negative CI, zero CI, large positive CI, NaN/inf, all-zero PnL, single-sided outcomes.
- Add query/index requirements to Plan 01 or 06. Verify indexes for `agent_id`, resolved/evaluated timestamps, live-agent selection, and `llm_calls` over 90-day window.
- Consider incremental or windowed aggregation if the raw 90-day scan is too large.
- Rename `FITNESS_VARIANCE_GATE_THRESHOLD` to `FITNESS_POPULATION_STDDEV_THRESHOLD` unless already locked.
- Expand calibration output to include reliability-bin diagnostics in `dimensions_jsonb`.
- Define `per_regime_composite` precisely in Plan 06 (formula + min-N behavior per regime).
- Clarify novelty alignment keys and handling of constant vectors, NaN Pearson, missing PnL, duplicate signals, agents with no overlaps.
- Reconcile FIT-05 with requirement wording. If latency/quality are deferred, document explicitly.
- Add integration tests for cold start: zero live agents, < 5 live agents, all NULL composites, mixed NULL/non-NULL, stale latest fitness row, first three cycles with insufficient gate history.
- Ensure `job_completed_total{job, status}` includes explicit `status` labels on all exits including exceptions, partial failures, and insufficient-population runs.

### Risk Assessment: MEDIUM-HIGH

The decomposition and architectural boundaries are strong, so implementation risk is manageable. The main risk is that the resulting fitness function may not be discriminative enough to satisfy FIT-06, or may satisfy it for accidental reasons (sparse novelty overlap). The second major risk is operational cost from the hourly 90-day scan. Tightening score definitions, cold-start semantics, query/index strategy, and FIT-06 diagnostics would bring the phase to medium risk.

---

## Ollama Review (nemotron-3-nano:4b)

### 1. Summary

The roadmap follows a sound, stage-gated approach that delivers pure-calculator functions, replaces the shadow-auditor logic with a reusable stateless gate architecture, and finally wires the hourly `fitness_auditor` into the DAG. Each plan advances from data-schema creation → pure-logic testing → system orchestration, and every step includes defensive thresholds (`min_n`, geometric-mean composite, staleness check). While the core statistical definitions are reasonable and the DAG invariant is respected, a handful of edge-case gaps (empty-pair handling, very short histories, cold-start races) and execution-risk concerns (90-day look-back size) merit attention.

### 2. Strengths

- **Stateful design with clear invariants** — hypertable only, settings-driven, no external SDKs (`prometheus_client`) or hard-coded topics.
- **Pure-function calculators** (plans 02-04) have no side effects, guaranteeing testability and enabling future swapping.
- **Atomic composition logic** — geometric-mean composite, "0.0" on any 0, "1.0" leaf cases — matches roadmap non-negotiable spec.
- **DAG compliance** — `_DAG_ORDER` updated, production services are `Type=oneshot`, emit `job_completed_total`.
- **Cold-start safety** — PromotionGate fails gracefully when dimensions are `None`; DemotionGate needs two consecutive failures (no spurious demotions).
- **Granular health-checks** — staleness (`FITNESS_STALENESS_THRESHOLD_HOURS=4`), 90-day rollback, min-N gates, and 3-row stddev fallback.

### 3. Concerns

| # | Concern | Severity |
|---|---------|----------|
| C1 | **Population-pair empty** — If all live agents have ≤ 1 resolved signal or no overlapping solved-signal pairs, `max(|Pearson r|)` over an empty sequence would raise a runtime error. | MEDIUM |
| C2 | **Historical-row depletion** — For agents with < 3 prior `agent_fitness` rows, `stddev(composite_score)` returns `None` → condition treated as failing. This may trigger false demotions for fresh agents. | HIGH |
| C3 | **90-day rolling window load** — Scanning all agents with a 90-day window for every live agent creates an N-agent query burst; could spike DB/network for N > ~200. | HIGH |
| C4 | **Cold-start race** — First evaluation may compare agents that have not yet reached `min_n` thresholds; PromotionGate correctly rejects, but schema currently stores `None` per-agent, potentially bloating `dimensions_jsonb`. | MEDIUM |
| C5 | **Systemd timer retry** — `indicagent-fitness-auditor.timer` is hourly; if a failure occurs at a full hour, the next iteration may miss up-to-hour data. The plan does not specify retry handling. | MEDIUM |

### 4. Suggestions

- **C1 Edge-case guard**: In `novelty.py`, wrap `max(|Pearson r|)` with a fallback to zero when the sequence is empty, setting `max_abs_r = 0`. Yields `novelty_score = 1` (same as population-size-1 rule).
- **C2 Historical safety**: In `fitness_auditor.py`, compute stddev only on the last 3 rows, ignoring `None`. If fewer than 3 rows exist, treat stddev as `None` and log a "stddev_lt_3_rows" metric.
- **C3 Performance mitigation**: Pre-compute per-agent aggregate stats and store as materialised views, or split into a lightweight "health-check" (3-row window) plus a batch full-scan.
- **C4 Record cleaning**: When a row has `None` for any dimension, ensure `dimensions_jsonb` stores `null` not `""` to prevent schema bloat.
- **C5 Retry policy**: Add `Restart=on-failure` and `RestartSec=300` to the systemd service unit for resilience.

### 5. Risk Assessment: MEDIUM

The core statistical definitions and DAG contract are sound, eliminating HIGH correctness risk. The main risks stem from edge-case handling (C1 empty-pair raise, C2 false demotion on sparse history) and performance scaling for the 90-day lookback (C3). These are manageable with the suggested mitigations but introduce medium-impact operational and correctness risk if left unaddressed.

---

## Consensus Summary

Phase 101 was reviewed independently by 3 AI systems. All reviewers agree the architecture is sound.

### Agreed Strengths

- Pure calculator separation from DB-accessing services — all three reviewers cited this as the phase's core structural strength
- Geometric mean composite formula correctly enforces "no hiding weaknesses" invariant
- TDD for pure calculators and gates before integration is the right approach
- Stateless PromotionGate/DemotionGate replacing inline shadow_auditor logic is a clear testability improvement
- Staleness check and min-N gates handle cold-start gracefully
- DAG invariants respected: OTel-only, asyncpg passthrough, no prometheus_client, _DAG_ORDER updated

### Agreed Concerns

1. **[HIGH] Hourly 90-day lookback scan performance** — All three reviewers flagged the N-agent × 90-day hourly scan as a scaling risk. Indexing, query shape, and potentially incremental computation need explicit attention in Plan 06.

2. **[HIGH] FIT-06 cold-start and NULL composite handling** — All reviewers noted that NULL composites must be explicitly excluded from the FIT-06 population stddev calculation, and the `insufficient_population` path needs to emit a distinct status metric.

3. **[MEDIUM/HIGH] Historical row depletion for fresh agents** — Two reviewers (Codex, Ollama) flagged that PromotionGate stability criterion (< 3 prior history rows) could cause fresh agents to be indefinitely blocked or falsely demoted. The "< 3 rows → history stddev = None" path should have explicit handling.

4. **[MEDIUM] Empty pair handling in novelty** — Two reviewers (Ollama, Codex) flagged that an empty sequence in `max(|Pearson r|)` raises a runtime error. The population-size-1 guard does not cover the case where all pairs have fewer than min-overlap resolved signals.

5. **[MEDIUM] Accuracy transform underspecified** — Two reviewers (Codex, Gemini) noted the exact mapping from CI lower bound to [0,1] is not defined, which affects score spread and therefore FIT-06 behavior.

### Divergent Views

- **Gemini** rated overall risk as LOW (strong architecture, mitigatable operationally)
- **Ollama** rated it MEDIUM (edge cases manageable but real)
- **Codex** rated it MEDIUM-HIGH (adding concern that FIT-06 discriminative power may not be achievable with compressed score distributions)

The divergence centers on whether the geometric-mean scoring will naturally produce stddev >= 0.2. Gemini trusts the architecture; Codex is more skeptical of the statistical discriminability.
