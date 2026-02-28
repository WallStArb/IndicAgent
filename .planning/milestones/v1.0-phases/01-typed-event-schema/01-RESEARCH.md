# Phase 1: Typed Event Schema - Research

**Researched:** 2026-02-22
**Domain:** Pydantic v2 schema migration, Redis stream format, service-level refactor
**Confidence:** HIGH

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**Sub-tier typing depth:**
- Every tier gets a dedicated typed Pydantic sub-model — not `dict[str, Any]`
- Models live in `src/intelligence/schemas.py` alongside `IntelligenceEvent`
- All models use `model_config = ConfigDict(extra="forbid")` — unknown fields are rejected at the publisher, not silently dropped downstream
- Sub-models: `OHLCVBar`, `I1Indicators`, `I3Structure`, `I4Context`, `I5Patterns`, `SMCContext`, `I6Confluence`

**i7 exclusion from IntelligenceEvent:**
- `IntelligenceEvent` does NOT include i7 signal output
- `source: Literal["live", "backfill"] = "live"` is included for provenance tracking

**i3 tier — keep as distinct tier:**
- i3 = structural facts about price: swing highs/lows, support/resistance, trend structure state
- Distinct from i4 (quantitative regime), i5 (pattern detection)

**Migration strategy — sequential by service, no compat shim:**
- No `to_legacy_dict()`, no dual-format publishing
- Three stages matching three plan tasks:
  1. `01-01`: Define schema models + update publisher (market_analysis_service.py) + update publisher tests
  2. `01-02`: Migrate signal_generator_service.py and SSE route + update their tests
  3. `01-03`: Delete intelligence_processor_service.py, audit remaining consumers, update remaining tests
- Each commit is a complete, green-tests migration of one service

**Schema versioning:**
- `schema_version: Literal["1.0"] = "1.0"` on `IntelligenceEvent`
- String literal, not int — allows minor versions ("1.1") without breaking consumers that check "1.x"
- Consumers receiving unknown version should log warning and skip the event (not crash)

### Claude's Discretion
- Exact field names within each sub-model tier (e.g., `rsi_14` vs `rsi14` within I1Indicators)
- Whether to use `model_validator` for cross-field validation within sub-models
- Exact type annotations for complex i3/i5/smc fields (e.g., list of swing points as `list[float]` vs named struct)
- How to handle None/optional fields within sub-models for plugins that may not run on all timeframes

### Deferred Ideas (OUT OF SCOPE)
- `intelligence_features` hypertable and Feature Writer Service — Phase 2
- Plugin state persistence (get_state/restore_state protocol) — Phase 2 or separate task
- Auth layer — Phase 6
- Cloudflare Tunnel / external access — Phase 6
- ML export endpoint — Phase 5+
</user_constraints>

---

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| BUS-01 | System defines `IntelligenceEvent` Pydantic model with tiered JSONB structure (i1/i3/i4/i5/smc/i6), version field, and `platform` dimension | Pydantic v2 `ConfigDict(extra="forbid")`, `Literal`, nested `BaseModel` sub-models — verified pattern in codebase; `src/intelligence/schemas.py` is the target file |
| BUS-02 | `market_analysis_service.py` publishes `IntelligenceEvent` to `intelligence:SYMBOL:TF` stream replacing flat k/v strings | `_publish_intelligence()` in `market_analysis_service.py` at line 351 is the exact method to replace; currently does `str(v)` for all values; replace with `event.model_dump_json()` XADD payload |
| BUS-03 | All downstream consumers (signal_generator, API, SSE route) deserialize `IntelligenceEvent` instead of raw field dicts — no bare dict access | `parse_intelligence_message()` in `signal_generator_service.py` (line 73) and `parseIntelligence()` in `dashboard/src/hooks/use-market-stream.ts` (line 54) are the two primary consumers to migrate |
| BUS-04 | `intelligence_processor_service.py` deprecated and removed; `market_analysis_service.py` is sole canonical pipeline | 3 test files reference the processor service; `wire-pipeline` SKILL.md references it in step 1; config/intelligence_processor.json exists |
</phase_requirements>

---

## Summary

Phase 1 is a schema migration and service deletion — no new infrastructure, no new services, no DB changes. The core work is: (1) create `src/intelligence/schemas.py` with typed Pydantic sub-models, (2) update `market_analysis_service.py` to publish validated `IntelligenceEvent` objects as JSON to the `intelligence:` Redis stream, (3) update `signal_generator_service.py` and the SSE route to deserialize via the model, and (4) delete `intelligence_processor_service.py` and its 3 test files.

The migration is straightforward because the intelligence stream format is already well-understood — the exact fields output by every plugin are catalogued in their `outputs: frozenset` declarations, and the dashboard's `parseIntelligence()` function in TypeScript already documents exactly which flat keys the SSE consumer expects. The key challenge is `extra="forbid"` on all sub-models: any plugin that outputs a field not declared in the corresponding sub-model will raise a `ValidationError` at the publisher. This is by design — it will surface mismatches during testing.

