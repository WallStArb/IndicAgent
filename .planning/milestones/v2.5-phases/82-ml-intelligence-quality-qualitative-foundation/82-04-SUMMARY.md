---
phase: 82-ml-intelligence-quality-qualitative-foundation
plan: "04"
subsystem: regime-gate-soft-multiplier
tags: [regime-gate, soft-multiplier, hmm, entropy, three-band, prometheus, settings]
dependency_graph:
  requires: [82-02]
  provides: [regime-soft-gate, REGIME_PROB_SOFT_MAX, REGIME_SOFT_GATE_SIGNALS_TOTAL]
  affects: [regime_gate.py, intelligence_pipeline_agent, settings, metrics]
tech_stack:
  added: []
  patterns: [linear-interpolation, entropy-attenuation, three-band-gate, prometheus-counter-labeling]
key_files:
  created:
    - tests/unit/test_regime_gate_soft.py
  modified:
    - src/intelligence/pipeline/regime_gate.py
    - src/config/settings.py
    - src/observability/metrics.py
    - services/intelligence_pipeline_agent.py
decisions:
  - "SOFT_BAND_FLOOR = 0.5 as module constant — minimum multiplier at prob_min edge"
  - "Entropy attenuation formula: multiplier *= max(0.5, 1 - 0.5 * entropy / log2(3)) — halves at uniform distribution"
  - "Division-by-zero protected via max(1e-9, prob_soft_max - prob_min)"
  - "Counter uses prometheus_client.Counter directly (not _safe_counter) since it's defined before the _safe_counter helper"
  - "intelligence_pipeline_agent caches self._regime_prob_soft_max at init from Settings"
metrics:
  duration_minutes: 3
  completed_date: "2026-05-13"
  tasks_completed: 3
  tasks_total: 3
  files_changed: 5
---

# Phase 82 Plan 04: Three-Band Regime Soft Gate Summary

**One-liner:** Binary regime gate replaced with three-band soft multiplier using linear interpolation and entropy-weighted attenuation in the 0.30–0.55 probability transition window, with per-band Prometheus counter and configurable Settings thresholds.

---

## Objective

Replace the binary regime gate (suppress below 0.30 / pass above) with a three-band design that preserves signals in the high-noise transition window (0.30–0.55) at attenuated confidence rather than discarding them entirely.

---

## Task 1: REGIME_PROB_SOFT_MAX Setting and Prometheus Counter

**Files modified:** `src/config/settings.py`, `src/observability/metrics.py`

**Changes:**
- Added `REGIME_PROB_SOFT_MAX: float = Field(default=0.55, validation_alias="REGIME_PROB_SOFT_MAX")` to `Settings` class, below the existing `regime_prob_min`/`regime_dur_min` fields
- Added comment referencing CONTEXT.md D-04
- Added `REGIME_SOFT_GATE_SIGNALS_TOTAL` Counter in `src/observability/metrics.py` with `["band"]` label, placed in the regime gate section
- Used `prometheus_client.Counter` directly (not `_safe_counter`) since the counter is defined before the `_safe_counter` helper further down in the file

**Verification:**
```
Settings().REGIME_PROB_SOFT_MAX == 0.55 ✓
REGIME_SOFT_GATE_SIGNALS_TOTAL.labels(band='soft').inc() — no error ✓
ruff check exits 0 ✓
```

---

## Task 2: Three-Band Gate Logic + Pipeline Wire

**Files modified:** `src/intelligence/pipeline/regime_gate.py`, `services/intelligence_pipeline_agent.py`

**Three-band logic:**
```
prob < 0.30                  → regime_eligible=False, suppression_reason="regime_prob"
0.30 <= prob < 0.55          → regime_eligible=True, calibrated_confidence *= multiplier
prob >= 0.55                 → regime_eligible=True, calibrated_confidence unchanged
```

