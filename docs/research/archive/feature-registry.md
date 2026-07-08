# Feature Registry — DB-Backed Feature Governance

**Status**: Implemented — `feature_registry` table (61 rows, all `active`), `src/intelligence/feature_registry_service.py`, consumed by `ic_engine.py` and `ensemble_trainer.py`. Design preserved below for reference. Slated to migrate into Concept Registry (`domain='feature'`) per [concept-governance-registries.md](concept-governance-registries.md) once that ships.
**Created**: 2026-06-27
**Refreshed**: 2026-07-01
**Type**: Renaissance-grade SOC microservice  
**Analogous to**: `shadow_registry` (plugins), `config_state` (parameters)

## Concept

The feature registry is **not documentation**. It is a **system component**:

- **Join surface** for `feature_ic_scores`
- **Promotion gate** for ensemble trainer
- **On/off switch** for IC engine
- **Lifecycle governance** for feature evolution

**Problem**: Current feature catalog is implicit — 61 fields on `FeatureVector`, no metadata, no lifecycle, no tier classification. Adding features beyond 61 without a registry creates the same drift problem the plugin catalog already has.

**Solution**: DB-backed registry with `feature_registry` table + `FeatureRegistryService` + lifecycle governance.

---

## Schema Design

### feature_registry (metadata registry)

```sql
CREATE TABLE feature_registry (
    feature_name      text PRIMARY KEY,     -- exact match to FeatureVector field name
    group_name        text NOT NULL         -- feature category
        CHECK (group_name IN (
            'momentum', 'volume', 'volatility', 'structure',
            'session', 'oscillator', 'calendar', 'cross_tf',
            'macro', 'regime'
        )),
    tier              text NOT NULL         -- feature complexity
        CHECK (tier IN ('0_atomic', '1_interaction', '2_theory')),
    formula_short     text NOT NULL,        -- one-line description
    normalization     text NOT NULL,        -- score characteristics
        CHECK (normalization IN ('bounded_signed', 'bounded_unsigned', 'z_scored', 'unbounded_ratio')),
    linear_ready      boolean NOT NULL,     -- usable in linear models without preprocessing?
    source_dims       text[],              -- INFORMATIONAL: which OHLCV dimensions used
    requires_htf      boolean NOT NULL DEFAULT false,
    window_apr_keys   text[],              -- APR keys for window parameters
    parent_features   text[],              -- tier-1 only: parent feature names
    status            text NOT NULL DEFAULT 'candidate'
        CHECK (status IN ('candidate', 'active', 'shadow_only', 'deprecated')),
    
    -- IC promotion gates (analogous to shadow_registry EV[R])
    min_ic_sharpe     float,               -- NULL = use APR global floor
    min_ic_n          integer NOT NULL DEFAULT 100,
    fdr_required      boolean NOT NULL DEFAULT true,
    fdr_alpha         float NOT NULL DEFAULT 0.05,
    
    -- IC snapshot (last known state)
    last_ic_value     float,
    last_ic_sharpe    float,
    last_ic_n         integer,
    last_eval_at      timestamptz,
    
    -- Metadata
    added_phase       text,
    notes             text,
    added_at          timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX feature_registry_tier_idx ON feature_registry (tier);
CREATE INDEX feature_registry_status_idx ON feature_registry (status);
CREATE INDEX feature_registry_group_idx ON feature_registry (group_name);
```

### feature_transition_log (audit trail)

```sql
CREATE TABLE feature_transition_log (
    id               bigserial PRIMARY KEY,
    feature_name     text NOT NULL,
    from_status      text NOT NULL,
    to_status        text NOT NULL,
    triggered_at     timestamptz NOT NULL DEFAULT now(),
    trigger_reason   text NOT NULL,        -- 'ic_promotion' | 'ic_demotion' | 'parent_cascade' | 'operator_override'
    ic_value         float,
    ic_sharpe        float,
    ic_n             integer
);
```

### feature_ic_scores (status tracking)

```sql
ALTER TABLE feature_ic_scores
    ADD COLUMN feature_status_at_eval text NOT NULL DEFAULT 'unknown';
```

