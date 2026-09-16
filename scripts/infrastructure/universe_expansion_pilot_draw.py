#!/usr/bin/env python3
"""
universe_expansion_pilot_draw.py -- D-10 pre-registered pilot gate draw (Phase 174, Plan 15)

Draws a small (30-50 symbol) down-cap pilot cohort via the same mechanical, seeded sampler
Plan 12's full-scale draw will use (Plan 08's `stratified_sample()`), onboards it through the
same qualification-gated path (`_run_commit`), and seeds it for 1d-only backfill (D-09) -- so
D-10's gate can measure whether the down-cap population actually decorrelates from the existing
single-name book before the phase pays the full backfill/OOM-fix engineering cost of the real
Plan 12 draw on a population that might deliver near-zero incremental effective breadth.

D-01 invariant this script must never violate: `alpha.universe.target_sample_size` stays 0
throughout. This script reads a SEPARATE key, `alpha.universe.pilot_sample_size` (migration
342), and asserts `target_sample_size == 0` at start-up, aborting loud if that invariant does
not hold (T-174-60) -- proving at run time that the pilot did not borrow the full-draw key.

Reuses, never re-derives, Plan 08's sampler:
    parse_holdings, stratified_sample, _bucket_population, _print_bucket_summary,
    _sha256_of, _run_commit
from universe_expansion_stratified_sourcing.py. `_run_commit` carries the V5 qualification
gate, the gateway pre-flight abort (T-174-50), and the savepoint-per-symbol atomicity -- do not
re-implement any part of that loop (Plan 03's SUMMARY already records two pre-existing
unsanctioned direct writers into the instruments table as a known gap; this script must not
add a third).
"""

from __future__ import annotations

import argparse
import csv
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import psycopg
import structlog

# sys.path bootstrap: scripts/infrastructure/<this file>.py -- 3 parents reach repo root
# (infrastructure/ -> scripts/ -> root), matching universe_expansion_stratified_sourcing.py's
# own bootstrap.
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from scripts.infrastructure.universe_expansion_fetch_iwv_holdings import (  # noqa: E402
    parse_holdings,
)
from scripts.infrastructure.universe_expansion_stratified_sourcing import (  # noqa: E402
    _bucket_population,
    _print_bucket_summary,
    _run_commit,
    _sha256_of,
    stratified_sample,
)
from src.config.settings import Settings  # noqa: E402
from src.observability.metrics import JOB_COMPLETED_TOTAL, flush_and_shutdown_metrics  # noqa: E402

_logger = structlog.get_logger(__name__)

# D-10's decision text: "roughly 30-50 symbols." A deliberate visible-act gate, not a silent
# clamp -- widening this band requires --allow-out-of-range with a logged reason, not a code
# edit to the constants themselves.
_PILOT_SIZE_MIN = 30
_PILOT_SIZE_MAX = 50

# Additive tag beside _run_commit's own eq_broad tag (Plan 08's _SAMPLE_TAGS, not modified
# here). The existing 117/128-name single-name book is discoverable via `single_name_equity`
# (instrument_tags); without this second tag the pilot cohort would be invisible to
# universe_expansion_correlation_structure_check.py's --tag mode and to every future
# "how big is the single-name book" query. source='human' -- this is a definitional
# classification (ITR: exposure/category tags are permanent human priors, not measured), not
# an impersonation of TagCalibrator's empirical rows. Asyncpg placeholder syntax ($1, $2) --
# see _tag_single_name_equity(), which runs this on a pooled asyncpg connection.
_INSERT_SINGLE_NAME_TAG_SQL = """
INSERT INTO instrument_tags (symbol, tag, weight, source, evidence)
VALUES ($1, 'single_name_equity', 1.0, 'human', $2::jsonb)
ON CONFLICT (symbol, tag) DO NOTHING
"""

_PILOT_COHORT_CSV = Path("/var/tmp/phase174_pilot_cohort.csv")


def _fetch_apr(cur: Any, key: str, default: Any) -> Any:
    """Fetch a live APR value from config_state -- never a hardcoded snapshot. Matches
    universe_expansion_stratified_sourcing.py's own _fetch_apr() pattern.
    """
    cur.execute("SELECT config_value FROM config_state WHERE config_key = %s", (key,))
    row = cur.fetchone()
    return type(default)(row[0]) if row else default


