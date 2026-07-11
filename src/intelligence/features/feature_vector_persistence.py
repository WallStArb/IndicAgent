"""Canonical persistence contract for the feature_vectors hypertable.

Single source of truth for:
  - INSERT SQL (column count derived from FeatureVector, not hardcoded: 1
    content-key + 8 structural + the rest feature floats)
  - Content-key derivation: SHA-256(symbol|tf|bar_ts_ns|pipeline_version|feature_factory_version)[:32] as UUID
  - Row serializer: FeatureVector fields -> INSERT tuple, one element per column

Both the live write path (FeatureVectorWriter, asyncpg) and the batch compute
path (backfill_feature_factory, psycopg2) import from here. One schema
definition, two consumers — schema drift is structurally impossible.

2026-07-08: extended from 70 to 161 columns. Phase 142.5 added 91 primitive
fields to FeatureVector and the DB schema (migration 206) with compute logic
fully wired, but this file was never updated to persist them -- the values
were computed correctly, then silently discarded before reaching the
database. 91/152 feature columns were 100% NULL across the entire corpus,
indistinguishable from "no signal" in every downstream IC measurement.
tests/unit/test_feature_vector_persistence_completeness.py guards this
invariant going forward: every dataclasses.fields(FeatureVector) entry must
appear as an INSERT column, checked structurally rather than by a hardcoded
count that itself needs remembering to update.

2026-07-09: dropped to 159 columns (migration 211). new_high_flag/new_low_flag
were removed from FeatureVector, proven redundant with dist_from_high/
dist_from_low (same rolling window, same comparison, new_high_flag was
exactly 1{dist_from_high <= eps}), violating the Feature Factory's own
zero-redundancy design contract. The column count derives automatically from
_RENAISSANCE_PRIMITIVE_FIELD_NAMES; no other hardcoded count needed updating.

2026-07-11: extended to 164 columns (migration 223, Phase 143.1 Plan 02, todo
068). 5 canary/control predictor fields added to FeatureVector -- same
derive-by-name discipline as _RENAISSANCE_PRIMITIVE_FIELD_NAMES applied via a
new _CANARY_FIELD_NAMES slice, appended immediately after it, so this file
cannot silently go stale the way it did in the 2026-07-08 incident above.

Ring 1: imports FeatureVector from src.intelligence.schemas.
Do not import from Ring 2 (services/) or Ring 3 (api/, production/).
"""

from __future__ import annotations

import dataclasses
import hashlib
import math
import uuid
from datetime import datetime, timedelta

from src.core.service_utils import TF_SECONDS as _TF_SECONDS
from src.intelligence.schemas import FeatureVector

# ── Schema constraint ─────────────────────────────────────────────────────────

# feature_vectors.regime_label_source is CHECK-constrained to these values.
# 'filtered' = causal forward-filter HMM (the only valid source for IC training).
# 'unknown'  = regime computation failed or not yet run.
# 'viterbi_batch' is explicitly excluded — it introduces look-ahead bias.
VALID_REGIME_LABEL_SOURCES: frozenset[str] = frozenset({"filtered", "unknown"})

# The Renaissance primitive fields (91 added in migration 206, Phase 142.5;
# 89 as of 2026-07-09 after removing the redundant new_high_flag/new_low_flag)
# are a contiguous, same-order slice of dataclasses.fields(FeatureVector) --
# from body_ratio through vol_skew_product. Deriving the name list here (once,
# at import time) instead of hand-typing each `vector.<name>` line is what
# makes the original bug class (fields silently missing from the INSERT tuple
# because this list was never updated) structurally impossible: the params
# tuple can no longer drift out of sync with the dataclass by hand-edit error.
_ALL_FEATURE_VECTOR_FIELD_NAMES: tuple[str, ...] = tuple(
    f.name for f in dataclasses.fields(FeatureVector)
)
_RENAISSANCE_PRIMITIVE_FIELD_NAMES: tuple[str, ...] = _ALL_FEATURE_VECTOR_FIELD_NAMES[
    _ALL_FEATURE_VECTOR_FIELD_NAMES.index("body_ratio") : _ALL_FEATURE_VECTOR_FIELD_NAMES.index(
        "vol_skew_product"
    )
    + 1
]

# The 5 canary/control predictor fields (Phase 143.1 Plan 02, todo 068; migration
# 223) are a second contiguous, same-order slice immediately following the
# Renaissance primitives and immediately preceding the 3 nullable cross-sectional
# fields -- same derive-don't-hand-type discipline as _RENAISSANCE_PRIMITIVE_FIELD_NAMES,
# for the exact same reason (module docstring): a hand-typed list is how 91/152
# fields went silently unpersisted for an entire corpus rebuild.
_CANARY_FIELD_NAMES: tuple[str, ...] = _ALL_FEATURE_VECTOR_FIELD_NAMES[
    _ALL_FEATURE_VECTOR_FIELD_NAMES.index(
        "canary_noise_gaussian"
    ) : _ALL_FEATURE_VECTOR_FIELD_NAMES.index("canary_acausal_placebo")
    + 1
]