The SSE route (`src/api/routes/sse.py`) passes intelligence stream messages raw to the frontend — it does NOT parse them itself. The frontend's `parseIntelligence()` in TypeScript accesses the flat payload dict (`p["field_name"]`). After the migration, the `intelligence:` stream will contain a single JSON field (the serialized `IntelligenceEvent`) rather than dozens of flat string k/v fields. This is the most significant breaking change: the SSE route's snapshot and live-read code passes `fields` directly as `payload` to the frontend. The frontend `parseIntelligence()` function will need updating to parse the new nested structure.

**Primary recommendation:** Define all sub-models first (with exact field names from plugin `outputs` frozensets), validate them in tests against live plugin output, then migrate services one by one. The `extra="forbid"` constraint will self-test the schema coverage.

---

## Standard Stack

### Core

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| pydantic | 2.12.0+ | Schema definition, validation, serialization | Already in project; project-wide `BaseModel` usage established |
| redis[hiredis] | 7.1.0 | Redis stream XADD/XREAD | Already in project; services already use this for streams |
| structlog | 25.5.0 | Structured logging for validation errors | Already project-wide logging standard |

### Supporting

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `typing.Literal` | stdlib | Pin `schema_version` and `source` fields | Use for all fields with a fixed set of allowed string values |
| `datetime` | stdlib | Timestamp field on `IntelligenceEvent` | Already used in existing service code |
| `json` | stdlib | Serializing event to Redis stream value | Used in `model_dump_json()` calls |
| `unittest.mock` | stdlib | Patching services during migration tests | Already the project's mock framework |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| `extra="forbid"` on all sub-models | `extra="ignore"` | `ignore` silently drops unexpected plugin outputs — defeats purpose of typed schema |
| Separate `src/intelligence/schemas.py` | Inline in `market_analysis_service.py` | Inline makes consumer import of the schema awkward; `schemas.py` follows existing module pattern |
| `model_dump_json()` as stream value | Multiple stream fields (one per tier) | Multiple fields keeps Redis readable but doesn't give us typed validation; single JSON value is cleaner |

**Installation:** No new dependencies needed. Pydantic v2 is already installed.

---

## Architecture Patterns

### Target File Structure

```
src/
└── intelligence/
    ├── schemas.py      # NEW — IntelligenceEvent + all sub-models (BUS-01)
    ├── plugins.py      # unchanged
    └── register_plugins.py  # unchanged

services/
├── market_analysis_service.py     # updated publisher (BUS-02)
├── signal_generator_service.py    # updated consumer (BUS-03)
└── intelligence_processor_service.py  # DELETED (BUS-04)

src/api/routes/
└── sse.py              # updated SSE consumer (BUS-03)

dashboard/src/hooks/
└── use-market-stream.ts  # updated parseIntelligence (BUS-03)

tests/unit/service_tests/
├── test_market_analysis_service.py    # updated (BUS-02 tests)
├── test_signal_generator_service.py   # updated (BUS-03 tests)
├── test_intelligence_processor.py     # DELETED (BUS-04)
├── test_intelligence_processor_ohlcv.py  # DELETED (BUS-04)
└── test_intelligence_source_filter.py   # DELETED or repurposed (BUS-04)
```

### Pattern 1: Pydantic v2 sub-model with extra="forbid"

**What:** Each intelligence tier gets its own `BaseModel` with all expected plugin output fields as optional typed fields. `ConfigDict(extra="forbid")` makes unknown fields a `ValidationError` at the publisher.

**When to use:** At the publisher (`market_analysis_service.py`) when assembling `IntelligenceEvent` from plugin outputs. Each tier dict goes through its sub-model constructor.

**Example (from verified Pydantic v2 docs):**
```python
# Source: https://github.com/pydantic/pydantic/blob/main/docs/errors/validation_errors.md
from pydantic import BaseModel, ConfigDict

class I4Context(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # I4: VolatilityRegime plugin outputs
    vol_regime: float | None = None
    vol_percentile: float | None = None
    vol_expansion: float | None = None
    bb_width_pct: float | None = None
    bb_width_percentile: float | None = None
    # I4: TrendRegime plugin outputs
    trend_regime: float | None = None
    trend_confidence: float | None = None
    ma_alignment: float | None = None
    price_vs_sma20_pct: float | None = None
    # I4: MomentumContext plugin outputs
    momentum_bias: float | None = None
    momentum_strength: float | None = None
    momentum_agreement: float | None = None
    momentum_n_signals: float | None = None
    # I4: GARCHVolatility plugin outputs
    garch_sigma: float | None = None
    garch_vol_ratio: float | None = None
    garch_vol_regime: float | None = None
    garch_shock: float | None = None
    # I4: KalmanTrend plugin outputs
    kalman_trend: float | None = None
    kalman_slope: float | None = None
    kalman_price_position: float | None = None
    kalman_uncertainty: float | None = None
    kalman_upper: float | None = None
    kalman_lower: float | None = None
    kalman_gain: float | None = None
```

### Pattern 2: Publisher build from plugin output dicts

**What:** In `market_analysis_service.py`, after `_run_analysis_pipeline()` returns tiered result dicts, each dict is validated through its Pydantic sub-model, then assembled into `IntelligenceEvent`. Validation errors are logged and the event is still published (with the bad tier omitted or None).