async def _tag_single_name_equity(settings: Settings, symbols: list[str]) -> int:
    """Add the single_name_equity tag for every symbol onboard_instrument()/_run_commit()
    already accepted, via a SEPARATE parameterized statement (not by modifying Plan 08's
    merged _SAMPLE_TAGS). Uses a pooled asyncpg connection like _run_commit() does, so the
    jsonb codec is registered for the evidence column.
    """
    from src.core.database_manager import DatabaseManager

    if not symbols:
        return 0

    db = DatabaseManager(settings.database_url)
    await db.initialize()
    n_tagged = 0
    try:
        async with db.pool.acquire() as conn:
            for symbol in symbols:
                result = await conn.execute(
                    _INSERT_SINGLE_NAME_TAG_SQL,
                    symbol,
                    {
                        "reason": (
                            "Phase 174 D-09/D-10 down-cap pilot draw -- tagged so this cohort "
                            "is discoverable by the same tag the existing single-name book "
                            "uses (universe_expansion_correlation_structure_check.py --tag "
                            "single_name_equity)"
                        )
                    },
                )
                if result != "INSERT 0 0":
                    n_tagged += 1
    finally:
        await db.close()
    return n_tagged


async def _async_main(args: argparse.Namespace) -> int:
    settings = Settings()
    dsn = settings.database_url.replace("postgresql+asyncpg://", "postgresql://")

    with psycopg.connect(dsn) as conn, conn.cursor() as cur:
        target_sample_size = _fetch_apr(cur, "alpha.universe.target_sample_size", 0)
        if target_sample_size != 0:
            print(
                "FAILED: alpha.universe.target_sample_size is "
                f"{target_sample_size} (expected 0). T-174-60: the pilot must never borrow "
                "the full-draw key -- this proves at run time it has not been set early. "
                "Aborting before any draw.",
                file=sys.stderr,
            )
            return 1

        seed = _fetch_apr(cur, "alpha.universe.stratified_sample_random_state", 42)
        bucket_count = _fetch_apr(cur, "alpha.universe.cap_bucket_count", 10)
        apr_pilot_size = _fetch_apr(cur, "alpha.universe.pilot_sample_size", 40)
        cur.execute("SELECT symbol FROM instruments")
        exclude = {row[0] for row in cur.fetchall()}

    pilot_size = args.pilot_size if args.pilot_size is not None else apr_pilot_size
    if args.pilot_size is not None:
        print(
            f"pilot_size override: --pilot-size={args.pilot_size} "
            f"(APR alpha.universe.pilot_sample_size={apr_pilot_size})"
        )
    else:
        print(f"pilot_size from APR alpha.universe.pilot_sample_size={apr_pilot_size}")

    if not (_PILOT_SIZE_MIN <= pilot_size <= _PILOT_SIZE_MAX) and not args.allow_out_of_range:
        print(
            f"FAILED: pilot_size={pilot_size} is outside D-10's stated range "
            f"[{_PILOT_SIZE_MIN}, {_PILOT_SIZE_MAX}]. D-10's decision text specifies roughly "
            "30-50 symbols for this pilot -- the band is a decision, not a tunable, so "
            "widening it requires a visible act (--allow-out-of-range --reason '...').",
            file=sys.stderr,
        )
        return 1
    if args.allow_out_of_range:
        print(
            f"--allow-out-of-range: pilot_size={pilot_size} outside "
            f"[{_PILOT_SIZE_MIN}, {_PILOT_SIZE_MAX}], reason={args.reason!r}"
        )

    holdings_sha256 = _sha256_of(args.holdings)
    population = parse_holdings(args.holdings)

    sample = stratified_sample(
        population, target_size=pilot_size, bucket_count=bucket_count, seed=seed, exclude=exclude
    )

    n_lowest_bucket = int((sample["cap_bucket"] == 0).sum()) if not sample.empty else 0

    print(
        "Provenance:",
        {
            "holdings_file": str(args.holdings),
            "holdings_sha256": holdings_sha256,
            "stratified_sample_random_state": seed,
            "cap_bucket_count": bucket_count,
            "pilot_sample_size": pilot_size,
            "target_sample_size": target_sample_size,
            "n_excluded": len(exclude),
            "n_drawn": len(sample),
            "n_drawn_lowest_bucket": n_lowest_bucket,
        },
    )

    if n_lowest_bucket == 0:
        print(
            "FINDING: zero symbols drawn from cap_bucket=0 (the SMALLEST-market-cap stratum). "
            "A pilot concentrated in the top buckets would re-test the large/mega-cap "
            "population alpha_score_residual_single_security_15m was already measured DEAD "
            "against, making D-10's gate meaningless. This is a finding about the population "
            "or the bucketing, not something to work around by hand-selecting names -- "
            "stopping here rather than proceeding to onboarding.",
            file=sys.stderr,
        )
        return 1

    if not args.commit:
        timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        dest = Path(f"/var/tmp/phase174_pilot_draw_dryrun_{timestamp}.csv")
        sample.to_csv(dest, index=False, quoting=csv.QUOTE_MINIMAL)
        print(f"Dry run -- wrote drawn list to {dest} (no database writes).")
        bucketed_pop = _bucket_population(population, bucket_count=bucket_count, exclude=exclude)
        _print_bucket_summary(sample, bucketed_pop)
        return 0

    # --commit: onboard through _run_commit() with ("1d",) -- the D-09 mechanism. One
    # backfill_status row per symbol, for 1d only; the other three timeframes are never
    # claimed, and compute_eligible/compute_eligible_1d both default False in
    # onboard_instrument() until Task 2's promotion step runs.
    result = await _run_commit(sample, settings, ("1d",))

    onboarded_symbols = sample["symbol"].tolist()[: result["n_onboarded"]]
    # _run_commit() iterates `sample` in row order and only advances n_onboarded on success --
    # rejected symbols interleave with accepted ones, so slicing the head of `sample` by
    # n_onboarded is NOT reliable for identifying which symbols actually landed. Query the
    # DB instead: it is the ground truth for which pilot-drawn symbols are now real rows.
    with psycopg.connect(dsn) as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT symbol FROM instruments WHERE symbol = ANY(%s)",
            (sample["symbol"].tolist(),),
        )
        onboarded_symbols = sorted(row[0] for row in cur.fetchall())
        rejected_symbols = sorted(set(sample["symbol"].tolist()) - set(onboarded_symbols))

    n_tagged = await _tag_single_name_equity(settings, onboarded_symbols)

    sample.to_csv(_PILOT_COHORT_CSV, index=False, quoting=csv.QUOTE_MINIMAL)

    print(
        "Commit run complete:",
        {
            "n_population": len(population),
            "n_excluded": len(exclude),
            "n_drawn": len(sample),
            "n_onboarded": result["n_onboarded"],
            "n_rejected": result["n_rejected"],
            "n_tagged_single_name_equity": n_tagged,
            "onboarded_symbols": onboarded_symbols,
            "rejected_symbols": rejected_symbols,
            "cohort_csv": str(_PILOT_COHORT_CSV),
        },
    )

    with psycopg.connect(dsn) as conn, conn.cursor() as cur:
        final_target = _fetch_apr(cur, "alpha.universe.target_sample_size", 0)
    if final_target != 0:
        print(
            f"FAILED (post-commit assertion): alpha.universe.target_sample_size is now "
            f"{final_target}, expected 0. The pilot must never leave this key set.",
            file=sys.stderr,
        )
        return 1
    print(f"Post-commit assertion: alpha.universe.target_sample_size={final_target} (expected 0)")

    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "D-10 pre-registered pilot gate draw (Phase 174, Plan 15): a 30-50 symbol "
            "down-cap pilot drawn by the same mechanical sampler Plan 12's full draw will "
            "use, onboarded and seeded for 1d-only backfill. Dry-run by default."
        )
    )
    parser.add_argument(
        "--holdings", type=Path, required=True, help="Path to a downloaded IWV holdings CSV."
    )
    parser.add_argument(
        "--pilot-size",
        type=int,
        default=None,
        help=(
            "Explicit override for the pilot draw size. Defaults to the live "
            "alpha.universe.pilot_sample_size APR value if omitted. Both the APR value and "
            "the override (if passed) are logged so the record shows which was used."
        ),
    )
    parser.add_argument(
        "--allow-out-of-range",
        action="store_true",
        default=False,
        help=(
            "Allow pilot_size outside D-10's stated [30, 50] band. Requires --reason. "
            "The band is a decision, not a tunable -- widening it should be a visible act."
        ),
    )
    parser.add_argument(
        "--reason",
        default="",
        help="Required justification when --allow-out-of-range is passed.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=True,
        help="Dry-run only (default): draw the sample, write a CSV, make no database writes.",
    )
    parser.add_argument(
        "--commit",
        action="store_true",
        default=False,
        help=(
            "Actually onboard the drawn pilot through _run_commit() with 1d-only backfill "
            "seeding (D-09), then tag every onboarded symbol single_name_equity. Off by "
            "default -- writing is opt-in, not opt-out."
        ),
    )
    args = parser.parse_args(argv)

    if args.allow_out_of_range and not args.reason:
        parser.error("--allow-out-of-range requires --reason")

    status = "success"
    try:
        import asyncio

        return_code = asyncio.run(_async_main(args))
        if return_code != 0:
            status = "failure"
        return return_code
    except Exception as error:
        status = "failure"
        _logger.error("universe_expansion_pilot_draw.failed", error=str(error))
        print(f"FAILED: {error}", file=sys.stderr)
        return 1
    finally:
        JOB_COMPLETED_TOTAL.add(1, {"job": "universe-expansion-pilot-draw", "status": status})
        flush_and_shutdown_metrics()


if __name__ == "__main__":
    from src.observability.otel import OTelInitError, init_otel_providers

    try:
        init_otel_providers("universe-expansion-pilot-draw")
    except OTelInitError as error:
        print(f"[warn] OTel init failed -- metrics disabled: {error}")
    sys.exit(main())
