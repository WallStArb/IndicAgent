# Phase 7: Composite Intelligence Score (CIS) — Research

**Researched:** 2026-02-27
**Domain:** Python ML-augmented signal aggregation, TimescaleDB schema evolution, I7 plugin protocol
**Confidence:** HIGH (all findings from direct codebase inspection + official docs)

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**Phase Boundary:** Replace the current winner-pick I7 aggregator with a principled Composite Intelligence Score (CIS) that:
- Aggregates ALL intelligence tiers (I1–I6) into 6 decorrelated factor buckets
- Produces a single directional probability score per bar (CIS ∈ [-1.0, +1.0])
- Self-improves via logistic regression trained on live signal outcomes
- Starts with designed weights, transitions to learned weights automatically
- Adds 5 new evidence-contributor I7 plugins (bringing total to 14)
- Improves entry type precision for 4 existing setups

This phase is self-contained: all existing 9 I7 plugins remain unchanged; stream keys, signal format, and trade_framer structural logic are unchanged.

**5 New I7 Plugins (Phase A — evidence contributors only, not standalone signals):**
All 5 follow standard PatternPlugin protocol and are registered in TIER_I7:
- `trad_CHoCHReversal` — early trend flip signal; inputs: `choch_detected`, `choch_direction`, `hmm_regime`; bucket: Structure + Regime
- `trad_FVGFill` — FVG magnetism; inputs: `fvg_type`, `fvg_open_count`, `fvg_top`, `fvg_bottom`; bucket: Institutional
- `trad_PatternCompletion` — confirmed I5 patterns; inputs: `dt_db_*`, `hs_*`, `tri_*` from I5; bucket: Pattern
- `trad_DivergenceStack` — dual divergence (RSI + volume must both agree); inputs: `rsi_div_*`, `vol_div_*`; bucket: Momentum + Pattern
- `trad_RegimeTransition` — regime flip bet; inputs: `cp_probability`, `choch_detected`, `hmm_regime` flip; bucket: Regime + Structure

**6 Factor Buckets (Phase B):**

| Bucket | Bootstrap Weight | Key Inputs |
|--------|-----------------|------------|
| Trend | 0.20 | trend_regime, kalman_slope, smc_trend_direction, ctf_trend_alignment, trend_confluence_score |
| Momentum | 0.20 | roc_14, macd_histogram, rsi_14 vs 50, momentum_context, stoch_k, DivergenceStack output |
| Structure | 0.15 | swing_pattern, bos_detected+direction, choch_detected+direction, trend_strength, CHoCHReversal output |
| Pattern | 0.05 | dt_db_confidence+direction, hs_confidence, tri_confidence+breakout_bias, PatternCompletion output |
| Institutional | 0.25 | ob_type+strength, fvg_type, in_demand/supply_zone, sweep_type, premium_position, bsl/ssl_significance, FVGFill output, SupplyDemand output |
| Regime | 0.15 | hmm_prob_trending_up/down/ranging, cp_probability, garch_vol_state, vol_regime, ctf_regime_agreement, RegimeTransition output |

**CIS Fire Conditions (Phase B):**
```
CIS = sum(weights[i] * bucket_scores[i] for i in range(6))
fires = abs(CIS) > 0.35 AND buckets_agreeing >= 3
```
Signal type label derived from two highest-weighted agreeing buckets.

**signal_ledger Schema Additions (Phase B):**
Four new columns: `cis_score FLOAT`, `bucket_scores JSONB`, `weights_version INTEGER`, `signal_quality FLOAT`

**cis_weights Table (Phase C):**
```sql
CREATE TABLE cis_weights (
    id SERIAL PRIMARY KEY,
    version INTEGER NOT NULL,
    weights_type TEXT NOT NULL,  -- 'designed' | 'learned'
    symbol TEXT DEFAULT 'global',
    timeframe TEXT DEFAULT 'global',
    trend_w FLOAT NOT NULL, momentum_w FLOAT NOT NULL,
    structure_w FLOAT NOT NULL, pattern_w FLOAT NOT NULL,
    institutional_w FLOAT NOT NULL, regime_w FLOAT NOT NULL,
    threshold FLOAT NOT NULL DEFAULT 0.35,
    n_training_samples INTEGER, signal_quality_mean FLOAT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
```

**Adaptive Weight Learning (Phase C):**
- n_resolved < 50: use 'designed' weights, no retraining
- 50 ≤ n < 100: train but keep 70% designed / 30% learned blend
- n ≥ 100: full learned weights, nightly retraining
- LogisticRegression (sklearn, C=1.0, max_iter=500) on bucket scores → binary quality above mean
- Normalize coefficients via softmax, enforce min_w=0.05 per bucket

