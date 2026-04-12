# Pipeline Hardening — Phase 68 Design

**Date:** 2026-04-11
**Status:** Approved — ready for GSD planning
**Author:** Brandon + Claude
**Phase:** 68 — Pipeline Hardening & Institutional Foundation
**Milestone:** v2.4 (follows Phase 67 Observability Hardening)

---

## Problem Statement

A systematic audit of the intelligence pipeline and write-path revealed that the system is
**architecturally sound but operationally fragile** in several concrete ways:

- Signal selection logic contains functional bugs that silently bypass regime filtering
- Confidence scoring has uncalibrated magic constants that defeat calibration curves
- Writer agents have inconsistent reliability contracts (offset commits, DLQ, buffer bounds)
- Critical state is lost on restart (alpha decay)
- Signal provenance is incomplete (resolution method discarded, attribution vector partial)
- No end-to-end trace from bar receipt to lifecycle exit

All historical signal data in `signal_ledger` was generated with bypassed regime type
filtering and is not trustworthy as training data. A clean slate on this table is part
of this phase.

---

## Renaissance Alignment

| Principle | Violation Fixed |
|-----------|----------------|
| Instrument everything | resolution_method discarded; attribution vector incomplete; agreement count not stored; regime suppression unmetered |
| Earn the right through proof | long bias hardcoded with no empirical backing; agree-boost defeats calibration |
| Degrade gracefully, adapt automatically | alpha decay resets on restart; offset commits inconsistent |
| Never drop data that could contain signal | malformed payloads silently dropped; n_agreeing never stored |
| Data quality over model complexity | contaminated signal_ledger from bypassed regime gate |
| Segment relentlessly | regime type filtering completely bypassed — trend/mean-reversion plugins fire in wrong regimes |

---

## Scope

**In scope:**
- 5 signal pipeline correctness fixes + 4 attribution/instrumentation improvements
- BaseWriterAgent base class + migration of all 5 writer agents
- 3 write-path reliability fixes (offset commit, DLQ, bounded buffer)
- End-to-end bar_id trace from provider to lifecycle exit
- DB schema migration (bar_id, attribution columns, unique constraint)
- TRUNCATE signal_ledger (clean slate — regime-contaminated data)

**Not in scope:**
- New I7 plugins
- Changes to I1–I6 tier logic
- Calibration curve retraining
- Historical signal_ledger backfill

---

## Plan 68-01 — Signal Pipeline Correctness

**Files:** `services/intelligence_pipeline_agent.py`, `src/intelligence/pipeline/`,
`src/config/settings.py`, `src/observability/metrics.py`

### Fix 1: Regime Type Filtering Bypassed (Critical Bug)

**Root cause:** `apply_regime_gate()` reads `sig.get("regime_type", "any")` from the
signal dict. Plugins declare `regime_type` as a class attribute but never include it in
their return dict. Result: every signal defaults to `"any"` → `_REGIME_MAP["any"] = [0,1,2]`
→ all regimes allowed. `MeanReversionPlugin` never suppresses in trending markets.
`MomentumBreakoutPlugin` never suppresses in ranging markets. The regime type gate
produces zero filtering.

**Fix:** In `_run_i7`, after collecting plugin output and before calling `apply_regime_gate`,
inject the plugin's class-level `regime_type` into the signal dict:

```python
for task, output in zip(tasks, outputs):
    if output.get("direction", 0) != 0:
        sig = output
        # Inject plugin's declared regime_type from class attribute
        plugin_inst = self._plugin_cache.get(task.plugin_name)
        sig["regime_type"] = getattr(plugin_inst, "regime_type", "any")
        sig["setup_plugin"] = task.plugin_name
        ...
```

This must happen BEFORE `apply_quality_gate` so the value is present for regime gating.
The annotation loop at line ~1419 that overwrites `sig["regime_type"]` with the HMM
numeric value must be removed (see Fix 3).

### Fix 2: `_regime_dur_min` Wrong Type + Settings Thresholds Never Wired

**Root cause:**
```python
self._regime_prob_min: float = 0.30
self._regime_dur_min: float = 0.30  # wrong: should be int ~1-5 bars
```
Neither value is passed to `apply_regime_gate()`. The call is:
```python
regime_gated = apply_regime_gate(quality_gated, features)
# prob_min and dur_min always use function defaults, Settings ignored
```

