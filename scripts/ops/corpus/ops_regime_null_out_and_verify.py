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
                               (zero non-NULL owned columns remain) before advancing.
  --mode verify-post-null     Re-run that same post-condition check without issuing any UPDATE --
                               a read-only sanity re-check.
  --mode verify-post-relabel  After a walk-forward relabel pass, prove the warmup prefix is
                               genuinely unlabeled (no stale pre-fix value survived) and write a
                               machine-readable provenance report.

Phase 172 plan 05 generalizes all three modes to a `--column-family` argument
(`regime` | `regime_volatility`), so the same tool covers both the legacy trend-flavored
`regime` column family and the new volatility-only `regime_volatility` family without a second,
less-tested tool. `--column-family` defaults to `regime`; every command that omits the flag
produces byte-identical SQL and behavior to before this generalization. The two families never
share a manifest or provenance-report path -- a volatility run's `verified_null` manifest entries
must never be able to mask a legacy cell that was never touched, and vice versa.

Safety, matching this project's write-path discipline (CLAUDE.md's worker-pool rule, DAG
Invariant 3): a single serial psycopg connection in the main process, never a worker pool. Never
runs against an implicit all-symbols scope -- `--symbols` is required, because
`_discover_symbols()` in regime_writer.py deliberately skips already-labeled symbols, which is
exactly the population this script exists to touch. This applies identically to both column
families.

Usage:
    python scripts/ops/corpus/ops_regime_null_out_and_verify.py --symbols SPY QQQ --tf 1h 1d
    python scripts/ops/corpus/ops_regime_null_out_and_verify.py --symbols SPY --tf 1d --dry-run
    python scripts/ops/corpus/ops_regime_null_out_and_verify.py --symbols SPY --tf 1d \
        --mode verify-post-null
    python scripts/ops/corpus/ops_regime_null_out_and_verify.py --symbols SPY --tf 1d \
        --mode verify-post-relabel
    python scripts/ops/corpus/ops_regime_null_out_and_verify.py --symbols SPY --tf 1d \
        --column-family regime_volatility --mode verify-post-relabel
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

import psycopg
import structlog

from services.regime_writer import _WALK_FORWARD_DEFAULT_PARAMS
from src.config.settings import Settings
from src.core.service_utils import setup_service_logging
from src.intelligence.features.feature_vector_persistence import (
    REGIME_VOLATILITY_WRITER_OWNED_COLUMN_NAMES,
    REGIME_WRITER_OWNED_COLUMN_NAMES,
)
from src.observability.metrics import JOB_COMPLETED_TOTAL, flush_and_shutdown_metrics
from src.observability.otel import OTelInitError, init_otel_providers

setup_service_logging("logs/regime_null_out_and_verify.log")
_logger = structlog.get_logger(__name__)

_JOB = "regime-null-out-and-verify"

_DEFAULT_TFS: tuple[str, ...] = ("5m", "15m", "1h", "1d")
_DEFAULT_MANIFEST_PATH = "cache/regime_null_out_manifest.json"
_PROVENANCE_REPORT_PATH = Path("cache/regime_relabel_provenance_report.json")

_MODE_NULL_OUT = "null-out"
_MODE_VERIFY_POST_NULL = "verify-post-null"
_MODE_VERIFY_POST_RELABEL = "verify-post-relabel"
_MODES = (_MODE_NULL_OUT, _MODE_VERIFY_POST_NULL, _MODE_VERIFY_POST_RELABEL)

_STATUS_IN_PROGRESS = "in_progress"
_STATUS_VERIFIED_NULL = "verified_null"
_STATUS_FAILED = "failed"


# ---------------------------------------------------------------------------
# Column-family registry -- Phase 172 plan 05
# ---------------------------------------------------------------------------
#
# Both families' owned-column tuples are imported from feature_vector_persistence.py, never
# hand-typed here, per this project's own already-documented column-list-drift incident (see
# that module's docstring). A separate manifest path and provenance-report path per family is
# the point, not an implementation detail: a shared manifest would let a volatility run's
# verified_null entries mask a legacy cell that was never touched, and the reverse.


