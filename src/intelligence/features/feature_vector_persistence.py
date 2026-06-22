"""Canonical persistence contract for the feature_vectors hypertable.

Single source of truth for:
  - INSERT SQL (61 columns: 1 content-key + 6 structural + 54 feature floats)
  - Content-key derivation: SHA-256(symbol|tf|bar_ts_ns|pipeline_version)[:32] as UUID
  - Row serializer: FeatureVector fields → 61-element INSERT tuple

Both the live write path (FeatureVectorWriter, asyncpg) and the batch compute
path (backfill_feature_factory, psycopg2) import from here. One schema
definition, two consumers — schema drift is structurally impossible.

Ring 1: imports FeatureVector from src.intelligence.schemas.
Do not import from Ring 2 (services/) or Ring 3 (api/, production/).
"""

from __future__ import annotations

import dataclasses
import hashlib
import math
import uuid
from datetime import datetime

from src.intelligence.schemas import FeatureVector

# ── Schema constraint ─────────────────────────────────────────────────────────

# feature_vectors.regime_label_source is CHECK-constrained to these values.
# 'filtered' = causal forward-filter HMM (the only valid source for IC training).
# 'unknown'  = regime computation failed or not yet run.
# 'viterbi_batch' is explicitly excluded — it introduces look-ahead bias.
VALID_REGIME_LABEL_SOURCES: frozenset[str] = frozenset({"filtered", "unknown"})


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

# 61 columns: $1 content-key, $2-$7 structural, $8-$61 feature floats.
# Column order is binding — matches FeatureVector field order exactly.
# ON CONFLICT DO NOTHING: idempotent replay; duplicate bars are skipped silently.
FEATURE_VECTOR_INSERT_SQL = """
INSERT INTO feature_vectors (
    feature_vector_id,
    symbol, tf, bar_ts, pipeline_version, regime, regime_label_source,
    momentum_z_5, momentum_z_20, range_position, bar_close_pos,
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
    amihud_illiq_z, high_52w_dist, ret_skew_z, ret_acf1_z
)
VALUES (
    $1,
    $2, $3, $4, $5, $6, $7,
    $8, $9, $10, $11,
    $12, $13, $14, $15, $16, $17, $18,
    $19, $20, $21, $22,
    $23, $24, $25, $26,
    $27, $28, $29, $30, $31, $32,
    $33, $34, $35, $36,
    $37, $38, $39, $40, $41, $42,
    $43, $44, $45,
    $46, $47, $48, $49, $50,
    $51, $52, $53, $54,
    $55, $56, $57,
    $58, $59, $60, $61
)
ON CONFLICT (symbol, tf, bar_ts) DO NOTHING
"""

# psycopg2 callers use %s placeholders; asyncpg uses $N. Both forms encode the
# same 61-column contract. Callers choose the right constant for their driver.
# Descending replacement order prevents $1 matching inside $10, $11, etc.
_pg2 = FEATURE_VECTOR_INSERT_SQL
for i in range(61, 0, -1):
    _pg2 = _pg2.replace(f"${i}", "%s")
FEATURE_VECTOR_INSERT_SQL_PSYCOPG2 = _pg2
del _pg2


# ── Content-key derivation ────────────────────────────────────────────────────


def make_feature_vector_id(
    symbol: str,
    tf: str,
    bar_ts: datetime,
    pipeline_version: str,
) -> uuid.UUID:
    """Derive the content-key UUID for a feature_vectors row.

    SHA-256(symbol|tf|bar_ts_ns|pipeline_version)[:32] cast to UUID.
    Deterministic and idempotent: same inputs always produce the same UUID.
    bar_ts_ns = nanosecond epoch integer to avoid sub-second precision loss.
    """
    bar_ts_ns = str(int(bar_ts.timestamp() * 1_000_000_000))
    digest = hashlib.sha256(f"{symbol}|{tf}|{bar_ts_ns}|{pipeline_version}".encode()).hexdigest()[
        :32
    ]
    return uuid.UUID(digest)


# ── Row serializer ────────────────────────────────────────────────────────────


