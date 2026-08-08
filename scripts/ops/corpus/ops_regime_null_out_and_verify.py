#!/usr/bin/env python3
"""ops_regime_null_out_and_verify.py -- the data-integrity tool Phase 171 cannot run without.

RESEARCH.md's Critical Finding proved that running `regime_writer.py --refit` with walk-forward
enabled against the CURRENT corpus silently blends two labeling methods in one column: most of
`feature_vectors` is already labeled by the retired full-history-fit method, `_discover_symbols()`
skips fully-labeled symbols entirely, `_bulk_update_by_key` leaves untouched rows unchanged, and
the walk-forward path deliberately writes nothing for warmup-prefix bars or degenerate segments.
The intersection is stale pre-fix values persisting indefinitely under a column nobody audits --
the same failure shape as the already-closed todo 205 incident, and precisely the "silent wrong
answers are worse than loud crashes" case CLAUDE.md forbids.

This script is the enforcement mechanism for the walk-forward path's own unenforced precondition
(it "must only run against rows that do not already carry a DIFFERENT method's regime value").
Three modes, one checked-in command:

  --mode null-out             NULL out the regime-writer-owned columns for an explicit (symbol,
                               tf) scope, one cell at a time, proving its own post-condition
                               (zero non-NULL owned columns remain) before advancing. (This task.)
  --mode verify-post-null     Re-run that same post-condition check without issuing any UPDATE.
                               (Task 2.)
  --mode verify-post-relabel  After a walk-forward relabel pass, prove the warmup prefix is
                               genuinely unlabeled and write a machine-readable provenance
                               report. (Task 2.)

Safety, matching this project's write-path discipline (CLAUDE.md's worker-pool rule, DAG
Invariant 3): a single serial psycopg connection in the main process, never a worker pool. Never
runs against an implicit all-symbols scope -- `--symbols` is required, because
`_discover_symbols()` in regime_writer.py deliberately skips already-labeled symbols, which is
exactly the population this script exists to touch.

Usage:
    python scripts/ops/corpus/ops_regime_null_out_and_verify.py --symbols SPY QQQ --tf 1h 1d
    python scripts/ops/corpus/ops_regime_null_out_and_verify.py --symbols SPY --tf 1d --dry-run
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

import psycopg
import structlog

from src.config.settings import Settings
from src.core.service_utils import setup_service_logging
from src.intelligence.features.feature_vector_persistence import (
    REGIME_WRITER_OWNED_COLUMN_NAMES,
)
from src.observability.metrics import JOB_COMPLETED_TOTAL, flush_and_shutdown_metrics
from src.observability.otel import OTelInitError, init_otel_providers

setup_service_logging("logs/regime_null_out_and_verify.log")
_logger = structlog.get_logger(__name__)

_JOB = "regime-null-out-and-verify"

_DEFAULT_TFS: tuple[str, ...] = ("5m", "15m", "1h", "1d")
_DEFAULT_MANIFEST_PATH = "cache/regime_null_out_manifest.json"

_MODE_NULL_OUT = "null-out"
_MODE_VERIFY_POST_NULL = "verify-post-null"
_MODE_VERIFY_POST_RELABEL = "verify-post-relabel"
_MODES = (_MODE_NULL_OUT, _MODE_VERIFY_POST_NULL, _MODE_VERIFY_POST_RELABEL)

_STATUS_IN_PROGRESS = "in_progress"
_STATUS_VERIFIED_NULL = "verified_null"
_STATUS_FAILED = "failed"

# Built from the imported ownership tuple -- never hand-typed, per this project's own
# already-documented column-list-drift incident (feature_vector_persistence.py's docstring).
_SET_NULL_CLAUSE_SQL = ",\n    ".join(f"{c} = NULL" for c in REGIME_WRITER_OWNED_COLUMN_NAMES)
_NULL_OUT_SQL = (
    f"UPDATE feature_vectors SET\n    {_SET_NULL_CLAUSE_SQL}\nWHERE symbol = %s AND tf = %s"
)

_ANY_OWNED_NONNULL_SQL = (
    "SELECT count(*) FROM feature_vectors WHERE symbol = %s AND tf = %s AND ("
    + " OR ".join(f"{c} IS NOT NULL" for c in REGIME_WRITER_OWNED_COLUMN_NAMES)
    + ")"
)

_PRE_NULL_LABELED_SQL = (
    "SELECT count(*) FROM feature_vectors WHERE symbol = %s AND tf = %s AND regime IS NOT NULL"
)

_CHUNK_COMPRESSION_SQL = (
    "SELECT count(*) FILTER (WHERE is_compressed), count(*) "
    "FROM timescaledb_information.chunks WHERE hypertable_name = %s"
)


def _manifest_key(symbol: str, tf: str) -> str:
    return f"{symbol}:{tf}"


def _load_manifest(path: Path) -> dict[str, dict[str, Any]]:
    """Read the resumability manifest. A missing or corrupt file is treated as empty --
    every cell is redone, never silently treated as a crash the caller must recover from."""
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError) as error:
        _logger.warning("regime_null_out.manifest_unreadable_treating_as_empty", error=str(error))
        return {}


def _flush_manifest(path: Path, manifest: dict[str, dict[str, Any]]) -> None:
    """Atomic tmp+rename write -- state_manager.py's checkpoint idiom, copied verbatim so a
    kill mid-write never leaves a truncated manifest that would defeat resumability."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(manifest, indent=2, sort_keys=True))
    tmp.rename(path)


