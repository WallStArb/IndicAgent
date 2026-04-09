# Intelligence Swarm Manifest: "The Renaissance Loop"

**Status:** Active Reference — Core swarm architecture principles
**Created:** 2026-03-07  
**Updated:** 2026-04-09
**Related:** 
- `docs/plans/2026-04-09-phase-56-swarm-foundation-design.md` — Phase 56 swarm infrastructure build

---

## 7. POC: Dual-Path Integration (Deterministic DAG vs. LLM-Swarm)
To ensure Renaissance-grade reliability, we are implementing a dual-path POC to validate intelligence contributions:

*   **Path A (Deterministic DAG):** High-performance, numeric feature extractors (Rust/Python) for real-time confidence modulation.
*   **Path B (LLM-Swarm):** Asynchronous, reasoning-based context analysis (PydanticAI) logging to `alpha_multiplier_shadow` for correlation analysis against realized PnL.

All contributors follow the `IAlphaContributor` protocol. Real-time signal execution will prioritize Path A, while Path B is validated in shadow mode to measure the alpha decay reduction before potential production promotion.
---

## 1. Overview
...
The Intelligence Swarm (The "Observer") is a collection of asynchronous agents tasked with quantifying market state friction and providing predictive alpha multipliers to the Signal Lifecycle. The goal is to move from descriptive narratives to ex-ante risk-adjusted scaling.

## 2. Core Principles
- **No Blocking:** Swarm agents run out-of-band; they never block signal execution.
- **Differentiable Intelligence:** Every agent output must be a quantifiable vector (e.g., multiplier, probability score, friction index).
- **Shadow-First Validation:** No agent impacts position sizing in production until it has passed 14 days of shadow-tracking correlation analysis.
- **Rigid Schemas:** All agent outputs must adhere to strict `PydanticAI` models.
- **Defense-in-Depth:** Use deterministic guardrails (Pydantic/Range checks) to prevent prompt injection or hallucinated sizing.

---

## 3. The Swarm Members (Agent Registry)

### A. Regime & Entropy
1.  **Regime Sentinel (Latent Manifold):** Projects data onto a 3D manifold (Entropy, Dispersion, Momentum). Outputs `RegimeTransitionProbability (RTP)`.
2.  **Volatility Arbiter:** Compares signal expected move (ATR) against current implied vol skew. Detects "volatility compression" vs. "expansion" states.

### B. SMC & Structural Liquidity
3.  **Liquidity Decay Arbiter:** Monitors LOB dynamics. Forecasts fill probability and calculates `LOB_Friction_Score`.
4.  **Structural Support/Resistance (SMC) Validator:** Maps signal entry against established Order Blocks (OB), FVG, and CHoCH levels. 
    *   *Alpha:* Quantifies the "Proximity to Structural Trap." Signals inside high-density OBs are statistically more likely to be liquidity hunts.
5.  **Liquidity Sweep Hunter:** Analyzes real-time volume clusters. Determines if a signal is a "true breakout" or a "fake-out sweep."

### C. Cross-Asset & Macro
6.  **Correlation Contagion Agent:** Monitors cross-asset drift. If the signal asset decorrelates from its lead index (e.g., ES/NQ) during a move, the signal is downgraded.
7.  **Macro Event Observer:** Monitors the flow of high-impact news and volatility events (e.g., FOMC, CPI). Dynamically adjusts `SignalConfidence` before event windows.