**Fix:**
1. Load from Settings in `_setup()`:
   ```python
   self._regime_prob_min: float = self._settings.regime_prob_min
   self._regime_dur_min: int = self._settings.regime_dur_min
   ```
2. Pass to call site:
   ```python
   regime_gated = apply_regime_gate(
       quality_gated, features,
       prob_min=self._regime_prob_min,
       dur_min=self._regime_dur_min,
   )
   ```
3. Verify `Settings.regime_dur_min` field type is `int` (not `float`).

### Fix 3: `regime_type` in Features is Numeric, Not a Label

**Root cause:**
```python
f["regime_type"] = f.get("hmm_regime", "ranging")  # hmm_regime is 0.0, 1.0, or 2.0
```
This stores a numeric HMM state as `regime_type`. At line ~1419,
`sig["regime_type"] = features.get("regime_type")` stamps a float into the ledger where
a string label is expected. Additionally, this overwrites the plugin's class-level
`regime_type` (injected in Fix 1) with a meaningless numeric value.

**Fix:** In `_build_features_from_event`, separate the two concepts:
```python
_HMM_TO_LABEL: dict[int, str] = {0: "ranging", 1: "trend", 2: "trend"}

# Keep numeric hmm_regime for regime gate numeric check
f["hmm_regime"] = hmm_val  # numeric: 0, 1, 2

# Separate label for human-readable annotation (ledger, logs)
hmm_int = int(hmm_val) if hmm_val is not None else None
f["hmm_regime_label"] = _HMM_TO_LABEL.get(hmm_int, "unknown")
```

In the annotation loop, stamp `hmm_regime_label` not `regime_type`:
```python
sig["hmm_regime_label"] = features.get("hmm_regime_label")
sig["hmm_regime_at_fire"] = features.get("hmm_regime")  # numeric, already present
# Do NOT overwrite sig["regime_type"] — it was set from plugin class attr in Fix 1
```

Add `hmm_regime_label` column to `signal_ledger` in migration 063.

### Fix 4: Long Bias Hardcoded in Winner Tie-break

**Root cause:**
```python
majority_group = by_direction[1] if longs >= shorts else by_direction[-1]
# "deliberately bias toward long to avoid short-side noise" — no empirical backing
```
This fires on every tied bar, has no parameter, no shadow mode, no statistical validation.

**Fix:** Add to `Settings`:
```python
winner_long_bias: bool = Field(default=True, validation_alias="WINNER_LONG_BIAS")
```

In `_aggregate_fallback`, neutral tiebreak when disabled:
```python
if longs == shorts:
    if settings.winner_long_bias:
        majority_group = by_direction[1]
    else:
        # Neutral: take highest adjusted_rank signal across both directions
        majority_group = sorted(active, key=lambda s: s.get("adjusted_rank", 999))[:1]
else:
    majority_group = by_direction[1] if longs > shorts else by_direction[-1]
```

Default `True` preserves current behavior. Set `WINNER_LONG_BIAS=false` to test neutral.

### Fix 5: `_CONFIDENCE_BOOST_PER_AGREE` Defeats Calibration

**Root cause:** `_CONFIDENCE_BOOST_PER_AGREE = 0.05` is applied in `_aggregate_via_cis`
BEFORE calibration curves run. 10 agreeing signals → +0.50 confidence, potentially
forcing a signal to 1.0 before isotonic calibration can correct it. Uncalibrated,
not statistically justified.

**Fix:** Remove the confidence boost entirely from `_aggregate_via_cis` and
`_aggregate_fallback`. Instead, record the agreement data so it can be analyzed:
```python
# In signal dict, before publish:
sig["n_agreeing_signals"] = len([s for s in active if s.get("direction") == winner_direction])
sig["n_opposing_signals"] = len([s for s in active if s.get("direction") != winner_direction])
```

Add `n_agreeing_signals INT`, `n_opposing_signals INT` columns to `signal_ledger`
(migration 063). Once 30+ days of clean data accumulates, run correlation analysis:
if agreement predicts outcomes (p < 0.05), add the boost back with calibrated coefficient.

### Fix A: `resolution_method` Discarded — Live Attribution Bug

**Root cause:**
```python
winner, _, resolution_method = select_winner(ranked, cis_result)
# _ throws away resolution_method — never stamped into signal dicts
```
`signal_ledger.resolution_method` column exists but is always NULL. Cannot query
"do CIS-overridden signals outperform priority-majority selections?"

