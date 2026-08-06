#!/usr/bin/env python3
"""Surgical CTF-column recompute at tf=15m -- todo 243's corrected-join fix.

`_rekey_ctf_series_to_actual_close()` (shipped 2026-08-03, `services/backfill_feature_factory.py`)
fixed a real lookahead bug in how `ctf_momentum`/`ctf_vwap_align`/`ctf_regime_align` are joined
onto lower-timeframe bars -- the batch join previously selected a still-forming HTF bar for LTF
rows inside its still-open window. The fix is shipped and tested, but `feature_vectors` itself
was never recomputed with it: every existing 15m row still carries the pre-fix (leaked) CTF
values. This script closes that gap for exactly the 3 affected columns, at tf=15m only.

**Do NOT use `backfill_feature_factory.py --refresh` for this.** That recomputes the entire
~292-column feature row via `ON CONFLICT DO UPDATE` at whatever the current git HEAD computes for
every feature, not just CTF -- it would silently conflate the join fix with every other
feature-compute change made since these rows were last written, with no way to attribute any
downstream IC delta to the join fix specifically. This script imports and calls
`_build_ctf_series`/`_rekey_ctf_series_to_actual_close` UNMODIFIED from
`backfill_feature_factory.py` and writes ONLY the 3 CTF columns via a targeted UPDATE -- every
other column on every touched row is left byte-identical.

Design (see docs/plans/2026-08-05-ctf-join-fix-scoped-recompute-and-gate1-reverify.md for the
full scoped-execution plan this script implements Steps 2-5 of):

1. Default symbol scope: every symbol with existing tf=15m `feature_vectors` rows
   (`SELECT DISTINCT symbol FROM feature_vectors WHERE tf='15m'`) -- data-driven, not a
   hardcoded/`instruments`-table-derived list, so it always matches the corpus that actually
   exists today regardless of how many new symbols have since been registered but not yet
   backfilled.
2. Per symbol: fetch the HTF (1h) bar history the same way `_compute_symbol_tf` does
   (`_fetch_bars_from_db`), build the corrected CTF series
   (`_rekey_ctf_series_to_actual_close(_build_ctf_series(htf_bars, config), "15m", "1h")`), then
   join it onto every existing 15m `feature_vectors` row for that symbol using the SAME
   `bisect.bisect_right(ctf_ts_list, bar_ts) - 1` logic `FeatureFactory.compute_batch` uses
   (`src/intelligence/feature_factory.py:7621`) -- including its `_idx < 0` fallback (all three
   CTF columns default to `0.0`, never `None`, for a bar with no eligible HTF cell yet).
3. Only rows whose corrected value actually differs from the stored value (tolerance 1e-9) are
   written -- an UPDATE that would set a column to its current value has no visible effect, so
   skipping it changes nothing about the end state while giving an honest "N rows actually
   touched" count for the audit trail.

Safety (non-negotiable, matches `ops_known_corrupt_print_cleanup.py`'s own convention): defaults
to dry-run behavior (report only, zero DB writes). Requires the explicit `--apply` flag to write.
This script must never be invoked with `--apply` without first reviewing the dry-run report --
a targeted 3-column UPDATE across up to ~8.8M rows is still a real corpus mutation.

Usage:
    python scripts/ops/corpus/ops_ctf_columns_recompute_15m.py --symbols SPY   # timed pilot, dry-run
    python scripts/ops/corpus/ops_ctf_columns_recompute_15m.py                 # full scope, dry-run
    python scripts/ops/corpus/ops_ctf_columns_recompute_15m.py --apply         # human-reviewed only
"""

from __future__ import annotations

import argparse
import bisect
import sys
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

import structlog

from services._batch_utils import bulk_update_by_key, load_config_service_sync
from services.backfill_feature_factory import (
    _build_ctf_series,
    _build_feature_factory_config,
    _connect_db,
    _fetch_bars_from_db,
    _rekey_ctf_series_to_actual_close,
)
from src.config.settings import Settings
from src.core.service_utils import setup_service_logging
from src.intelligence.feature_cache import _CTF_HIGHER_TF
from src.observability.metrics import JOB_COMPLETED_TOTAL, flush_and_shutdown_metrics
from src.observability.otel import OTelInitError, init_otel_providers

setup_service_logging("logs/ctf_columns_recompute_15m.log")
_logger = structlog.get_logger(__name__)

_JOB = "ctf-columns-recompute-15m"
_TF = "15m"
_CHANGED_TOLERANCE = 1e-9

_FETCH_ROWS_SQL = """
    SELECT bar_ts, ctf_momentum, ctf_vwap_align, ctf_regime_align
    FROM feature_vectors
    WHERE symbol = %s AND tf = %s
    ORDER BY bar_ts
"""

_SYMBOLS_WITH_15M_ROWS_SQL = """
    SELECT DISTINCT symbol FROM feature_vectors WHERE tf = %s ORDER BY symbol
"""


def _value_changed(old: float | None, new: float, tolerance: float) -> bool:
    return old is None or abs(new - old) > tolerance