### D. Model & System Integrity
8.  **Execution Quality Observer:** Monitors model drift in real-time. If recent signal outcomes drop 3σ below 30-day mean, triggers `SystemicPause`.
9.  **SkepticAgent (Devil's Advocate):** Runs counterfactual analysis. "Given this market state, what is the probability this signal fails?" (PydanticAI-based).

---

## 4. The Data Contract (AlphaMultiplier)

```json
{
  "signal_id": "uuid",
  "ts": "UTC_ISO",
  "agents": {
    "regime_sentinel": {"rtp": 0.82, "multiplier": 0.3},
    "liquidity_arbiter": {"friction_score": 0.1, "multiplier": 1.0},
    "smc_validator": {"trap_probability": 0.15, "multiplier": 1.2}
  },
  "final_alpha_multiplier": 0.36
}
```

---

## 5. Architectural Deep Dives & Alpha Insights

### A. The "Shadow-to-Production" Pipeline
To ensure alpha stability, every agent follows this lifecycle:
1.  **Shadow Mode:** Emits `AlphaMultiplier` predictions to a dedicated PostgreSQL table without touching `SignalLifecycle`.
2.  **Correlation Analysis:** An automated daily job computes `Pearson(Agent_Confidence, Realized_PnL_R)`.
3.  **Promotion:** Only agents with `ρ > 0.4` over a 14-day rolling window are eligible for `AlphaMultiplier` production injection.
4.  **Decay/Retraining:** Agents are re-trained (or weights reset) if their correlation drops below `0.2`.

### B. High-Alpha Nuance: SMC "Trap" Quantification
The SMC Validator does not just look for support/resistance. It looks for **"Absorption Patterns."**
- **Pattern:** When a signal is generated *inside* a large Order Block, if the volume profile is *declining* (decreasing absorption), it suggests the price is about to "slide" through the block.
- **Action:** If the validator detects this "low-absorption slide," it will set a `multiplier: 0.0` (Kill switch) for that specific signal, even if the base model says BUY.

### C. Cross-Asset Contagion Logic
- **Insight:** High-frequency alpha often appears in the NQ before it moves into the ES.
- **Agent Logic:** If the NQ is showing a "Liquidity Decay" while the ES signal is active, the agent predicts that the ES will catch the "decay contagion" within 3 bars. It preemptively reduces the ES signal size.

### D. Defensive Security (Guardrails)
To prevent prompt injection/hallucinations, the system employs a "SafeSwarm" pattern:
- **Hard-Shell (Deterministic):** `PydanticAI` models enforce strict JSON schema for all outputs. Invalid JSON causes an immediate "Neutral/1.0" multiplier default.
- **Soft-Shell (Heuristic):** The `SafeSwarmWrapper` applies a range-clamp `[0.0, 2.0]` on the final `AlphaMultiplier`.
- **Telemetry:** All agent operations are traced via `LangSmith` (reasoning/context) and `OpenTelemetry` (infrastructure/latency).

---

## 6. Implementation Status

**✅ Architecture Defined** (2026-03-07)
- Manifest approved with 9 core agents
- IAlphaContributor protocol established
- Shadow-first validation framework designed

**🚧 Phase 56: Swarm Foundation** (2026-04-09) — Ready to Execute
- Shared LLM layer (`src/core/llm/`), corrected DAG protocols, narrative refactor, `SwarmOrchestratorAgent` + `SwarmWriterAgent`, `alpha_multiplier_shadow` hypertable
- See: `docs/plans/2026-04-09-phase-56-swarm-foundation-design.md`

**🎯 Agent Build Backlog** (build 1 at a time, validate before next)

| Priority | Agent | Tagline | What it does | Testable hypothesis | Build | Validate |
|----------|-------|---------|--------------|---------------------|-------|----------|
| 1 | **SkepticAgent (S6)** | *"What's wrong with this signal?"* | Analyze signal features, predict failure probability. "This signal has 30% fail risk because: [reasons]" | Do high fail-prob signals actually fail more? | 2-3d | 7-14d |
| 2 | **Volume Profile Anomaly (S2)** | *"Price rejected at VAH/VAL — reversal coming?"* | Detect VP rejections (price touches VAH/VAL and reverses). "VP rejection at VAH — potential reversal incoming" | Do VP rejections correlate with reversals? | 3-4d | 7-14d |
| 3 | **Regime Explainer (N6)** | *"Why was this signal suppressed?"* | Explain regime gating logic in plain language. "Signal suppressed: trend filter (-0.3), regime disagreement (0.2)" | Do humans understand system decisions better? | 1-2d | 3-5d (human feedback) |
| 4 | **Trade Journal (Service 4)** | *Daily summary: signals taken, outcomes, lessons learned* | Aggregate signal_ledger daily. "Today: 12 signals, 8 winners, +2.3R. Top signal: CIS +1.8R" | Do humans who read it improve faster? | 2-3d | 14-30d |
| 5 | **Counterfactual Narratives (N5)** | *"What if we'd taken the other signal?"* | Compare 2 signals with outcomes. "You took CIS (+1.2R). Alpha setup (-0.8R). Correct decision." | Do humans make better decisions after seeing these? | 3-4d | 14-30d |
| 6 | **Correlation Cluster (S1)** | *"Equities decoupled — regime breakdown?"* | Track equity correlations, detect breakdowns. "ES/NQ decorrelation (0.12) → potential regime change" | Do decorrelation periods predict regime changes? | 4-5d | 14-30d |

**Rule:** p < 0.05, n ≥ 30 → keep it and build next. p > 0.05 → kill it, re-prioritize.

**🎯 Next Steps:**
1. Execute Phase 56 (Swarm Foundation infrastructure)
2. Build Priority 1: SkepticAgent (Phase 57)
3. Track → validate → decide before building Priority 2