def _compute_bar_close_ts(bar_ts: datetime, tf: str) -> datetime:
    """Compute bar close timestamp from bar open timestamp and timeframe.

    For intraday TFs: bar_ts + TF duration.
    For '1d': bar_ts + 1 calendar day (midnight UTC = daily bar close).
    Raises ValueError for unrecognized TF strings.
    """
    if tf not in _TF_SECONDS:
        raise ValueError(f"Unknown tf for bar_close_ts: {tf!r}. Known: {sorted(_TF_SECONDS)}")
    if tf == "1d":
        return bar_ts.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
    return bar_ts + timedelta(seconds=_TF_SECONDS[tf])


# ── NaN/Inf guard ─────────────────────────────────────────────────────────────


def validate_feature_vector(vector: FeatureVector) -> list[str]:
    """Return list of non-finite field names (empty = clean). Caller decides action.

    Iterates all dataclass fields and checks for nan/inf. The `v is not None` guard
    handles Optional[float] fields that will be None for cross-sectional cols.
    """
    bad = []
    for field in dataclasses.fields(vector):
        v = getattr(vector, field.name)
        if v is not None and not math.isfinite(v):
            bad.append(field.name)
    return bad


# ── Canonical INSERT SQL ──────────────────────────────────────────────────────

# 164 columns (as of 2026-07-11): $1 content-key, $2-$8 structural, $9-$62
# original feature floats, $63-$70 migration-159 additions, $71-$159
# migration-206 Renaissance primitives (2026-07-08 fix, then reduced from 91
# to 89 primitives 2026-07-09), $160-$164 migration-223 canary/control
# predictors (see module docstring).
# Column order is binding — matches migration 159/206/223 column definition order.
# ON CONFLICT DO NOTHING: idempotent replay; duplicate bars are skipped silently.
FEATURE_VECTOR_INSERT_SQL = f"""
INSERT INTO feature_vectors (
    feature_vector_id,
    symbol, tf, bar_ts, pipeline_version, feature_factory_version,
    regime, regime_label_source,
    momentum_z_fast, momentum_z_mid, range_position, bar_close_pos,
    gap_z, informed_flow, volume_z, ofi_z, ofi_div, cvd_slope_z, cmf,
    rel_volume, vwap_dev_sigma, atr_z, vol_ratio,
    poc_dist_atr, va_position, sr_support_dist, sr_resist_dist,
    hmm_regime_prob, hmm_entropy, hmm_duration, hurst, shannon, garch_ratio,
    hma_slope_z, adx, aroon_fast, aroon_slow,
    rsi_fast, rsi_mid, rsi_slow, cci_fast, cci_mid, cci_slow,
    vix_z, flight_quality, yield_slope_z,
    in_ny_session, in_london_kz, in_overlap, power_hour, opening_range,
    above_wk_vwap, dow_sin, dow_cos, month_position,
    ctf_momentum, ctf_vwap_align, ctf_regime_align,
    amihud_illiq_z, high_52w_dist, ret_skew_z, ret_acf1_z,
    bar_close_ts,
    momentum_z_slow, momentum_reversal_z, quarter_position, days_to_month_end,
    momentum_rank_z, volume_rank_z, volatility_rank_z,
    {", ".join(_RENAISSANCE_PRIMITIVE_FIELD_NAMES)},
    {", ".join(_CANARY_FIELD_NAMES)}
)
VALUES (
    $1,
    $2, $3, $4, $5, $6,
    $7, $8,
    $9, $10, $11, $12,
    $13, $14, $15, $16, $17, $18, $19,
    $20, $21, $22, $23,
    $24, $25, $26, $27,
    $28, $29, $30, $31, $32, $33,
    $34, $35, $36, $37,
    $38, $39, $40, $41, $42, $43,
    $44, $45, $46,
    $47, $48, $49, $50, $51,
    $52, $53, $54, $55,
    $56, $57, $58,
    $59, $60, $61, $62,
    $63,
    $64, $65, $66, $67,
    $68, $69, $70,
    {", ".join(f"${i}" for i in range(71, 71 + len(_RENAISSANCE_PRIMITIVE_FIELD_NAMES)))},
    {
    ", ".join(
        f"${i}"
        for i in range(
            71 + len(_RENAISSANCE_PRIMITIVE_FIELD_NAMES),
            71 + len(_RENAISSANCE_PRIMITIVE_FIELD_NAMES) + len(_CANARY_FIELD_NAMES),
        )
    )
}
)
ON CONFLICT (symbol, tf, bar_ts) DO NOTHING
"""