def feature_vector_to_insert_params(
    symbol: str,
    tf: str,
    bar_ts: datetime,
    pipeline_version: str,
    regime: str | None,
    regime_label_source: str,
    vector: FeatureVector,
) -> tuple:
    """Serialize a FeatureVector to the canonical 61-element INSERT tuple.

    Column order matches FEATURE_VECTOR_INSERT_SQL exactly:
      $1:     feature_vector_id (content-key UUID)
      $2-$7:  structural (symbol, tf, bar_ts, pipeline_version, regime, regime_label_source)
      $8-$61: 54 feature floats in FeatureVector field order

    Args:
        symbol: Instrument symbol (e.g. 'SPY').
        tf: Timeframe string (e.g. '5m', '1h', '1d').
        bar_ts: UTC bar open timestamp.
        pipeline_version: Semver string stamped by the FeatureFactory run.
        regime: HMM regime label or None if not yet assigned.
        regime_label_source: Must be in VALID_REGIME_LABEL_SOURCES.
            Callers are responsible for passing a valid value — this function
            raises ValueError on violation rather than silently inserting a
            schema-invalid row.
        vector: Fully-populated FeatureVector from FeatureFactory.compute().

    Returns:
        61-element tuple for use with asyncpg executemany() or psycopg2
        execute_batch(). Compatible with both drivers — asyncpg and psycopg2
        handle uuid.UUID and datetime natively.

    Raises:
        ValueError: If regime_label_source is not in VALID_REGIME_LABEL_SOURCES.
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

    feature_vector_id = make_feature_vector_id(symbol, tf, bar_ts, pipeline_version)

    return (
        feature_vector_id,  # $1  content-key UUID
        symbol,  # $2
        tf,  # $3
        bar_ts,  # $4
        pipeline_version,  # $5
        regime,  # $6  nullable
        regime_label_source,  # $7
        # Momentum (5)
        vector.momentum_z_5,  # $8
        vector.momentum_z_20,  # $9
        vector.range_position,  # $10
        vector.bar_close_pos,  # $11
        vector.gap_z,  # $12
        # Volume and order flow (8)
        vector.informed_flow,  # $13
        vector.volume_z,  # $14
        vector.ofi_z,  # $15
        vector.ofi_div,  # $16
        vector.cvd_slope_z,  # $17
        vector.cmf,  # $18
        vector.rel_volume,  # $19
        vector.vwap_dev_sigma,  # $20
        # Volatility (2)
        vector.atr_z,  # $21
        vector.vol_ratio,  # $22
        # Session-level (4)
        vector.poc_dist_atr,  # $23
        vector.va_position,  # $24
        vector.sr_support_dist,  # $25
        vector.sr_resist_dist,  # $26
        # Regime-level (10)
        vector.hmm_regime_prob,  # $27
        vector.hmm_entropy,  # $28
        vector.hmm_duration,  # $29
        vector.hurst,  # $30
        vector.shannon,  # $31
        vector.garch_ratio,  # $32
        vector.hma_slope_z,  # $33
        vector.adx,  # $34
        vector.aroon_fast,  # $35
        vector.aroon_slow,  # $36
        # Oscillators (6)
        vector.rsi_fast,  # $37
        vector.rsi_mid,  # $38
        vector.rsi_slow,  # $39
        vector.cci_fast,  # $40
        vector.cci_mid,  # $41
        vector.cci_slow,  # $42
        # Cross-asset (3)
        vector.vix_z,  # $43
        vector.flight_quality,  # $44
        vector.yield_slope_z,  # $45
        # Calendar (9)
        vector.in_ny_session,  # $46
        vector.in_london_kz,  # $47
        vector.in_overlap,  # $48
        vector.power_hour,  # $49
        vector.opening_range,  # $50
        vector.above_wk_vwap,  # $51
        vector.dow_sin,  # $52
        vector.dow_cos,  # $53
        vector.month_position,  # $54
        # Cross-timeframe (3)
        vector.ctf_momentum,  # $55
        vector.ctf_vwap_align,  # $56
        vector.ctf_regime_align,  # $57
        # Statistical / liquidity (4)
        vector.amihud_illiq_z,  # $58
        vector.high_52w_dist,  # $59
        vector.ret_skew_z,  # $60
        vector.ret_acf1_z,  # $61
    )