IC engine records feature's status at evaluation time. Ensemble trainer filters `WHERE feature_status_at_eval = 'active'`.

---

## Tier Taxonomy

| tier | meaning | examples | lifecycle |
|---|---|---|---|
| **0_atomic** | Single OHLCV dimension, fixed window. Irreducible inputs. | `body_ratio`, `ret_lag_1`, `volume_z` | IC → ensemble |
| **1_interaction** | Deterministic combination of two tier-0 features. No theory. | `vol_body_product`, `price_vol_corr_fast` | IC → ensemble |
| **2_theory** | Encodes market structure, regime, or cross-asset model. | `poc_dist_atr`, `hmm_regime_prob`, `ctf_momentum` | IC → primitive-only |

**`tier` is the sole classification column.** Display labels (`atomic_primitive`, etc.) are derived in application layer — never stored.

### Tier-1 Parent Cascade

When a tier-0 feature is deprecated, auto-deprecate its tier-1 children:

```sql
CREATE OR REPLACE FUNCTION fn_cascade_parent_deprecation()
RETURNS TRIGGER AS $$
BEGIN
    IF NEW.status = 'deprecated' AND OLD.status != 'deprecated' THEN
        UPDATE feature_registry
        SET status = 'deprecated'
        WHERE tier = '1_interaction'
          AND status != 'deprecated'
          AND NEW.feature_name = ANY(parent_features);
        
        INSERT INTO feature_transition_log (feature_name, from_status, to_status, trigger_reason)
        SELECT feature_name, 'active', 'deprecated', 'parent_cascade'
        FROM feature_registry
        WHERE tier = '1_interaction'
          AND NEW.feature_name = ANY(parent_features);
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_cascade_parent_deprecation
AFTER UPDATE OF status ON feature_registry
FOR EACH ROW EXECUTE FUNCTION fn_cascade_parent_deprecation();
```

**Enforcement**: DB trigger at write time, not startup check.

---

## Lifecycle States

**Forward note (2026-07-04, cluster review F10):** the diagram and table below describe today's
*live, running* schema and behavior — accurate as production fact, not as target design.
ROADMAP Phase 143 (LIFECYCLE-01, adopted 2026-07-03 from `docs/research/intel-14-integrity-monitor.md`)
will amend this state machine: auto-`ic_demotion` redirects to `shadow_only` instead of
`deprecated` (`deprecated` becomes operator-only), a new evidence-based `shadow_only → active`
transition is added, and the "cooldown + IC re-pass" recovery path shown below is replaced by
pure evidence (2 consecutive passing corpus runs + a new-observations floor) — no calendar
cooldown. Read this section as "what runs today," not as the destination.

```
candidate ──[IC gate pass]──► active ──[IC fail N periods]──► deprecated
                                  ▲                               │
                                  └───[cooldown + IC re-pass]──┘

active ──[manual]──► shadow_only
active ──[manual]──► deprecated
```

### Transitions

| Transition | Trigger | Record |
|-----------|---------|--------|
| candidate → active | IC Sharpe > gate, passes FDR, n >= min_ic_n | `ic_promotion` |
| active → deprecated | IC below gate for N consecutive periods (APR-backed) | `ic_demotion` |
| active → shadow_only | Operator override (manual flag) | `operator_override` |
| active → deprecated | Operator decision (feature broken, redundant) | `operator_override` |
| deprecated → * | Never (one-way street) | — |

**All transitions** write to `feature_transition_log` (immutable, append-only).

---

## FeatureRegistryService

Analogous to `ConfigService`. Singleton. Loaded at daemon startup before alignment gate.

```python
class FeatureRegistryService:
    """DB-backed feature governance service (async singleton)"""
    
    async def load(self, pool: asyncpg.Pool) -> None:
        """Load all features into memory at startup"""
        
    def get_active_features(self, tier: str | None = None) -> list[dict]:
        """Get active features, optionally filtered by tier"""
        
    def get_feature(self, feature_name: str) -> dict | None:
        """Get single feature metadata"""
        
    def get_ic_sharpe_gate(self, feature_name: str) -> float:
        """Get per-feature IC Sharpe override, or APR global floor"""
        
    async def record_transition(
        self, feature_name: str, from_status: str, to_status: str,
        reason: str, ic_value: float | None = None, 
        ic_sharpe: float | None = None, ic_n: int | None = None
    ) -> None:
        """Record lifecycle transition (fire-and-forget async write)"""
```