**Entry Type Improvements (Phase D):**
- `momentum_breakout_*` → `at_limit` at `swing_high/low`
- `squeeze_expansion_*` → `at_limit` at `bb_middle`
- `trend_long/short` → `at_pullback` at `nearest_support/resistance` or key MA
- `mtf_alignment_*` → `at_pullback` at `ctf` confluence level
- Implementation: `_resolve_entry()` in `trade_framer.py` gains two new entry type cases

**Unchanged Components:**
- All 9 existing I7 plugins, PatternPlugin protocol, stream keys, signal format, trade_framer structural logic, dashboard field names

### Claude's Discretion
- Exact bucket scorer implementation structure (separate class vs inline in aggregator)
- Test organization within plans (unit tests per plugin vs consolidated test file)
- Whether weight_updater.py is a standalone script or importable module
- sklearn dependency handling (already in project or needs adding)
- Specific logistic regression feature engineering details not covered by PRD

### Deferred Ideas (OUT OF SCOPE)
- Per-symbol cis_weights rows (deferred until ≥100 resolved signals per symbol)
- i7/i8 columns in intelligence_features (backlog)
- ML scoring model (backlog — XGBoost/LightGBM, needs 90 days history)
- Dashboard visualization of CIS score and bucket breakdown (not in this phase)
</user_constraints>

---

## Summary

Phase 7 replaces the current priority-based winner-pick aggregator (`src/intelligence/trading/aggregator.py`) with a principled Composite Intelligence Score (CIS) architecture. The research confirms all required intelligence fields are already computed and published in `IntelligenceEvent` — no upstream changes are needed. The 5 new I7 plugins follow the identical `PatternPlugin` dataclass pattern used by the 9 existing plugins and slot cleanly into the `TIER_I7` constant.

The most important discovery is that **scikit-learn is not installed** in the project venv. The weight_updater.py logistic regression requires `scikit-learn` to be added to `requirements.txt` and installed. This is the only new external dependency. The signal_ledger migration is a straightforward `ADD COLUMN IF NOT EXISTS` pattern consistent with prior migrations (010_signal_ledger_feature_cols.sql). The cis_weights table is a standard PostgreSQL table (not a hypertable) since it is version-keyed by integer, not time-series.

The implementation order (A → B → C → D) must be sequential: new plugins are needed before the CIS scorer can call them, and the scorer must exist before weight learning has anything to train on. Entry type improvements in Phase D are independent of weight learning but depend on the CIS aggregator being in place to produce the signals that use the new entry types.

**Primary recommendation:** Implement in strict A→B→C→D sequence. Each plan is independently testable and deployable. Start Phase A with TDD for all 5 new plugins before touching the aggregator.

---

## Standard Stack

### Core (already in project)

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| numpy | >=2.4.0 | Numerical computation in plugins | Already in requirements.txt; all I7 plugins use it |
| pandas | >=3.0.0 | DataFrame used in `frames["main"]` | Already in requirements.txt; plugin interface requires it |
| pydantic | >=2.12.0 | IntelligenceEvent schema | Already in use throughout the pipeline |
| asyncpg | >=0.31.0 | Async PostgreSQL writes | Already used in signal_ledger.py and db_manager.py |
| structlog | >=25.5.0 | Structured logging | Already used throughout services |

### New Dependency (must be added)

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| scikit-learn | >=1.5.0 | LogisticRegression for weight_updater.py | Only Python ML library with LogisticRegression + softmax out of box; lightweight, no GPU required |

**Installation (Phase C prerequisite):**
```bash
pip install scikit-learn>=1.5.0
# Add to requirements.txt: scikit-learn>=1.5.0
```

### Supporting (already available)

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| pytest | >=8.4.0 | Unit test framework | All new plugin + CIS tests |
| json (stdlib) | stdlib | JSONB serialization in signal_ledger | LedgerEntry.to_insert_params() already uses it |
| scipy | optional | softmax for weight normalization | NOT needed — implement softmax inline (3 lines) |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| scikit-learn LogisticRegression | scipy.special.expit + manual gradient descent | More code, no benefit — sklearn is the standard |
| scikit-learn | statsmodels | statsmodels heavier; sklearn is already the reference for simple logistic regression |
| Inline softmax | scipy.special.softmax | scipy is not in requirements.txt; inline is trivial and avoids new dep |

---

## Architecture Patterns

### Recommended Project Structure (new files only)