**When to use:** In `_publish_intelligence()` in `market_analysis_service.py`.

**Example:**
```python
# In _publish_intelligence() — replacing the current flat str(v) approach
from src.intelligence.schemas import IntelligenceEvent, I3Structure, I4Context, ...

event = IntelligenceEvent(
    ts=timestamp,
    symbol=symbol,
    tf=timeframe,
    bar=OHLCVBar(o=bar_data["open"], h=bar_data["high"], ...),
    i1=I1Indicators(**{k: v for k, v in i1_features.items()}),
    i3=I3Structure(**i3_results),
    i4=I4Context(**i4_results),
    i5=I5Patterns(**i5_results),
    smc=SMCContext(**smc_results),
    i6=I6Confluence(**i6_results),
    source="live",
)
stream_name = sk_intelligence(self.env_prefix, symbol, timeframe)
# Single field "event" with JSON value — or expand as multiple fields
await self.redis_client.xadd(
    stream_name,
    {"event": event.model_dump_json()},
    maxlen=1000,
    approximate=True,
)
```

### Pattern 3: Consumer deserialization

**What:** Consumers (`signal_generator_service.py`, SSE route) parse the stream message's `"event"` field via `IntelligenceEvent.model_validate_json()` instead of doing bare dict access.

**Example:**
```python
# In signal_generator_service.py _process_single_message()
# Replaces parse_intelligence_message() which does bare dict access
from src.intelligence.schemas import IntelligenceEvent

raw_event_json = fields.get(b"event", b"").decode()
if not raw_event_json:
    return  # skip malformed
try:
    event = IntelligenceEvent.model_validate_json(raw_event_json)
except ValidationError as e:
    self.logger.warning("Invalid IntelligenceEvent", error=str(e))
    return

# Access is now typed, not bare dict
features = {
    "trend_regime": event.i4.trend_regime,
    "garch_sigma": event.i4.garch_sigma,
    "ctf_score": event.i6.ctf_score,
    ...
}
```

### Pattern 4: SSE route — pass event JSON to frontend

**What:** The SSE route (`src/api/routes/sse.py`) currently passes the raw Redis stream `fields` dict directly to the frontend as `payload`. After the migration, `fields` will contain a single `"event"` key with JSON. The route does NOT need to parse `IntelligenceEvent` — it just passes the JSON through. The frontend's `parseIntelligence()` in TypeScript will need to handle the new nested structure.

**When to use:** SSE route passes the raw JSON through; frontend parses the new nested schema.

**Example (SSE route — minimal change):**
```python
# In sse.py event_generator — intelligence stream messages already pass through as-is
# The route doesn't parse intelligence content — it just relays bytes
# Only change needed: the `payload` shape will change from flat dict to {"event": "...json..."}
# Frontend handles the new shape
```

**Example (frontend parseIntelligence — needs update):**
```typescript
// After migration: payload has one field "event" containing JSON string
function parseIntelligence(p: Record<string, string>): { ... } {
  // Parse the nested event JSON
  const event = JSON.parse(p.event || "{}");
  const i3 = event.i3 || {};
  const i4 = event.i4 || {};
  const structure: StructureData = {
    nearest_support: i3.nearest_support ?? undefined,
    ...
  };
  const context: ContextData = {
    // vol_regime is now a float (not already converted to string)
    volatility_regime: mapVolRegime(i4.vol_regime),
    ...
  };
  ...
}
```

### Anti-Patterns to Avoid

- **Dual-format publishing:** Never publish both the new nested JSON and the old flat fields in the same stream message. One format, one migration.
- **`extra="ignore"` on sub-models:** Silently drops plugin outputs that don't match the schema — defeats the purpose of validation at the publisher.
- **Catching `ValidationError` silently:** Log and record a metric, but do not swallow — these indicate a plugin contract violation.
- **Making sub-model fields required (non-optional):** Plugins may return `{}` if `min_lookback` not met. All sub-model fields must be `float | None = None` (or appropriate optional type).
- **Importing `IntelligenceEvent` inside services that don't need the type:** Only import where deserializing. The schema module is the single source of truth.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Field-level validation at publisher | Custom `if k in KNOWN_I4_FIELDS` guards | `ConfigDict(extra="forbid")` on Pydantic sub-model | Pydantic raises `ValidationError` with field name + type — manual guards miss nested type errors |
| JSON serialization of event | `json.dumps({k: str(v) for k, v in...})` | `event.model_dump_json()` | Handles datetime, None, float precision correctly; produces consistent output |
| Stream message parsing | Custom `fields[b"key"].decode()` access pattern | `IntelligenceEvent.model_validate_json()` | Type coercion, missing field defaults, schema version checking all handled |
| Schema version routing | Multiple `if version == "1.0"` blocks | `Literal["1.0"]` on `schema_version` field | Pydantic rejects unknown versions at parse time; add new literal values for future versions |

**Key insight:** The entire value of this phase is that Pydantic does the enforcement. Custom validation logic is worse in every way — it misses edge cases, doesn't self-document, and doesn't raise actionable errors.

