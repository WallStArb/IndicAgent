# Feature Registry — DB-Backed Feature Governance

## Context

Analogous to `shadow_registry` for plugins. The current feature catalog is implicit —
61 fields on `FeatureVector`, no metadata, no lifecycle, no on/off switch, no tier
classification. Adding features beyond 61 without a registry creates the same drift
problem the plugin catalog already has (stale docs, no runtime governance).

The feature registry is not documentation. It is a system component: the join surface
for `feature_ic_scores`, the promotion gate for the ensemble trainer, and the on/off
switch for the IC engine.

---

## Schema

```sql
CREATE TABLE feature_registry (
    feature_name      text PRIMARY KEY,     -- exact match to FeatureVector field name
    group_name        text NOT NULL         -- see CHECK below
        CHECK (group_name IN (
            'momentum', 'volume', 'volatility', 'structure',
            'session', 'oscillator', 'calendar', 'cross_tf',
            'macro', 'regime'
        )),
    tier              text NOT NULL         -- 0_atomic | 1_interaction | 2_theory
        CHECK (tier IN ('0_atomic', '1_interaction', '2_theory')),
    formula_short     text NOT NULL,        -- one-line description
    normalization     text NOT NULL,        -- bounded_signed | bounded_unsigned | z_scored | unbounded_ratio
    linear_ready      boolean NOT NULL,     -- usable in linear models without preprocessing?
    source_dims       text[],              -- INFORMATIONAL ONLY, NOT ENFORCED — which of O/H/L/C/V the feature uses
    requires_htf      boolean NOT NULL DEFAULT false,
    window_apr_keys   text[],              -- APR keys controlling window lengths (nullable = no window)
    parent_features   text[],              -- tier-1 only: the two atomics being combined
    status            text NOT NULL DEFAULT 'candidate'
        CHECK (status IN ('candidate', 'active', 'shadow_only', 'deprecated')),
    -- IC promotion gates (analogous to shadow_registry EV[R] gates)
    -- min_ic_sharpe: per-feature override. global floor is APR alpha.feature_registry.min_ic_sharpe_default
    -- seed value ~0.5 — calibrate from Phase 138/139 IC distribution before setting final default
    min_ic_sharpe     float,               -- NULL means: use APR global floor
    min_ic_n          integer NOT NULL DEFAULT 100,
    fdr_required      boolean NOT NULL DEFAULT true,
    fdr_alpha         float NOT NULL DEFAULT 0.05, -- Benjamini-Hochberg threshold; APR key: alpha.feature_registry.fdr_alpha
    -- last IC eval snapshot
    last_ic_value     float,
    last_ic_sharpe    float,
    last_ic_n         integer,
    last_eval_at      timestamptz,
    added_phase       text,
    notes             text,
    added_at          timestamptz NOT NULL DEFAULT now()
);

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

-- Tier-1 parent cascade: when a tier-0 feature is deprecated, auto-deprecate its
-- tier-1 children. Enforced at write time via trigger — not a startup check or nightly job.
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

CREATE INDEX feature_registry_tier_idx ON feature_registry (tier);
CREATE INDEX feature_registry_status_idx ON feature_registry (status);
CREATE INDEX feature_registry_group_idx ON feature_registry (group_name);
```

### feature_ic_scores — add column

```sql
ALTER TABLE feature_ic_scores
    ADD COLUMN feature_status_at_eval text NOT NULL DEFAULT 'unknown';
```

The IC engine records the feature's status at eval time. The ensemble trainer filters
`WHERE feature_status_at_eval = 'active'` — ensuring it does not train on IC scores
from periods when the feature was in `shadow_only` or `candidate`.

### APR keys required before migration

```
alpha.feature_registry.min_ic_sharpe_default  -- global IC Sharpe floor; calibrate from Phase 138/139 IC distribution
alpha.feature_registry.fdr_alpha              -- Benjamini-Hochberg alpha; default 0.05
alpha.feature_registry.demotion_periods       -- consecutive eval periods below gate before auto-demotion; default 3
```

---

## Tier Taxonomy

| tier | meaning | examples |
|---|---|---|
| `0_atomic` | Single OHLCV dimension, fixed window. Irreducible inputs. | `body_ratio`, `ret_lag_1`, `volume_z` |
| `1_interaction` | Deterministic combination of two tier-0 features. No theory. | `vol_body_product`, `price_vol_corr_fast` (planned — none in current 61) |
| `2_theory` | Encodes market structure, regime, or cross-asset model. | `poc_dist_atr`, `hmm_regime_prob`, `ctf_momentum` |