@dataclass(frozen=True)
class _ColumnFamily:
    name: str
    owned_columns: tuple[str, ...]
    label_column: str
    default_manifest_path: str
    default_provenance_report_path: Path


_FAMILY_REGIME = "regime"
_FAMILY_REGIME_VOLATILITY = "regime_volatility"
_DEFAULT_COLUMN_FAMILY = _FAMILY_REGIME

_COLUMN_FAMILIES: dict[str, _ColumnFamily] = {
    _FAMILY_REGIME: _ColumnFamily(
        name=_FAMILY_REGIME,
        owned_columns=REGIME_WRITER_OWNED_COLUMN_NAMES,
        label_column="regime",
        default_manifest_path=_DEFAULT_MANIFEST_PATH,
        default_provenance_report_path=_PROVENANCE_REPORT_PATH,
    ),
    _FAMILY_REGIME_VOLATILITY: _ColumnFamily(
        name=_FAMILY_REGIME_VOLATILITY,
        owned_columns=REGIME_VOLATILITY_WRITER_OWNED_COLUMN_NAMES,
        label_column="regime_volatility",
        default_manifest_path="cache/regime_volatility_null_out_manifest.json",
        default_provenance_report_path=Path(
            "cache/regime_volatility_relabel_provenance_report.json"
        ),
    ),
}

_DEFAULT_COLUMN_FAMILY_OBJ = _COLUMN_FAMILIES[_DEFAULT_COLUMN_FAMILY]

_VALID_LABEL_COLUMNS = frozenset(family.label_column for family in _COLUMN_FAMILIES.values())


def _validate_label_column(label_column: str) -> None:
    """Defense-in-depth: re-validate against the family mapping right before SQL
    interpolation, even though this script's only caller path (main(), via an
    argparse choices=-constrained flag) can never pass an untrusted value. Same
    pattern as regime_writer.py's _discover_symbols(label_column=) (plan 172-04)."""
    if label_column not in _VALID_LABEL_COLUMNS:
        raise ValueError(
            f"invalid label column {label_column!r}; must be one of {sorted(_VALID_LABEL_COLUMNS)}"
        )


# ---------------------------------------------------------------------------
# SQL builders -- pure functions of the owned-column tuple / label column, never a hand-typed
# column list. Column-agnostic queries (_ROWS_BEFORE_TS_SQL, _CONFIG_VALUE_SQL,
# _CHUNK_COMPRESSION_SQL) stay module-level constants, unchanged by this generalization.
# ---------------------------------------------------------------------------


def _build_set_null_clause_sql(owned_columns: tuple[str, ...]) -> str:
    return ",\n    ".join(f"{c} = NULL" for c in owned_columns)


def _build_null_out_sql(owned_columns: tuple[str, ...]) -> str:
    set_clause = _build_set_null_clause_sql(owned_columns)
    return f"UPDATE feature_vectors SET\n    {set_clause}\nWHERE symbol = %s AND tf = %s"


def _build_any_owned_nonnull_sql(owned_columns: tuple[str, ...]) -> str:
    return (
        "SELECT count(*) FROM feature_vectors WHERE symbol = %s AND tf = %s AND ("
        + " OR ".join(f"{c} IS NOT NULL" for c in owned_columns)
        + ")"
    )


def _build_pre_null_labeled_sql(label_column: str) -> str:
    _validate_label_column(label_column)
    return (
        f"SELECT count(*) FROM feature_vectors WHERE symbol = %s AND tf = %s "
        f"AND {label_column} IS NOT NULL"
    )


def _build_labeled_count_and_min_ts_sql(label_column: str) -> str:
    _validate_label_column(label_column)
    return (
        f"SELECT count(*) FILTER (WHERE {label_column} IS NOT NULL), "
        f"min(bar_ts) FILTER (WHERE {label_column} IS NOT NULL) "
        "FROM feature_vectors WHERE symbol = %s AND tf = %s"
    )


_ROWS_BEFORE_TS_SQL = (
    "SELECT count(*) FROM feature_vectors WHERE symbol = %s AND tf = %s AND bar_ts < %s"
)

