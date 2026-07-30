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

2026-07-23: extended to 181 columns (migration 255, Phase 163 Plan 01). 17
new structural VP/SR fields (12 volume-profile ATR-distance/bounded fields +
5 support/resistance strength/age/count fields, D-13/D-16/D-17/D-18/D-19)
added to FeatureVector's session-level block, immediately after the original
4 (poc_dist_atr/va_position/sr_support_dist/sr_resist_dist). Same
derive-by-name discipline as _RENAISSANCE_PRIMITIVE_FIELD_NAMES /
_CANARY_FIELD_NAMES via a new _STRUCTURAL_VP_SR_FIELD_NAMES slice, appended
at the end of the column list (after the canary fields) per this module's
established append-only convention -- column SQL order does not need to
match dataclass field order since every accessor is by name.

2026-07-28: extended to 217 columns (migration 266, Phase 164 Plan 01). 36
new Smart Money Concepts fields (order blocks, breaker/mitigation blocks,
fair value gaps, liquidity sweeps, liquidity pools, supply/demand zones,
BOS/CHoCH, AMD cycle -- all ATR-distance/bounded/count/ordinal, never a raw
price level, D-16) added to FeatureVector as a contiguous block immediately
after the canary fields (dataclass field-ordering requires this since the
canary block already carries defaults). Same derive-by-name discipline via a
new _SMC_FIELD_NAMES slice, appended at the end of the column list. All 36
values are None placeholders in this plan -- Plans 02-04 wire real compute
logic in without touching this file's column wiring again.

2026-07-28: extended to 258 columns (migration 267, Phase 165 Plan 01). 41
new Swing/Fib/Trend/Session Structure fields (swing detection, trend
structure, swing momentum, fibonacci zones, session levels -- all
ATR-distance/bounded/count/categorical, never a raw price level or raw bar
index, D-02/D-04) added to FeatureVector as a contiguous block immediately
BEFORE the canary fields (unlike the SMC block above -- D-01's nullable-field
fix requires these 41 fields to be non-defaulted `float | None`, so dataclass
ordering forces them ahead of the first defaulted field). Same
derive-by-name discipline via a new _SWING_FIB_TREND_FIELD_NAMES slice,
appended at the end of the column list (SQL column order does not need to
match dataclass field order since every accessor is by name -- this module's
established append-only convention). All 41 values are None placeholders in
this plan -- Plans 02-04 wire real compute logic in without touching this
file's column wiring again.

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

# The 17 new structural VP/SR fields (Phase 163 Plan 01, migration 255) are a third
# contiguous, same-order slice -- immediately following the original 4 session-level
# fields (poc_dist_atr/va_position/sr_support_dist/sr_resist_dist) in the dataclass.
# Same derive-don't-hand-type discipline as the two slices above; appended at the end
# of the column list (after the canary fields) below, matching this module's
# append-only convention.
_STRUCTURAL_VP_SR_FIELD_NAMES: tuple[str, ...] = _ALL_FEATURE_VECTOR_FIELD_NAMES[
    _ALL_FEATURE_VECTOR_FIELD_NAMES.index(
        "nearest_hvn_above_dist_atr"
    ) : _ALL_FEATURE_VECTOR_FIELD_NAMES.index("sr_level_count")
    + 1
]

# The 36 new Smart Money Concepts fields (Phase 164 Plan 01, migration 266) are
# a fourth contiguous, same-order slice -- immediately following the canary
# fields in the dataclass (schemas.py placed this block right before the 3
# nullable cross-sectional fields, after the canary block, since Python
# dataclass field ordering requires every field after a defaulted field to
# also carry a default). Same derive-don't-hand-type discipline as the three
# slices above; appended at the end of the column list below.
_SMC_FIELD_NAMES: tuple[str, ...] = _ALL_FEATURE_VECTOR_FIELD_NAMES[
    _ALL_FEATURE_VECTOR_FIELD_NAMES.index(
        "ob_bull_dist_atr"
    ) : _ALL_FEATURE_VECTOR_FIELD_NAMES.index("manip_strength")
    + 1
]