**All registry reads** go through service — no direct `feature_registry` queries in application code.

---

## Startup Alignment Gate

Crash-loud gate in IC engine and ensemble trainer startup. Registry must match `FeatureVector` dataclass fields exactly.

```python
# In ic_engine.py and ensemble_trainer.py startup
registry_names = {r['feature_name'] for r in await registry.get_active_features()}
dataclass_names = {f.name for f in dataclasses.fields(FeatureVector)}

if registry_names != dataclass_names:
    raise RuntimeError(
        f"feature_registry drift detected: {registry_names ^ dataclass_names}. "
        "Run migration to sync registry with FeatureVector."
    )
```

**Enforcement**: Adding a feature requires three atomic changes in one migration:
1. Add field to `FeatureVector` dataclass
2. Schema migration for new column
3. INSERT row to `feature_registry`

Gate enforces all three land together.

---

## Compute Parity Invariant

**Batch and live must produce identical feature values.**

Single `compute_features(bar, cache) -> FeatureVector` function called by both:
- Live feature factory (real-time)
- Batch backfill (historical corpus)

If batch and live diverge, IC scores measure something different from what live ensemble receives → **silent wrong answer**.

### Status Switch Affects Both Paths

| status | live pipeline | batch / IC engine | ensemble |
|---|---|---|---|
| `candidate` | computed | computed + measured | ignored |
| `active` | computed | computed + measured | weighted |
| `shadow_only` | computed | computed + measured | ignored |
| `deprecated` | **excluded** | **excluded** | excluded |

**`deprecated` is the only status that suppresses computation.** All others compute the feature — difference is only whether ensemble weights it.

---

## Runtime Integration

### IC Engine