_CONFIG_VALUE_SQL = "SELECT config_value FROM config_state WHERE config_key = %s"

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


def _pre_null_labeled_count(
    conn: Any, symbol: str, tf: str, family: _ColumnFamily = _DEFAULT_COLUMN_FAMILY_OBJ
) -> int:
    sql = _build_pre_null_labeled_sql(family.label_column)
    with conn.cursor() as cur:
        cur.execute(sql, (symbol, tf))
        (count,) = cur.fetchone()
    return int(count)


def _issue_null_out_update(
    conn: Any, symbol: str, tf: str, family: _ColumnFamily = _DEFAULT_COLUMN_FAMILY_OBJ
) -> int:
    sql = _build_null_out_sql(family.owned_columns)
    with conn.cursor() as cur:
        cur.execute(sql, (symbol, tf))
        rows_affected = cur.rowcount
    return int(rows_affected)


def _count_any_owned_nonnull(
    conn: Any, symbol: str, tf: str, family: _ColumnFamily = _DEFAULT_COLUMN_FAMILY_OBJ
) -> int:
    sql = _build_any_owned_nonnull_sql(family.owned_columns)
    with conn.cursor() as cur:
        cur.execute(sql, (symbol, tf))
        (count,) = cur.fetchone()
    return int(count)


def _null_out_cell(
    conn: Any, symbol: str, tf: str, family: _ColumnFamily = _DEFAULT_COLUMN_FAMILY_OBJ
) -> dict[str, Any]:
    """NULL out one (symbol, tf) cell's owned columns for `family` and prove the post-condition.

    Order: pre-count -> UPDATE -> commit -> verify SELECT. A non-zero post-condition count
    marks the cell failed but does NOT raise -- one bad cell must not strand the rest of scope.
    """
    t0 = time.monotonic()
    pre_null_labeled = _pre_null_labeled_count(conn, symbol, tf, family)
    rows_affected = _issue_null_out_update(conn, symbol, tf, family)
    conn.commit()
    remaining_nonnull = _count_any_owned_nonnull(conn, symbol, tf, family)
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
        column_family=family.name,
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
    family: _ColumnFamily = _DEFAULT_COLUMN_FAMILY_OBJ,
) -> int:
    manifest = _load_manifest(manifest_path)
    n_failed = 0

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
                would_null = _pre_null_labeled_count(conn, symbol, tf, family)
                print(  # noqa: T201
                    f"[DRY-RUN] {symbol}/{tf}: would NULL {would_null} labeled row(s) "
                    f"across the {len(family.owned_columns)} {family.name}-owned columns; "
                    "0 UPDATE statements issued"
                )
                _logger.info(
                    "regime_null_out.dry_run_plan",
                    symbol=symbol,
                    tf=tf,
                    column_family=family.name,
                    would_null_rows=would_null,
                )
                continue

            manifest[key] = {"status": _STATUS_IN_PROGRESS}
            _flush_manifest(manifest_path, manifest)

            entry = _null_out_cell(conn, symbol, tf, family)
            manifest[key] = entry
            _flush_manifest(manifest_path, manifest)

            if entry["status"] == _STATUS_FAILED:
                n_failed += 1

    if dry_run:
        print(  # noqa: T201
            f"\nDRY-RUN SUMMARY: {len(symbols) * len(tfs)} cell(s) planned, "
            "0 UPDATE statement(s) issued."
        )

    _logger.info(
        "regime_null_out.run_complete",
        mode=_MODE_NULL_OUT,
        column_family=family.name,
        n_cells=len(symbols) * len(tfs),
        n_failed=n_failed,
        dry_run=dry_run,
    )
    return n_failed