# psycopg2 callers use %s placeholders; asyncpg uses $N. Both forms encode the
# same column contract. Callers choose the right constant for their driver.
# Total column count is derived, not hardcoded, so it can't drift out of sync
# with _RENAISSANCE_PRIMITIVE_FIELD_NAMES the way a fixed number could.
# Descending replacement order prevents $1 matching inside $10, $11, etc.
_TOTAL_COLUMNS = 70 + len(_RENAISSANCE_PRIMITIVE_FIELD_NAMES) + len(_CANARY_FIELD_NAMES)
_pg2 = FEATURE_VECTOR_INSERT_SQL
for i in range(_TOTAL_COLUMNS, 0, -1):
    _pg2 = _pg2.replace(f"${i}", "%s")
FEATURE_VECTOR_INSERT_SQL_PSYCOPG2 = _pg2
del _pg2


# ── Content-key derivation ────────────────────────────────────────────────────


def make_feature_vector_id(
    symbol: str,
    tf: str,
    bar_ts: datetime,
    pipeline_version: str,
    feature_factory_version: str,
) -> uuid.UUID:
    """Derive the content-key UUID for a feature_vectors row.

    SHA-256(symbol|tf|bar_ts_ns|pipeline_version|feature_factory_version)[:32] as UUID.
    Deterministic and idempotent: same inputs always produce the same UUID.
    bar_ts_ns = nanosecond epoch integer to avoid sub-second precision loss.
    feature_factory_version isolates IC estimates across algorithm changes.
    """
    bar_ts_ns = str(int(bar_ts.timestamp() * 1_000_000_000))
    digest = hashlib.sha256(
        f"{symbol}|{tf}|{bar_ts_ns}|{pipeline_version}|{feature_factory_version}".encode()
    ).hexdigest()[:32]
    return uuid.UUID(digest)


# ── Row serializer ────────────────────────────────────────────────────────────