Runs on all `status != 'deprecated'`` features regardless of tier.

**Primitive-only IC pass**:
```sql
WHERE tier IN ('0_atomic', '1_interaction') AND status != 'deprecated'
```

**Theory-embedded pass**:
```sql
WHERE tier = '2_theory' AND status != 'deprecated'
```

**Separate cohorts** — not mixed. Records `feature_status_at_eval` on every IC score row.

### Ensemble Trainer

Filters by active status:
```sql
SELECT ... FROM feature_ic_scores
WHERE status = 'active' AND feature_status_at_eval = 'active'
```

The `feature_status_at_eval` filter ensures training data excludes IC scores from periods when feature was not yet active.

### Tier-1 Parent Check

`FeatureRegistryService.load()` verifies all `parent_features` of active/shadow tier-1 features are non-deprecated.

**Crash-loud** if violation — a tier-1 feature cannot be computed without its parents. DB trigger enforces at write time; startup check is belt-and-suspenders.

---

## Seed Data (Current 61 Features)

Migration seeds all 61 current `FeatureVector` fields with `status = 'active'`.

**Theory-embedded features** (tier='2_theory'):
- `poc_dist_atr`, `va_position`
- `sr_support_dist`, `sr_resist_dist`
- `hmm_regime_prob`, `hmm_entropy`, `hmm_duration`
- `garch_ratio`
- `ctf_momentum`, `ctf_vwap_align`, `ctf_regime_align`
- `flight_quality`

**All others**: tier='0_atomic' → reclassify to '1_interaction' later as data migration.

### Complete Field Mapping (61 Features)

| feature_name | group_name | tier | notes |
|---|---|---|---|
| momentum_z_fast | momentum | 0_atomic | |
| momentum_z_mid | momentum | 0_atomic | |
| momentum_z_slow | momentum | 0_atomic | |
| momentum_reversal_z | momentum | 0_atomic | 1-bar return z-score |
| ret_acf1_z | momentum | 0_atomic | autocorrelation = momentum persistence |
| momentum_rank_z | momentum | 0_atomic | nullable; cross-sectional |
| range_position | structure | 0_atomic | intra-bar anatomy |
| bar_close_pos | structure | 0_atomic | intra-bar anatomy |
| gap_z | structure | 0_atomic | |
| high_52w_dist | structure | 0_atomic | distance from 52w high |
| informed_flow | volume | 0_atomic | |
| volume_z | volume | 0_atomic | |
| ofi_z | volume | 0_atomic | |
| ofi_div | volume | 0_atomic | |
| cvd_slope_z | volume | 0_atomic | |
| cmf | volume | 0_atomic | |
| rel_volume | volume | 0_atomic | |
| vwap_dev_sigma | volume | 0_atomic | |
| amihud_illiq_z | volume | 0_atomic | liquidity measure |
| volume_rank_z | volume | 0_atomic | nullable; cross-sectional |
| atr_z | volatility | 0_atomic | |
| vol_ratio | volatility | 0_atomic | short/long vol ratio |
| ret_skew_z | volatility | 0_atomic | return distribution shape |
| volatility_rank_z | volatility | 0_atomic | nullable; cross-sectional |
| poc_dist_atr | session | 2_theory | volume profile theory |
| va_position | session | 2_theory | volume profile theory |
| sr_support_dist | session | 2_theory | S/R zone theory |
| sr_resist_dist | session | 2_theory | S/R zone theory |
| rsi_fast | oscillator | 0_atomic | |
| rsi_mid | oscillator | 0_atomic | |
| rsi_slow | oscillator | 0_atomic | |
| cci_fast | oscillator | 0_atomic | |
| cci_mid | oscillator | 0_atomic | |
| cci_slow | oscillator | 0_atomic | |
| hmm_regime_prob | regime | 2_theory | HMM model output |
| hmm_entropy | regime | 2_theory | HMM model output |
| hmm_duration | regime | 2_theory | HMM model output |
| hurst | regime | 0_atomic | raw Hurst exponent |
| shannon | regime | 0_atomic | raw Shannon entropy |
| garch_ratio | regime | 2_theory | GARCH model output |
| hma_slope_z | regime | 0_atomic | |
| adx | regime | 0_atomic | |
| aroon_fast | regime | 0_atomic | |
| aroon_slow | regime | 0_atomic | |
| vix_z | macro | 0_atomic | z-score of external series |
| flight_quality | macro | 2_theory | composite cross-asset measure |
| yield_slope_z | macro | 0_atomic | z-score of external spread |
| in_ny_session | calendar | 0_atomic | |
| in_london_kz | calendar | 0_atomic | |
| in_overlap | calendar | 0_atomic | |
| power_hour | calendar | 0_atomic | |
| opening_range | calendar | 0_atomic | |
| above_wk_vwap | calendar | 0_atomic | |
| dow_sin | calendar | 0_atomic | |
| dow_cos | calendar | 0_atomic | |
| month_position | calendar | 0_atomic | |
| quarter_position | calendar | 0_atomic | |
| days_to_month_end | calendar | 0_atomic | |
| ctf_momentum | cross_tf | 2_theory | HTF alignment model |
| ctf_vwap_align | cross_tf | 2_theory | HTF alignment model |
| ctf_regime_align | cross_tf | 2_theory | HTF alignment model |

**Group distribution**: momentum 6 · structure 4 · volume 10 · volatility 4 · session 4 · oscillator 6 · regime 10 · macro 3 · calendar 11 · cross_tf 3 = **61 features**

---

## APR Keys

Required before migration:

```
alpha.feature_registry.min_ic_sharpe_default  -- global IC Sharpe floor; calibrate from Phase 138/139 IC distribution
alpha.feature_registry.fdr_alpha              -- Benjamini-Hochberg alpha; default 0.05
alpha.feature_registry.demotion_periods       -- consecutive eval periods below gate before auto-demotion; default 3
```

---

## Cross-Sectional Regime Outputs as Tier-2 Features

The regime signal registry (`src/intelligence/regime_signals/REGISTRY`) and the feature registry are complementary, not competing:

- **Regime signal modules** — cataloged in-code `REGISTRY` dict. No IC promotion lifecycle needed; you don't deprecate `breadth_vol` because its IC dropped, you retune the whole module. In-code dispatch is the right level.
- **Regime signal outputs** — cataloged HERE as `tier='2_theory'`, `group_name='regime'` entries.

The pattern already exists: `hmm_regime_prob`, `hmm_entropy`, `hmm_duration` are per-symbol HMM outputs, already seeded as tier-2_theory regime features. Cross-sectional regime outputs follow the same pattern.

### Candidate cross-sectional regime features (future, post regime-group redesign)

| feature_name | group_name | tier | notes |
|---|---|---|---|
| `equity_regime_bull_prob` | regime | 2_theory | P(bull) from equity breadth_vol signal |
| `equity_regime_bear_prob` | regime | 2_theory | P(bear) from equity breadth_vol signal |
| `rates_regime_steep_prob` | regime | 2_theory | P(steep_tight) from curve_credit signal |
| `rates_regime_inverted_prob` | regime | 2_theory | P(inverted) from curve_credit signal |
| `commodity_energy_regime_prob` | regime | 2_theory | P(backwardation) from commodity_momentum_ts |
| `fx_regime_strong_dollar_prob` | regime | 2_theory | P(strong_dollar) from fx_dollar_carry signal |

**Why this matters:** adding regime state as soft probability features lets the IC engine score whether current regime membership is itself predictive, and lets the ensemble learn regime-conditional weights naturally through feature weights — without hard regime stratification buckets. This is a softer, more data-driven alternative to the 9-label hard conditioning system.

**Dependency:** these features require the cross-sectional regime model (Phase 141) to ship first. Add as `status='candidate'` in that migration; promote via IC gate.

---

## Open Questions

1. **Should tier-1 interaction features be implemented?** Currently none in 61 features. Interaction Factory (todo 010) depends on this registry — coordinate.
2. **IC Sharpe floor calibration**: What should `alpha.feature_registry.min_ic_sharpe_default` be? Calibrate from Phase 138/139 IC distribution.
3. **FDR for theory features**: Should tier='2_theory' features have different FDR requirements? Currently all use `fdr_alpha`.
4. **Manual promotion**: Should operators be able to manually promote `candidate → active` without IC evidence? Currently no — only demotion is manual.

---

## Revision History

| Date | Change | Reason |
|------|--------|--------|
| 2026-06-27 | Initial idea doc extracted from completed 008 todo | Baseline design |
| 2026-06-27 | Add cross-sectional regime outputs as tier-2 feature candidates | Regime signal modules catalog in-code; outputs catalog here |

---

## See Also

- **`docs/research/archive/feature-vector-lifecycle.md`** — original (archived) promotion/demotion design; its `candidate → active → decaying → deprecated` sketch used a `decaying` status this registry never actually had (decay lives in the demotion mechanism, not an enum value) — superseded by the evidence-based recovery policy in `docs/research/concept-governance-registries.md` and ROADMAP Phase 143's LIFECYCLE-01 (see forward note above)
- **`docs/research/renaissance-primitives-ohlcv.md`** — 200+ candidate primitives catalog (add as `status='candidate'`, promote via IC)
- **`docs/research/interaction-factory.md`** — depends on this registry (tier-1 parent metadata)
- **`008-feature-registry.md`** — historical completed TODO (superseded by this living idea doc)

---

**Next Steps**:

1. **Review design** — Is tier taxonomy correct? Is lifecycle governance complete?
2. **Answer open questions** — IC Sharpe floor, manual promotion policy, FDR settings
3. **Design migration** — Create `172_feature_registry.sql` with schema + seed data + APR keys
4. **Implement service** — Build `FeatureRegistryService` in `src/intelligence/feature_registry_service.py`
5. **Integrate** — Wire up IC engine + ensemble trainer with registry reads + alignment gates
6. **Validate** — Gate passes: registry matches FeatureVector, service loads features, ensemble filters correctly
