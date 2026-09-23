#!/usr/bin/env python3
"""
universe_expansion_promote_compute_eligible.py -- dimension-aware compute-eligibility
promotion tool (Phase 174, Plan 15)

Re-runnable tool serving both eligibility dimensions -- the four-timeframe `compute`
dimension (D-07, migration 337) and the 1d-only `compute_1d` dimension (D-09, migration
341) -- so Plan 12's full-scale down-cap draw can reuse this tool rather than building a
second one.

`--dimension` selects the target column and predicate constant through a module-owned
literal dict, never from argv text reaching SQL (same structural pattern Plan 06 used for
`_ACTIVE_CONTRACTS_DIMENSION_CLAUSES`): a caller-supplied string indexes into
`_DIMENSION_CONFIG`, which is the only place either the column name or the predicate SQL is
named. Both predicates are imported verbatim from
`scripts.analysis.instrument_compute_eligibility_audit` -- never retyped -- because both
halves of each predicate (the `backfill_status` bookkeeping count AND the
`market_data_ohlcv_tradeable` ground-truth count) are counted aggregates, and a hand-written
`EXISTS (...)` would silently degrade to "at least one timeframe complete."
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import NamedTuple

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import psycopg  # noqa: E402
import structlog  # noqa: E402

from scripts.analysis.instrument_compute_eligibility_audit import (  # noqa: E402
    COMPUTE_READY_1D_PREDICATE_SQL,
    COMPUTE_READY_PREDICATE_SQL,
    load_compute_timeframes,
)
from src.config.settings import Settings  # noqa: E402
from src.core.service_utils import setup_service_logging  # noqa: E402
from src.observability.metrics import JOB_COMPLETED_TOTAL, flush_and_shutdown_metrics  # noqa: E402

setup_service_logging("logs/universe_expansion_promote_compute_eligible.log")
_logger = structlog.get_logger(__name__)

_JOB_NAME = "universe-expansion-promote-compute-eligible"


class _DimensionConfig(NamedTuple):
    column: str
    predicate_sql: str
    # True: bind the predicate's %(timeframes)s to the APR compute stack at run time.
    # False: the predicate has its timeframe baked in and takes no binding.
    binds_compute_timeframes: bool


# Module-owned literal map: --dimension indexes into this dict, never builds SQL text or a
# column name from argv directly. `compute` binds COMPUTE_READY_PREDICATE_SQL's
# %(timeframes)s placeholder to the APR compute stack (feature.factory.target_timeframes);
# `compute_1d`'s predicate has '1d' baked in as a literal (see
# instrument_compute_eligibility_audit.py) and needs no binding.
_DIMENSION_CONFIG: dict[str, _DimensionConfig] = {
    "compute": _DimensionConfig(
        column="compute_eligible",
        predicate_sql=COMPUTE_READY_PREDICATE_SQL,
        binds_compute_timeframes=True,
    ),
    "compute_1d": _DimensionConfig(
        column="compute_eligible_1d",
        predicate_sql=COMPUTE_READY_1D_PREDICATE_SQL,
        binds_compute_timeframes=False,
    ),
}


def _fetch_candidates(conn: psycopg.Connection, config: _DimensionConfig) -> list[str]:
    """is_active=true AND <target_column>=false candidates satisfying the dimension's
    predicate. Both halves of the gate (backfill_status bookkeeping count AND
    market_data_ohlcv_tradeable ground truth) already live inside `config.predicate_sql`.
    """
    params: dict[str, object] = {}
    if config.binds_compute_timeframes:
        params["timeframes"] = load_compute_timeframes(conn)
    sql = f"""
        SELECT i.symbol
        FROM instruments i
        WHERE i.is_active = true
          AND i.{config.column} = false
          AND ({config.predicate_sql})
        ORDER BY i.symbol
    """
    with conn.cursor() as cur:
        cur.execute(sql, params)
        return [row[0] for row in cur.fetchall()]


def _fetch_holds(
    conn: psycopg.Connection, column: str, candidate_pool_symbols: list[str]
) -> dict[str, str]:
    """For every is_active=true, <column>=false symbol NOT in the promoted candidate
    list, classify why it was held back -- never log per-symbol, but the caller needs a
    breakdown of hold reasons, not just a count.
    """
    with conn.cursor() as cur:
        cur.execute(f"SELECT symbol FROM instruments WHERE is_active = true AND {column} = false")
        all_ineligible = {row[0] for row in cur.fetchall()}
    held = all_ineligible - set(candidate_pool_symbols)
    return dict.fromkeys(sorted(held), "predicate not satisfied (backfill incomplete or no bars)")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Dimension-aware compute-eligibility promotion tool (Phase 174 D-07/D-09). "
            "Promotes is_active=true candidates satisfying the selected dimension's "
            "compute-readiness predicate. Dry-run by default."
        )
    )
    parser.add_argument(
        "--dimension",
        required=True,
        choices=sorted(_DIMENSION_CONFIG),
        help="Which eligibility dimension to promote against.",
    )
    # Mutually exclusive: --dry-run is the default, and "--dry-run --commit" is a usage
    # error rather than a silent commit (174 review IN-02).
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--dry-run",
        action="store_true",
        default=True,
        help="Dry-run only (default): report candidates, make no database writes.",
    )
    mode.add_argument(
        "--commit",
        action="store_true",
        default=False,
        help="Actually run the promotion UPDATE. Off by default.",
    )
    args = parser.parse_args(argv)

    status = "success"
    try:
        config = _DIMENSION_CONFIG[args.dimension]
        settings = Settings()
        conn = psycopg.connect(settings.database_url)
        conn.autocommit = True
        try:
            candidates = _fetch_candidates(conn, config)
            holds = _fetch_holds(conn, config.column, candidates)

            print(
                f"Dimension: {args.dimension} (column={config.column})\n"
                f"n_candidates: {len(candidates)}\n"
                f"n_held: {len(holds)}\n"
                f"hold_reasons: {list(dict.fromkeys(holds.values()))}\n"
                f"held_symbols: {sorted(holds)}"
            )

            if not args.commit:
                print("Dry run -- no database writes. Candidates:", candidates)
                return 0

            n_promoted = 0
            if candidates:
                # str.format(), not an f-string, builds the column-name substitution --
                # deliberately visible as a distinct construction from the parameterized
                # %(symbols)s value binding below. config.column only ever takes one of the
                # two hardcoded values in _DIMENSION_CONFIG (never argv text), but the two
                # substitution mechanisms are kept textually distinct on purpose.
                update_sql = (  # noqa: UP032 -- deliberately not an f-string, see comment above
                    "UPDATE instruments SET {col} = true "
                    "WHERE symbol = ANY(%(symbols)s) AND is_active = true AND {col} = false"
                ).format(col=config.column)
                with conn.cursor() as cur:
                    cur.execute(update_sql, {"symbols": candidates})
                    n_promoted = cur.rowcount

            print(
                f"Commit run complete: dimension={args.dimension} n_candidates="
                f"{len(candidates)} n_promoted={n_promoted} n_held={len(holds)}"
            )
            _logger.info(
                "universe_expansion_promote_compute_eligible.summary",
                dimension=args.dimension,
                n_candidates=len(candidates),
                n_promoted=n_promoted,
                n_held=len(holds),
                hold_reasons=list(dict.fromkeys(holds.values())),
            )
            return 0
        finally:
            conn.close()
    except Exception as error:
        status = "failure"
        _logger.error("universe_expansion_promote_compute_eligible.failed", error=str(error))
        print(f"FAILED: {error}", file=sys.stderr)
        return 1
    finally:
        JOB_COMPLETED_TOTAL.add(1, {"job": _JOB_NAME, "status": status})
        flush_and_shutdown_metrics()


if __name__ == "__main__":
    from src.observability.otel import OTelInitError, init_otel_providers

    try:
        init_otel_providers(_JOB_NAME)
    except OTelInitError as error:
        print(f"[warn] OTel init failed -- metrics disabled: {error}")
    sys.exit(main())
