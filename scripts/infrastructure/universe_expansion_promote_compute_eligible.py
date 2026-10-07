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
`scripts.infrastructure.instrument_compute_eligibility_audit` -- never retyped.

Since plan 185-41 promotion reads computed truth: every required `bar_integrity` verdict D7
writes must be passed and fresh (`src/intelligence/bars/verdict_gate.py`); the retired
`fetch_complete` bookkeeping flag is not read. The candidate list comes from the SQL
predicate; the pure gate then re-judges both candidates and holds and the tool raises if the two
disagree, so the hold reasons name the failing check and the two renderings cannot drift silently.
A name D7 has not judged (D7 judges the `compute_1d` universe) holds as "missing".
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import NamedTuple

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import psycopg  # noqa: E402
import structlog  # noqa: E402

from scripts.infrastructure._write_mode_args import add_write_mode_args  # noqa: E402
from scripts.infrastructure.instrument_compute_eligibility_audit import (  # noqa: E402
    COMPUTE_READY_1D_PREDICATE_SQL,
    COMPUTE_READY_PREDICATE_SQL,
    load_compute_timeframes,
    load_report_max_age_hours,
)
from src.config.settings import Settings  # noqa: E402
from src.core.service_utils import setup_service_logging  # noqa: E402
from src.intelligence.bars.verdict_gate import fetch_verdict_scan  # noqa: E402
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
    # The timeframes the pure gate judges when the predicate binds none (None: the APR stack).
    fixed_timeframes: tuple[str, ...] | None = None


# Module-owned literal map: --dimension indexes into this dict, never builds SQL text or a
# column name from argv directly. `compute` binds COMPUTE_READY_PREDICATE_SQL's
# %(timeframes)s placeholder to the APR compute stack (feature.factory.target_timeframes);
# `compute_1d`'s predicate has '1d' baked in as a literal (see
# scripts/infrastructure/instrument_compute_eligibility_audit.py) and needs no binding.
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
        fixed_timeframes=("1d",),
    ),
}


def _gate_timeframes(conn: psycopg.Connection, config: _DimensionConfig) -> list[str]:
    if config.fixed_timeframes is not None:
        return list(config.fixed_timeframes)
    return load_compute_timeframes(conn)


def _fetch_candidates(
    conn: psycopg.Connection, config: _DimensionConfig, max_age_hours: float
) -> list[str]:
    """is_active=true AND <target_column>=false candidates satisfying the dimension's
    predicate: every required verdict passed and fresh (the gate lives in `config.predicate_sql`).
    """
    params: dict[str, object] = {"max_age_hours": max_age_hours}
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
    conn: psycopg.Connection,
    config: _DimensionConfig,
    candidate_pool_symbols: list[str],
    max_age_hours: float,
) -> dict[str, list[str]]:
    """For every is_active=true, <column>=false symbol NOT in the promoted candidate list, the
    verdict reasons it was held back (`tf:check failed|missing|stale ...`).

    The pure gate also re-judges the candidates. Either rendering disagreeing with the other is a
    defect, not a hold: the tool raises rather than promote or hold on one reading.
    """
    with conn.cursor() as cur:
        cur.execute(
            f"SELECT symbol FROM instruments WHERE is_active = true AND {config.column} = false"
        )
        all_ineligible = {row[0] for row in cur.fetchall()}
    held = sorted(all_ineligible - set(candidate_pool_symbols))
    timeframes = _gate_timeframes(conn, config)
    failures = fetch_verdict_scan(conn, held, timeframes, max_age_hours).failures
    passing_but_held = sorted(set(held) - set(failures))
    failing_but_candidate = sorted(
        fetch_verdict_scan(conn, sorted(candidate_pool_symbols), timeframes, max_age_hours).failures
    )
    if passing_but_held or failing_but_candidate:
        raise RuntimeError(
            "verdict gate disagreement between the SQL predicate and the pure gate: "
            f"held by SQL but passing the gate {passing_but_held[:10]}; "
            f"candidate by SQL but failing the gate {failing_but_candidate[:10]}"
        )
    return failures


def _hold_check_counts(holds: dict[str, list[str]]) -> dict[str, int]:
    """Held names per `tf:check` (the reason's first token), for the summary line."""
    counts: dict[str, int] = {}
    for reasons in holds.values():
        for reason in reasons:
            key = reason.split(" ", 1)[0]
            counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))


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
    add_write_mode_args(
        parser,
        dry_run="Dry-run only (default): report candidates, make no database writes.",
        commit="Actually run the promotion UPDATE. Off by default.",
    )
    args = parser.parse_args(argv)

    status = "success"
    try:
        config = _DIMENSION_CONFIG[args.dimension]
        settings = Settings()
        conn = psycopg.connect(settings.database_url)
        conn.autocommit = True
        try:
            max_age_hours = load_report_max_age_hours(conn)
            candidates = _fetch_candidates(conn, config, max_age_hours)
            holds = _fetch_holds(conn, config, candidates, max_age_hours)
            hold_checks = _hold_check_counts(holds)

            print(
                f"Dimension: {args.dimension} (column={config.column})\n"
                f"n_candidates: {len(candidates)}\n"
                f"n_held: {len(holds)}\n"
                f"held_by_failing_check: {hold_checks}\n"
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
                held_by_failing_check=hold_checks,
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