def _run_verify_post_null(
    conn: Any,
    symbols: list[str],
    tfs: list[str],
    family: _ColumnFamily = _DEFAULT_COLUMN_FAMILY_OBJ,
) -> int:
    n_failed = 0
    for symbol in symbols:
        for tf in tfs:
            remaining_nonnull = _count_any_owned_nonnull(conn, symbol, tf, family)
            passed = remaining_nonnull == 0
            if not passed:
                n_failed += 1
            _logger.info(
                "regime_null_out.verify_post_null_cell",
                symbol=symbol,
                tf=tf,
                column_family=family.name,
                remaining_nonnull=remaining_nonnull,
                passed=passed,
            )
    _logger.info(
        "regime_null_out.run_complete",
        mode=_MODE_VERIFY_POST_NULL,
        column_family=family.name,
        n_cells=len(symbols) * len(tfs),
        n_failed=n_failed,
    )
    return n_failed


def _load_initial_warmup_bars(conn: Any, tf: str) -> int:
    """Read alpha.hmm.walk_forward.initial_warmup_bars.<tf> straight from config_state --
    this is a read-only ops script, so a plain SELECT is sufficient and avoids pulling the
    async ConfigService into a synchronous script. Falls back to the module default, logging
    loudly, only when the key is genuinely missing. Shared unchanged across both column
    families -- both reuse the same per-tf walk-forward schedule keys (172-05's interfaces
    section), since the warmup-prefix floor is a property of the timeframe, not of which
    observation columns are fitted."""
    key = f"alpha.hmm.walk_forward.initial_warmup_bars.{tf}"
    with conn.cursor() as cur:
        cur.execute(_CONFIG_VALUE_SQL, (key,))
        row = cur.fetchone()
    if row is None or row[0] is None:
        fallback = _WALK_FORWARD_DEFAULT_PARAMS[tf][1]
        _logger.warning(
            "regime_null_out.warmup_bars_apr_fallback",
            tf=tf,
            config_key=key,
            fallback=fallback,
        )
        return fallback
    return int(row[0])


def _labeled_count_and_min_ts(
    conn: Any, symbol: str, tf: str, family: _ColumnFamily = _DEFAULT_COLUMN_FAMILY_OBJ
) -> tuple[int, datetime | None]:
    sql = _build_labeled_count_and_min_ts_sql(family.label_column)
    with conn.cursor() as cur:
        cur.execute(sql, (symbol, tf))
        labeled_rows, first_labeled_bar_ts = cur.fetchone()
    return int(labeled_rows), first_labeled_bar_ts


def _rows_before_ts(conn: Any, symbol: str, tf: str, ts: datetime) -> int:
    with conn.cursor() as cur:
        cur.execute(_ROWS_BEFORE_TS_SQL, (symbol, tf, ts))
        (count,) = cur.fetchone()
    return int(count)


def _run_verify_post_relabel(
    conn: Any,
    symbols: list[str],
    tfs: list[str],
    family: _ColumnFamily = _DEFAULT_COLUMN_FAMILY_OBJ,
    provenance_report_path: Path | None = None,
) -> int:
    """Prove, per cell, that the warmup prefix (however many bars precede the first labeled
    bar) is at least that tf's initial_warmup_bars -- a smaller count means either the
    NULL-out did not cover the cell or a stale prior-method value survived in the prefix. Pure
    SQL against (symbol, tf, bar_ts); needs no obs-matrix rebuild, so it cannot drift from the
    labeling code's own feature-window logic. Works identically for either column family --
    only the label column filtered on and the report's destination path change."""
    report_path = (
        provenance_report_path
        if provenance_report_path is not None
        else family.default_provenance_report_path
    )
    n_failed = 0
    records: list[dict[str, Any]] = []

    for symbol in symbols:
        for tf in tfs:
            initial_warmup_bars = _load_initial_warmup_bars(conn, tf)
            labeled_rows, first_labeled_bar_ts = _labeled_count_and_min_ts(conn, symbol, tf, family)

            if labeled_rows == 0:
                records.append(
                    {
                        "symbol": symbol,
                        "tf": tf,
                        "labeled_rows": 0,
                        "first_labeled_bar_ts": None,
                        "rows_before_first_label": None,
                        "initial_warmup_bars": initial_warmup_bars,
                        "verdict": "no_labels",
                    }
                )
                _logger.info(
                    "regime_null_out.verify_post_relabel_no_labels",
                    symbol=symbol,
                    tf=tf,
                    column_family=family.name,
                )
                continue

            rows_before_first_label = _rows_before_ts(conn, symbol, tf, first_labeled_bar_ts)
            verdict = "pass" if rows_before_first_label >= initial_warmup_bars else "fail"
            if verdict == "fail":
                n_failed += 1

            records.append(
                {
                    "symbol": symbol,
                    "tf": tf,
                    "labeled_rows": labeled_rows,
                    "first_labeled_bar_ts": (
                        first_labeled_bar_ts.isoformat()
                        if hasattr(first_labeled_bar_ts, "isoformat")
                        else first_labeled_bar_ts
                    ),
                    "rows_before_first_label": rows_before_first_label,
                    "initial_warmup_bars": initial_warmup_bars,
                    "verdict": verdict,
                }
            )
            _logger.info(
                "regime_null_out.verify_post_relabel_cell",
                symbol=symbol,
                tf=tf,
                column_family=family.name,
                labeled_rows=labeled_rows,
                rows_before_first_label=rows_before_first_label,
                initial_warmup_bars=initial_warmup_bars,
                verdict=verdict,
            )

    _write_provenance_report(records, report_path)
    _print_provenance_banner(records, n_failed, family.name)

    _logger.info(
        "regime_null_out.run_complete",
        mode=_MODE_VERIFY_POST_RELABEL,
        column_family=family.name,
        n_cells=len(symbols) * len(tfs),
        n_failed=n_failed,
    )
    return n_failed


