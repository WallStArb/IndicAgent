# Phase 092: Signal Quality Completeness - Context

**Gathered:** 2026-05-18
**Status:** Ready for planning

<domain>
## Phase Boundary

Add four distribution-shape metrics to `signal_metrics` (skewness, kurtosis, min_r, recovery_factor) and run the compute per-symbol in addition to the global '*' aggregate. With 1.27M resolved signals across 8 outcome types, the data volume is sufficient for statistically valid distribution shape metrics on every setup.

Pure compute additions: DB schema migration + `_build_metrics_result()` update + `SignalMetricsComputeAgent` grouping change. Zero change to signal generation or the I1-I7 pipeline.

</domain>

<decisions>
## Implementation Decisions

### New Metrics
- **D-01:** Four new columns in `signal_metrics` table:
  - `skewness float` — Fisher-Pearson skewness of pnl_rs. Negative = left-tail risk (rare large losses). Computed via `scipy.stats.skew(pnl_rs)` or manual formula to avoid new import (scipy already used in compute.py for t-distribution).
  - `kurtosis float` — Excess kurtosis (Fisher definition, 0=normal). Positive = fat tails. `scipy.stats.kurtosis(pnl_rs, fisher=True)`.
  - `min_r float` — `min(pnl_rs)` — worst single outcome in the rolling window. Simple and interpretable.
  - `p5_r float` — 5th percentile of pnl_rs (`np.percentile(pnl_rs, 5)`). More robust than min_r for recovery_factor denominator — a single outlier event cannot distort the ratio. Use p5_r for recovery_factor; keep min_r for raw worst-case visibility.
  - `recovery_factor float` — `avg_mfe / abs(p5_r)` if `p5_r < 0` else `NULL`. Ratio of average best-case to tail loss. Uses p5_r denominator for outlier robustness.
- **D-02:** All four are `NULL` when `n < 3` (skewness/kurtosis are undefined for tiny samples). `min_r` and `recovery_factor` are `NULL` when `n < MIN_SAMPLE_SIZE` (30) for consistency with other metrics.
- **D-03:** `SignalMetricsResult` dataclass gains four new optional fields with `None` defaults. `SignalMetricsRow` alias unchanged.

### DB Migration
- **D-04:** Idempotent migration — four `ALTER TABLE signal_metrics ADD COLUMN IF NOT EXISTS ...` statements. Run at `SignalMetricsComputeAgent` startup in a dedicated `ensure_schema()` method (follows CacheManager self-management principle).
- **D-05:** Existing rows get `NULL` for new columns — consumers must handle NULL. All existing queries `SELECT ... FROM signal_metrics` are unaffected (no SELECT * anywhere that would break on new columns).

### Per-Symbol Compute
- **D-06:** `SignalMetricsComputeAgent` currently groups by `(setup_plugin, tf, regime_type, window_days)` and writes one row per group with `symbol='*'`. Add a second pass: group by `(setup_plugin, tf, regime_type, window_days, symbol)` and write per-symbol rows — only for symbols with `n >= MIN_SAMPLE_SIZE` (30). Global '*' rows are always written regardless of sample size.
- **D-07:** Per-symbol rows use the same `_build_metrics_result()` function — no new compute logic. The accumulation loop gains a second `by_symbol` dict alongside the existing `by_group` dict.
- **D-08:** Row count increase: ~22 setup_plugins × 4 tfs × 3 regimes × 3 windows × 12 symbols × 2 tracks = ~19k rows max vs current ~1.6k. Acceptable — `signal_metrics` is a small analytics table, not a hypertable. Primary key `(track, setup_plugin, tf, regime_type, window_days, symbol)` already includes symbol.

### Compute Logic
- **D-09:** `_build_metrics_result()` receives `acc` dict with `pnl_rs`, `maes`, `mfes` lists. Skewness and kurtosis computed only when `len(pnl_rs) >= 3`. min_r = `min(pnl_rs)`. p5_r = `float(np.percentile(pnl_rs, 5))` when `len(pnl_rs) >= 20` else `None`. recovery_factor = `round(avg_mfe / abs(p5_r), 4)` when `p5_r is not None and p5_r < -1e-9` else `None`.
- **D-10:** scipy.stats is already imported in compute.py (`from scipy.stats import t as _scipy_t`). Add `from scipy.stats import skew as _scipy_skew, kurtosis as _scipy_kurtosis` — no new dependency.

### Plan Structure
- **D-11:** Two plans, sequential:
  - Plan 01: DB migration + `SignalMetricsResult` dataclass + `_build_metrics_result()` compute additions + unit tests
  - Plan 02: Per-symbol grouping in `SignalMetricsComputeAgent` + integration test verifying per-symbol rows written

### Claude's Discretion
- Whether to extract `_distribution_shape(pnl_rs)` helper returning a dataclass (prefer helper — testable in isolation)
- Exact minimum sample size for per-symbol rows (30 is consistent with MIN_SAMPLE_SIZE)

</decisions>

<canonical_refs>
## Canonical References

- `src/intelligence/metrics/compute.py` — `_build_metrics_result()`, `SignalMetricsResult` dataclass, accumulator pattern
- `src/intelligence/metrics/validator.py` — validation logic (unchanged but read before modifying compute)
- `src/intelligence/services/feature_validation_compute_agent.py` — reference for self-managed startup schema migration pattern
- `.planning/REQUIREMENTS.md` §QUAL-01–QUAL-04
- DB: `signal_metrics` table schema (PK: `track, setup_plugin, tf, regime_type, window_days, symbol`)

</canonical_refs>

<code_context>
## Existing Code Insights

### Compute Pipeline
- `_build_metrics_result(acc, track, setup_plugin, tf, regime_type, window_days, symbol='*')` — adding per-symbol means calling this with `symbol=actual_symbol` in the second accumulation pass.
- `acc` dict has `pnl_rs: list[float]`, `maes: list[float]`, `mfes: list[float]`, `win_flags: list[bool]`, `n_never_activated: int`, `n_total: int`, `n_outliers: int`. All four new metrics derive from `pnl_rs` and `mfes` — no new accumulator fields needed.
- scipy already in requirements.txt (scipy.stats.t used for p-value computation).

### Signal Metrics DB
- `signal_metrics` PK already includes `symbol` column — per-symbol rows are additive, no PK change needed.
- `SELECT ... FROM signal_metrics WHERE symbol = '*'` — existing queries use explicit symbol filter; adding symbol != '*' rows won't affect them.
- `SignalMetricsComputeAgent` runs on a timer (batch, not daemon) — `inactive (dead)` between runs is expected.

### Data Volume
- 1.27M resolved signals across 8 outcome types as of 2026-05-18. Sufficient for statistically valid distribution shape on every setup and per-symbol breakdown.

</code_context>

<specifics>
- "Measure everything, especially tails" — skewness and kurtosis are the minimum viable distribution shape metrics. A signal factory with Sharpe=1.5 but skewness=-2.0 is a liability.
- Per-symbol breakdown: a strategy that's 1.2 Sharpe globally might be 2.0 on ES and -0.3 on ZN. Without per-symbol rows, this is invisible.
- Data is ready: 1.27M resolved signals means no waiting for sample size requirements.
</specifics>

<deferred>
- Maximum drawdown series (not just min_r — full drawdown curve)
- Conditional Value at Risk (CVaR) — 95th percentile loss
- IC decay curve (how information coefficient degrades with signal age)
- Benchmark-relative metrics (alpha vs SPY)
</deferred>

---
*Phase: 092-signal-quality-completeness*
*Context gathered: 2026-05-18 (restored from deferral — data volume confirmed sufficient)*