```
src/intelligence/trading/
├── choch_reversal.py          # Phase A: trad_CHoCHReversal plugin
├── fvg_fill.py                # Phase A: trad_FVGFill plugin
├── pattern_completion.py      # Phase A: trad_PatternCompletion plugin
├── divergence_stack.py        # Phase A: trad_DivergenceStack plugin
├── regime_transition.py       # Phase A: trad_RegimeTransition plugin
├── cis_scorer.py              # Phase B: BucketScorer class + CISResult dataclass
└── aggregator.py              # Phase B: REPLACE current winner-pick with CIS logic

production/migrations/
└── 011_signal_ledger_cis_cols.sql   # Phase B: cis_score, bucket_scores, weights_version, signal_quality
└── 012_cis_weights_table.sql        # Phase C: CREATE TABLE cis_weights

src/intelligence/
└── weight_updater.py          # Phase C: nightly weight retraining script
```

### Pattern 1: New I7 Evidence-Contributor Plugin

**What:** Follows identical PatternPlugin dataclass protocol as existing 9 plugins. Returns directional score and confidence but is designed to be consumed by CIS bucket scorers, not published directly as a signal winner.

**When to use:** For all 5 new plugins in Phase A.

**Example:**
```python
# Source: direct codebase inspection of src/intelligence/trading/trend_following.py
# and src/intelligence/trading/momentum_breakout.py

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any
import numpy as np
from ..plugins import InputSpec

@dataclass
class CHoCHReversalPlugin:
    """Evidence contributor: early CHoCH reversal signal for CIS Structure+Regime buckets."""

    name: str = "trad_CHoCHReversal"
    outputs: frozenset[str] = frozenset({
        "signal_type", "direction", "entry_price", "stop_loss",
        "targets", "confidence", "regime_context", "supporting_factors",
    })
    min_lookback: int = 20
    supports_incremental: bool = False
    capability_tags: frozenset[str] = frozenset({"trading", "structure", "reversal"})
    inputs: tuple[InputSpec, ...] = (InputSpec(symbol=".*", timeframe="1m", lookback=100),)
    _state: dict = field(default_factory=dict)

    def compute_full(self, frames: dict[str, Any]) -> dict[str, Any]:
        features = frames.get("features") or {}
        df = frames.get("main")
        if df is None or len(df) < self.min_lookback:
            return {}

        choch_detected = float(features.get("choch_detected", 0.0))
        if choch_detected != 1.0:
            return self._no_signal()

        choch_direction = int(features.get("choch_direction", 0))
        hmm_regime = float(features.get("hmm_regime", 0.0))
        # ... computation ...

    def compute_next(self, windows: dict[str, Any]) -> dict[str, Any]:
        return self.compute_full(windows)

    @staticmethod
    def _no_signal() -> dict[str, Any]:
        return {"signal_type": "none", "direction": 0, "confidence": 0.0}

plugin = CHoCHReversalPlugin()
```

**Critical:** The `plugin` module-level singleton must be declared at the bottom. `register_plugins.py` imports `plugin` from each module.

### Pattern 2: CIS Scorer Class

**What:** Separate `CISScorer` class in `cis_scorer.py` that reads bucket inputs from the flat `features` dict and computes 6 directional scores.

**When to use:** Instantiated once by the new CIS aggregator in `aggregator.py`.

**Example:**
```python
# Source: PRD design doc + codebase patterns
from dataclasses import dataclass
from typing import Any

BUCKET_NAMES = ("trend", "momentum", "structure", "pattern", "institutional", "regime")

BOOTSTRAP_WEIGHTS: dict[str, float] = {
    "trend": 0.20,
    "momentum": 0.20,
    "structure": 0.15,
    "pattern": 0.05,
    "institutional": 0.25,
    "regime": 0.15,
}

@dataclass
class CISResult:
    cis_score: float                   # [-1.0, +1.0]
    direction: int                     # -1, 0, +1
    bucket_scores: dict[str, float]    # {"trend": 0.4, ...}
    weights_version: int               # from cis_weights table
    buckets_agreeing: int

class CISScorer:
    def score(
        self, features: dict[str, Any], plugin_outputs: dict[str, dict]
    ) -> CISResult:
        ...
```

### Pattern 3: Aggregator Replacement

**What:** `aggregator.py` is replaced wholesale. New `aggregate()` function signature must remain compatible because `signal_generator_service.py` calls `aggregate(raw_signals, trend_regime=...)` and uses `result.selected_signal` and `result.all_ranked`.

**Critical compatibility requirement:** `AggregatedResult` dataclass fields `selected_signal`, `all_ranked`, `resolution_method`, `num_signals_fired`, `num_agreeing`, `num_conflicting` must all still be present. The `selected_signal` dict must still contain `signal_type`, `direction`, `entry_price`, `stop_loss`, `targets`, `confidence`, `supporting_factors`. New fields `cis_score`, `bucket_scores`, `weights_version` are additions, not replacements.

**When to use:** Phase B replaces the existing `aggregate()` function.