def feature_vector_to_insert_params(
    symbol: str,
    tf: str,
    bar_ts: datetime,
    pipeline_version: str,
    feature_factory_version: str,
    regime: str | None,
    regime_label_source: str,
    vector: FeatureVector,
) -> tuple:
    """Serialize a FeatureVector to the canonical 164-element INSERT tuple.

    Column order matches FEATURE_VECTOR_INSERT_SQL exactly:
      $1:        feature_vector_id (content-key UUID)
      $2-$8:     structural (symbol, tf, bar_ts, pipeline_version,
                 feature_factory_version, regime, regime_label_source)
      $9-$62:    54 feature floats in FeatureVector field order
      $63:       bar_close_ts (computed from bar_ts + TF duration)
      $64-$67:   4 new computed features (momentum_z_slow, momentum_reversal_z,
                 quarter_position, days_to_month_end)
      $68-$70:   3 cross-sectional Optional features (None until Phase 139)
      $71-$159:  89 Renaissance primitives (migration 206, Phase 142.5; 91
                 originally, 2 removed 2026-07-09 as redundant) in
                 dataclasses.fields(FeatureVector) order — wired 2026-07-08,
                 see module docstring for the gap this closes
      $160-$164: 5 canary/control predictors (migration 223, Phase 143.1
                 Plan 02, todo 068) in dataclasses.fields(FeatureVector) order

    Args:
        symbol: Instrument symbol (e.g. 'SPY').
        tf: Timeframe string (e.g. '5m', '1h', '1d').
        bar_ts: UTC bar open timestamp.
        pipeline_version: Semver string stamped by the FeatureFactory run.
        feature_factory_version: Algorithm version from FEATURE_FACTORY_VERSION constant.
            Included in content-key; rows from different versions sort independently.
        regime: HMM regime label or None if not yet assigned.
        regime_label_source: Must be in VALID_REGIME_LABEL_SOURCES.
            Callers are responsible for passing a valid value — this function
            raises ValueError on violation rather than silently inserting a
            schema-invalid row.
        vector: Fully-populated FeatureVector from FeatureFactory.compute().

    Returns:
        164-element tuple for use with asyncpg executemany() or psycopg2
        execute_batch(). Compatible with both drivers — asyncpg and psycopg2
        handle uuid.UUID and datetime natively.

    Raises:
        ValueError: If regime_label_source is not in VALID_REGIME_LABEL_SOURCES.
        ValueError: If vector contains nan/inf in any field.
        ValueError: If tf is not in _TF_SECONDS (unknown timeframe).
    """
    if regime_label_source not in VALID_REGIME_LABEL_SOURCES:
        raise ValueError(
            f"regime_label_source={regime_label_source!r} not in"
            f" {VALID_REGIME_LABEL_SOURCES}. Only forward-filter HMM labels"
            f" are permitted in feature_vectors (look-ahead bias prevention)."
        )

    bad = validate_feature_vector(vector)
    if bad:
        raise ValueError(
            f"Degenerate features (nan/inf): {bad}." f" symbol={symbol} tf={tf} bar_ts={bar_ts}"
        )

    feature_vector_id = make_feature_vector_id(
        symbol, tf, bar_ts, pipeline_version, feature_factory_version
    )
    bar_close_ts = _compute_bar_close_ts(bar_ts, tf)

    return (
        feature_vector_id,  # $1  content-key UUID
        symbol,  # $2
        tf,  # $3
        bar_ts,  # $4
        pipeline_version,  # $5
        feature_factory_version,  # $6
        regime,  # $7  nullable
        regime_label_source,  # $8
        # Momentum (5 original)
        vector.momentum_z_fast,  # $9
        vector.momentum_z_mid,  # $10
        vector.range_position,  # $11
        vector.bar_close_pos,  # $12
        vector.gap_z,  # $13
        # Volume and order flow (8)
        vector.informed_flow,  # $14
        vector.volume_z,  # $15
        vector.ofi_z,  # $16
        vector.ofi_div,  # $17
        vector.cvd_slope_z,  # $18
        vector.cmf,  # $19
        vector.rel_volume,  # $20
        vector.vwap_dev_sigma,  # $21
        # Volatility (2)
        vector.atr_z,  # $22
        vector.vol_ratio,  # $23
        # Session-level (4)
        vector.poc_dist_atr,  # $24
        vector.va_position,  # $25
        vector.sr_support_dist,  # $26
        vector.sr_resist_dist,  # $27
        # Regime-level (10)
        vector.hmm_regime_prob,  # $28
        vector.hmm_entropy,  # $29
        vector.hmm_duration,  # $30
        vector.hurst,  # $31
        vector.shannon,  # $32
        vector.garch_ratio,  # $33
        vector.hma_slope_z,  # $34
        vector.adx,  # $35
        vector.aroon_fast,  # $36
        vector.aroon_slow,  # $37
        # Oscillators (6)
        vector.rsi_fast,  # $38
        vector.rsi_mid,  # $39
        vector.rsi_slow,  # $40
        vector.cci_fast,  # $41
        vector.cci_mid,  # $42
        vector.cci_slow,  # $43
        # Cross-asset (3)
        vector.vix_z,  # $44
        vector.flight_quality,  # $45
        vector.yield_slope_z,  # $46
        # Calendar (9 original)
        vector.in_ny_session,  # $47
        vector.in_london_kz,  # $48
        vector.in_overlap,  # $49
        vector.power_hour,  # $50
        vector.opening_range,  # $51
        vector.above_wk_vwap,  # $52
        vector.dow_sin,  # $53
        vector.dow_cos,  # $54
        vector.month_position,  # $55
        # Cross-timeframe (3)
        vector.ctf_momentum,  # $56
        vector.ctf_vwap_align,  # $57
        vector.ctf_regime_align,  # $58
        # Statistical / liquidity (4)
        vector.amihud_illiq_z,  # $59
        vector.high_52w_dist,  # $60
        vector.ret_skew_z,  # $61
        vector.ret_acf1_z,  # $62
        # New columns (migration 159)
        bar_close_ts,  # $63  computed from bar_ts + TF duration
        vector.momentum_z_slow,  # $64
        vector.momentum_reversal_z,  # $65
        vector.quarter_position,  # $66
        vector.days_to_month_end,  # $67
        vector.momentum_rank_z,  # $68  None until Phase 139 enrichment
        vector.volume_rank_z,  # $69  None until Phase 139 enrichment
        vector.volatility_rank_z,  # $70  None until Phase 139 enrichment
        # Renaissance Primitives (migration 206, Phase 142.5) — wired 2026-07-08,
        # see module docstring. $71 onward: derived by name from
        # _RENAISSANCE_PRIMITIVE_FIELD_NAMES (dataclasses.fields(FeatureVector)
        # order) rather than hand-typed, so this segment can't silently drift
        # out of sync with the dataclass again.
        *(getattr(vector, name) for name in _RENAISSANCE_PRIMITIVE_FIELD_NAMES),
        # Canary / Control Predictors (migration 223, Phase 143.1 Plan 02,
        # todo 068) — same derive-by-name discipline as the Renaissance
        # primitives above, appended immediately after them.
        *(getattr(vector, name) for name in _CANARY_FIELD_NAMES),
    )