---

## Common Pitfalls

### Pitfall 1: Plugin output types are not all `float`

**What goes wrong:** Some plugin outputs are strings (`"HH"`, `"bearish_fvg"`, `"uptrend"`), booleans (`True/False`), or integers (`0`, `1`, `-1`). Declaring them all as `float | None` will cause `ValidationError` when Pydantic tries to coerce `"HH"` to float.

**Why it happens:** The existing `parse_intelligence_message()` in `signal_generator_service.py` does `try: features[key] = float(val) except (ValueError, TypeError): features[key] = val` — it silently falls back to string. The new typed schema must handle this explicitly.

**How to avoid:** Check actual plugin `outputs` types. Concrete examples:
- `swing_pattern` (SwingDetectorPlugin): returns `"HH→HL"` — type must be `str | None`
- `bos_detected` (BOSCHoCHPlugin): returns `bool` — type must be `bool | None`
- `garch_vol_regime` (GARCHVolatilityPlugin): returns `int` (0/1/2) — type must be `int | None`
- `fvg_type` (FairValueGapPlugin): returns `int` (-1/0/1) — type must be `int | None`
- Most numeric outputs: `float | None`

**Warning signs:** `ValidationError: Input should be a valid number` during first test run with `extra="forbid"`.

### Pitfall 2: I1 features — 50+ fields from 23 plugins with parametric names

**What goes wrong:** I1 indicator plugins have outputs like `rsi_14`, `atr_14`, `macd_12_26_9`, `bb_20_2_upper` — the period is encoded in the field name. Several plugins generate dynamic output names (e.g., `RSIPlugin.outputs` calls `frozenset({f"rsi_{p}" for p in self.periods})`). `I1Indicators` sub-model must include all expected field names.

**Why it happens:** Default period = 14 for RSI, ATR, etc. The sub-model must enumerate these explicitly.

**How to avoid:** Run `register_all_plugins()` and collect all I1 plugin `outputs` sets programmatically to build the complete field list. Alternatively declare `I1Indicators` with a relaxed `extra="allow"` since I1 fields are already validated by `indicator_service.py` upstream.