### Pattern 4: signal_ledger Schema Migration

**What:** `ADD COLUMN IF NOT EXISTS` statements, consistent with migration 010.

**When to use:** Phase B migration file.

**Example:**
```sql
-- Source: production/migrations/010_signal_ledger_feature_cols.sql pattern
-- 011_signal_ledger_cis_cols.sql

ALTER TABLE signal_ledger
    ADD COLUMN IF NOT EXISTS cis_score        FLOAT,
    ADD COLUMN IF NOT EXISTS bucket_scores    JSONB,
    ADD COLUMN IF NOT EXISTS weights_version  INTEGER,
    ADD COLUMN IF NOT EXISTS signal_quality   FLOAT;

-- Index for weight_updater queries (resolved signals with outcomes)
CREATE INDEX IF NOT EXISTS idx_ledger_resolved_cis
    ON signal_ledger (weights_version, signal_quality)
    WHERE weights_version IS NOT NULL AND signal_quality IS NOT NULL;
```

### Pattern 5: LedgerEntry Extension

**What:** `LedgerEntry` dataclass gains 4 new optional fields. `to_insert_params()` grows from 24 to 28 elements. The INSERT SQL gains 4 new parameters.

**Critical:** asyncpg uses positional parameters ($1, $2, ...). Adding new params requires updating both the SQL string AND the `to_insert_params()` tuple length in sync. JSONB fields (bucket_scores) must be `json.dumps()` serialized.

```python
# New fields on LedgerEntry dataclass
cis_score: float | None = None
bucket_scores: dict | None = None
weights_version: int | None = None
signal_quality: float | None = None  # populated by signal_tracker on exit

# in to_insert_params():
# $25: cis_score (FLOAT, nullable)
# $26: bucket_scores::jsonb (nullable — json.dumps or None)
# $27: weights_version (INTEGER, nullable)
# $28: signal_quality (FLOAT, nullable)
```

### Pattern 6: Weight Updater Script

