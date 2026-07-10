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
from src.config.settings import Settings
from src.core.agent.base_batch import BaseBatch
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
) -> tuple[float, float, float]:
    """ATR-only frame geometry (review H2 — the sole target path; the support/resistance
    distance columns are 100% NULL across the corpus, so no conditional branch on them).

    `atr` is a caller-supplied price-unit value — this function never reads a table.

    Returns (stop_price, target_price, r_multiple).
    """
    if direction == "long":
        stop_price = entry_price - stop_atr_mult * atr
        stop_distance = entry_price - stop_price
        target_price = entry_price + target_r_multiple * stop_distance
        r_multiple = (target_price - entry_price) / (entry_price - stop_price)
    elif direction == "short":
        stop_price = entry_price + stop_atr_mult * atr
        stop_distance = stop_price - entry_price
        target_price = entry_price - target_r_multiple * stop_distance
        r_multiple = (entry_price - target_price) / (stop_price - entry_price)
    else:
        raise ValueError(f"compute_frame_geometry: unknown direction {direction!r}")
    return stop_price, target_price, r_multiple


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


@dataclass(frozen=True)
class FrameConfig:
    """APR-bound frame geometry parameters (FRAME-01). Frozen for pickling/dispatch safety,
    mirroring EnsembleICConfig's binding pattern (test_ensemble_ic_config.py style)."""

    stop_atr_mult: float
    target_r_multiple: float
    atr_period: int

    @classmethod
    def from_apr(cls, cfg_dict: dict[str, Any]) -> FrameConfig:
        return cls(
            stop_atr_mult=_cfg(cfg_dict, "alpha.frame.stop_atr_mult", 1.5),
            target_r_multiple=_cfg(cfg_dict, "alpha.frame.target_r_multiple", 2.0),
            atr_period=_cfg(cfg_dict, "alpha.frame.atr_period", 14),
        )


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
            max_hold_bars, stop_atr_mult, status,
            corpus_run_id, weight_epoch
        ) VALUES (
            $1, $2, $3, $4, $5, $6, $7, $8,
            $9, $10, $11,
            $12, $13, $14,
            $15, $16, $17,
            $18, $19
        )
        ON CONFLICT (event_id, bar_ts, frame_variant) DO NOTHING
    """

    # Pattern 4: anti-join against alpha_frames itself — the target table IS the
    # checkpoint. The same query serves nightly-incremental and --backfill.
    _PENDING_SQL = """
        SELECT ae.event_id, ae.bar_ts, ae.symbol, ae.tf, ae.regime, ae.direction,
               ae.alpha_score, ae.alpha_ci_lower, ae.alpha_ci_upper, ae.cost_hurdle,
               ae.weight_version
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

        async with pool.acquire() as conn:
            async with conn.transaction():
                async for row in conn.cursor(self._PENDING_SQL, symbol, tf, prefetch=10000):
                    regime = row["regime"]
                    direction = row["direction"]
                    alpha_score = float(row["alpha_score"])
                    cost_r = float(row["cost_hurdle"]) if row["cost_hurdle"] is not None else 0.0

                    gross_expected_r, net_expected_r = compute_expected_r_snapshot(
                        alpha_score, frame_config.target_r_multiple, cost_r
                    )

                    hold_key = f"alpha.frame.hold_max_bars.{regime}.{tf}"
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
                            frame_config.stop_atr_mult,
                            "open",
                            corpus_run_id,
                            row["weight_version"],
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