**Fix:** Stamp into winner signal and all ranked signals:
```python
winner, _, resolution_method = select_winner(ranked, cis_result)
for sig in ranked:
    sig["resolution_method"] = resolution_method
```

### Fix B: `setup_last_fire` Not Checkpointed — Alpha Decay Resets on Restart

**Root cause:** `_checkpoint_state` saves 5 fields. `_setup_last_fire` is absent.
Every restart: alpha decay state = empty → every plugin fires at full confidence
for the first bar regardless of how recently it fired before restart.

**Fix:** Add `_setup_last_fire` to state checkpoint:
```python
state = {
    "_plugin_states": self._plugin_states,
    "_kalman_state": self._kalman_state,
    "_tod_priors": self._tod_priors,
    "_bar_history": self._bar_history._data,
    "_last_bar_offset": self._last_bar_offset,
    "_setup_last_fire": self._setup_last_fire,   # ADD
}
```

### Fix C: Full 5-Point Confidence Attribution Vector

**Current state:** `pre_quality_confidence` and `pre_calibration_confidence` exist.
Missing: `pre_regime_confidence` (after quality, before regime gate) and
`pre_tod_confidence` (after regime, before TOD). Cannot measure regime gate drag
or TOD adjuster drag individually.

**Fix:** Capture at all 4 intermediate checkpoints:
```python
# Before quality gate (existing)
for sig in raw_signals:
    sig["pre_quality_confidence"] = sig.get("confidence", 0.0)

quality_gated = apply_quality_gate(raw_signals, features)

# NEW: before regime gate
for sig in quality_gated:
    sig["pre_regime_confidence"] = sig.get("confidence", 0.0)

regime_gated = apply_regime_gate(quality_gated, features, ...)

# NEW: before TOD adjustment
for sig in regime_gated:
    sig["pre_tod_confidence"] = sig.get("confidence", 0.0)

tod_adjusted = apply_tod_adjustment(regime_gated, ...)

# Before calibration (existing)
for sig in tod_adjusted:
    sig["pre_calibration_confidence"] = sig.get("confidence", 0.0)

calibrated = apply_calibration(tod_adjusted, ...)
```

Add `pre_regime_confidence FLOAT`, `pre_tod_confidence FLOAT` to `signal_ledger`
(migration 063).

**Attribution invariant (enforced by test):**
`pre_quality >= pre_regime >= pre_tod >= pre_calibration >= calibrated_confidence`

### Fix F: Regime Suppression Not Metered

After fixing regime type filtering, suppression starts working — but is unmetered.
Without a counter, we can't verify the fix, measure suppression rate, or detect
a market condition causing 80%+ suppression (which would indicate a different problem).

**Fix:** Add to `src/observability/metrics.py`:
```python
REGIME_GATE_SUPPRESSIONS_TOTAL = counter(
    "regime_gate_suppressions_total",
    "Signals suppressed by regime gate",
    labelnames=["reason", "plugin", "tf"],
)
```

In `_run_i7`, after `apply_regime_gate`, for each suppressed signal:
```python
for sig in regime_gated:
    if not sig.get("regime_eligible", True):
        REGIME_GATE_SUPPRESSIONS_TOTAL.labels(
            reason=sig.get("suppression_reason", "unknown"),
            plugin=sig.get("setup_plugin", "unknown"),
            tf=tf,
        ).inc()
```

---

## Plan 68-02 — BaseWriterAgent + Write-path Reliability

**Files:** `src/core/agent/base_writer.py` (new), `services/signal_writer_agent.py`,
`services/lifecycle_writer_agent.py`, `services/bar_writer_agent.py`,
`services/feature_writer_agent.py`, `services/swarm_writer_agent.py`

### BaseWriterAgent

The buffer/flush/consume/teardown pattern is copy-pasted across all 5 writer agents.
The reliability fixes (offset commit, DLQ, bounded buffer) are the same in each.
A `BaseWriterAgent` consolidates shared machinery so fixes land once and every
current + future writer inherits them.

**Location:** `src/core/agent/base_writer.py`

