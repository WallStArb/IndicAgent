"""Integration test: feature_vectors schema validation (Phase 142.5 Plan 00).

GREEN as of migration 206_add_renaissance_primitives.sql (Plan 06); updated
for migration 211 (2026-07-09), which dropped new_high_flag/new_low_flag as
redundant with dist_from_high/dist_from_low. Verifies the reconciled
Renaissance Primitives inventory (142.5-PLAN-OUTLINE.md):

    61 baseline FeatureVector columns + 89 Renaissance primitive columns
    == 150 total feature_vectors columns.

No missing columns, no silent count drift. This test enumerates every expected
column name explicitly rather than deriving it from src.intelligence.schemas.FeatureVector
so that it independently cross-checks the DB schema against the dataclass —
a divergence between the two is exactly the failure mode this test exists to catch.

IMPORTANT: This test validates the real database (indicagent), not indicagent_test —
same override idiom as tests/integration/test_pipeline_flow.py. indicagent_test has
no feature_vectors schema (nor, historically, the retiring feature-registry
dimension table) at all in this environment (pre-existing gap, confirmed unrelated
to this migration — see 142.5-06-SUMMARY.md Deviations), so this test bypasses
get_settings() (whose module-level Settings singleton would otherwise cache
conftest.py's indicagent_test DATABASE_URL) and connects directly to the real dev
database that migration 206 was applied against.

Run: pytest tests/integration/ -m integration
"""

from __future__ import annotations

import asyncpg
import pytest

pytestmark = pytest.mark.integration

# IMPORTANT: Override conftest.py's indicagent_test setting — this test must
# validate the real database that migration 206 is applied against, not the
# (unmigrated) indicagent_test DB. Bypasses get_settings() entirely since its
# Settings singleton may already be cached from conftest.py's env var by the
# time this module is collected.
_DB_URL = "postgresql://postgres:postgres@localhost:5432/indicagent"

# 61 baseline columns (src.intelligence.schemas.FeatureVector, Phase 137-141).
BASELINE_COLUMNS: frozenset[str] = frozenset(
    {
        # Momentum (7)
        "momentum_z_fast",
        "momentum_z_mid",
        "range_position",
        "bar_close_pos",
        "gap_z",
        "momentum_z_slow",
        "momentum_reversal_z",
        # Volume and order flow (8)
        "informed_flow",
        "volume_z",
        "ofi_z",
        "ofi_div",
        "cvd_slope_z",
        "cmf",
        "rel_volume",
        "vwap_dev_sigma",
        # Volatility (2)
        "atr_z",
        "vol_ratio",
        # Session-level (4)
        "poc_dist_atr",
        "va_position",
        "sr_support_dist",
        "sr_resist_dist",
        # Regime-level (10)
        "hmm_regime_prob",
        "hmm_entropy",
        "hmm_duration",
        "hurst",
        "shannon",
        "garch_ratio",
        "hma_slope_z",
        "adx",
        "aroon_fast",
        "aroon_slow",
        # Oscillators (6)
        "rsi_fast",
        "rsi_mid",
        "rsi_slow",
        "cci_fast",
        "cci_mid",
        "cci_slow",
        # Cross-asset (3)
        "vix_z",
        "flight_quality",
        "yield_slope_z",
        # Calendar (11)
        "in_ny_session",
        "in_london_kz",
        "in_overlap",
        "power_hour",
        "opening_range",
        "above_wk_vwap",
        "dow_sin",
        "dow_cos",
        "month_position",
        "quarter_position",
        "days_to_month_end",
        # Cross-timeframe (3)
        "ctf_momentum",
        "ctf_vwap_align",
        "ctf_regime_align",
        # Statistical / liquidity (4)
        "amihud_illiq_z",
        "high_52w_dist",
        "ret_skew_z",
        "ret_acf1_z",
        # Cross-sectional (3, nullable)
        "momentum_rank_z",
        "volume_rank_z",
        "volatility_rank_z",
    }
)