def _write_provenance_report(records: list[dict[str, Any]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(records, indent=2, sort_keys=True))
    tmp.rename(path)


def _print_provenance_banner(
    records: list[dict[str, Any]], n_failed: int, family_name: str = _DEFAULT_COLUMN_FAMILY
) -> None:
    # "REQ-3 PROVENANCE:" prefix kept byte-identical (not renamed) so any existing grep for
    # that string keeps matching; the family name is appended to the same line so the output
    # stays unambiguous about which column family was checked.
    print("=" * 80)  # noqa: T201
    if n_failed == 0:
        print(f"REQ-3 PROVENANCE: PASS (column_family={family_name})")  # noqa: T201
    else:
        failing = [f"{r['symbol']}/{r['tf']}" for r in records if r["verdict"] == "fail"]
        print(  # noqa: T201
            f"REQ-3 PROVENANCE: FAIL (column_family={family_name}) -- "
            f"failing cells: {', '.join(failing)}"
        )
    print("=" * 80)  # noqa: T201


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
            "derive this script's scope. Applies identically to both column families."
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
        "--column-family",
        choices=list(_COLUMN_FAMILIES.keys()),
        default=_DEFAULT_COLUMN_FAMILY,
        help=(
            f"Regime column family to operate on. Default: {_DEFAULT_COLUMN_FAMILY}. "
            f"{_FAMILY_REGIME_VOLATILITY} covers the 8 columns in "
            "REGIME_VOLATILITY_WRITER_OWNED_COLUMN_NAMES."
        ),
    )
    parser.add_argument(
        "--manifest",
        default=None,
        help=(
            "Resumability manifest path. Default: the selected column family's own default "
            f"path ({_DEFAULT_MANIFEST_PATH} for {_FAMILY_REGIME}, a separate path for "
            f"{_FAMILY_REGIME_VOLATILITY}) -- the two families never share a manifest."
        ),
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

    family = _COLUMN_FAMILIES[args.column_family]
    _validate_label_column(family.label_column)

    status = "success"
    n_failed = 0
    try:
        if args.mode == _MODE_NULL_OUT:
            manifest_path = (
                Path(args.manifest) if args.manifest else Path(family.default_manifest_path)
            )
            n_failed = _run_null_out(
                conn, args.symbols, args.tf, manifest_path, args.dry_run, family
            )
        elif args.mode == _MODE_VERIFY_POST_NULL:
            n_failed = _run_verify_post_null(conn, args.symbols, args.tf, family)
        elif args.mode == _MODE_VERIFY_POST_RELABEL:
            n_failed = _run_verify_post_relabel(conn, args.symbols, args.tf, family)
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
