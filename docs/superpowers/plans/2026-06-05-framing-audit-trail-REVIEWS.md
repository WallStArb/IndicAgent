---
reviewers: [gemini, codex]
reviewed_at: 2026-06-05T16:30:00Z
plan_reviewed: docs/superpowers/plans/2026-06-05-framing-audit-trail.md
---

# Cross-AI Plan Review — Framing Audit Trail

## Gemini Review

### 1. Summary
The plan is structurally sound and effectively addresses the goal of capturing framing audit trails, with a clear sequential path from memory to persistent storage. It correctly identifies the necessity of maintaining architectural invariants by centralizing the `TradeFrame` generation and propagating data through the signal schema rather than ad-hoc injection. However, there is a significant risk concerning the plugin categorization logic which requires immediate remediation before implementation begins.

### 2. Strengths
- **Architectural Cleanliness:** Refactoring manual key injection (e.g., in `cross_asset_divergence.py`) back into the canonical `make_signal_from_frame()` is an excellent move for system consistency.
- **Instrumentation Strategy:** The use of OpenTelemetry histograms combined with specific structlog debug triggers provides high-quality observability for regime drift without polluting standard logs.
- **Sequential Logic:** The plan maps out dependencies clearly, ensuring that data structures are updated before database schemas and persistence logic.

### 3. Concerns
- **HIGH — Categorization Inconsistency:** The plan admits in Task 3, step 3.4 that the listed "any-regime" plugins overlap with the "trend" and "mean-reversion" plugins defined earlier. Implementing this as-is will lead to mis-labeled data in `signal_ledger` and inaccurate OTel metrics.
- **MEDIUM — Database Schema Drift:** The plan does not explicitly address handling of legacy data (pre-migration) when `signal_writer` processes historical events or re-reads from the ledger.
- **MEDIUM — Positional Parameter Fragility:** Hardcoding positional parameters (e.g., `$33` in `_INSERT_SQL`) is highly brittle and error-prone during refactors.
- **LOW — Missing Invariant Check:** No mention of a validation step to ensure `adaptive_buffer_mult` is never negative, which could cause issues in downstream volatility calculations.

### 4. Suggestions
- **Audit Plugin Categorization:** Before starting Task 3, create a simple script to extract `regime_type` definitions from all 24 plugins to ensure each is explicitly assigned exactly one of `("trend", "mean_reversion", "any")`. Update the implementation plan with this finalized mapping.
- **Refactor SQL Queries:** Consider a helper to generate the query string dynamically to reduce the risk of index misalignment.
- **Backward Compatibility:** Ensure `signal_writer.py` provides sensible defaults (e.g., `1.0` for multiplier, `None` for regime) when reading pre-migration ledger entries to prevent runtime type errors.
- **Add Invariant Validation:** Add a `__post_init__` check in the `TradeFrame` dataclass to assert `adaptive_buffer_mult > 0`.

### 5. Risk Assessment: **MEDIUM**
The risk is primarily tied to the data integrity of the audit trail due to the current categorization conflicts. If the mapping is corrected and validated before execution, the implementation itself is low-risk. Proceeding with the current inconsistent categorization will result in polluted analytical data, necessitating a difficult post-facto cleanup.

---

## Codex Review

### 1. Summary
The plan is directionally sound: it follows the existing in-process framing-to-signal-to-ledger path and keeps the audit fields close to where framing decisions are made. The main risks are schema/API consistency and undercounting the surface area. The migration plan needs to include `signal_ledger_full` view recreation and downstream read paths. I would rate this as a good plan that needs tightening before implementation.

### 2. Strengths
- Capturing framing metadata in `TradeFrame` is the right source of truth; it avoids recomputing stop logic later in persistence.
- Propagating through `make_signal_from_frame()` preserves the construction invariant for I7 signals.
- Nullable DB columns are appropriate for a backward-compatible migration.
- Adding tests at framer, schema, and writer boundaries covers the most important handoff points.
- OTel metric placement in `src/observability/metrics.py` matches the project constraint to avoid `prometheus_client`.
- Removing manual `signal["stop_basis"]` injection is the right cleanup if `make_signal_from_frame()` becomes authoritative.