def _log_compression_state(conn: Any) -> None:
    """Log chunk compression state once before the first UPDATE, per
    performance-investigation-sop.md -- a bulk UPDATE against compressed chunks decompresses
    and recompresses, so elapsed time should be interpreted afterward, not theorized about."""
    with conn.cursor() as cur:
        cur.execute(_CHUNK_COMPRESSION_SQL, ("feature_vectors",))
        n_compressed, n_total = cur.fetchone()
    _logger.info(
        "regime_null_out.chunk_compression_state",
        hypertable="feature_vectors",
        n_compressed=n_compressed,
        n_total=n_total,
    )


def _pre_null_labeled_count(conn: Any, symbol: str, tf: str) -> int:
    with conn.cursor() as cur:
        cur.execute(_PRE_NULL_LABELED_SQL, (symbol, tf))
        (count,) = cur.fetchone()
    return int(count)


def _issue_null_out_update(conn: Any, symbol: str, tf: str) -> int:
    with conn.cursor() as cur:
        cur.execute(_NULL_OUT_SQL, (symbol, tf))
        rows_affected = cur.rowcount
    return int(rows_affected)


def _count_any_owned_nonnull(conn: Any, symbol: str, tf: str) -> int:
    with conn.cursor() as cur:
        cur.execute(_ANY_OWNED_NONNULL_SQL, (symbol, tf))
        (count,) = cur.fetchone()
    return int(count)


def _null_out_cell(conn: Any, symbol: str, tf: str) -> dict[str, Any]:
    """NULL out one (symbol, tf) cell's 8 owned columns and prove the post-condition.

    Order: pre-count -> UPDATE -> commit -> verify SELECT. A non-zero post-condition count
    marks the cell failed but does NOT raise -- one bad cell must not strand the rest of scope.
    """
    t0 = time.monotonic()
    pre_null_labeled = _pre_null_labeled_count(conn, symbol, tf)
    rows_affected = _issue_null_out_update(conn, symbol, tf)
    conn.commit()
    remaining_nonnull = _count_any_owned_nonnull(conn, symbol, tf)
    elapsed_s = round(time.monotonic() - t0, 3)

    verified = remaining_nonnull == 0
    entry = {
        "status": _STATUS_VERIFIED_NULL if verified else _STATUS_FAILED,
        "pre_null_labeled": pre_null_labeled,
        "rows_affected": rows_affected,
        "elapsed_s": elapsed_s,
    }
    if not verified:
        entry["remaining_nonnull"] = remaining_nonnull

    _logger.info(
        "regime_null_out.cell_done" if verified else "regime_null_out.cell_failed_postcondition",
        symbol=symbol,
        tf=tf,
        rows_affected=rows_affected,
        pre_null_labeled=pre_null_labeled,
        elapsed_s=elapsed_s,
        verified=verified,
    )
    return entry