**Interface:**
```python
class BaseWriterAgent(BaseAgent, ABC):
    """Owns: buffer lifecycle, flush scheduling, manual offset commit,
    DLQ routing, Prometheus buffer depth gauge, teardown flush.

    Subclasses declare:
      _topic_name()    → str
      _consumer_group  → str (class var)
      _parse_payload() → list | None  (None = route to DLQ)
      _flush_batch()   → None         (raise on failure = retry)
      _dlq_topic()     → str | None   (None = log-only fallback)
    """

    BATCH_SIZE: ClassVar[int] = 100
    FLUSH_INTERVAL_SECS: ClassVar[float] = 5.0
    MAX_BUFFER_SIZE: ClassVar[int] = 10_000
    BUFFER_ALERT_PCT: ClassVar[float] = 0.80  # alert when depth > 80% of max

    @abstractmethod
    def _topic_name(self) -> str: ...

    @property
    @abstractmethod
    def _consumer_group(self) -> str: ...

    @abstractmethod
    async def _parse_payload(self, payload: dict) -> list | None: ...

    @abstractmethod
    async def _flush_batch(self, batch: list) -> None: ...

    def _dlq_topic(self) -> str | None:
        return None  # override in subclass to enable DLQ routing
```

**Run loop (owned by base):**
```
consume → _parse_payload() → None? → DLQ  → continue
                            → rows → buffer → check flush
                                              → size trigger → _flush_batch()
                                              → time trigger → _flush_batch()
                                              → _flush_batch() success → commit offset
                                              → _flush_batch() failure → retain buffer, log
```

**Reliability properties guaranteed by base:**
- `enable_auto_commit=False` on all consumers
- Offset committed only after `_flush_batch()` succeeds
- Buffer capped at `MAX_BUFFER_SIZE` with overflow metric
- `_buffer_depth` gauge published every consume cycle
- Alert log when depth > `BUFFER_ALERT_PCT * MAX_BUFFER_SIZE`
- Teardown: final flush before consumer stop
- DLQ route when `_parse_payload()` returns None

**Writer migration:** Each of the 5 writers reduces to:
- `_parse_payload()` — deserialization / validation
- `_flush_batch()` — repository call
- `_topic_name()` — topic string
- `_consumer_group` — group ID
- Domain-specific `_setup()` additions (e.g., contract cache for bar_writer)

Estimated post-migration size: ~50–80 lines per writer vs 200–800 today.

---

## Plan 68-03 — Trace ID + Clean Slate + DB Hardening

**Files:** `services/ibkr_provider_agent.py`, `src/core/schemas/bar_message.py`,
`services/intelligence_pipeline_agent.py`, writer agents (via BaseWriterAgent),
`production/migrations/063_pipeline_hardening.sql`

### Trace ID: bar_id Originates at the Provider

`bar_id` must originate in `ibkr_provider_agent` when publishing to `market.bars`,
not in `intelligence_pipeline_agent`. This enables `bar_auditor_agent` to detect bars
that reached Kafka but never appeared in `intelligence_features` — i.e., bars lost
mid-pipeline.

**Changes:**
1. `src/core/schemas/bar_message.py`: add `bar_id: UUID = Field(default_factory=uuid4)`
2. `ibkr_provider_agent`: stamp `bar_id=uuid4()` on each `BarMessage` before publish
3. `intelligence_pipeline_agent`: carry `bar.bar_id` through to `IntelligenceEvent`
   and `BarIntelligenceRecord` — no new UUID generation at this layer
4. Writer agents (via BaseWriterAgent): pass `bar_id` through to DB insert
5. `bar_auditor_agent`: cross-reference `market.bars` bar_ids vs `intelligence_features`
   bar_ids to detect pipeline drops (future — not in this phase scope)

### Migration 063: `063_pipeline_hardening.sql`

All schema changes in a single migration file:

```sql
-- bar_id trace column
ALTER TABLE signal_ledger         ADD COLUMN IF NOT EXISTS bar_id UUID;
ALTER TABLE intelligence_features ADD COLUMN IF NOT EXISTS bar_id UUID;

-- Full confidence attribution vector (pre_regime, pre_tod)
ALTER TABLE signal_ledger
    ADD COLUMN IF NOT EXISTS pre_regime_confidence FLOAT,
    ADD COLUMN IF NOT EXISTS pre_tod_confidence    FLOAT;

-- HMM regime label (string)
ALTER TABLE signal_ledger ADD COLUMN IF NOT EXISTS hmm_regime_label TEXT;

-- Agreement signal counts
ALTER TABLE signal_ledger
    ADD COLUMN IF NOT EXISTS n_agreeing_signals INT,
    ADD COLUMN IF NOT EXISTS n_opposing_signals INT;

-- Signal deduplication (idempotent replay safety)
ALTER TABLE signal_ledger
    ADD CONSTRAINT IF NOT EXISTS uq_signal_ledger_identity
    UNIQUE (symbol, feature_ts, feature_tf, setup_plugin);

-- Clean slate: all historical signals have bypassed regime type filtering
TRUNCATE TABLE signal_ledger;

-- Indexes for new columns
CREATE INDEX IF NOT EXISTS idx_signal_ledger_bar_id ON signal_ledger (bar_id);
CREATE INDEX IF NOT EXISTS idx_intel_features_bar_id ON intelligence_features (bar_id);
```

