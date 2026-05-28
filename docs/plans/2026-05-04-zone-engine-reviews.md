---
phase: zone-engine
reviewers: [claude-code, codex]
reviewed_at: 2026-05-04
plans_reviewed: [2026-05-04-structural-zone-engine-plan.md]
---

# Cross-AI Plan Review — Structural Zone Engine

**Version:** 1.0
**Status:** archived
**Last Updated:** 2026-05-05
## Claude Code Review

### Summary
Plan has good bones — zone engine core (Tasks 1-2) and schema bump (Task 5) are clean. Tasks 4, 6, and 7 have significant issues that need rework before execution.

### Blockers (3)
1. **Task 4:** `_resolve_zone_bounds` replacement calls `features.get("stop_loss", 0.0)` — key doesn't exist in features dict. Stop is a local variable in `frame_trade()`.
2. **Task 6:** `self._ledger_repo` doesn't exist on `SignalTrackerComputeAgent`. Agent is DB-ignorant by design. `update_market_entry` doesn't exist on repo.
3. **Task 6:** Uses `sig.get("market_price_at_signal")` — wrong field. Bootstrap query uses `market_entry_price`.

### Warnings (8)
1. `counter()` helper doesn't support labels — will crash at runtime
2. No `histogram()` helper in metrics.py
3. **Loses setup_type-aware zone logic** — specialized zones for FVG, OB, sweep, demand/supply replaced with generic structural
4. `features["zone_source"]` mutates dict in-place
5. Market-entry code placement fragile relative to error handling
6. Fibonacci retracement levels used as extension targets (dead code for longs)
7. Hidden dependency between Task 3 and Task 2
8. Schema bump may break downstream consumers

---

## Codex Review

### Summary
Directionally useful, but would not approve as written. Biggest issue: treats the new structural zone engine as a *replacement* for setup-specific execution geometry, when current code already encodes materially different entry semantics. Task 6 also violates the architecture.

### Blockers (3 — all confirmed)
1. **Task 6 persistence architecture is wrong.** Compute agent has no repo and should not get one. Current flow is compute -> Kafka `lifecycle.transitions` -> writer -> repository. `TransitionType` has no market-entry event today.
2. **Wrong market-entry source field.** Bootstrap selects `market_entry_price`, not `market_price_at_signal`.
3. **Zone engine cannot depend on `features["stop_loss"]`.** `frame_trade()` resolves stop before zone bounds — pass `stop` explicitly.

### Additional High-Severity Findings (missed by first reviewer)
1. **Candidate clustering can select wrong side of setup.** Filtering between entry and stop excludes zones around/above entry for sweep/reclaim and momentum continuation.
2. **Clustering score ignores candidate quality.** `member_count * width_penalty` prefers three weak stale levels over two high-quality structural ones. Strength, source diversity, recency, and setup relevance should be in score.
3. **Duplicate level inflation.** Multiple features may represent the same underlying level (nearest_support, sr_nearest_support, swing_low, VAL, demand boundary). Without dedup by source family and price tolerance, clusters get artificial member counts.

### Medium Findings
1. Metrics plan doesn't match helper API
2. Lifecycle market-entry state is underspecified
3. Schema bump incomplete (no DB migration for `zone_source`)
4. Stop/target candidates need feature key verification (avoid duplicating existing VWAP/VP/FVG/OB/Kalman/S/R/liquidity levels)

### Architecture Call on Task 6
Market-entry outcomes should go through Kafka:
1. Add `TransitionType.MARKET_RESOLUTION` to `LifecycleTransition`
2. SignalTrackerComputeAgent maintains separate market track state, uses `sig["market_entry_price"]`
3. On market track resolution, publish `market_resolution` lifecycle event
4. Add writer support in `LifecycleWriterAgent`/`SignalLedgerRepository.batch_execute()`

### Design Call on Setup-Specific Logic
**Preserve setup-specific logic. Structural engine should augment, not replace.**

Recommended approach:
```
resolve_zone_bounds(setup_type, direction, entry, stop, features, atr):
  1. Ask setup-specific resolver for primary thesis zone
  2. Ask structural engine for confluence inside/near thesis zone
  3. If setup zone exists: refine or score it, don't replace
  4. If setup zone absent/invalid: use generic structural zone
  5. If no structure: use setup-aware ATR fallback
```

### Zone Quality Recommendations
- Deduplicate candidates within tick/ATR tolerance by source family
- Require source diversity for "confluence" rather than raw count
- Include strength in cluster score
- Penalize stale swing/liquidity levels
- Handle invalid ATR, inverted stop/entry, NaN/inf, zero-width clusters
- Avoid LVN as support/resistance — LVNs are traversal zones; HVN/VA boundaries are better

### Stop/Target Recommendations
- MA stops: gate on protective side of entry + trend context agreement
- Fib retracements are not extension targets — keep as entry-zone/stop-side candidates only
- Good additions: prior day H/L, session H/L, opposing supply/demand boundary, BSL for longs / SSL for shorts
- LVN targets: target far edge of LVN or next HVN, not midpoint

### Codex Approval Condition
Split Task 6 into event-contract/writer change, and rewrite Task 4 so zone engine is setup-aware instead of replacing existing setup geometry wholesale.

---

## Consensus Summary

### Agreed Strengths
- Extracting zone resolution into pure `zone_engine.py` is correct — testable, keeps trade_framer clean
- Candidate collection from S/R, MAs, VP, liquidity, overnight is the right direction
- Dual tracking is conceptually sound — `evaluate_market_entry()` already exists
- `zone_source` attribution is valuable for ML analysis

### Agreed Concerns (highest priority)
1. **Setup-type regression is the biggest design flaw** — both reviewers flag that replacing specialized zone geometry with generic confluence is a behavioral regression, not an improvement. Codex recommends "augment, don't replace" architecture.
2. **Task 6 must use Kafka events, not DB repo** — unanimous. Compute agents stay DB-ignorant.
3. **Wrong field names** — `market_entry_price` not `market_price_at_signal`, `stop` not `features.get("stop_loss")`.
4. **Metrics API mismatch** — must use `Counter()`/`Histogram()` directly, not non-existent helpers.

### Divergent Views
- Codex identified additional issues missed by first review: duplicate level inflation, clustering score ignoring candidate quality, and setup-type-aware zone filtering. These are genuine gaps.
- Codex was more specific on the "augment not replace" architecture, providing concrete pseudocode.

### Action Items Before Execution
1. **Rewrite Task 4** — zone engine as augment layer over setup-specific logic, not replacement
2. **Rewrite Task 6** — Kafka event contract + writer change, not DB repo
3. **Fix all three blockers** (wrong field names, missing API)
4. **Add deduplication + source diversity to clustering** (Task 2)
5. **Remove Fib extension targets from Task 7**, keep as pullback candidates only
