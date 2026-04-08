# Phase 50: Roll Monitor & DualDivergence Graduation - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-03-30
**Phase:** 50-roll-monitor-graduation
**Areas discussed:** Dependencies (5m backfill), Roll Premium population, DualDivergence gate, Phase scope

---

## Dependencies (5m Backfill)

**Question:** Phase 50's D-21 validation requires market_data_5m which doesn't exist (deferred to v2.3). How should we proceed?

| Option | Description | Selected |
|--------|-------------|----------|
| Include 5m backfill in Phase 50 | Create market_data_5m view and run historical backfill as part of this phase | |
| Skip D-21, graduate on trust | Defer roll monitor graduation; wait for v2.3 which has market_data_5m on roadmap | |
| Validate with 1m data | Run validate_roll_detection.py against market_data_ohlcv 1m bars instead of 5m | |
| Defer Phase 50 entirely | Postpone to v2.3 when market_data_5m is properly implemented | |

**User's choice:** Free text response
> "We want to design this like Renaissance would. Ask yourself how would a senior engineer/quant at Renaissance think about this? What would Jim Simons demand? We want to ensure we are aligned with our core principles of modularity, reuse, separation of concerns, microservices DAG and we want to balance efficiency with simplicity as well keeping in mind compute costs, maintenance - we don't want manual tasks, prefer automation - why wouldnt we backfill all bars if we can?"

**Notes:** User emphasized Renaissance principles — Jim Simons would demand complete data. "Why wouldn't we backfill all bars if we can?" This led to the decision to create 5m data in Phase 50.1.

---

## Roll Premium Population

**Question:** The roll_premium_pct column exists but is always 0.0. Should Phase 50 implement the population logic?

| Option | Description | Selected |
|--------|-------------|----------|
| Leave as placeholder (0.0) | Leave the column as-is; Phase 50 only graduates the RollComputeAgent service itself | |
| Compute from RollEvent data | Calculate from price spreads between front/back contracts when roll is detected | |
| Wire downstream consumer | FeatureWriterAgent should read market.events.roll and populate for each bar in roll window | |
| Defer implementation | Defer to a later phase when the pricing data source is clear | |

**User's choice:** Free text response
> "What do you feel?"

**Notes:** User asked for recommendation. After Renaissance analysis, recommended removing feature entirely (see final decision).

---

## Roll Premium (Follow-up - Agent Ownership)

**Question:** The roll_premium_pct column needs population. Which agent owns this concern?

| Option | Description | Selected |
|--------|-------------|----------|
| Wire into BarAggregatorComputeAgent | BarAggregatorComputeAgent already processes HTF bars; it can derive front/back price from active contracts and populate roll_premium_pct for bars in roll windows | |
| FeatureWriterAgent enriches | FeatureWriterAgent already writes to intelligence_features; have it subscribe to market.events.roll and enrich applicable bars | |
| RollComputeAgent publishes gap | RollComputeAgent already detects rolls; extend RollEvent schema to include price gap, FeatureWriter consumes | |

**User's choice:** Free text response
> "i dont even recall wha all this logic is supposed to do. We want to design this like Renaissance would..."

**Notes:** User didn't recall the feature's purpose. This highlighted that the feature was incomplete experimental code. Renaissance analysis led to removal decision.

---

## Graduation Meaning

**Question:** RollComputeAgent exists but is disabled. What does 'graduation' mean here?

| Option | Description | Selected |
|--------|-------------|----------|
| Enable systemd service | Enable and start indicagent-roll-compute.service; verify RollEvents flow to topic_roll_events | |
| Wait for D-21 validation | Service should be deployed but we need 5m data first — graduation conditional on D-21 pass | |
| Decommission RollComputeAgent | Remove the systemd unit entirely — roll detection was a failed experiment | ✓ |

**User's choice:** Free text response
> "We want to design this like Renaissance would..."

**Notes:** Renaissance principle "Ship complete features or remove them" applied. Feature removed entirely.

---

## DualDivergence Gate

**Question:** trad_DualDivergence has 0 signals, so the N≥100 gate can never pass. Is this expected?

| Option | Description | Selected |
|--------|-------------|----------|
| Expected — wait for gate | Plugin fires rarely (dual OFI+CVD divergence); may take months to reach N=100 | ✓ |
| Add manual override path | Allow manual promotion after human review of even small sample sizes | |
| Lower the threshold | Adjust the gate (e.g., N=30) for this rare-fire pattern | |
| Defer indefinitely | Accept that DualDivergence may never graduate; remove gate check | |

**User's choice:** Free text response
> "We dont have a 2nd provider and the logic should be bypassed unless we have 2 to compare"

**Notes:** User commented on "2nd provider" which referred to dual OFI+CVD confirmation (not data providers). Clarified that DualDivergence should stay in shadow awaiting data.

---

## Phase Scope

**Question:** Given these decisions, what should Phase 50 actually deliver?

| Option | Description | Selected |
|--------|-------------|----------|
| Comprehensive phase | Full scope: 5m view + backfill, roll feature end-to-end, DualDivergence decision — 4-5 plans | |
| Cleanup only | Minimal scope: Just remove dead code (roll agent, DualDivergence) — 1-2 plans | |
| Split into subphases | Split Phase 50: 50.1 (5m backfill), 50.2 (roll decision), 50.3 (DualDivergence decision) | ✓ |

**User's choice:** Split into subphases

**Notes:** Phase split into 50.1, 50.2, 50.3 for clearer scope boundaries.

---

## Claude's Discretion

**Areas deferred to Claude:**
- Migration reversion strategy (DROP COLUMN syntax)
- Service cleanup order (stop/disable before removal)
- 5m view type decision (materialized vs continuous aggregation)
- RollComputeAgent removal scope (which files/references)

---

## Deferred Ideas

None — discussion stayed within phase scope.

---