`tier` is the sole column for classification. Display labels (`atomic_primitive`, etc.) are derived
in the application layer from a static lookup — they are not stored. Storing a 1:1 derived label
in the DB creates a drift surface with no enforcement mechanism.

**Tier-1 parent validation:** `parent_features` must reference two tier-0 features.
When a parent is deprecated, the child auto-demotes via the `trg_cascade_parent_deprecation` trigger.

---

## Lifecycle

```
candidate → active       IC Sharpe > gate (per-feature min_ic_sharpe, else APR floor),
                         passes FDR at fdr_alpha, n >= min_ic_n
active    → deprecated   IC Sharpe below gate for alpha.feature_registry.demotion_periods
                         consecutive eval periods (N is APR-backed, not baked in)
active    → shadow_only  Operator override (manual flag, no IC evidence required)
```

All transitions written to `feature_transition_log` (immutable, append-only).
Tier-1 child demotion on parent deprecation is written by the DB trigger, not application code.
Mirrors `shadow_transition_log` semantics exactly.

---

## Startup Alignment Gate

Crash-loud gate in IC engine and ensemble trainer startup. Registry must match
`FeatureVector` dataclass fields exactly — misalignment is a hard `RuntimeError`,
not a warning.

```python
registry_names = {r['feature_name'] for r in ...}
dataclass_names = {f.name for f in dataclasses.fields(FeatureVector)}
if registry_names != dataclass_names:
    raise RuntimeError(
        f"feature_registry drift detected: {registry_names ^ dataclass_names}. "
        "Run migration to sync registry with FeatureVector."
    )
```

Adding a feature = FeatureVector field + schema migration + registry INSERT.
All three must land in the same migration. The gate enforces this.

---

## FeatureRegistryService

Analogous to `ConfigService`. Singleton. Loaded at daemon startup before the alignment gate runs.

```python
class FeatureRegistryService:
    async def load(self, pool: asyncpg.Pool) -> None: ...
    def get_active_features(self, tier: str | None = None) -> list[dict]: ...
    def get_feature(self, feature_name: str) -> dict | None: ...
    def get_ic_sharpe_gate(self, feature_name: str) -> float:
        # per-feature override if set, else APR global floor
        ...
    async def record_transition(
        self, feature_name: str, from_status: str, to_status: str,
        reason: str, ic_value: float | None, ic_sharpe: float | None, ic_n: int | None
    ) -> None: ...
```

Both the IC engine and ensemble trainer depend on this interface. Neither queries
`feature_registry` directly — all reads go through `FeatureRegistryService`.

---

## Compute Parity Invariant

Batch and live must produce identical feature values for the same bar. A single
`compute_features(bar, cache) -> FeatureVector` function is called by both the live
feature factory and the batch backfill — no separate implementations. This is
non-negotiable: if batch and live diverge, IC scores measure something different from
what the live ensemble receives. Silent wrong answer.

The registry's status switch affects both paths atomically:

| status | live pipeline | batch / IC engine | ensemble |
|---|---|---|---|
| `candidate` | computed | computed + measured | ignored |
| `active` | computed | computed + measured | weighted |
| `shadow_only` | computed | computed + measured | ignored |
| `deprecated` | excluded | excluded | excluded |

`deprecated` is the only status that suppresses computation. All other statuses compute
the feature — the difference is only whether the ensemble weights it.

---

## Runtime Integration

**IC engine:** runs on all non-deprecated features regardless of status — IC data must
be gathered before promotion decisions are made. Primitive-only IC pass:
`WHERE tier IN ('0_atomic', '1_interaction') AND status != 'deprecated'`. Theory-embedded
pass: `WHERE tier = '2_theory' AND status != 'deprecated'`. Separate cohorts — not mixed.
Records `feature_status_at_eval` on every IC score row.

**Ensemble trainer:** `WHERE status = 'active' AND feature_status_at_eval = 'active'`
before reading `feature_ic_scores`. The `feature_status_at_eval` filter ensures training
data excludes IC scores from periods when the feature was not yet active.

**Tier-1 parent check:** `FeatureRegistryService.load()` verifies all `parent_features`
of active/shadow tier-1 features are non-deprecated. Crash-loud if not — a tier-1 feature
cannot be computed without its parents. The DB trigger ensures this condition holds at
write time; the startup check is a belt-and-suspenders guard.