def _recompute_symbol(conn: Any, symbol: str, config: Any, apply: bool) -> dict[str, Any]:
    """Recompute corrected CTF values for one symbol's tf=15m rows, write only the changed
    ones (unless `apply` is False, in which case nothing is written). Returns a stats dict --
    never logs per row (CLAUDE.md: accumulate a counter, report once per partition)."""
    htf_tf = _CTF_HIGHER_TF.get(_TF)
    if not htf_tf:
        raise RuntimeError(f"No HTF mapping for tf={_TF!r} in _CTF_HIGHER_TF")

    htf_bars = _fetch_bars_from_db(conn, symbol, htf_tf)
    if not htf_bars:
        _logger.warning("ctf_recompute.no_htf_bars", symbol=symbol, htf_tf=htf_tf)
        return {"symbol": symbol, "rows_examined": 0, "rows_changed": 0, "rows_written": 0}

    ctf_by_ts = _rekey_ctf_series_to_actual_close(_build_ctf_series(htf_bars, config), _TF, htf_tf)
    ctf_ts_list = sorted(ctf_by_ts.keys())

    with conn.cursor() as cur:
        cur.execute(_FETCH_ROWS_SQL, (symbol, _TF))
        rows = cur.fetchall()

    # Mirrors src/intelligence/feature_factory.py's FeatureFactory.compute_batch CTF join
    # (currently ~line 7621) exactly, including its idx<0 fallback below -- that logic isn't
    # exported as a reusable function (it's inline in a large per-bar production loop), so this
    # is a deliberate narrow duplication, not an oversight. If that join logic ever changes,
    # this copy must be updated to match.
    updates: list[tuple[float, float, float, str, str, Any]] = []
    for bar_ts, old_mom, old_vwap, old_regime in rows:
        idx = bisect.bisect_right(ctf_ts_list, bar_ts) - 1
        if idx >= 0:
            ctf = ctf_by_ts[ctf_ts_list[idx]]
            new_mom, new_vwap, new_regime = (
                ctf.ctf_momentum,
                ctf.ctf_vwap_align,
                ctf.ctf_regime_align,
            )
        else:
            new_mom = new_vwap = new_regime = 0.0

        changed = (
            _value_changed(old_mom, new_mom, _CHANGED_TOLERANCE)
            or _value_changed(old_vwap, new_vwap, _CHANGED_TOLERANCE)
            or _value_changed(old_regime, new_regime, _CHANGED_TOLERANCE)
        )
        if changed:
            updates.append((new_mom, new_vwap, new_regime, symbol, _TF, bar_ts))

    rows_written = 0
    if apply and updates:
        # Bulk COPY-into-temp-table + single JOIN-UPDATE, not executemany() -- the prior
        # per-row executemany() sent one round-trip per row (confirmed via pg_stat_activity
        # during the 2026-08-05/06 --apply attempt: 8.28M individual single-row UPDATEs,
        # 10+ hours and still not done). Same helper regime_writer.py already uses for its
        # own per-symbol feature_vectors write.
        bulk_update_by_key(
            conn,
            table="feature_vectors",
            temp_table="_ctf_columns_recompute_staging",
            key_cols=["symbol", "tf", "bar_ts"],
            set_cols=["ctf_momentum", "ctf_vwap_align", "ctf_regime_align"],
            col_types={
                "ctf_momentum": "double precision",
                "ctf_vwap_align": "double precision",
                "ctf_regime_align": "double precision",
                "symbol": "text",
                "tf": "text",
                "bar_ts": "timestamptz",
            },
            rows=updates,
        )
        conn.commit()
        rows_written = len(updates)

    _logger.info(
        "ctf_recompute.symbol_done",
        symbol=symbol,
        rows_examined=len(rows),
        rows_changed=len(updates),
        rows_written=rows_written,
        apply=apply,
    )
    return {
        "symbol": symbol,
        "rows_examined": len(rows),
        "rows_changed": len(updates),
        "rows_written": rows_written,
    }


def _resolve_symbols(conn: Any, requested: list[str] | None) -> list[str]:
    if requested:
        return requested
    with conn.cursor() as cur:
        cur.execute(_SYMBOLS_WITH_15M_ROWS_SQL, (_TF,))
        return [r[0] for r in cur.fetchall()]


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--symbols",
        nargs="*",
        default=None,
        help="Restrict to these symbols. Default: every symbol with existing tf=15m rows.",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        default=False,
        help="Write the corrected CTF columns. DEFAULT IS DRY-RUN (report only, zero DB "
        "writes). A human must review the dry-run summary before ever passing this flag.",
    )
    args = parser.parse_args()

    try:
        init_otel_providers(service_name=_JOB)
    except OTelInitError as error:
        _logger.warning("ctf_recompute.otel_init_failed", error=str(error))

    status = "success"
    try:
        settings = Settings()
        conn = _connect_db(settings)
        conn.autocommit = False  # transaction-controlled writes, one commit per symbol
        try:
            cfg = load_config_service_sync(conn)
            config = _build_feature_factory_config(cfg)
            symbols = _resolve_symbols(conn, args.symbols)

            _logger.info("ctf_recompute.start", n_symbols=len(symbols), apply=args.apply)

            total_examined = 0
            total_changed = 0
            total_written = 0
            start = time.monotonic()
            for symbol in symbols:
                stats = _recompute_symbol(conn, symbol, config, args.apply)
                total_examined += stats["rows_examined"]
                total_changed += stats["rows_changed"]
                total_written += stats["rows_written"]
            elapsed = time.monotonic() - start

            _logger.info(
                "ctf_recompute.done",
                n_symbols=len(symbols),
                total_examined=total_examined,
                total_changed=total_changed,
                total_written=total_written,
                elapsed_seconds=round(elapsed, 2),
                apply=args.apply,
            )
            print(  # noqa: T201
                f"\n{'APPLIED' if args.apply else 'DRY-RUN'}: {len(symbols)} symbol(s), "
                f"{total_examined} row(s) examined, {total_changed} row(s) would change"
                f"{' (written)' if args.apply else ' (not written -- pass --apply to write)'}, "
                f"{elapsed:.1f}s elapsed."
            )
        finally:
            conn.close()
    except Exception as error:
        status = "failure"
        _logger.error("ctf_recompute.fatal_error", error=str(error))
        raise
    finally:
        JOB_COMPLETED_TOTAL.add(1, {"job": _JOB, "status": status})
        flush_and_shutdown_metrics()


if __name__ == "__main__":
    main()
