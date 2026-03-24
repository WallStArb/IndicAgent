# Intelligence Swarm Manifest: "The Renaissance Loop"

## 1. Overview
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

### B. Defensive Security (Guardrails)
To prevent prompt injection/hallucinations, the system employs a "SafeSwarm" pattern:
- **Hard-Shell (Deterministic):** `PydanticAI` models enforce strict JSON schema for all outputs. Invalid JSON causes an immediate "Neutral/1.0" multiplier default.
- **Soft-Shell (Heuristic):** The `SafeSwarmWrapper` applies a range-clamp `[0.0, 2.0]` on the final `AlphaMultiplier`.
- **Telemetry:** All agent operations are traced via `LangSmith` (reasoning/context) and `OpenTelemetry` (infrastructure/latency).

### C. Cross-Asset Contagion Logic
- **Insight:** High-frequency alpha often appears in the NQ before it moves into the ES.
- **Agent Logic:** If the NQ is showing a "Liquidity Decay" while the ES signal is active, the agent predicts that the ES will catch the "decay contagion" within 3 bars. It preemptively reduces the ES signal size.

---

## 6. Implementation Roadmap
1.  **Manifest Approval:** Review and refine the registry.
2.  **Schema Definition:** Formalize `PydanticAI` schemas for the agents (include telemetry fields).
3.  **Hook Implementation:** Inject `AlphaMultiplier` logic (with `SafeSwarmWrapper` checks) into `signal_lifecycle_service.py`.
4.  **Shadow Deployment:** Deploy all agents in "shadow mode" (log outputs to Postgres, don't execute).
5.  **Correlation Audit:** Analyze shadow performance; tune weights; enable production.