---

## Seed — Current 61 Features

Migration seeds all 61 current `FeatureVector` fields with `status = 'active'`.
Theory-embedded features (`poc_dist_atr`, `va_position`, `sr_support_dist`,
`sr_resist_dist`, `hmm_*`, `ctf_*`, `flight_quality`) seed as `tier = '2_theory'`.
All others seed as `tier = '0_atomic'` — reclassification to `1_interaction` follows
as a data migration once parent relationships are mapped.

### Complete field mapping (61 fields)

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

**Group counts:** momentum 6 · structure 4 · volume 10 · volatility 4 · session 4 ·
oscillator 6 · regime 10 · macro 3 · calendar 11 · cross_tf 3 = **61**

---

## Relationship to Other Todos

- `001-ic-engine-correctness-p0.md` — primitive-only IC pass requires `tier` filter; registry is the prerequisite
- `docs/research/renaissance-primitives-ohlcv.md` — new primitives add as `status = 'candidate'`; promoted to `active` only after IC validation
- `006-asset-class-regime-model.md` — regime features (`hmm_*`) classified `2_theory`; asset-class regime replacement would add new tier-0 features

## Trigger

Implement before expanding beyond current 61 features. The primitives expansion
(renaissance-primitives-ohlcv.md) should add features as `candidate` rows and
promote via IC evidence — not directly to `active`.

---

## Flow Activity Primitives (First-Order Expansion)

**Context**: Renaissance-grade approach to detecting flow synchronization/crowding. See `docs/research/renaissance-primitives-ohlcv.md` for full catalog. **Key insight**: Don't pre-judge what "crowding" means — provide raw primitives, let IC engine + ensemble discover patterns.

### Design Philosophy (vs. Theory-Heavy Approach)

| Dimension | Theory-Heavy (Rejected) | Renaissance-Grade (Adopted) |
|-----------|------------------------|-------------------------|
| **What to measure** | Composite "crowding index" with weighted formula | Raw 1st/2nd-order primitives (volume_change, trade_count_change) |
| **How to aggregate** | Cross-sectional correlation matrices across 58 ETFs | Per-symbol only — ensemble discovers cross-symbol patterns |
| **Where to detect** | Pre-built regime filter at feature level | IC stratification + ensemble weight discovery |
| **Human theory** | "When synchronized, momentum crashes" | None — let data speak |

**Renaissance principle**: Throw thousands of simple primitives at the ensemble. If volume synchronization predicts momentum decay, the model will learn:
```
WHEN volume_z_5 > 1.0 for >70% of ETFs → momentum_z_fast IC drops by 40%
```

No human theory required.

### New Primitives to Add (10 Flow Activity Features)

All are **tier='0_atomic'** (first/second-order transforms, no cross-section theory):

| feature_name | group_name | formula_short | normalization | linear_ready | window_apr_keys | notes |
|---|---|---|---|---|---|---|
| `volume_change` | volume | `volume_t - volume_{t-1}` | unbounded_ratio | FALSE | [] | 1st-order raw change |
| `volume_pct_change` | volume | `(volume_t - volume_{t-1}) / volume_{t-1}` | unbounded_ratio | FALSE | [] | Rate of change (scale-free) |
| `volume_acceleration` | volume | `volume_change_t - volume_change_{t-1}` | unbounded_ratio | FALSE | [] | 2nd-order change-of-change |
| `volume_z_5` | volume | `z-score(volume, window=5)` | z_scored | TRUE | ['feature.volume.z_5_window'] | Short-window volume z-score |
| `trade_count_change` | volume | `trade_count_t - trade_count_{t-1}` | unbounded_ratio | FALSE | [] | Activity raw change |
| `trade_count_acceleration` | volume | `trade_count_change_t - trade_count_change_{t-1}` | unbounded_ratio | FALSE | [] | Activity acceleration |
| `range_pct_change` | volatility | `((H_t-L_t) - (H_{t-1}-L_{t-1})) / (H_{t-1}-L_{t-1})` | unbounded_ratio | FALSE | [] | Vol expansion rate |
| `body_ratio_change` | structure | `body_ratio_t - body_ratio_{t-1}` | bounded_signed | TRUE | [] | Conviction acceleration |
| `ret_lag_1` | momentum | `log(close_t / close_{t-1})` | unbounded_ratio | FALSE | [] | Foundation 1-bar return (duplicate: exists) |
| `trade_count_z_5` | volume | `z-score(trade_count, window=5)` | z_scored | TRUE | ['feature.trade_count.z_5_window'] | Short-window activity z-score |

