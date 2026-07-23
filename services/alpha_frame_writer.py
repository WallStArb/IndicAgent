#!/usr/bin/env python3
"""Alpha Frame Writer — oneshot that turns alpha_events rows into hypothetical alpha_frames.

FRAME-01: writes one `alpha_frames` row per `alpha_events` row (`frame_variant='primary'`),
snapshotting the alpha signal and the D-03 diagnostic expected-R triad at creation time.
Geometry columns (entry/stop/target/r_multiple) are written NULL — CounterfactualTracker
(Plan 02) fills them at T+1 bar open using `compute_frame_geometry` (defined here, imported
by the tracker) with a price-unit ATR it computes from `market_data_ohlcv` (review H2 —
the feature-vector corpus has no price-unit ATR column).

CORRECTNESS INVARIANTS:
- Anti-join checkpoint (Pattern 4): the same query serves nightly-incremental and --backfill —
  `alpha_frames` itself is the resume state, no separate checkpoint file.
- Per-(symbol, tf) partitioned read+flush (review L1): no single long-running read transaction
  over the full alpha_events backlog.
- frame_id = BaseBatch.content_key(event_id, str(bar_ts), 'primary') — deterministic; a re-run
  over the same alpha_events row is idempotent via ON CONFLICT (event_id, bar_ts, frame_variant)
  DO NOTHING (uq_alpha_frames_variant).
- compute_frame_geometry is a pure function, ATR-only target path (the support/resistance
  distance columns are 100% NULL across the corpus — no conditional branch on them), correct
  for both long and short.
- compute_expected_r_snapshot is a pure function; gross_expected_r/cost_r/net_expected_r are
  written non-NULL on every row (D-03 diagnostic snapshot, never a gate input).
- cost_r is copied through from alpha_events.cost_hurdle — never re-derived live from APR
  (prevents silent historical drift on the next cost-hurdle recalibration).
- No Kafka: this table has no live consumer, matching EnsembleICEngine's precedent (Pitfall 5).

Phase 166 Plan 05 — geometry_source dispatch (D-01b/D-01c/D-03):
- `alpha.frame.geometry_source` (global | per_cell_scalar | structural) selects which
  stop_atr_mult/target_r_multiple SCALAR values get snapshotted onto each frame's
  stop_atr_mult/target_r_multiple columns — the same two columns the writer has always
  snapshotted (never live entry/stop/target prices; those stay CounterfactualTracker's job at
  T+1, per the invariants above). "global" is byte-identical to pre-166-05 behavior (the sole
  regression-tested default). "per_cell_scalar" mirrors the hold_key per-(regime,tf) lookup
  pattern exactly. "structural" additionally reads `feature_vectors` (Phase-163 columns only,
  opaque to this file — passed through to `structural_confluence.resolve_structural_zone` as a
  generic dict) and computes an independent, causal, scan-time ATR from
  `market_data_ohlcv_tradeable` (gated to `geometry_source == "structural"` only — H2's
  "ATR is caller-supplied, never a feature_vectors column" constraint is unchanged: this ATR is
  computed from OHLCV, never read as a feature_vectors column) to derive an EFFECTIVE
  stop_atr_mult ratio, which is what actually gets snapshotted — never a raw price. The
  entry_price used for this resolution is the alpha_event's own bar_ts close (a scan-time
  proxy, not the true T+1 execution entry CounterfactualTracker computes independently) —
  sufficient because only the resulting ATR-relative ratio is persisted (RESEARCH.md A2 flags
  the ATR-consistency assumption for a live spot-check in Plan 166-06).

Usage:
    python services/alpha_frame_writer.py [--backfill]
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import asyncpg
import structlog

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from services._batch_utils import cfg as _cfg
from services._batch_utils import load_apr_dict_async as _load_apr
from src.config.config_service import ConfigService
from src.config.settings import Settings
from src.core.agent.base_batch import BaseBatch
from src.intelligence.trading.structural_confluence import (
    resolve_structural_zone,
    set_config_service,
)
from src.observability.corpus_manifest import CorpusManifest
from src.observability.otel import OTelInitError, init_otel_providers

_logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Pure functions — no DB, no table reads. Plan 02's CounterfactualTracker imports
# compute_frame_geometry to fill entry/stop/target/r_multiple at T+1 bar open.
# ---------------------------------------------------------------------------


def compute_frame_geometry(
    direction: str,
    entry_price: float,
    atr: float,
    stop_atr_mult: float,
    target_r_multiple: float,
    min_stop_price_fraction: float,
) -> tuple[float, float, float]:
    """ATR-only frame geometry (review H2 — the sole target path; the support/resistance
    distance columns are 100% NULL across the corpus, so no conditional branch on them).

    `atr` is a caller-supplied price-unit value — this function never reads a table.

    Raises ValueError if atr is non-positive (stale/forward-filled bars collapse the stop
    distance to zero, which would otherwise raise an unguarded ZeroDivisionError on r_multiple
    — code-review CR-01). Callers must catch this and skip the frame rather than let it
    propagate out of a batch scan. `stop_atr_mult` is a single global APR value shared by every
    frame in a run, so it is validated once, eagerly, at config-load time in
    `FrameConfig.from_apr` rather than rediscovered here per-frame.

    Also raises ValueError if the resulting stop_distance is below min_stop_price_fraction of
    entry_price (todo 162): a small-but-*positive* ATR on a thin-absolute-volatility instrument
    (observed: FX/commodity ETFs at 5m -- FXY, FXE, DBB, DBC, GLD, SLV) passes the atr<=0 guard
    but still produces an economically meaningless, razor-thin stop -- ordinary price noise then
    blows through it by dozens of stop-distances, producing counterfactual_pnl_r far beyond a
    normal stop-out (observed down to -926.87R in-sample). This is deliberately a SKIP, not a
    widened floor: artificially widening the stop would also widen target_price by the same
    factor (it's derived from stop_distance), fabricating a trading rule real ATR-based sizing
    never specified, rather than declining to score a frame the data can't support.

    Returns (stop_price, target_price, r_multiple). r_multiple is always exactly
    `target_r_multiple` by construction (target_price is defined as
    `entry ± target_r_multiple * stop_distance`, so the realized ratio is the input ratio) —
    returned directly rather than recomputed via division, which also avoids a needless
    float round-trip through the same value.
    """
    if atr <= 0:
        raise ValueError(
            f"compute_frame_geometry: non-positive atr ({atr}) — cannot derive a stop/target"
        )
    if direction == "long":
        stop_price = entry_price - stop_atr_mult * atr
        stop_distance = entry_price - stop_price
        target_price = entry_price + target_r_multiple * stop_distance
    elif direction == "short":
        stop_price = entry_price + stop_atr_mult * atr
        stop_distance = stop_price - entry_price
        target_price = entry_price - target_r_multiple * stop_distance
    else:
        raise ValueError(f"compute_frame_geometry: unknown direction {direction!r}")
    if stop_distance < min_stop_price_fraction * entry_price:
        raise ValueError(
            f"compute_frame_geometry: stop_distance ({stop_distance}) below "
            f"min_stop_price_fraction ({min_stop_price_fraction}) of entry_price ({entry_price})"
        )
    return stop_price, target_price, target_r_multiple


def compute_expected_r_snapshot(
    alpha_score: float,
    target_r_multiple: float,
    cost_r: float,
) -> tuple[float, float]:
    """D-03 diagnostic expected-R snapshot (pure fn), computable at frame-creation time
    (uses APR target_r_multiple and alpha_score, not the NULL geometry columns).

    gross_expected_r = the ex-ante expected payoff MAGNITUDE in R at entry: the model's
    directional-confidence magnitude (alpha_score) scaled by the frame's design R-multiple
    on a win. Direction-agnostic (abs value) — the traded direction is already fixed by the
    frame's `direction` column. This is a diagnostic magnitude, not a probability and not a
    gate input (units documented in migration 214's column comments, review M5).

    net_expected_r = gross_expected_r - cost_r. Reporting-only (D-01/D-02) — never feeds
    FRAME-04's gate, which evaluates realized counterfactual_pnl_r.

    Returns (gross_expected_r, net_expected_r), both non-NULL/non-NaN for any finite input.
    """
    gross_expected_r = abs(alpha_score) * target_r_multiple
    net_expected_r = gross_expected_r - cost_r
    return gross_expected_r, net_expected_r


# geometry_source dispatch (Phase 166 Plan 05, D-01b/D-01c/D-03). "global" is the sole
# regression-tested default (byte-identical to pre-166-05 behavior).
_VALID_GEOMETRY_SOURCES = frozenset({"global", "per_cell_scalar", "structural"})


@dataclass(frozen=True)
class FrameConfig:
    """APR-bound frame geometry parameters (FRAME-01). Frozen for pickling/dispatch safety,
    mirroring EnsembleICConfig's binding pattern (test_ensemble_ic_config.py style)."""

    stop_atr_mult: float
    target_r_multiple: float
    atr_period: int
    min_stop_price_fraction: float
    geometry_source: str

    @classmethod
    def from_apr(cls, cfg_dict: dict[str, Any]) -> FrameConfig:
        stop_atr_mult = _cfg(cfg_dict, "alpha.frame.stop_atr_mult", 1.5)
        if stop_atr_mult <= 0:
            # A misconfigured global APR value would otherwise collapse every frame this run
            # writes to zero-width geometry (stop == entry == target) with no error — validated
            # once here, eagerly, rather than rediscovered per-frame deep in a batch scan.
            raise ValueError(f"alpha.frame.stop_atr_mult must be positive, got {stop_atr_mult}")
        min_stop_price_fraction = _cfg(cfg_dict, "alpha.frame.min_stop_price_fraction", 0.001)
        if min_stop_price_fraction < 0:
            raise ValueError(
                f"alpha.frame.min_stop_price_fraction must be >= 0, got {min_stop_price_fraction}"
            )
        geometry_source = _cfg(cfg_dict, "alpha.frame.geometry_source", "global")
        if geometry_source not in _VALID_GEOMETRY_SOURCES:
            # Same eager-validation-at-config-load discipline as stop_atr_mult above — an
            # invalid selector would otherwise silently fall through to whichever branch
            # string-equality happens to miss, deep in a --backfill scan.
            raise ValueError(
                f"alpha.frame.geometry_source must be one of {sorted(_VALID_GEOMETRY_SOURCES)}, "
                f"got {geometry_source!r}"
            )
        return cls(
            stop_atr_mult=stop_atr_mult,
            target_r_multiple=_cfg(cfg_dict, "alpha.frame.target_r_multiple", 2.0),
            atr_period=_cfg(cfg_dict, "alpha.frame.atr_period", 14),
            min_stop_price_fraction=min_stop_price_fraction,
            geometry_source=geometry_source,
        )


# ---------------------------------------------------------------------------
# geometry_source resolution (Phase 166 Plan 05, Tasks 1-2) — pure functions, no DB. Called
# once per pending alpha_events row inside _process_partition; the DB-touching bulk fetches
# structural mode needs are separate async helpers below (never a per-row round trip).
# ---------------------------------------------------------------------------


def _resolve_scalar_geometry(
    cfg: dict[str, Any],
    regime: str,
    tf: str,
    frame_config: FrameConfig,
    missing_stop_keys: set[str],
    missing_target_keys: set[str],
) -> tuple[float, float]:
    """per_cell_scalar geometry_source (Task 1): mirrors the existing hold_key per-(regime,tf)
    lookup pattern exactly (`alpha.frame.stop_atr_mult.{regime}.{tf}` /
    `alpha.frame.target_r_multiple.{regime}.{tf}`), each falling back to the current global
    scalar (`frame_config.stop_atr_mult`/`target_r_multiple`) when the per-cell key is absent
    — additive, backward-compatible. Also used by "structural" as the scalar seed bounding the
    structural candidate search window (Task 2).

    Missing per-cell keys accumulate into the given sets — never a per-row log call
    (CLAUDE.md's "never log per-row inside a loop over the full corpus" rule); the caller warns
    once per partition after the full scan.
    """
    stop_key = f"alpha.frame.stop_atr_mult.{regime}.{tf}"
    if stop_key not in cfg:
        missing_stop_keys.add(stop_key)
    stop_atr_mult = float(_cfg(cfg, stop_key, frame_config.stop_atr_mult))

    target_key = f"alpha.frame.target_r_multiple.{regime}.{tf}"
    if target_key not in cfg:
        missing_target_keys.add(target_key)
    target_r_multiple = float(_cfg(cfg, target_key, frame_config.target_r_multiple))

    return stop_atr_mult, target_r_multiple


def _resolve_structural_geometry(
    features: dict[str, Any],
    direction: str,
    entry_price: float,
    atr: float,
    scalar_stop_atr_mult: float,
    target_r_multiple: float,
    min_stop_price_fraction: float,
) -> tuple[float, float] | None:
    """structural geometry_source (Task 2): derives an EFFECTIVE stop_atr_mult from
    `structural_confluence.resolve_structural_zone`, falling back to the scalar seed
    (`scalar_stop_atr_mult` — the per_cell_scalar/global resolution already performed by the
    caller) when the confluence tier is "atr" (no usable structural candidates — e.g. before
    Phase 163 executes, NULL_PENDING_163 per 166-01-SUMMARY.md).

    Only the resulting RATIO is ever returned/persisted — never a raw structural price.
    `entry_price`/`atr` bound the structural candidate search window and convert the resolved
    structural stop price back into that ratio; `compute_frame_geometry`'s
    atr<=0/min_stop_price_fraction ValueError-skip contract (todo 162) is preserved for BOTH
    the scalar-seed stop (used only to bound the search window, never persisted) and the final
    effective geometry — returns None (caller skips the frame) on either degenerate-stop-
    distance failure, never fabricating a frame the data can't support.
    """
    if atr is None or atr <= 0:
        return None
    try:
        seed_stop_price, _, _ = compute_frame_geometry(
            direction,
            entry_price,
            atr,
            scalar_stop_atr_mult,
            target_r_multiple,
            min_stop_price_fraction,
        )
    except ValueError:
        return None

    direction_int = 1 if direction == "long" else -1
    zone = resolve_structural_zone(features, direction_int, entry_price, seed_stop_price, atr)

    if zone.tier == "atr":
        effective_stop_atr_mult = scalar_stop_atr_mult
    else:
        # "The near bound on the stop side" (166-05-PLAN.md): for long the stop sits below
        # entry, so the zone's lower bound (zone_low) is the side away from entry — mirrors
        # trade_framer.py's own "stop < zone_low" convention for a support-side zone; for
        # short the mirror is zone_high.
        structural_stop_price = zone.zone_low if direction == "long" else zone.zone_high
        effective_stop_atr_mult = abs(entry_price - structural_stop_price) / atr

    try:
        compute_frame_geometry(
            direction,
            entry_price,
            atr,
            effective_stop_atr_mult,
            target_r_multiple,
            min_stop_price_fraction,
        )
    except ValueError:
        return None

    return effective_stop_atr_mult, target_r_multiple


def _resolve_row_geometry(
    geometry_source: str,
    cfg: dict[str, Any],
    regime: str,
    tf: str,
    frame_config: FrameConfig,
    missing_stop_keys: set[str],
    missing_target_keys: set[str],
    *,
    features: dict[str, Any] | None = None,
    direction: str | None = None,
    entry_price: float | None = None,
    atr: float | None = None,
) -> tuple[float, float] | None:
    """Dispatch on geometry_source (Tasks 1-2), returning the (stop_atr_mult,
    target_r_multiple) pair to snapshot onto this row, or None when the frame must be skipped
    entirely (structural mode's degenerate-stop ValueError-skip contract, todo 162).

    "global": frame_config's scalars, completely unchanged — no cfg lookups performed at all
    (Test 1: proven byte-identical to pre-166-05 behavior).
    "per_cell_scalar": `_resolve_scalar_geometry` — per-(regime,tf) key with global fallback.
    "structural": resolves the same per-cell scalar seed first, then
    `_resolve_structural_geometry`. When entry_price/atr/features are unavailable for this
    bar (no market data resolvable, distinct from the degenerate-ATR condition
    compute_frame_geometry itself guards against), degrades to the scalar seed rather than
    skipping the frame.
    """
    if geometry_source == "global":
        return frame_config.stop_atr_mult, frame_config.target_r_multiple

    scalar_stop_atr_mult, target_r_multiple = _resolve_scalar_geometry(
        cfg, regime, tf, frame_config, missing_stop_keys, missing_target_keys
    )
    if geometry_source == "per_cell_scalar":
        return scalar_stop_atr_mult, target_r_multiple

    # geometry_source == "structural" (the only remaining value — validated at
    # FrameConfig.from_apr load time).
    if features is None or direction is None or entry_price is None or atr is None:
        return scalar_stop_atr_mult, target_r_multiple

    return _resolve_structural_geometry(
        features,
        direction,
        entry_price,
        atr,
        scalar_stop_atr_mult,
        target_r_multiple,
        frame_config.min_stop_price_fraction,
    )


# ---------------------------------------------------------------------------
# structural geometry_source bulk fetches (Task 2) — one query per (symbol, tf) partition,
# never a per-row round trip. Gated to geometry_source == "structural" only by the caller.
# ---------------------------------------------------------------------------

# Causal, scan-time ATR (simple average of true range over the trailing atr_period bars,
# inclusive of the current bar) computed independently from market_data_ohlcv_tradeable — same
# methodology as CounterfactualTracker's own _true_range/tr_window (never a feature_vectors
# column, H2). `close` doubles as this file's entry_price proxy (see module docstring's
# Phase 166 Plan 05 note) — the true T+1 execution entry remains CounterfactualTracker's job.
_STRUCTURAL_MARKET_DATA_SQL = """
    WITH tr AS (
        SELECT
            timestamp,
            close,
            GREATEST(
                high - low,
                COALESCE(ABS(high - LAG(close) OVER (ORDER BY timestamp)), 0),
                COALESCE(ABS(low - LAG(close) OVER (ORDER BY timestamp)), 0)
            ) AS true_range
        FROM market_data_ohlcv_tradeable
        WHERE symbol = $1 AND timeframe = $2
    )
    SELECT
        timestamp,
        close,
        AVG(true_range) OVER (
            ORDER BY timestamp ROWS BETWEEN $3 PRECEDING AND CURRENT ROW
        ) AS atr
    FROM tr
    ORDER BY timestamp
"""

# SELECT * (not an explicit Phase-163 column list) — this file stays opaque to which specific
# structural fields structural_confluence.py's spec table reads; keeps that ownership boundary
# in one module (never names an individual Phase-163 structural column here — that belongs to
# the confluence module, not this file's own logic).
_STRUCTURAL_FEATURES_SQL = """
    SELECT * FROM feature_vectors WHERE symbol = $1 AND tf = $2
"""


async def _fetch_structural_market_data(
    conn: asyncpg.Connection, symbol: str, tf: str, atr_period: int
) -> dict[Any, tuple[float, float]]:
    """bar_ts -> (entry_price proxy, causal scan-time ATR) for one (symbol, tf) partition."""
    rows = await conn.fetch(_STRUCTURAL_MARKET_DATA_SQL, symbol, tf, max(atr_period - 1, 0))
    return {row["timestamp"]: (float(row["close"]), float(row["atr"])) for row in rows}


async def _fetch_structural_features(
    conn: asyncpg.Connection, symbol: str, tf: str
) -> dict[Any, dict[str, Any]]:
    """bar_ts -> feature_vectors row (as a plain dict) for one (symbol, tf) partition."""
    rows = await conn.fetch(_STRUCTURAL_FEATURES_SQL, symbol, tf)
    return {row["bar_ts"]: dict(row) for row in rows}


def _build_structural_config_service(cfg: dict[str, Any]) -> ConfigService:
    """Cache-only ConfigService (no DB pool) for structural_confluence's threshold reads,
    populated directly from the already-loaded alpha.* cfg dict — mirrors
    services/_batch_utils.py's load_config_service_sync cache-only pattern, avoiding a second
    DB round trip for keys `_load_apr` already fetched this run."""
    service = ConfigService(database_url="")
    for key, default in (
        ("alpha.frame.cluster_radius_atr", 0.5),
        ("alpha.frame.single_level_radius_atr", 0.25),
        ("alpha.frame.zone_buffer_atr", 0.1),
        ("alpha.frame.min_width_atr", 0.05),
        ("alpha.frame.strength_weight", 0.6),
        ("alpha.frame.proximity_weight", 0.4),
    ):
        service._cache[key] = _cfg(cfg, key, default)
    return service


# ---------------------------------------------------------------------------
# AlphaFrameWriter
# ---------------------------------------------------------------------------

_DEFAULT_HOLD_MAX_BARS = 60  # matches migration 195's [initial_estimate] seed default


class AlphaFrameWriter(BaseBatch):
    """Batch compute service: alpha_events -> alpha_frames (FRAME-01).

    Writes one 'primary' hypothetical frame per pending alpha_events row via a
    per-(symbol, tf) chunked anti-join write pass. Geometry columns are left NULL for
    Plan 02's CounterfactualTracker to fill at T+1 bar open.
    """

    job_name = "alpha-frame-writer"
    compute_version = "1.0.0"

    def __init__(self, db_dsn: str, backfill: bool = False) -> None:
        super().__init__(db_dsn)
        self.backfill = backfill

    _INSERT_SQL = """
        INSERT INTO alpha_frames (
            frame_id, event_id, bar_ts, symbol, tf, regime, direction, frame_variant,
            alpha_score, alpha_ci_lower, alpha_ci_upper,
            gross_expected_r, cost_r, net_expected_r,
            max_hold_bars, stop_atr_mult, target_r_multiple, status,
            corpus_run_id, weight_epoch, is_shadow
        ) VALUES (
            $1, $2, $3, $4, $5, $6, $7, $8,
            $9, $10, $11,
            $12, $13, $14,
            $15, $16, $17, $18,
            $19, $20, $21
        )
        ON CONFLICT (event_id, bar_ts, frame_variant) DO NOTHING
    """

    # Pattern 4: anti-join against alpha_frames itself — the target table IS the
    # checkpoint. The same query serves nightly-incremental and --backfill.
    _PENDING_SQL = """
        SELECT ae.event_id, ae.bar_ts, ae.symbol, ae.tf, ae.regime, ae.direction,
               ae.alpha_score, ae.alpha_ci_lower, ae.alpha_ci_upper, ae.cost_hurdle,
               ae.weight_version, ae.is_shadow
        FROM alpha_events ae
        LEFT JOIN alpha_frames af
            ON af.event_id = ae.event_id
           AND af.bar_ts = ae.bar_ts
           AND af.frame_variant = 'primary'
        WHERE ae.symbol = $1 AND ae.tf = $2 AND af.frame_id IS NULL
    """

    async def execute(self, pool: asyncpg.Pool) -> None:  # type: ignore[override]
        """Read alpha_events per (symbol, tf) partition, write pending alpha_frames rows."""
        manifest = CorpusManifest("alpha_frame_writer", CorpusManifest.DEFAULT_MANIFEST_DIR)
        try:
            await self._execute_inner(pool, manifest)
        except Exception as error:
            manifest.add_error(str(error))
            try:
                manifest.write()
            except Exception:
                pass
            raise

    async def _execute_inner(self, pool: asyncpg.Pool, manifest: CorpusManifest) -> None:
        async with pool.acquire() as conn:
            cfg = await _load_apr(conn, extra_like_patterns=["infra.alpha_frame_writer.%"])
            frame_config = FrameConfig.from_apr(cfg)
            chunk_size = _cfg(cfg, "infra.alpha_frame_writer.chunk_size", 50_000)

            partitions = await conn.fetch(
                "SELECT DISTINCT symbol, tf FROM alpha_events ORDER BY symbol, tf"
            )

        # Wire structural_confluence's module-level config singleton once per run, not once
        # per partition (Task 2 — "inject the config service once at writer init"). Only
        # needed when geometry_source == "structural"; harmless no-op cache build otherwise.
        if frame_config.geometry_source == "structural":
            set_config_service(_build_structural_config_service(cfg))

        # Pinned once per invocation (mirrors ensemble_ic_engine.py's run_ts pattern, A2) and
        # stamped onto every frame this run writes.
        corpus_run_id = datetime.now(UTC).isoformat()

        self.logger.info(
            "alpha_frame_writer.config_loaded",
            stop_atr_mult=frame_config.stop_atr_mult,
            target_r_multiple=frame_config.target_r_multiple,
            atr_period=frame_config.atr_period,
            chunk_size=chunk_size,
            n_partitions=len(partitions),
            backfill=self.backfill,
            corpus_run_id=corpus_run_id,
        )
        manifest.set_inputs(
            backfill=self.backfill,
            corpus_run_id=corpus_run_id,
            n_partitions=len(partitions),
        )

        total_written = 0
        rows_by_tf: dict[str, int] = {}

        for part in partitions:
            symbol = part["symbol"]
            tf = part["tf"]
            written = await self._process_partition(
                pool, symbol, tf, cfg, frame_config, corpus_run_id, chunk_size
            )
            total_written += written
            rows_by_tf[tf] = rows_by_tf.get(tf, 0) + written
            if written:
                self.logger.info(
                    "alpha_frame_writer.partition_complete",
                    symbol=symbol,
                    tf=tf,
                    written=written,
                )

        self.logger.info(
            "alpha_frame_writer.complete",
            total_written=total_written,
            rows_by_tf=rows_by_tf,
        )

        manifest.add_output(
            table_name="alpha_frames",
            rows_total=total_written,
            rows_by_tf=rows_by_tf,
        )
        manifest.mark_success()
        manifest_path = manifest.write()
        self.logger.info("alpha_frame_writer.manifest_written", path=str(manifest_path))

    async def _process_partition(
        self,
        pool: asyncpg.Pool,
        symbol: str,
        tf: str,
        cfg: dict[str, Any],
        frame_config: FrameConfig,
        corpus_run_id: str,
        chunk_size: int,
    ) -> int:
        """Anti-join + chunked flush for one (symbol, tf) partition.

        Each partition's read+flush is its own short transaction rather than one giant
        streaming transaction over all (symbol, tf) partitions (review L1).
        """
        written = 0
        chunk: list[tuple] = []
        # IN-01/WR-02: distinguish "cost known to be zero" / "hold key legitimately seeded"
        # from "data never populated" / "un-seeded regime label" without a per-row log call —
        # this loop runs over the full alpha_events backlog on --backfill (potentially millions
        # of rows), so visibility is an aggregate count per partition, not a log line per row.
        missing_cost_hurdle_count = 0
        missing_hold_keys: set[str] = set()
        missing_stop_keys: set[str] = set()
        missing_target_keys: set[str] = set()
        degenerate_geometry_skip_count = 0

        # structural geometry_source only (Task 2): one bulk fetch per partition, never a
        # per-row round trip. Empty dicts (harmless .get() misses -> scalar-seed fallback in
        # _resolve_row_geometry) for every other geometry_source.
        market_data_by_bar_ts: dict[Any, tuple[float, float]] = {}
        features_by_bar_ts: dict[Any, dict[str, Any]] = {}
        if frame_config.geometry_source == "structural":
            async with pool.acquire() as sconn:
                market_data_by_bar_ts = await _fetch_structural_market_data(
                    sconn, symbol, tf, frame_config.atr_period
                )
                features_by_bar_ts = await _fetch_structural_features(sconn, symbol, tf)

        async with pool.acquire() as conn:
            async with conn.transaction():
                async for row in conn.cursor(self._PENDING_SQL, symbol, tf, prefetch=10000):
                    regime = row["regime"]
                    direction = row["direction"]
                    alpha_score = float(row["alpha_score"])
                    if row["cost_hurdle"] is None:
                        missing_cost_hurdle_count += 1
                    cost_r = float(row["cost_hurdle"]) if row["cost_hurdle"] is not None else 0.0

                    bar_ts = row["bar_ts"]
                    entry_price, atr = market_data_by_bar_ts.get(bar_ts, (None, None))
                    features = features_by_bar_ts.get(bar_ts)

                    geometry = _resolve_row_geometry(
                        frame_config.geometry_source,
                        cfg,
                        regime,
                        tf,
                        frame_config,
                        missing_stop_keys,
                        missing_target_keys,
                        features=features,
                        direction=direction,
                        entry_price=entry_price,
                        atr=atr,
                    )
                    if geometry is None:
                        # structural mode's degenerate-stop ValueError-skip contract
                        # (compute_frame_geometry, todo 162) — never fabricate a frame the
                        # data can't support. Counted, reported once below (never per row).
                        degenerate_geometry_skip_count += 1
                        continue
                    stop_atr_mult, target_r_multiple = geometry

                    gross_expected_r, net_expected_r = compute_expected_r_snapshot(
                        alpha_score, target_r_multiple, cost_r
                    )

                    hold_key = f"alpha.frame.hold_max_bars.{regime}.{tf}"
                    if hold_key not in cfg:
                        missing_hold_keys.add(hold_key)
                    max_hold_bars = int(_cfg(cfg, hold_key, _DEFAULT_HOLD_MAX_BARS))

                    frame_id = BaseBatch.content_key(row["event_id"], str(row["bar_ts"]), "primary")  # fmt: skip

                    chunk.append(
                        (
                            frame_id,
                            row["event_id"],
                            row["bar_ts"],
                            symbol,
                            tf,
                            regime,
                            direction,
                            "primary",
                            alpha_score,
                            row["alpha_ci_lower"],
                            row["alpha_ci_upper"],
                            gross_expected_r,
                            cost_r,
                            net_expected_r,
                            max_hold_bars,
                            stop_atr_mult,
                            target_r_multiple,
                            "open",
                            corpus_run_id,
                            row["weight_version"],
                            row["is_shadow"],
                        )
                    )

                    if len(chunk) >= chunk_size:
                        async with pool.acquire() as wconn:
                            await wconn.executemany(self._INSERT_SQL, chunk)
                        written += len(chunk)
                        chunk.clear()

                if chunk:
                    async with pool.acquire() as wconn:
                        await wconn.executemany(self._INSERT_SQL, chunk)
                    written += len(chunk)
                    chunk.clear()

        if missing_cost_hurdle_count:
            self.logger.warning(
                "alpha_frame_writer.cost_hurdle_missing",
                symbol=symbol,
                tf=tf,
                count=missing_cost_hurdle_count,
            )
        if missing_hold_keys:
            self.logger.warning(
                "alpha_frame_writer.hold_max_bars_key_missing",
                symbol=symbol,
                tf=tf,
                hold_keys=sorted(missing_hold_keys),
            )
        if missing_stop_keys:
            self.logger.warning(
                "alpha_frame_writer.stop_atr_mult_key_missing",
                symbol=symbol,
                tf=tf,
                stop_keys=sorted(missing_stop_keys),
            )
        if missing_target_keys:
            self.logger.warning(
                "alpha_frame_writer.target_r_multiple_key_missing",
                symbol=symbol,
                tf=tf,
                target_keys=sorted(missing_target_keys),
            )
        if degenerate_geometry_skip_count:
            self.logger.warning(
                "alpha_frame_writer.degenerate_geometry_skip",
                symbol=symbol,
                tf=tf,
                count=degenerate_geometry_skip_count,
            )

        return written


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Alpha Frame Writer — alpha_events -> alpha_frames (FRAME-01)"
    )
    parser.add_argument(
        "--backfill",
        action="store_true",
        help=(
            "Process the full existing alpha_events backlog in chunks (D-05). Uses the same "
            "anti-join query as nightly-incremental — the target table is the checkpoint."
        ),
    )
    args = parser.parse_args()

    try:
        init_otel_providers("indicagent-alpha-frame-writer")
    except OTelInitError as error:
        _logger.warning("alpha_frame_writer.otel_init_failed", error=str(error))

    settings = Settings()
    db_dsn = settings.database_url.replace("postgresql+asyncpg://", "postgresql://")
    asyncio.run(AlphaFrameWriter(db_dsn=db_dsn, backfill=args.backfill).run())