def _run_null_out(
    conn: Any,
    symbols: list[str],
    tfs: list[str],
    manifest_path: Path,
    dry_run: bool,
) -> int:
    manifest = _load_manifest(manifest_path)
    n_failed = 0
    n_dry_run_updates = 0

    if not dry_run:
        _log_compression_state(conn)
    else:
        print("DRY-RUN MODE -- zero UPDATE statements will be issued.")  # noqa: T201

    for symbol in symbols:
        for tf in tfs:
            key = _manifest_key(symbol, tf)
            existing = manifest.get(key)
            if existing and existing.get("status") == _STATUS_VERIFIED_NULL:
                _logger.info("regime_null_out.cell_skipped_already_verified", symbol=symbol, tf=tf)
                continue

            if dry_run:
                would_null = _pre_null_labeled_count(conn, symbol, tf)
                print(  # noqa: T201
                    f"[DRY-RUN] {symbol}/{tf}: would NULL {would_null} labeled row(s) "
                    "across the 8 regime-writer-owned columns; 0 UPDATE statements issued"
                )
                _logger.info(
                    "regime_null_out.dry_run_plan",
                    symbol=symbol,
                    tf=tf,
                    would_null_rows=would_null,
                )
                continue

            manifest[key] = {"status": _STATUS_IN_PROGRESS}
            _flush_manifest(manifest_path, manifest)

            entry = _null_out_cell(conn, symbol, tf)
            manifest[key] = entry
            _flush_manifest(manifest_path, manifest)

            if entry["status"] == _STATUS_FAILED:
                n_failed += 1

    if dry_run:
        print(  # noqa: T201
            f"\nDRY-RUN SUMMARY: {len(symbols) * len(tfs)} cell(s) planned, "
            f"{n_dry_run_updates} UPDATE statement(s) issued."
        )

    _logger.info(
        "regime_null_out.run_complete",
        mode=_MODE_NULL_OUT,
        n_cells=len(symbols) * len(tfs),
        n_failed=n_failed,
        dry_run=dry_run,
    )
    return n_failed


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--symbols",
        nargs="+",
        required=True,
        help=(
            "Explicit symbol scope -- REQUIRED, no all-symbols default. "
            "regime_writer.py's _discover_symbols() skips fully-labeled symbols, which is "
            "exactly the set this script must be able to touch, so it must never be used to "
            "derive this script's scope."
        ),
    )
    parser.add_argument(
        "--tf",
        nargs="+",
        default=list(_DEFAULT_TFS),
        choices=list(_DEFAULT_TFS),
        help=f"Timeframes to scope to. Default: {' '.join(_DEFAULT_TFS)}.",
    )
    parser.add_argument(
        "--manifest",
        default=_DEFAULT_MANIFEST_PATH,
        help=f"Resumability manifest path. Default: {_DEFAULT_MANIFEST_PATH}.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        help="Print the per-cell plan and row counts that would be nulled. Issues no UPDATE.",
    )
    parser.add_argument(
        "--mode",
        choices=list(_MODES),
        default=_MODE_NULL_OUT,
        help=f"Operation to run. Default: {_MODE_NULL_OUT}.",
    )
    return parser.parse_args(argv)


def _connect(settings: Settings) -> Any:
    dsn = settings.database_url.replace("postgresql+asyncpg://", "postgresql://")
    conn = psycopg.connect(dsn)
    conn.autocommit = False
    return conn


def main() -> None:
    args = _parse_args()

    try:
        init_otel_providers(service_name=_JOB)
    except OTelInitError as error:
        _logger.warning("regime_null_out.otel_init_failed", error=str(error))

    settings = Settings()
    conn = _connect(settings)

    status = "success"
    n_failed = 0
    try:
        if args.mode == _MODE_NULL_OUT:
            n_failed = _run_null_out(conn, args.symbols, args.tf, Path(args.manifest), args.dry_run)
        elif args.mode in (_MODE_VERIFY_POST_NULL, _MODE_VERIFY_POST_RELABEL):
            # Task 2's work -- lands in the same argparse surface, same file, next commit.
            raise NotImplementedError(f"--mode {args.mode} lands in Plan 03 Task 2")
    except Exception as error:
        status = "failure"
        _logger.error("regime_null_out.fatal_error", error=str(error))
        raise
    finally:
        conn.close()
        JOB_COMPLETED_TOTAL.add(1, {"job": _JOB, "status": status})
        flush_and_shutdown_metrics()

    sys.exit(1 if n_failed > 0 else 0)


if __name__ == "__main__":
    main()