# 91 new Renaissance primitive columns (Plans 01, 02, 03, 04, 05, 05.5).
RENAISSANCE_COLUMNS: frozenset[str] = frozenset(
    {
        # Bar Anatomy (8) — Plan 01
        "body_ratio",
        "upper_wick_ratio",
        "lower_wick_ratio",
        "range_vs_atr",
        "close_vs_open_direction",
        "overnight_gap",
        "overnight_gap_z",
        "range_efficiency",
        # Lagged Returns (6) — Plan 01
        "ret_lag_1",
        "ret_lag_2",
        "ret_lag_3",
        "ret_lag_fast",
        "ret_lag_mid",
        "ret_lag_slow",
        # Open-to-Close Split (4) — Plan 01
        "open_ret",
        "intraday_ret",
        "open_vs_intraday",
        "session_time_pos",
        # Temporal Coordinates: new pairs + month_sin/cos (10) — Plan 02
        "hour_of_day_sin",
        "hour_of_day_cos",
        "week_of_month_sin",
        "week_of_month_cos",
        "day_of_month_sin",
        "day_of_month_cos",
        "week_of_year_sin",
        "week_of_year_cos",
        "month_sin",
        "month_cos",
        # Volume Structure (12) — Plan 02
        "vol_acceleration",
        "dollar_vol_z",
        "vol_range_ratio",
        "vol_trend_ratio",
        "up_vol_ratio_fast",
        "up_vol_ratio_slow",
        "vol_percentile",
        "vol_persistence",
        "vol_std_z",
        "mfi_fast",
        "mfi_slow",
        "obv_z",
        # Return Distribution (7) — Plan 03
        "ret_kurtosis_z_fast",
        "ret_kurtosis_z_slow",
        "ret_autocorr_1",
        "ret_autocorr_5",
        "updown_ratio_fast",
        "updown_ratio_slow",
        "streak_z",
        # Realized Variance (14) — Plan 03
        "realized_var_ratio_fast",
        "realized_var_ratio_slow",
        "range_to_close",
        "true_range_pct",
        "vol_of_vol",
        "high_low_corr",
        "variance_ratio_fast",
        "variance_ratio_slow",
        "vol_asymmetry_z",
        "bb_pct_b_fast",
        "bb_pct_b_slow",
        "hv_z_fast",
        "hv_z_slow",
        "hv_ratio",
        # Alternative Volatility (3) — Plan 04
        "parkinson_vol_z",
        "garman_klass_vol_z",
        "yang_zhang_vol_z",
        # Volatility Dynamics (5) — Plan 04
        "parkinson_vol_velocity",
        "garman_klass_vol_velocity",
        "yang_zhang_vol_velocity",
        "vol_velocity_z",
        "intraday_noise_ratio",
        # Breakout Distance (12) — Plan 05
        "dist_from_high_fast",
        "dist_from_high_slow",
        "dist_from_low_fast",
        "dist_from_low_slow",
        "range_pct_fast",
        "range_pct_slow",
        "stoch_k_fast",
        "stoch_k_slow",
        "price_percentile_fast",
        "price_percentile_slow",
        "efficiency_ratio_fast",
        "efficiency_ratio_slow",
        # Price-Volume Interactions (8) — Plan 05.5
        "vol_body_product",
        "ret_vol_product_fast",
        "price_vol_corr_fast",
        "price_vol_corr_slow",
        "range_vol_product",
        "up_vol_body_diff",
        "ret_vol_ratio_fast",
        "vol_skew_product",
    }
)

assert len(BASELINE_COLUMNS) == 61, f"Expected 61 baseline columns, got {len(BASELINE_COLUMNS)}"
assert (
    len(RENAISSANCE_COLUMNS) == 89
), f"Expected 89 Renaissance columns, got {len(RENAISSANCE_COLUMNS)}"
assert not (BASELINE_COLUMNS & RENAISSANCE_COLUMNS), "Baseline/Renaissance column name collision"