**Recommendation (Claude's discretion):** For `I1Indicators`, use `model_config = ConfigDict(extra="allow")` rather than `extra="forbid"`. I1 fields are already validated by `indicator_service.py` and are not the target of this schema — the value is in strict validation of I3/I4/I5/SMC/I6 tiers where schema drift matters most.

### Pitfall 3: Redis stream message format change breaks SSE frontend

**What goes wrong:** The SSE route (`src/api/routes/sse.py`) passes the raw `fields` dict from XREAD directly as `payload` to the frontend. The current format is ~50 flat string k/v fields. After migration, the format becomes `{"event": "<json_string>"}`. The frontend `parseIntelligence()` accesses `payload["garch_sigma"]` directly — this will return `undefined` after migration.

**Why it happens:** The SSE route is transparent (does not parse intelligence content). The frontend owns the parsing logic in TypeScript. Both must be updated together in task 01-02.

**How to avoid:** In task 01-02, update `parseIntelligence()` in `use-market-stream.ts` to parse `p.event` as JSON first, then access nested fields (`event.i4.garch_sigma`). Update `dashboard/src/lib/types.ts` if field names change. Run `npx next build` to verify TypeScript type safety (as required by `wire-pipeline` skill, step 7).

**Warning signs:** Dashboard panels show all zeros or nulls after migration. `npx next build` type errors.

### Pitfall 4: `_run_analysis_pipeline()` returns a flat merged dict — tier separation is lost

**What goes wrong:** The current `_run_analysis_pipeline()` method in `market_analysis_service.py` merges all tier results into a single flat `intelligence` dict before returning. Building `IntelligenceEvent` from this merged dict loses the tier boundaries.

**Why it happens:** The current architecture was designed for flat Redis stream publishing. To build the tiered sub-models, the publisher needs the per-tier result dicts before they are merged.

**How to avoid:** Modify `_run_analysis_pipeline()` to return a structured result (e.g., a dataclass or named tuple with `i3`, `i4`, `i5`, `smc`, `i6` dicts) OR keep the existing flat return and add a post-processing step that routes fields to their correct sub-model by matching against each sub-model's declared field names. The latter is simpler to implement without breaking internal caching logic.

**Recommendation:** Return a `dict` with tier keys from `_run_analysis_pipeline()`:
```python
return {
    "i3": i3_results,
    "i4": i4_results,
    "i5": i5_results,
    "smc": smc_results,
    "i6": i6_results,
}
```
Then update `self.intelligence_cache` to store the same structure. This is a 1-line return change and a cache key update.

### Pitfall 5: `intelligence_processor_service.py` — 3 test files must be deleted, not just the service

**What goes wrong:** Deleting the service but leaving its test files causes no test failures (they become dead code), but they bloat the test suite and confuse future developers.

**Why it happens:** Easy to forget test cleanup.

**Test files to delete:**
- `tests/unit/service_tests/test_intelligence_processor.py` (28+ tests)
- `tests/unit/service_tests/test_intelligence_processor_ohlcv.py`
- `tests/unit/service_tests/test_intelligence_source_filter.py`

**Also update:**
- `config/intelligence_processor.json` — delete or mark archived
- `.claude/skills/wire-pipeline/SKILL.md` — step 1 references `intelligence_processor_service.py`; update to point to `market_analysis_service.py`
- `docs/for-ai-assistants/CLAUDE.md` — likely references the service

### Pitfall 6: `OHLCVBar` naming conflict

**What goes wrong:** `src/providers/base.py` already defines an `OHLCVBar` class. If `src/intelligence/schemas.py` defines a second `OHLCVBar`, imports become ambiguous.

**Why it happens:** The existing `OHLCVBar` in `base.py` has a `source: str` field that won't be appropriate for use inside `IntelligenceEvent` (which tracks source at the event level).

**How to avoid:** Option A: Import and reuse `from src.providers.base import OHLCVBar` in schemas.py (but it has a `source` field that doesn't fit). Option B: Define a new `BarSnapshot` or `IntelligenceBar` model in `schemas.py` with just `o/h/l/c/v` fields to avoid the naming collision. Option C: Reuse the existing `OHLCVBar` and exclude `source` via field alias or `model_config`. **Recommendation:** Define `class BarSnapshot(BaseModel)` in `schemas.py` with just `o`, `h`, `l`, `c`, `v` fields — minimal footprint, no naming collision.

---

## Code Examples

Verified patterns from official sources and codebase analysis:

### Complete IntelligenceEvent structure

```python
# src/intelligence/schemas.py (new file)
# Source: Pydantic v2 docs + codebase plugin outputs audit

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict


class BarSnapshot(BaseModel):
    """OHLCV snapshot that triggered this intelligence computation."""
    model_config = ConfigDict(extra="forbid")
    o: float
    h: float
    l: float
    c: float
    v: int


class I1Indicators(BaseModel):
    """I1 indicator outputs — 23 plugins, ~50+ fields."""
    # Allow extra: I1 fields are already validated by indicator_service upstream.
    # Strict forbid on I3–I6 where schema drift matters.
    model_config = ConfigDict(extra="allow")
    # Core fields (declared for IDE/type checker support)
    rsi_14: float | None = None
    atr_14: float | None = None
    macd_12_26_9: float | None = None
    # ... additional fields at Claude's discretion


class I3Structure(BaseModel):
    """I3 market structure outputs — swing, S/R, trend structure."""
    model_config = ConfigDict(extra="forbid")
    # SwingDetectorPlugin outputs
    swing_high: float | None = None
    swing_low: float | None = None
    swing_high_idx: float | None = None
    swing_low_idx: float | None = None
    swing_pattern: str | None = None       # "HH→HL" etc — string, not float
    swing_high_type: str | None = None
    swing_low_type: str | None = None
    swing_high_age_bars: float | None = None
    swing_low_age_bars: float | None = None
    # SupportResistancePlugin outputs
    nearest_resistance: float | None = None
    nearest_support: float | None = None
    resistance_strength: float | None = None
    support_strength: float | None = None
    resistance_dist_pct: float | None = None
    support_dist_pct: float | None = None
    sr_level_count: float | None = None
    resistance_age_bars: float | None = None
    support_age_bars: float | None = None
    # TrendStructurePlugin outputs
    trend_direction: float | None = None
    trend_strength: float | None = None
    trend_leg_count: float | None = None
    structure_integrity: float | None = None
    price_position: float | None = None
    trend_duration_bars: float | None = None


class I4Context(BaseModel):
    """I4 context classification outputs — regimes, GARCH, Kalman."""
    model_config = ConfigDict(extra="forbid")
    # VolatilityRegimePlugin
    vol_regime: float | None = None
    vol_percentile: float | None = None
    vol_expansion: float | None = None
    bb_width_pct: float | None = None
    bb_width_percentile: float | None = None
    # TrendRegimePlugin
    trend_regime: float | None = None
    trend_confidence: float | None = None
    ma_alignment: float | None = None
    price_vs_sma20_pct: float | None = None
    # MomentumContextPlugin
    momentum_bias: float | None = None
    momentum_strength: float | None = None
    momentum_agreement: float | None = None
    momentum_n_signals: float | None = None
    # GARCHVolatilityPlugin
    garch_sigma: float | None = None
    garch_vol_ratio: float | None = None
    garch_vol_regime: int | None = None   # int: 0/1/2 regime levels
    garch_shock: float | None = None
    # KalmanTrendPlugin
    kalman_trend: float | None = None
    kalman_slope: float | None = None
    kalman_price_position: float | None = None
    kalman_uncertainty: float | None = None
    kalman_upper: float | None = None
    kalman_lower: float | None = None
    kalman_gain: float | None = None


class I5Patterns(BaseModel):
    """I5 pattern detection outputs."""
    model_config = ConfigDict(extra="forbid")
    # RSIDivergencePlugin
    rsi_div_bullish: bool | None = None
    rsi_div_bearish: bool | None = None
    rsi_div_strength: float | None = None
    # BollingerSqueezePlugin outputs (verify field names)
    squeeze_active: float | None = None
    squeeze_duration: float | None = None
    # ConfluencePlugin
    confluence_score: float | None = None
    confluence_n_signals: float | None = None
    confluence_agreement: float | None = None
    meanrev_confluence_score: float | None = None
    meanrev_confluence_n_signals: float | None = None
    meanrev_confluence_agreement: float | None = None
    # VolumeDivergencePlugin
    vol_div_bullish: bool | None = None
    vol_div_bearish: bool | None = None
    vol_div_strength: float | None = None
    # TrendConfluencePlugin outputs (verify field names)
    # DoubleTopBottomPlugin outputs (verify field names)
    # HeadShouldersPlugin outputs (verify field names)
    # TriangleWedgePlugin outputs (verify field names)


class SMCContext(BaseModel):
    """Smart Money Concepts outputs."""
    model_config = ConfigDict(extra="forbid")
    # BOSCHoCHPlugin
    bos_detected: bool | None = None
    bos_direction: int | None = None
    bos_level: float | None = None
    choch_detected: bool | None = None
    choch_direction: int | None = None
    trend_direction: int | None = None   # NOTE: also in I3 — SMC has its own version
    # FairValueGapPlugin
    fvg_type: int | None = None           # -1/0/1
    fvg_top: float | None = None
    fvg_bottom: float | None = None
    fvg_midpoint: float | None = None
    fvg_size_pct: float | None = None
    fvg_open_count: int | None = None
    # OrderBlocksPlugin
    ob_type: int | None = None
    ob_top: float | None = None
    ob_bottom: float | None = None
    ob_strength: float | None = None
    ob_mitigated: bool | None = None
    ob_distance_pct: float | None = None
    # LiquiditySweepsPlugin
    sweep_detected: bool | None = None
    sweep_type: int | None = None
    sweep_level: float | None = None
    sweep_depth_pct: float | None = None
    sweep_reclaimed: bool | None = None
    # BOCPDChangepointPlugin (verify field names from smart_money/bocpd_changepoint.py)
    # HMMRegimePlugin (verify field names from smart_money/hmm_regime.py)
    # LiquidityPoolsPlugin (verify field names from smart_money/liquidity_pools.py)
    # SupplyDemandZonesPlugin (verify field names from smart_money/supply_demand_zones.py)


class I6Confluence(BaseModel):
    """I6 cross-timeframe confluence outputs."""
    model_config = ConfigDict(extra="forbid")
    ctf_score: float | None = None
    ctf_trend_alignment: float | None = None
    ctf_structure_alignment: float | None = None
    ctf_regime_agreement: float | None = None
    ctf_timeframes_aligned: float | None = None
    ctf_highest_aligned_tf: float | None = None


class IntelligenceEvent(BaseModel):
    """Canonical typed intelligence event published to intelligence:SYMBOL:TF stream."""
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0"] = "1.0"
    ts: datetime
    symbol: str
    tf: str
    platform: str = "futures"            # v2 multi-platform prep; always "futures" for now
    bar: BarSnapshot
    i1: I1Indicators
    i3: I3Structure
    i4: I4Context
    i5: I5Patterns
    smc: SMCContext
    i6: I6Confluence
    source: Literal["live", "backfill"] = "live"
```

### Publisher update in market_analysis_service.py

```python
# Modify _run_analysis_pipeline() return type
def _run_analysis_pipeline(self, symbol, timeframe, frames):
    # ... existing tier execution ...
    return {               # CHANGED: return tiered dict, not flat merged dict
        "i3": i3_results,
        "i4": i4_results,
        "i5": i5_results,
        "smc": smc_results,
        "i6": i6_results,
        "flat": {**i3_results, **i4_results, **i5_results, **smc_results, **i6_results},
    }

# In _publish_intelligence() — replace flat str(v) loop with typed event
async def _publish_intelligence(self, symbol, timeframe, tiered, timestamp, bar_data, i1_features):
    from src.intelligence.schemas import (
        IntelligenceEvent, BarSnapshot, I1Indicators,
        I3Structure, I4Context, I5Patterns, SMCContext, I6Confluence,
    )
    try:
        event = IntelligenceEvent(
            ts=timestamp,
            symbol=symbol,
            tf=timeframe,
            bar=BarSnapshot(
                o=bar_data.get("open", 0.0),
                h=bar_data.get("high", 0.0),
                l=bar_data.get("low", 0.0),
                c=bar_data.get("close", 0.0),
                v=int(bar_data.get("volume", 0)),
            ),
            i1=I1Indicators(**{k: v for k, v in i1_features.items() if v is not None}),
            i3=I3Structure(**tiered["i3"]),
            i4=I4Context(**tiered["i4"]),
            i5=I5Patterns(**tiered["i5"]),
            smc=SMCContext(**tiered["smc"]),
            i6=I6Confluence(**tiered["i6"]),
        )
    except ValidationError as e:
        self.logger.error("IntelligenceEvent validation failed", error=str(e),
                          symbol=symbol, tf=timeframe)
        self.error_count_total.inc()
        return  # drop malformed events — do NOT publish

    stream_name = sk_intelligence(self.env_prefix, symbol, timeframe)
    await self.redis_client.xadd(
        stream_name,
        {"event": event.model_dump_json()},
        maxlen=1000,
        approximate=True,
    )
```

### Consumer update in signal_generator_service.py

```python
# Replace parse_intelligence_message() with typed deserialization
from src.intelligence.schemas import IntelligenceEvent
from pydantic import ValidationError

def _parse_intelligence_event(fields: dict[bytes, bytes]) -> IntelligenceEvent | None:
    """Parse intelligence stream message into typed IntelligenceEvent."""
    raw = fields.get(b"event", b"")
    if not raw:
        return None
    try:
        return IntelligenceEvent.model_validate_json(raw)
    except (ValidationError, ValueError) as e:
        logger.warning("Failed to parse IntelligenceEvent", error=str(e))
        return None

# In _process_single_message(): replace parse_intelligence_message() call
event = _parse_intelligence_event(fields)
if event is None:
    await self.redis_client.xack(stream_name, self.consumer_group, message_id)
    return

# Access features via typed attributes — no bare dict access
features = {
    "trend_regime": event.i4.trend_regime or 0.0,
    "garch_sigma": event.i4.garch_sigma,
    "kalman_price_position": event.i4.kalman_price_position,
    "ctf_score": event.i6.ctf_score or 0.0,
    ...
}
bar = {"open": event.bar.o, "high": event.bar.h, "low": event.bar.l,
       "close": event.bar.c, "volume": event.bar.v}
timestamp = event.ts
```

---

## Inventory of Files to Change

This section is critical for the planner. Every file that must change is listed.

### Task 01-01: Schema definition + publisher update

**New file:**
- `src/intelligence/schemas.py` — define all sub-models + `IntelligenceEvent`

**Modified files:**
- `services/market_analysis_service.py`
  - `_run_analysis_pipeline()`: change return type to tiered dict
  - `_publish_intelligence()`: replace flat `str(v)` loop with `IntelligenceEvent` construction + `model_dump_json()`
  - `_calculate_intelligence()`: update to pass tiered results through
  - `_persist_intelligence()`: update to persist `IntelligenceEvent` JSON (optional: keep scalar-only for backward compat with old `intelligence` table until Phase 2)
  - Add import for `IntelligenceEvent` and sub-models

**New/updated test files:**
- `tests/unit/service_tests/test_market_analysis_service.py` — add tests for:
  - `IntelligenceEvent` is a valid Pydantic model with correct sub-models
  - Publisher produces valid JSON with `extra="forbid"` enforcement
  - Malformed plugin output raises `ValidationError` (not silently published)
  - `schema_version` field is `"1.0"`

### Task 01-02: Consumer migration

**Modified files:**
- `services/signal_generator_service.py`
  - Replace `parse_intelligence_message()` with typed `_parse_intelligence_event()`
  - Update `_process_single_message()` to use typed event
  - Update `build_ledger_entries()` to accept typed features dict (no structural change needed if features are converted to dict for I7 plugin frames)
  - Add import for `IntelligenceEvent`
- `src/api/routes/sse.py`
  - No parsing change needed (SSE passes raw fields through)
  - The stream format changes — `payload` becomes `{"event": "<json>"}` instead of flat fields
  - `parseIntelligence()` caller in `use-market-stream.ts` must be updated
- `dashboard/src/hooks/use-market-stream.ts`
  - Update `parseIntelligence()` to parse `p.event` as JSON then access nested fields
- `dashboard/src/lib/types.ts`
  - No structural changes needed (interfaces stay the same — just the parsing logic changes)

**Updated test files:**
- `tests/unit/service_tests/test_signal_generator_service.py` (if exists) or create it — add tests for typed event parsing

### Task 01-03: Delete intelligence_processor_service.py

**Files to delete:**
- `services/intelligence_processor_service.py`
- `tests/unit/service_tests/test_intelligence_processor.py`
- `tests/unit/service_tests/test_intelligence_processor_ohlcv.py`
- `tests/unit/service_tests/test_intelligence_source_filter.py`

**Files to update (reference cleanup):**
- `config/intelligence_processor.json` — delete or archive
- `.claude/skills/wire-pipeline/SKILL.md` — step 1 says "Add plugin name to the correct tier list in `services/intelligence_processor_service.py`" — update to `market_analysis_service.py`
- `docs/for-ai-assistants/CLAUDE.md` — search for any version line or service list mentioning `intelligence_processor_service`
- Any other docs referencing the service (run `grep -r "intelligence_processor_service" --include="*.md"`)

---

## SMC Plugins — Fields to Verify

Three SMC plugins require additional field lookup before writing `SMCContext`. The planner should include a verification step in task 01-01:

| Plugin | File | Status |
|--------|------|--------|
| `bocpd_changepoint.py` | `src/intelligence/smart_money/bocpd_changepoint.py` | Need to read `outputs` frozenset |
| `hmm_regime.py` | `src/intelligence/smart_money/hmm_regime.py` | Need to read `outputs` frozenset |
| `liquidity_pools.py` | `src/intelligence/smart_money/liquidity_pools.py` | Need to read `outputs` frozenset |
| `supply_demand_zones.py` | `src/intelligence/smart_money/supply_demand_zones.py` | Need to read `outputs` frozenset |

These were partially researched (frozenset confirmed at line 41, 32, 32, 89 in respective files) but the exact field names were not fully extracted. The implementer must read these files and add the field names to `SMCContext`.

Similarly, `I5Patterns` has 8 plugins — only `rsi_divergence`, `bollinger_squeeze`, `confluence`, and `volume_divergence` were confirmed. The remaining 4 (`double_top_bottom`, `head_shoulders`, `trend_confluence`, `triangle_wedge`) need their `outputs` frozensets read before writing the sub-model.

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Flat string k/v stream messages (`str(v)` for all values) | Single `"event"` field with typed JSON (IntelligenceEvent) | Phase 1 | Type safety at publisher; tiered structure for Phase 2 DB persistence |
| `parse_intelligence_message()` bare dict access | `IntelligenceEvent.model_validate_json()` | Phase 1 | ValidationError on malformed events; typed access in consumers |
| Dual pipeline (intelligence_processor + market_analysis) | Single canonical pipeline (market_analysis only) | Phase 1 | Eliminates code duplication and ambiguity about which service is authoritative |

**Deprecated/outdated:**
- `intelligence_processor_service.py`: Full service deletion in task 01-03
- `parse_intelligence_message()` function in `signal_generator_service.py`: Replaced by typed deserialization
- Flat string Redis stream format for `intelligence:` stream: Replaced by tiered JSON

---

## Open Questions

1. **`trend_direction` field name collision between I3Structure and SMCContext**
   - What we know: `struct_TrendStructure` outputs `trend_direction` (int) and `smc_BOSCHoCH` also outputs `trend_direction` (int). Both are in the flat merged dict currently, so the last writer wins.
   - What's unclear: Is this an intentional shared field, or is one of them misnamed?
   - Recommendation: In `SMCContext`, rename the SMC version to `smc_trend_direction` to avoid collision. Check if any I7 plugins consume `trend_direction` and which source they expect.

2. **I1Indicators: `extra="allow"` vs explicit field enumeration**
   - What we know: 23 I1 plugins produce ~50+ fields; field names include period suffixes (`rsi_14`); some plugins generate names dynamically.
   - What's unclear: Whether completeness of I1 declaration is worth the maintenance cost vs `extra="allow"` on that sub-model.
   - Recommendation (already in Claude's Discretion): Use `extra="allow"` for `I1Indicators` and only declare the most commonly accessed fields for IDE support.

3. **Dashboard `parseIntelligence()` — existing field name mappings**
   - What we know: The TypeScript `parseIntelligence()` function maps stream field names to TS interface fields (e.g., `p["trend_strength"]` → `swing_score`). Some mappings are non-obvious (line 69 in `use-market-stream.ts`).
   - What's unclear: Whether the new nested JSON format (`event.i3.trend_strength`) should maintain the same aliased mapping or normalize to the plugin's actual field name.
   - Recommendation: Maintain exact same mapping logic in `parseIntelligence()` — just change how the source dict is obtained (`event.i3` instead of `p` directly).

---

## Sources

### Primary (HIGH confidence)
- Codebase direct inspection — `services/market_analysis_service.py`, `services/signal_generator_service.py`, `src/api/routes/sse.py`, `dashboard/src/hooks/use-market-stream.ts`, `dashboard/src/lib/types.ts`
- Codebase direct inspection — all I3/I4/I5/SMC/I6 plugin `outputs: frozenset` declarations
- `/pydantic/pydantic` Context7 — `ConfigDict(extra="forbid")`, `Literal`, `model_dump_json()`, `model_validate_json()` patterns

### Secondary (MEDIUM confidence)
- Design doc: `docs/plans/2026-02-22-unified-intelligence-data-bus-design.md` — architecture decisions
- `.planning/codebase/ARCHITECTURE.md`, `STACK.md`, `TESTING.md`, `CONVENTIONS.md` — project patterns

### Tertiary (LOW confidence)
- SMC plugin outputs for `bocpd_changepoint`, `hmm_regime`, `liquidity_pools`, `supply_demand_zones` — confirmed frozenset exists at specific line numbers but exact field names not extracted. **Flag: implementer must read these files.**
- I5 pattern outputs for `double_top_bottom`, `head_shoulders`, `trend_confluence`, `triangle_wedge` — same status.

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — Pydantic v2 already in project; patterns verified in Context7 and existing codebase usage
- Architecture: HIGH — all service files read in full; exact change sites identified with line numbers
- Pitfalls: HIGH — derived from direct code inspection of current parsing logic and type mismatches
- SMC/I5 field names: LOW — frozensets confirmed but not fully extracted; planner should include a "read plugin outputs" step in task 01-01

**Research date:** 2026-02-22
**Valid until:** 2026-03-22 (30 days — Pydantic v2 stable, codebase not expected to change)