### 3. Concerns
- **HIGH — `signal_ledger_full` missing from migration plan:** The ledger is split — fire-time columns in `signal_ledger`, lifecycle columns in `signal_outcomes`, many consumers query `signal_ledger_full`. Adding columns only to `signal_ledger` and the insert path will not expose them to existing readers unless the view is recreated in the same migration.
- **HIGH — Call-site count and categorization unreliable:** The plan says 26 call sites but does not guarantee this is exhaustive. The plan also admits the any-regime list duplicates trend/mean-reversion plugins. This is likely to leave Hurst tightening partially inactive or incorrectly active.
- **HIGH — Field naming internally inconsistent:** The plan uses `regime_type_used` (TradeFrame), `plugin_regime_type` (signal dict), and `regime_type` in existing code. Pick one semantic contract for the signal payload and one DB column name, otherwise aggregator/persistence/analytics may silently diverge.
- **MEDIUM — `stop_type_col` is probably unnecessary and harmful:** `stop_type` is not a PostgreSQL reserved word. Naming the DB column `stop_type_col` creates avoidable mapping friction and makes analytics less natural. Prefer `stop_type` unless there is a proven migration conflict.
- **MEDIUM — "Five audit fields" is underspecified:** Task 2 lists four added signal keys while `stop_type` already exists and `stop_structure_type`/`stop_structure_age_bars` already exist on `TradeFrame` but are not mentioned for signal/DB persistence. The exact audit contract should be enumerated once.
- **MEDIUM — Adaptive multiplier capture may be ambiguous:** `_adaptive_buffer()` can be called with different base multipliers for different stop bases. The plan should explicitly define whether `adaptive_buffer_mult` is the final absolute multiplier, the regime adjustment factor, or `_adaptive_buffer(features, 1.0, regime_type)` — those are analytically different.
- **MEDIUM — Metrics cardinality:** `stop_type` should be normalized to a bounded enum-like value before recording. Recording every `frame_trade()` call is okay only if signal volume is modest and rejected frames are intentionally included or excluded.
- **LOW — Structlog debug condition is incomplete:** Logging only when multiplier differs from 1.0 may miss bad wiring where `regime_type` is never passed. Temporary counters for `regime_type=None` / `"any"` rates would catch that better.
- **LOW — Test plan misses migration/view verification:** Unit tests cover Python propagation, but there should be at least one schema-oriented assertion that `signal_ledger_full` exposes the new columns.

### 4. Suggestions
- Define a single canonical audit payload — `stop_type`, `stop_basis`, `structural_stop_distance_atr`, `adaptive_buffer_mult`, `plugin_regime_type` — and use the same names in `TradeFrame`, signal dict, DB, and analytics.
- Recreate `signal_ledger_full` view in migration 119.
- Prefer `stop_type` as the DB column name unless a real conflict is demonstrated.
- Replace "26 call sites" with a mechanical acceptance check: every `frame_trade(` call in `src/intelligence/trading` must pass `regime_type=` or appear in an explicit short allowlist.
- Fix plugin regime categorization before implementation. A duplicated any-regime list changes stop behavior, not just documentation.
- Add tests for rejected/non-viable frames, or explicitly document that audit fields are only persisted for viable frames.
- Add a writer test that verifies `dict` and `list` values go directly into JSONB fields without `json.dumps`.

### 5. Risk Assessment: **MEDIUM**
The implementation is not conceptually risky and the data path is well chosen. The risk comes from schema/view drift, inconsistent naming, and incomplete call-site coverage. Fix those before coding and this becomes a contained observability and persistence enhancement.

---

## Consensus Summary

Both Gemini and Codex independently flagged the same core risks and agreed on the plan's strengths.

### Agreed Strengths
- Centralizing audit field construction in `make_signal_from_frame()` is the right invariant — both reviewers praised it
- OTel histogram + conditional structlog debug is good operational strategy
- Sequential task ordering (TradeFrame → signal dict → DB) is the correct dependency chain
- Nullable DB columns are the right backward-compat choice

### Agreed Concerns

1. **Plugin categorization is broken (HIGH — both reviewers):** The any-regime list in Task 3.4 duplicates trend and mean-reversion plugins. This will produce mis-labeled `plugin_regime_type` in `signal_ledger`, corrupting the primary research value of this feature. Must be audited with a grep before Task 3 begins.

2. **Positional parameter fragility (MEDIUM — both reviewers):** `_INSERT_SQL` hardcoded to `$33` is brittle. The parameter count must be verified against the dataclass field count before execution.

### Divergent Views

- **Gemini** flagged missing backward-compat defaults when reading pre-migration rows. Codex did not raise this (nullable columns with `sig.get(...)` defaulting to `None` may be sufficient).

- **Codex** raised `signal_ledger_full` view omission (HIGH) — the view will not expose the new columns until recreated. Gemini did not flag this. This is a real gap: migration 119 must include `CREATE OR REPLACE VIEW signal_ledger_full AS ...`.

- **Codex** flagged `stop_type_col` as an unnecessary renaming — `stop_type` is not a PostgreSQL reserved word. Worth confirming before creating the avoidable friction.

- **Codex** raised the naming inconsistency (`regime_type_used` vs `plugin_regime_type`) as HIGH. Worth picking one name and aligning TradeFrame field, signal dict key, and DB column before execution.