EXPECTED_COLUMNS: frozenset[str] = BASELINE_COLUMNS | RENAISSANCE_COLUMNS
assert len(EXPECTED_COLUMNS) == 150, f"Expected 150 total columns, got {len(EXPECTED_COLUMNS)}"


@pytest.mark.asyncio
async def test_renaissance_columns_exist() -> None:
    """feature_vectors must have all 150 expected columns (61 baseline + 89 Renaissance).

    GREEN as of migration 211_drop_redundant_breakout_flags.sql. Queries
    information_schema.columns directly rather than trusting ORM/dataclass state
    — silent wrong answers (a column silently missing) are worse than a loud
    assertion failure here.
    """
    conn = await asyncpg.connect(_DB_URL)
    try:
        rows = await conn.fetch(
            "SELECT column_name FROM information_schema.columns " "WHERE table_name = $1",
            "feature_vectors",
        )
    finally:
        await conn.close()

    actual_columns = {row["column_name"] for row in rows}
    missing = EXPECTED_COLUMNS - actual_columns
    assert not missing, (
        f"feature_vectors missing {len(missing)} expected column(s): {sorted(missing)}. "
        "Run migration 206_add_renaissance_primitives.sql (Phase 142.5 Plan 06)."
    )

    # Structural/key columns (symbol, tf, bar_ts, pipeline_version, regime,
    # regime_label_source, feature_factory_version) are additional to the 150
    # feature columns — only assert the feature-column subset totals 150, not
    # the raw information_schema row count for the whole table.
    feature_columns_present = actual_columns & EXPECTED_COLUMNS
    assert len(feature_columns_present) == 150, (
        f"Expected exactly 150 feature_vectors feature columns, found "
        f"{len(feature_columns_present)}. Missing: {sorted(EXPECTED_COLUMNS - actual_columns)}"
    )


@pytest.mark.asyncio
async def test_concept_registry_feature_row_count_matches_gate() -> None:
    """concept_registry's domain='feature' row count must match
    len(dataclasses.fields(FeatureVector)) (the startup alignment gate's derivation),
    so it grows whenever a field is added - not asserted against a fixed number here,
    since hardcoding one just guarantees this test goes stale again at the next field
    addition (confirmed 2026-07-14: the count had drifted from an earlier 150 to that
    day's 155 with no corresponding test update).

    Phase 170 Plan 07: repointed from the retiring registry service module's
    own _REGISTRY_ROW_COUNT constant (that module is deleted in Plan 08) to a
    locally-derived field count -- same anti-drift derivation, without importing
    a module this test would otherwise outlive.

    Row count excludes migration 284's 2 gate-less tombstone concept_registry rows
    (new_high_flag/new_low_flag, kept only to preserve orphaned
    feature_transition_log history) via an INNER JOIN concept_gate -- matching
    services/ic_engine.py's _watermark_concept_registry and ConceptRegistryService's
    own _LOAD_CONCEPTS_SYNC_SQL semantics exactly. Without that join this query
    returns 251, never matching FeatureVector's 249 fields, and this test would
    permanently fail.

    Without this alignment holding, ConceptRegistryService.load_sync() raises at
    daemon startup (antigravity H2/H3, ported from the retiring registry
    service's original gate).
    """
    import dataclasses

    from src.intelligence.schemas import FeatureVector

    expected_count = len(dataclasses.fields(FeatureVector))

    conn = await asyncpg.connect(_DB_URL)
    try:
        count = await conn.fetchval(
            "SELECT COUNT(*) FROM concept_registry cr "
            "JOIN concept_gate cg ON cg.concept_id = cr.concept_id "
            "WHERE cr.domain = 'feature'"
        )
    finally:
        await conn.close()

    assert count == expected_count, (
        f"concept_registry(domain='feature') has {count} rows; expected "
        f"{expected_count} (len(dataclasses.fields(FeatureVector))). See migration 284."
    )