**`_entropy_multiplier(prob, entropy, prob_min, prob_soft_max) -> float`:**
```python
t = clamp((prob - prob_min) / max(1e-9, prob_soft_max - prob_min), 0, 1)
base = SOFT_BAND_FLOOR + (1 - SOFT_BAND_FLOOR) * t          # [0.5, 1.0]
if entropy is not None:
    entropy_factor = max(0.5, 1 - 0.5 * entropy / log2(3))  # [0.5, 1.0]
    base *= entropy_factor
return base
```

- `SOFT_BAND_FLOOR = 0.5` — minimum multiplier at the lower edge
- At `prob = 0.30, entropy=None` → multiplier = 0.5
- At `prob = 0.55, entropy=None` → multiplier ≈ 1.0
- Uniform entropy (`log2(3)`) halves the effective multiplier relative to zero-entropy
- Division-by-zero protected via `max(1e-9, prob_soft_max - prob_min)`

**Counter band assignments:**
- Band 1 (suppressed): `REGIME_SOFT_GATE_SIGNALS_TOTAL.labels(band="suppressed").inc()`
- Band 2 (soft): `REGIME_SOFT_GATE_SIGNALS_TOTAL.labels(band="soft").inc()`
- Band 3 (full): `REGIME_SOFT_GATE_SIGNALS_TOTAL.labels(band="full").inc()`

**`apply_regime_gate` signature change:**
```python
async def apply_regime_gate(
    signals, regime_data, *, prob_min=0.30, prob_soft_max=0.55, dur_min=1, ...
)
```

**intelligence_pipeline_agent.py:**
- Added `self._regime_prob_soft_max: float = self.settings.REGIME_PROB_SOFT_MAX` at init (~line 467)
- Added `prob_soft_max=self._regime_prob_soft_max` kwarg to `apply_regime_gate` call (~line 1337)

**Boundary math verified:**
```
_entropy_multiplier(0.30, None, 0.30, 0.55) = 0.5000 ✓
_entropy_multiplier(0.549, None, 0.30, 0.55) = 0.9980 ✓
```

---

## Task 3: Unit Tests

**File created:** `tests/unit/test_regime_gate_soft.py`

**9 tests (all pass):**

| Test | Covers |
|------|--------|
| `test_entropy_multiplier_boundary_low` | multiplier == 0.5 at prob_min |
| `test_entropy_multiplier_boundary_high` | multiplier ≈ 1.0 at prob_soft_max - ε |
| `test_entropy_multiplier_division_safety` | finite float when band width = 0 |
| `test_suppress_below_prob_min` | band 1 suppression path |
| `test_soft_band_attenuates_confidence` | band 2 eligible + attenuated |
| `test_soft_band_eligible_with_high_entropy_further_reduces` | entropy interaction |
| `test_full_band_unchanged_confidence` | band 3 full confidence unchanged |
| `test_counter_increments_in_soft_band` | Prometheus counter band="soft" |
| `test_settings_wire_through` | Settings.REGIME_PROB_SOFT_MAX == 0.55, regime_prob_min == 0.30 |

---

## Deviations from Plan

None — plan executed exactly as written. One minor implementation note: the `REGIME_SOFT_GATE_SIGNALS_TOTAL` counter was registered with `prometheus_client.Counter` directly (not `_safe_counter`) because it is defined before the `_safe_counter` helper function appears in `metrics.py`. This is consistent with the pattern used by `REGIME_GATE_SUPPRESSIONS_TOTAL` immediately above it.

---

## Self-Check: PASSED

- `src/intelligence/pipeline/regime_gate.py` modified: YES (SOFT_BAND_FLOOR, _entropy_multiplier, three-band logic, counter increments)
- `src/config/settings.py` modified: YES (REGIME_PROB_SOFT_MAX field)
- `src/observability/metrics.py` modified: YES (REGIME_SOFT_GATE_SIGNALS_TOTAL counter)
- `services/intelligence_pipeline_agent.py` modified: YES (_regime_prob_soft_max + kwarg)
- `tests/unit/test_regime_gate_soft.py` created: YES
- All 9 unit tests pass: YES
- ruff check exits 0 on all modified files: YES
- Commits: 584c099a, 2f976fb7, 7a49c1b4