# The 41 new Swing/Fib/Trend/Session Structure fields (Phase 165 Plan 01,
# migration 267) are a fifth contiguous, same-order slice -- immediately
# preceding the canary fields in the dataclass (D-01's nullable-field fix
# requires these to be non-defaulted `float | None`, so Python dataclass
# field ordering places this block BEFORE _CANARY_FIELD_NAMES rather than
# after it like _SMC_FIELD_NAMES above). Same derive-don't-hand-type
# discipline as the four slices above; appended at the end of the column
# list below (SQL column order does not need to match dataclass field order
# since every accessor is by name).
_SWING_FIB_TREND_FIELD_NAMES: tuple[str, ...] = _ALL_FEATURE_VECTOR_FIELD_NAMES[
    _ALL_FEATURE_VECTOR_FIELD_NAMES.index(
        "swing_high_dist_atr"
    ) : _ALL_FEATURE_VECTOR_FIELD_NAMES.index("gap_filled")
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


# ── Canonical INSERT/UPSERT SQL ───────────────────────────────────────────────

# 258 columns (as of 2026-07-28): $1 content-key, $2-$8 structural, $9-$62
# original feature floats, $63-$70 migration-159 additions, $71-$159
# migration-206 Renaissance primitives (2026-07-08 fix, then reduced from 91
# to 89 primitives 2026-07-09), $160-$164 migration-223 canary/control
# predictors, $165-$181 migration-255 structural VP/SR fields (Phase 163
# Plan 01), $182-$217 migration-266 SMC institutional-footprint fields
# (Phase 164 Plan 01), $218-$258 migration-267 swing/fib/trend/session
# structure fields (Phase 165 Plan 01, see module docstring).
# Column order is binding — matches migration 159/206/223/255/266/267 column definition order.
_STRUCTURAL_PREFIX_COLUMN_NAMES: tuple[str, ...] = (
    "feature_vector_id",
    "symbol",
    "tf",
    "bar_ts",
    "pipeline_version",
    "feature_factory_version",
    "regime",
    "regime_label_source",
    "momentum_z_fast",
    "momentum_z_mid",
    "range_position",
    "bar_close_pos",
    "gap_z",
    "informed_flow",
    "volume_z",
    "ofi_z",
    "ofi_div",
    "cvd_slope_z",
    "cmf",
    "rel_volume",
    "vwap_dev_sigma",
    "atr_z",
    "vol_ratio",
    "poc_dist_atr",
    "va_position",
    "sr_support_dist",
    "sr_resist_dist",
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
    "rsi_fast",
    "rsi_mid",
    "rsi_slow",
    "cci_fast",
    "cci_mid",
    "cci_slow",
    "vix_z",
    "flight_quality",
    "yield_slope_z",
    "in_ny_session",
    "in_london_kz",
    "in_overlap",
    "power_hour",
    "opening_range",
    "above_wk_vwap",
    "dow_sin",
    "dow_cos",
    "month_position",
    "ctf_momentum",
    "ctf_vwap_align",
    "ctf_regime_align",
    "amihud_illiq_z",
    "high_52w_dist",
    "ret_skew_z",
    "ret_acf1_z",
    "bar_close_ts",
    "momentum_z_slow",
    "momentum_reversal_z",
    "quarter_position",
    "days_to_month_end",
    "momentum_rank_z",
    "volume_rank_z",
    "volatility_rank_z",
)

# Single source of truth for column order -- both SQL statements below and the
# psycopg2 placeholder count are derived from this tuple, so they cannot drift
# out of sync with each other the way separately-hand-typed VALUES lists could.
_ALL_COLUMN_NAMES: tuple[str, ...] = (
    _STRUCTURAL_PREFIX_COLUMN_NAMES
    + _RENAISSANCE_PRIMITIVE_FIELD_NAMES
    + _CANARY_FIELD_NAMES
    + _STRUCTURAL_VP_SR_FIELD_NAMES
    + _SMC_FIELD_NAMES
    + _SWING_FIB_TREND_FIELD_NAMES
)
_TOTAL_COLUMNS = len(_ALL_COLUMN_NAMES)

_INSERT_COLUMNS_SQL = ",\n    ".join(_ALL_COLUMN_NAMES)
_VALUES_PLACEHOLDERS_SQL = ", ".join(f"${i}" for i in range(1, _TOTAL_COLUMNS + 1))

# Shared scaffolding for both statements below -- they differ only in the trailing
# ON CONFLICT clause, so that clause is the only thing appended per variant. This
# makes it structurally impossible for the two statements to diverge in column
# list, order, or placeholder count (the exact drift class this module's docstring
# describes for the 2026-07-08 incident).
_INSERT_VALUES_SQL = f"""
INSERT INTO feature_vectors (
    {_INSERT_COLUMNS_SQL}
)
VALUES (
    {_VALUES_PLACEHOLDERS_SQL}
)
"""

_PK_COLUMN_NAMES = frozenset({"symbol", "tf", "bar_ts"})

# Single source of truth for regime_writer.py's column ownership (Ring 1, this module,
# is the legal place for it -- services/regime_writer.py, Ring 2, imports FROM here,
# never the reverse). regime_writer batch-UPDATEs these 8 columns via one atomic
# `UPDATE feature_vectors ... WHERE regime IS NULL` pass, per-symbol fitted K=5 HMM
# (BIC-validated, APR-governed via alpha.hmm.random_state). Previously this ownership
# list was hand-typed independently in two places (here and regime_writer.py's own
# set_cols literal) -- exactly the hand-typed-list-drift failure mode this module's own
# docstring already documents (2026-07-08, todo 176): a column added to one list and not
# the other fails silently. Deriving both from one tuple makes that drift structurally
# impossible instead of merely tested-for.
REGIME_WRITER_OWNED_COLUMN_NAMES: tuple[str, ...] = (
    "regime",
    "hmm_prob_trending_up",
    "hmm_prob_ranging",
    "hmm_prob_trending_down",
    "hmm_regime_prob",
    "hmm_entropy",
    "hmm_duration",
    "hmm_churn",
)

# Of REGIME_WRITER_OWNED_COLUMN_NAMES' 8 columns, hmm_prob_trending_up/hmm_prob_ranging/
# hmm_prob_trending_down/hmm_churn aren't in this module's column list at all (safe by
# construction -- no caller here ever writes them). The intersection with
# _ALL_COLUMN_NAMES is what must be excluded from DO UPDATE SET:
#
# - regime: callers always pass None (they don't compute a regime label themselves).
#   If included in DO UPDATE SET, a --refresh recompute would silently overwrite every
#   already-labeled row's regime back to NULL with EXCLUDED's always-None value,
#   discarding regime_writer's prior work corpus-wide. Confirmed root cause of the
#   2026-07-30 incident: a --refresh run nulled feature_vectors.regime across all
#   36.8M rows this way. (A second, independent violation of the same invariant was
#   found and fixed the same day: services/feature_vector_pipeline.py's live path was
#   assigning its own heuristic regime value on every bar -- see that file's
#   _process_bar_compute docstring.)
#
# - hmm_regime_prob/hmm_entropy/hmm_duration: NOT solely regime_writer's, unlike
#   regime -- FeatureFactory.compute()/compute_batch() (feature_cache.py's inline
#   K=3 forward-filter HMM) also populates these same field names on every FeatureVector,
#   a second, different model writing the same column name as regime_writer's fitted
#   K=5 HMM. Confirmed live on 2026-07-30: 11% of SPY/1d rows carrying regime_writer's
#   probability triple violated the same-model invariant hmm_regime_prob <= max(p_up,
#   p_ranging, p_down), i.e. the two models' outputs were already mixed in this column.
#   Excluding them here preserves regime_writer's explicitly-claimed values from being
#   silently overwritten by the K=3 compute value on --refresh, same protection as
#   regime -- but note this exclusion only stops --refresh from being the tiebreaker by
#   accident, it does not un-mix rows that already carry a K=3 value written before
#   regime_writer ever reached them. These three ARE live ML input: ensemble_trainer.py's
#   `_get_feature_columns()` (`_META_COLS` excludes regime/regime_label_source but not
#   these three) feeds them to ensemble training as ordinary features, so a row whose
#   value came from K=3 vs K=5 is silently indistinguishable downstream. Which model
#   *should* be authoritative for this column name is a separate, unresolved design
#   question (todo 207) -- resolution is presumably a rename (distinct hmm_*_k3 vs
#   hmm_*_fitted columns), not a preference call.
#
# - regime_label_source: NOT actually regime_writer-owned (absent from
#   REGIME_WRITER_OWNED_COLUMN_NAMES) -- every caller hardcodes the constant 'filtered'
#   already, so exclusion vs inclusion here is a no-op in practice. Left excluded for
#   symmetry with regime; if this field ever becomes genuinely computed/contested,
#   revisit.
_EXTERNALLY_OWNED_COLUMN_NAMES = frozenset(REGIME_WRITER_OWNED_COLUMN_NAMES) | {
    "regime_label_source"
}
_UPDATE_SET_SQL = ",\n    ".join(
    f"{name} = EXCLUDED.{name}"
    for name in _ALL_COLUMN_NAMES
    if name not in _PK_COLUMN_NAMES and name not in _EXTERNALLY_OWNED_COLUMN_NAMES
)

# feature_vectors' real uniqueness constraint is (symbol, tf, bar_ts) -- NOT
# feature_vector_id, which is a derived content-key, not a constraint target.
# DO NOTHING therefore skips ANY re-insert of an existing bar regardless of what
# changed (new columns added since the row was first written, corrected compute
# logic, a bumped feature_factory_version) -- confirmed 2026-07-27 as the reason
# a naive backfill re-run never populated Phase 163's 17 VP/SR columns on 36.7M
# pre-existing rows (todo 176). FEATURE_VECTOR_INSERT_SQL keeps DO NOTHING for
# the live write path (a replayed Kafka message for an already-finalized bar
# should stay a no-op). FEATURE_VECTOR_UPSERT_SQL is the deliberate escape
# hatch for recompute/backfill callers that need to overwrite existing rows.
FEATURE_VECTOR_INSERT_SQL = _INSERT_VALUES_SQL + "ON CONFLICT (symbol, tf, bar_ts) DO NOTHING\n"

FEATURE_VECTOR_UPSERT_SQL = (
    _INSERT_VALUES_SQL + f"ON CONFLICT (symbol, tf, bar_ts) DO UPDATE SET\n    {_UPDATE_SET_SQL}\n"
)


# psycopg2 callers use %s placeholders; asyncpg uses $N. Both forms encode the
# same column contract. Callers choose the right constant for their driver.
# Descending replacement order prevents $1 matching inside $10, $11, etc.
def _to_psycopg2_placeholders(sql: str) -> str:
    for i in range(_TOTAL_COLUMNS, 0, -1):
        sql = sql.replace(f"${i}", "%s")
    return sql


FEATURE_VECTOR_INSERT_SQL_PSYCOPG2 = _to_psycopg2_placeholders(FEATURE_VECTOR_INSERT_SQL)
FEATURE_VECTOR_UPSERT_SQL_PSYCOPG2 = _to_psycopg2_placeholders(FEATURE_VECTOR_UPSERT_SQL)


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
    """Serialize a FeatureVector to the canonical 258-element INSERT tuple.

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
      $165-$181: 17 structural VP/SR fields (migration 255, Phase 163 Plan 01)
                 in dataclasses.fields(FeatureVector) order
      $182-$217: 36 Smart Money Concepts fields (migration 266, Phase 164
                 Plan 01) in dataclasses.fields(FeatureVector) order — all
                 None placeholders until Plans 02-04 wire real compute logic
      $218-$258: 41 Swing/Fib/Trend/Session Structure fields (migration 267,
                 Phase 165 Plan 01) in dataclasses.fields(FeatureVector)
                 order — all None placeholders until Plans 02-04 wire real
                 compute logic

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
        258-element tuple for use with asyncpg executemany() or psycopg2
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
        # Structural VP/SR fields (migration 255, Phase 163 Plan 01) — same
        # derive-by-name discipline, appended immediately after the canary
        # fields (module docstring).
        *(getattr(vector, name) for name in _STRUCTURAL_VP_SR_FIELD_NAMES),
        # Smart Money Concepts fields (migration 266, Phase 164 Plan 01) — same
        # derive-by-name discipline, appended immediately after the structural
        # VP/SR fields (module docstring). All None until Plans 02-04 wire real
        # compute logic in.
        *(getattr(vector, name) for name in _SMC_FIELD_NAMES),
        # Swing/Fib/Trend/Session Structure fields (migration 267, Phase 165
        # Plan 01) — same derive-by-name discipline, appended immediately
        # after the SMC fields (module docstring). All None until Plans 02-04
        # wire real compute logic in.
        *(getattr(vector, name) for name in _SWING_FIB_TREND_FIELD_NAMES),
    )