**Total**: 10 new primitives. All tier='0_atomic', status='candidate' on seed.

### Seed Migration Update

When adding these 10 features:

```sql
-- Insert new flow activity primitives
INSERT INTO feature_registry (feature_name, group_name, tier, formula_short, normalization, linear_ready, source_dims, requires_htf, window_apr_keys, parent_features, status, min_ic_n, fdr_required, fdr_alpha, notes) VALUES
    ('volume_change', 'volume', '0_atomic', 'volume_t - volume_{t-1}', 'unbounded_ratio', FALSE, ARRAY['volume'], FALSE, NULL, NULL, 'candidate', 100, TRUE, 0.05, '1st-order raw change'),
    ('volume_pct_change', 'volume', '0_atomic', '(volume_t - volume_{t-1}) / volume_{t-1}', 'unbounded_ratio', FALSE, ARRAY['volume'], FALSE, NULL, NULL, 'candidate', 100, TRUE, 0.05, 'Rate of change (scale-free)'),
    -- ... (8 more rows)
ON CONFLICT (feature_name) DO NOTHING;
```

### Validation Strategy

1. **Seed as `status='candidate'`** — not active, no ensemble weight
2. **Run IC engine** — compute IC for all candidates
3. **Promote to `status='active'`** ONLY if:
   - `ic_sharpe >= min_ic_sharpe` (per-feature or APR floor)
   - `n >= min_ic_n` (default 100)
   - Passes FDR at `fdr_alpha` (default 0.05)
4. **No human theory about "crowding"** — if flow synchronization matters, IC will show it

### Registry Integration Points

**FeatureRegistryService additions** (if needed beyond base implementation):

```python
def get_candidates_by_group(self, group: str) -> list[dict]:
    """Get all candidate features in a group (for batch IC testing)"""
    ...

def promote_features(self, feature_names: list[str], ic_results: dict) -> None:
    """Bulk promote candidates to active based on IC evidence"""
    ...
```

**IC engine integration**:
- IC engine already runs on all `status != 'deprecated'` features
- Candidates are included in IC runs (status='candidate' != 'deprecated')
- Write `feature_status_at_eval='candidate'` on IC score rows
- Ensemble trainer excludes `candidate` rows automatically

### Expected Discovery Patterns

If flow synchronization/crowding is real, the ensemble will discover patterns like:

- **Volume synchronization**: `WHEN volume_z_5 > 1.0 for >70% of ETFs, momentum_z_fast IC drops 40%`
- **Activity bursts**: `WHEN trade_count_change > 0 for SPY+QQQ+IWM, next-bar returns negative`
- **Volatility expansion**: `WHEN range_pct_change > 0.5 across market, regime shifting`

**No pre-judgment** — the registry is the neutral repository. IC engine + ensemble determine signal.

### Relationship to Theory-Heavy Approach

**Alternative considered** (see `docs/research/comomentum-crowding-metric.md`):
- Cross-sectional correlation metrics (volume_sync_z, return_abnormal_resid)
- Composite crowding_index with weighted formula
- Pre-built regime filter ("crowded" vs "uncrowded")

**Why rejected**:
- Encodes human theory about what "crowding" means
- Requires cross-sectional data (all 58 ETFs) to compute per-symbol value
- P6-P8 priority (problem-specific), not foundational
- Renaissance doesn't pre-judge composites — throws primitives at ensemble

**Current approach** (this doc):
- True primitives (1st/2nd-order, per-symbol only)
- P2-P3 priority (foundational, like bar anatomy)
- Let IC engine discover cross-symbol patterns
- Ensemble trainer learns the composites automatically

### See Also

- `docs/research/renaissance-primitives-ohlcv.md` — full catalog (200+ candidates organized by computation order)
- `docs/research/comomentum-crowding-metric.md` — theory-heavy approach we chose NOT to use
- `docs/research/feature-vector-lifecycle.md` — promotion/demotion (candidate → active → decaying → deprecated)

**Key distinction**: Feature registry = metadata repository (what exists, what tier). Feature lifecycle = IC-driven promotion (what works). Flow activity primitives = raw inputs (how we detect crowding without theory).