**What:** Standalone Python script (importable as module per Claude's Discretion). Queries `signal_ledger` for resolved signals, trains LogisticRegression, writes new version to `cis_weights`.

**When to use:** Phase C. Can be run manually or via cron.

```python
# Source: PRD design doc, sklearn LogisticRegression API
from sklearn.linear_model import LogisticRegression
import numpy as np

def _softmax(x: np.ndarray) -> np.ndarray:
    """3-line inline softmax — avoids scipy dependency."""
    e = np.exp(x - x.max())
    return e / e.sum()

def _clip_and_renormalize(weights: np.ndarray, min_w: float = 0.05) -> np.ndarray:
    clipped = np.maximum(weights, min_w)
    return clipped / clipped.sum()

# Training
model = LogisticRegression(C=1.0, max_iter=500, random_state=42)
model.fit(X, y)
raw_weights = _softmax(model.coef_[0])
final_weights = _clip_and_renormalize(raw_weights)
```

### Pattern 7: Entry Type Extension in trade_framer.py

**What:** `_resolve_entry()` currently handles 3 cases: `sweep_reclaim_*`, `supply_demand_*`, and fallthrough `at_close`. Phase D adds `at_limit` (for breakout setups) and `at_pullback` (for trend/MTF setups).

**Key constraint:** `TradeFrame.entry_type` field annotation currently lists `"at_close" | "at_reclaim" | "zone_proximal"`. The string annotation comment in the dataclass must be updated to include `"at_limit" | "at_pullback"`.

```python
# Extended _resolve_entry() — Phase D
def _resolve_entry(setup_type, direction, entry_price, features):
    st = setup_type.lower()
    if st.startswith("sweep_reclaim") or st.startswith("liquidity_hunt"):
        return entry_price, "at_reclaim"
    if st.startswith("supply_demand"):
        # ... existing zone_proximal logic ...
    if st.startswith("momentum_breakout"):
        # at_limit: enter at the broken structure level
        level = _fval(features, "swing_high" if direction == 1 else "swing_low")
        if level > 0:
            return level, "at_limit"
    if st.startswith("squeeze_expansion") or st.startswith("squeeze"):
        # at_limit: enter at bb_middle (squeeze centre)
        bb_middle = _fval(features, "bb_middle")
        if bb_middle > 0:
            return bb_middle, "at_limit"
    if st.startswith("trend_"):
        # at_pullback: nearest_support (long) or nearest_resistance (short)
        if direction == 1:
            level = _fval(features, "nearest_support") or _fval(features, "sr_nearest_support")
        else:
            level = _fval(features, "nearest_resistance") or _fval(features, "sr_nearest_resistance")
        if level > 0:
            return level, "at_pullback"
    if st.startswith("mtf_alignment"):
        # at_pullback: ctf confluence level (use nearest_support/resistance as proxy)
        if direction == 1:
            level = _fval(features, "nearest_support") or _fval(features, "sr_nearest_support")
        else:
            level = _fval(features, "nearest_resistance") or _fval(features, "sr_nearest_resistance")
        if level > 0:
            return level, "at_pullback"
    return entry_price, "at_close"
```

### Anti-Patterns to Avoid

- **Modifying existing I7 plugin files in Phase A.** The 9 existing plugins must remain untouched.
- **Changing stream key format or signal dict top-level keys.** The dashboard reads from `signals:SYMBOL:TF:aggregated` and expects `signal_type`, `entry_price`, `stop_loss`, etc.
- **Using a hypertable for cis_weights.** It is version-keyed by integer, not time. Use a plain `CREATE TABLE`.
- **Forgetting to update `TIER_I7` in `register_plugins.py`.** `registry.validate_tier()` hard-crashes at startup if any TIER_I7 name is missing from the registry. The service will not start.
- **Forgetting to update `test_i7_registration.py`.** The test asserts `total == 57` (23 indicators + 34 patterns). Adding 5 new I7 plugins brings patterns to 39 and total to 62. Both the expected set and the count assertion must be updated.
- **Using MagicMock without `isinstance` guard.** The codebase rule: `isinstance(val, (int, float))` not `if val` — MagicMock is truthy and `float(MagicMock())` returns 1.0.
- **Skipping the fallback `at_close` in `_resolve_entry`.** If no structural level is found for `at_limit` or `at_pullback`, must fall back to `at_close` — not return None or raise.
- **Building bucket scorer without handling None features.** All IntelligenceEvent fields are `Optional[float]` or `Optional[int]`. The `_fval()` helper from `trade_framer.py` is the canonical safe-getter — use it or replicate its pattern.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Logistic regression weight training | Custom gradient descent | `sklearn.linear_model.LogisticRegression` | Handles convergence, regularization, numerical stability |
| Softmax normalization | scipy.special.softmax | 3-line inline (`np.exp(x - x.max()) / sum`) | Avoids scipy dependency; trivial to implement correctly |
| JSONB serialization | Custom encoder | `json.dumps()` (already used in signal_ledger.py) | Already the project pattern for asyncpg JSONB params |
| Safe float feature extraction | Direct `features["key"]` | `_fval()` from trade_framer.py | Handles None, missing keys, type errors — 10 lines, tested |
| Feature flattening from IntelligenceEvent | Custom mapper | `_build_features_from_event()` in signal_generator_service.py | Already flattens all tiers + handles BB/SR aliases |

**Key insight:** The `features` dict that arrives at the CIS scorer is already fully flattened by `_build_features_from_event()`. The bucket scorers never need to touch `event.i3.swing_pattern` directly — they call `features.get("swing_pattern")`.

---

## Common Pitfalls

### Pitfall 1: TIER_I7 / Registration Mismatch

**What goes wrong:** New plugin file exists but not imported in `register_plugins.py` or not added to `TIER_I7` constant. `registry.validate_tier(I7_PLUGINS, "I7")` is called at service startup and raises `ValueError`, crashing the service.

**Why it happens:** Two separate places require updating: (1) `register_all_plugins()` function body, (2) `TIER_I7` list at the bottom of the file.

**How to avoid:** In Phase A, for each new plugin: add import at top of `register_plugins.py`, add `registry.register_pattern(plugin)` call in `register_all_plugins()`, add `plugin.name` to `TIER_I7` list.

**Warning signs:** `ValueError: Tier I7 references unregistered plugin(s)` at service start.

### Pitfall 2: test_i7_registration.py Stale Assertions

**What goes wrong:** After Phase A, the test `test_total_plugin_count` still asserts `total == 57` but the actual count is now 62 (57 + 5 new). Test fails immediately.

**Why it happens:** The test hardcodes both the expected set of I7 plugins and the total count.

**How to avoid:** Update `test_i7_registration.py` as part of Phase A plan:
- Change `expected_i7` set to include all 14 plugin names
- Change count assertion to `assert total == 62`

### Pitfall 3: LedgerEntry / INSERT SQL Parameter Count Mismatch

**What goes wrong:** `to_insert_params()` returns a 28-element tuple but the SQL has $1–$24 (or vice versa). asyncpg raises `PostgresError: too many positional parameters` or a binding error.

**Why it happens:** The SQL positional parameter count and the tuple length must always match. Easy to miss when adding columns.

**How to avoid:** Count the `$N` params in the SQL string and assert `len(params[0]) == N` in a unit test. The existing `test_signal_ledger.py` pattern should be extended.

### Pitfall 4: cis_weights Table Not Bootstrapped Before Service Start

**What goes wrong:** CIS aggregator queries `MAX(version) WHERE symbol = 'global'` but the table is empty → None result → AttributeError or fallback not implemented → service crash on first bar.

**Why it happens:** Phase C introduces the table but the bootstrap row must be seeded.

**How to avoid:** Phase C migration includes an `INSERT` for the bootstrap designed weights row (version=1, weights_type='designed'). CIS aggregator must have a hardcoded fallback to bootstrap weights if the table is unreachable or empty.

### Pitfall 5: bucket_scores JSONB Serialization

**What goes wrong:** `bucket_scores` is a `dict[str, float]` in Python. asyncpg requires JSONB params to be passed as JSON strings (same as `targets`, `supporting_factors` in existing code). Forgetting `json.dumps(bucket_scores)` causes asyncpg type error.

**Why it happens:** asyncpg does not auto-serialize dicts to JSONB. The project pattern (see `to_insert_params()`) already uses `json.dumps()` for all JSONB columns.

**How to avoid:** In `to_insert_params()` extension, `json.dumps(self.bucket_scores) if self.bucket_scores else None`.

### Pitfall 6: New Entry Types Break RR Gate Silently

**What goes wrong:** `at_limit` entry uses `swing_high` as entry price for momentum_breakout_long. If `swing_high < current_close`, entry is *below* current price for a long — the RR gate may reject it as `zero_risk` or compute negative RR.

**Why it happens:** The limit entry level must be checked for validity before use. `_resolve_entry()` must validate that `at_limit` level is directionally sensible.

**How to avoid:** For `at_limit` long, only use the level if `level <= entry_price` (limit below current price). For `at_pullback`, only use if `level <= entry_price` for longs. If the structural level is above current price, fall through to `at_close`.

### Pitfall 7: sklearn Not in requirements.txt

**What goes wrong:** `weight_updater.py` fails with `ModuleNotFoundError: No module named 'sklearn'`. The venv does not have sklearn installed.

**Why it happens:** sklearn is not currently in `requirements.txt` (confirmed by direct inspection).

**How to avoid:** Phase C plan must include a Wave 0 task to add `scikit-learn>=1.5.0` to `requirements.txt` and install it.

### Pitfall 8: Divergence Stack Dual-Agree Logic

**What goes wrong:** `trad_DivergenceStack` plugin requires BOTH RSI divergence AND volume divergence to agree. If only one is present, the plugin returns no signal. The temptation is to fire on either one — but the design locks in the dual-gate.

**Why it happens:** `rsi_div_bullish` and `vol_div_bullish` are confidence scores (0.0–1.0), NOT boolean flags. Threshold must be applied (e.g., > 0.3) before treating as "detected".

**How to avoid:** Explicitly gate on both: `rsi_bullish > threshold AND vol_bullish > threshold` (or both bearish). Return `_no_signal()` if only one fires.

---

## Code Examples

### IntelligenceEvent Fields Available to CIS Buckets

All bucket inputs are already present in the features dict built by `_build_features_from_event()`:

```python
# Source: src/intelligence/schemas.py — verified field names

# Trend bucket inputs
"trend_regime"           # I4Context.trend_regime (float -1..1)
"kalman_slope"           # I4Context.kalman_slope (float)
"smc_trend_direction"    # SMCContext.smc_trend_direction (int -1/0/1)
"ctf_trend_alignment"    # I6Confluence.ctf_trend_alignment (float)
"trend_confluence_score" # I5Patterns.trend_confluence_score (float)

# Momentum bucket inputs
"roc_14"                 # I1Indicators.roc_14 (float — extra field)
"macd_hist_12_26_9"      # I1Indicators.macd_hist_12_26_9 (float)
"rsi_14"                 # I1Indicators.rsi_14 (float)
"momentum_bias"          # I4Context.momentum_bias (float)
"stoch_k"                # I1Indicators.stoch_k (float)

# Structure bucket inputs
"swing_pattern"          # I3Structure.swing_pattern (float -1/0/1)
"bos_detected"           # SMCContext.bos_detected (float 0.0/1.0)
"bos_direction"          # SMCContext.bos_direction (int -1/0/1)
"choch_detected"         # SMCContext.choch_detected (float 0.0/1.0)
"choch_direction"        # SMCContext.choch_direction (int -1/0/1)
"trend_strength"         # I3Structure.trend_strength (float)

# Pattern bucket inputs
"dt_db_confidence"       # I5Patterns.dt_db_confidence (float)
"dt_db_pattern"          # I5Patterns.dt_db_pattern (float 0-4)
"hs_confidence"          # I5Patterns.hs_confidence (float)
"hs_pattern"             # I5Patterns.hs_pattern (float 0-4)
"tri_confidence"         # I5Patterns.tri_confidence (float)
"tri_breakout_bias"      # I5Patterns.tri_breakout_bias (float -1/0/1)

# Institutional bucket inputs
"ob_type"                # SMCContext.ob_type (int -1/0/1)
"ob_strength"            # SMCContext.ob_strength (float)
"fvg_type"               # SMCContext.fvg_type (int -1/0/1)
"in_demand_zone"         # SMCContext.in_demand_zone (float 0.0/1.0)
"in_supply_zone"         # SMCContext.in_supply_zone (float 0.0/1.0)
"sweep_type"             # SMCContext.sweep_type (int -1/0/1)
"premium_position"       # SMCContext.premium_position (float -1..1)
"bsl_significance"       # SMCContext.bsl_significance (float)
"ssl_significance"       # SMCContext.ssl_significance (float)

# Regime bucket inputs
"hmm_prob_trending_up"   # SMCContext.hmm_prob_trending_up (float)
"hmm_prob_trending_down" # SMCContext.hmm_prob_trending_down (float)
"hmm_prob_ranging"       # SMCContext.hmm_prob_ranging (float)
"cp_probability"         # SMCContext.cp_probability (float)
"garch_vol_regime"       # I4Context.garch_vol_regime (int 0/1/2)
"vol_regime"             # I4Context.vol_regime (float)
"ctf_regime_agreement"   # I6Confluence.ctf_regime_agreement (float)
```

### Test Pattern for New I7 Plugins

```python
# Source: tests/unit/intelligence/test_trading_setups.py pattern
# and tests/unit/intelligence/helpers.py

import numpy as np
from tests.unit.intelligence.helpers import make_ohlcv

class TestCHoCHReversal:
    def test_bullish_choch_fires_long(self):
        """choch_detected=1.0 + choch_direction=1 → long signal."""
        from src.intelligence.trading.choch_reversal import CHoCHReversalPlugin
        close = np.full(50, 5000.0)
        df = make_ohlcv(close)
        features = {
            "choch_detected": 1.0,
            "choch_direction": 1,
            "hmm_regime": 0.0,   # ranging → regime flip in direction
            "atr_14": 10.0,
        }
        plugin = CHoCHReversalPlugin()
        result = plugin.compute_full({"main": df, "features": features})
        assert result["direction"] == 1
        assert 0.0 < result["confidence"] <= 1.0

    def test_no_choch_no_signal(self):
        """choch_detected=0 → no signal."""
        from src.intelligence.trading.choch_reversal import CHoCHReversalPlugin
        df = make_ohlcv(np.full(50, 5000.0))
        result = CHoCHReversalPlugin().compute_full({"main": df, "features": {"choch_detected": 0.0}})
        assert result.get("direction", 0) == 0

    def test_insufficient_data_returns_empty(self):
        """Too few bars → empty result."""
        from src.intelligence.trading.choch_reversal import CHoCHReversalPlugin
        df = make_ohlcv(np.full(5, 5000.0))
        result = CHoCHReversalPlugin().compute_full({"main": df, "features": {}})
        assert result == {} or result.get("signal_type", "none") == "none"
```

### CIS Aggregator Call Site (signal_generator_service.py)

The aggregator call in `_process_bar()` currently is:
```python
# Source: services/signal_generator_service.py line ~417
result = aggregate(raw_signals, trend_regime=trend_regime)
```

Phase B must preserve this interface. The new `aggregate()` function signature:
```python
def aggregate(
    signals: list[dict],
    *,
    trend_regime: float = 0.0,
    features: dict | None = None,   # NEW — for CIS bucket scoring
) -> AggregatedResult:
```

The call site in `signal_generator_service.py` must also pass `features=features` after Phase B:
```python
result = aggregate(raw_signals, trend_regime=trend_regime, features=features)
```

This is a controlled, single-file change in `signal_generator_service.py`.

---

## State of the Art

| Old Approach | Current Approach | Introduced | Impact |
|---|---|---|---|
| Winner-pick by priority + regime tiebreak | CIS weighted-bucket aggregation | Phase 7 | Consumes all I1-I6 intelligence; principled directionality |
| at_close for all setups | at_limit / at_pullback for 4 setup types | Phase 7D | Better entry prices, improved RR |
| Static hand-crafted aggregator | Self-learning via logistic regression | Phase 7C | Weights adapt to live market outcomes |

**What stays the same:**
- `signals:SYMBOL:TF:aggregated` Redis stream key format
- Signal dict field names (signal_type, entry_price, stop_loss, targets, confidence)
- All 9 existing I7 plugins (untouched)
- trade_framer.py structural stop/target resolution
- Dashboard field names (new signal_type labels like `cis_trend_momentum_long` are additions)

---

## Open Questions

1. **CIS aggregator: should plugin outputs be passed as first-class inputs to bucket scorers?**
   - What we know: The 5 new plugins produce `direction` and `confidence` outputs. The bucket scorers need a score from each evidence plugin.
   - What's unclear: Does the CIS scorer call `plugin.compute_full(frames)` itself, or does it receive pre-computed `raw_signals` list (which already contains all 14 plugin outputs)?
   - Recommendation: The CIS scorer receives the `raw_signals` list from the service loop (same as current). It finds each plugin's output by `setup_plugin` name in the list. This avoids re-running plugins and keeps the service loop unchanged.

2. **Where does `signal_quality` get populated on signal_ledger?**
   - What we know: `signal_quality = (rr_achieved × confidence_at_fire) / vol_regime_at_fire` — requires outcome data.
   - What's unclear: `signal_tracker_service.py` handles lifecycle exits (pending→active→exit). It would need to compute and write `signal_quality` on exit.
   - Recommendation: Phase C plan includes extending `signal_tracker_service.py` to compute and write `signal_quality` on exit events. The `weight_updater.py` queries `WHERE signal_quality IS NOT NULL`.

3. **mtf_alignment `at_pullback` level — which CTF level to use?**
   - What we know: The CONTEXT.md says "at ctf confluence level". `I6Confluence` has `ctf_score`, `ctf_trend_alignment`, `ctf_structure_alignment` — none are price levels.
   - What's unclear: There is no `ctf_level` price field in the schema.
   - Recommendation: Use `nearest_support` (long) or `nearest_resistance` (short) as the `at_pullback` level for `mtf_alignment_*`. This is the closest structural proxy. Document this as the implementation decision in the Phase D plan.

4. **Bootstrap weight load at CIS startup — sync or async DB query?**
   - What we know: `signal_generator_service.py` is fully async. The CIS aggregator is called from within `_process_bar()`.
   - What's unclear: The current `aggregate()` function is synchronous. Loading weights requires a DB query.
   - Recommendation: Cache weights in a module-level variable updated at service startup and refreshed when a new weight version is available (check MAX(version) every N bars). Do NOT make `aggregate()` async — that would require widespread callsite changes.

---

## Sources

### Primary (HIGH confidence)
- Direct codebase inspection: `src/intelligence/trading/aggregator.py` — current aggregator implementation
- Direct codebase inspection: `src/intelligence/trading/trend_following.py`, `momentum_breakout.py`, `squeeze_expansion.py`, `mtf_alignment.py` — plugin protocol patterns
- Direct codebase inspection: `src/intelligence/schemas.py` — all IntelligenceEvent fields verified
- Direct codebase inspection: `src/intelligence/register_plugins.py` — TIER_I7 constant and registration pattern
- Direct codebase inspection: `src/intelligence/trading/signal_ledger.py` — LedgerEntry and INSERT SQL pattern
- Direct codebase inspection: `src/intelligence/trading/trade_framer.py` — `_resolve_entry()` extension point
- Direct codebase inspection: `services/signal_generator_service.py` — service integration point
- Direct codebase inspection: `production/migrations/010_signal_ledger_feature_cols.sql` — migration pattern
- Direct codebase inspection: `production/schemas/signal_ledger_migration.sql` — hypertable + index patterns
- Direct codebase inspection: `tests/unit/intelligence/test_trading_setups.py` — test structure and helpers
- Direct codebase inspection: `tests/unit/intelligence/test_i7_registration.py` — registration test (must update)
- Direct codebase inspection: `docs/plans/2026-02-27-composite-intelligence-score-design.md` — PRD
- Direct inspection: `.venv/bin/python -c "import sklearn"` → ModuleNotFoundError (sklearn NOT installed)

### Secondary (MEDIUM confidence)
- `requirements.txt` inspection confirms sklearn absent; numpy>=2.4.0, pandas>=3.0.0, asyncpg>=0.31.0 present
- `.planning/config.json` — no `workflow.nyquist_validation` key present (validation section skipped per instructions)

---

## Metadata

**Confidence breakdown:**
- Plugin protocol patterns: HIGH — verified against 4 existing I7 plugin implementations
- CIS architecture: HIGH — PRD design doc plus direct IntelligenceEvent field verification
- Schema migration patterns: HIGH — two existing migrations examined
- Weight learning: HIGH — PRD specifies sklearn LogisticRegression with exact parameters
- sklearn absence: HIGH — confirmed by running import in project venv
- Entry type extension: HIGH — `_resolve_entry()` fully read and understood

**Research date:** 2026-02-27
**Valid until:** 2026-03-27 (stable project, no external API dependencies in scope)
