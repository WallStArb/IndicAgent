"""Reads of market_data_ohlcv_tradeable for batch compute."""

from __future__ import annotations

from typing import Any

import numpy as np
import structlog

from src.config.config_service import ConfigService

_logger = structlog.get_logger()


TRADEABLE_SERIES_BLOCK_ROWS_KEY = "infra.tradeable_series.fetch_block_rows"
_TRADEABLE_SERIES_BLOCK_ROWS_DEFAULT = 10000  # migration 576 seed


def load_tradeable_series_block_rows(cfg: ConfigService) -> int:
    """Rows per server-cursor round trip for `fetch_tradeable_series` (APR, migration 576)."""
    return int(cfg.get_sync(TRADEABLE_SERIES_BLOCK_ROWS_KEY, _TRADEABLE_SERIES_BLOCK_ROWS_DEFAULT))


def fetch_tradeable_series(
    conn: Any, symbol: str, tf: str, block_rows: int, with_volume: bool = True
) -> dict[str, Any] | None:
    """Timestamps, closes and (with `with_volume`) volumes of one whole (symbol, tf) series from
    `market_data_ohlcv_tradeable`, or None (logging `batch_utils.no_tradeable_bars`) when there
    are none. No proven-start floor and no horizon: the regime screening and golden-capture
    tools read the full series (moved verbatim from the retired regime_writer, todo 590).

    `block_rows` is `load_tradeable_series_block_rows(cfg)`. Server-side cursors require no
    active transaction, so any open one is committed first.
    """
    timestamps: list = []
    closes: list = []
    volumes: list = []
    columns = "timestamp, close, volume" if with_volume else "timestamp, close"
    conn.commit()
    with conn.cursor("ohlcv_stream") as cur:
        cur.execute(
            f"SELECT {columns} "
            "FROM market_data_ohlcv_tradeable "
            "WHERE symbol = %s AND timeframe = %s "
            "ORDER BY timestamp ASC",
            (symbol, tf),
        )
        while True:
            batch = cur.fetchmany(block_rows)
            if not batch:
                break
            by_column = list(zip(*batch, strict=True))
            timestamps.extend(by_column[0])
            closes.extend(by_column[1])
            if with_volume:
                volumes.extend(by_column[2])
    if not timestamps:
        _logger.warning("batch_utils.no_tradeable_bars", symbol=symbol, tf=tf)
        return None
    return {
        "timestamps": timestamps,
        "close": np.array(closes, dtype=float),
        "volume": np.array(volumes, dtype=float) if with_volume else None,
    }