**Why TRUNCATE is correct:**
- Every signal in `signal_ledger` was generated with Fix 1's bug active — regime type
  filtering was completely bypassed. Mean-reversion signals fired in trending markets,
  trend signals fired in ranging markets. The outcome labels are valid but the entry
  conditions are contaminated. Using this data to train or calibrate would embed the bug.
- `intelligence_features` is unaffected — feature vectors are not influenced by signal
  selection logic. Keep intact as ML training dataset.
- `market_data_ohlcv` unaffected — raw price data, ground truth.

---

## Wave Ordering

```
Wave A (independent):  Plan 68-01 — Signal pipeline correctness
Wave A (independent):  Plan 68-02 — BaseWriterAgent + write-path reliability
Wave B (after 68-01):  Plan 68-03 — Trace ID + clean slate + migration
```

Plans 68-01 and 68-02 can execute in parallel — they touch disjoint files.
Plan 68-03 depends on 68-01 because `bar_id` must flow through the corrected
pipeline (if the pipeline has bugs, the trace is also incorrect).

---

## Success Criteria

1. A `MeanReversionPlugin` signal is suppressed (status=regime_suppressed) when
   `hmm_regime=1` (trending-up) — verifiable via `signal_ledger` query
2. `regime_gate_suppressions_total{reason="regime_type"}` counter increments in
   production within first trading session after deploy
3. `Settings.regime_prob_min` and `regime_dur_min` changes take effect on next
   service restart without code changes
4. `signal_ledger.resolution_method` is non-null for all rows after deploy
5. `signal_ledger.pre_regime_confidence` and `pre_tod_confidence` are non-null
6. After service restart, alpha decay does not reset (first bar confidence matches
   expected decayed value, not raw plugin confidence)
7. All 5 writer agents inherit `BaseWriterAgent`; offset committed only after
   successful DB flush (verify via manual-commit consumer group lag)
8. Malformed Kafka payloads route to DLQ, not silent drop
9. `signal_ledger.bar_id` matches the `bar_id` in the corresponding
   `intelligence_features` row for the same `(symbol, feature_ts, feature_tf)`
10. `signal_ledger` is empty after TRUNCATE; new signals accumulate with clean
    regime filtering from first bar

---

## Files Changed Summary

| File | Plan | Change |
|------|------|--------|
| `services/intelligence_pipeline_agent.py` | 68-01 | Fixes 1-5, A, B, C, F |
| `src/intelligence/pipeline/winner_selector.py` | 68-01 | Fix 4 (long bias param), Fix 5 (remove boost) |
| `src/intelligence/pipeline/regime_gate.py` | 68-01 | No change (fix is in caller) |
| `src/config/settings.py` | 68-01 | `winner_long_bias`, `regime_dur_min` type fix |
| `src/observability/metrics.py` | 68-01 | `regime_gate_suppressions_total` counter |
| `src/core/agent/base_writer.py` | 68-02 | New file — BaseWriterAgent |
| `services/signal_writer_agent.py` | 68-02 | Migrate to BaseWriterAgent |
| `services/lifecycle_writer_agent.py` | 68-02 | Migrate to BaseWriterAgent |
| `services/bar_writer_agent.py` | 68-02 | Migrate to BaseWriterAgent |
| `services/feature_writer_agent.py` | 68-02 | Migrate to BaseWriterAgent |
| `services/swarm_writer_agent.py` | 68-02 | Migrate to BaseWriterAgent |
| `src/core/schemas/bar_message.py` | 68-03 | Add `bar_id: UUID` field |
| `services/ibkr_provider_agent.py` | 68-03 | Stamp `bar_id=uuid4()` on publish |
| `production/migrations/063_pipeline_hardening.sql` | 68-03 | All schema changes + TRUNCATE |
