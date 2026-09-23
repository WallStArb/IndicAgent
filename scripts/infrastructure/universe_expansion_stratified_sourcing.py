#!/usr/bin/env python3
"""
universe_expansion_stratified_sourcing.py -- market-cap-stratified sampler (Phase 174, Plan 08)

Turns Plan 04's validated Russell 3000 population (`parse_holdings()` in
universe_expansion_fetch_iwv_holdings.py) into the concrete symbol list this phase
onboards (D-02): a market-cap-stratified random sample, seeded from an APR key so
the draw is reproducible and auditable. This directly tests the down-cap breadth
hypothesis empirically instead of hand-picking promising small-caps, which would
smuggle in a prior about where signal lives before any measurement happens -- the
current 128 single-names are almost entirely large/mega-cap (only 1 tagged
`eq_small_cap`), the exact segment `alpha_score_residual_single_security_15m` was
already measured DEAD against.

D-01: `alpha.universe.target_sample_size` stays 0 (= UNSET) until Plan 11 measures
the ic_engine OOM fix's actually-supported scale -- this script fails loud naming
that key rather than picking a number. Do NOT run this script in --commit mode in
this plan; Plan 12 owns the real run, once Plan 11 has set the target size.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import psycopg
import structlog

# sys.path bootstrap: this file is scripts/infrastructure/<this file>.py -- 3 parents
# reach repo root (infrastructure/ -> scripts/ -> root). Matches
# universe_expansion_fetch_iwv_holdings.py's own header comment, which documents
# the class of bug a wrong parent count causes (import src fails unless PYTHONPATH
# is already set externally).
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from scripts.infrastructure._write_mode_args import add_write_mode_args  # noqa: E402
from scripts.infrastructure.universe_expansion_fetch_iwv_holdings import (  # noqa: E402
    parse_holdings,
)
from src.config.instrument_onboarding import (  # noqa: E402
    OnboardingRejected,
    load_compute_timeframes,
    onboard_instrument,
)
from src.config.settings import Settings  # noqa: E402
from src.core.database_manager import DatabaseManager  # noqa: E402
from src.core.models import AssetClass, Instrument  # noqa: E402
from src.observability.metrics import JOB_COMPLETED_TOTAL, flush_and_shutdown_metrics  # noqa: E402
from src.providers.ibkr import IBKRProvider  # noqa: E402

_logger = structlog.get_logger(__name__)

# Dedicated client ID, distinct from other in-repo IBKR client IDs (40=default
# backfill, 44=chunk/rate-limit probe, 48=personal_cost_hurdle) -- see
# src/providers/ibkr.py's _MAX_CLIENT_ID=50 ceiling. Used only for the --commit
# gateway pre-flight probe; never used for the actual backfill (that's Plan 12).
_GATEWAY_PROBE_CLIENT_ID = 45

# Every sampled single-name equity gets this exposure tag. The IWV holdings file's
# narrow three-column contract (symbol/name/index_position_value, per Plan 04's
# parse_holdings()) carries no sector/value/growth data through to this script, so
# a finer eq_* split is not derivable here without a second data source -- eq_broad
# is the correct, honest default; a follow-on sector/factor re-tagging pass is a
# separate task, not this plan's scope.
_SAMPLE_TAGS: tuple[tuple[str, float, dict], ...] = (
    ("eq_broad", 1.0, {"reason": "Phase 174 D-02 market-cap-stratified Russell 3000 sample"}),
)


def _bucket_population(
    population: pd.DataFrame, *, bucket_count: int, exclude: set[str]
) -> pd.DataFrame:
    """Exclusion + qcut bucketing shared by stratified_sample() and the CLI's
    per-bucket population summary -- factored out so the draw and the report
    can never compute the bucket boundaries differently. pandas.qcut, not a
    hand-rolled quantile boundary (RESEARCH.md Don't Hand-Roll table).
    """
    pop = population.loc[~population["symbol"].isin(exclude)].reset_index(drop=True)
    if pop.empty:
        return pop.assign(cap_bucket=pd.Series(dtype=int))
    cap_bucket = pd.qcut(
        pop["index_position_value"], q=bucket_count, labels=False, duplicates="drop"
    )
    return pop.assign(cap_bucket=cap_bucket.astype(int))


def stratified_sample(
    population: pd.DataFrame,
    *,
    target_size: int,
    bucket_count: int,
    seed: int,
    exclude: set[str],
) -> pd.DataFrame:
    """Draw a seeded, market-cap-stratified random sample from `population`.

    Bucket ordering is ASCENDING by market cap: cap_bucket=0 is the SMALLEST-
    market-cap stratum, cap_bucket=bucket_count-1 (or fewer, if pandas.qcut()
    drops duplicate edges) is the LARGEST. Every use of "lowest bucket" in this
    module, its CLI output, and downstream documents means lowest market cap --
    this follows directly from pandas.qcut(labels=False) assigning integer codes
    in ascending order of the binned value. A runtime assertion below re-checks
    this rather than assuming it, since a silent reversal here would invert the
    whole down-cap reading of the sample, which is the entire point of D-02.

    Pure, no I/O -- unit-testable without a database (D-02's reproducibility
    requirement). The RNG is created once and drawn from sequentially across
    buckets in ascending order, so the draw sequence is fully determined by
    (seed, population, target_size, bucket_count).

    Args:
        population: frame with columns symbol/name/index_position_value (Plan 04's
            parse_holdings() contract).
        target_size: number of symbols to draw. Must be > 0 -- the D-01 guard,
            fires before any draw, not after.
        bucket_count: number of market-cap strata for pandas.qcut().
        seed: RNG seed (caller must source this from
            alpha.universe.stratified_sample_random_state, never a literal).
        exclude: symbols already present in `instruments` -- dropped from the
            population BEFORE bucketing, so strata are computed over the
            addressable population the draw can actually use.

    Returns:
        Frame with columns symbol, name, index_position_value, cap_bucket, cap_bucket_min,
        cap_bucket_max -- the bounds carried on every row make "lowest bucket"
        unambiguous downstream without re-deriving qcut's boundaries.

    Raises:
        ValueError: target_size <= 0.
    """
    if target_size <= 0:
        raise ValueError(
            f"stratified_sample: target_size must be > 0, got {target_size} -- a "
            "target size of 0 means UNSET (D-01); the caller must set "
            "alpha.universe.target_sample_size from a measurement before drawing."
        )

    _empty = pd.DataFrame(
        columns=[
            "symbol",
            "name",
            "index_position_value",
            "cap_bucket",
            "cap_bucket_min",
            "cap_bucket_max",
        ]
    )

    pop = _bucket_population(population, bucket_count=bucket_count, exclude=exclude)
    if pop.empty:
        return _empty

    bucket_means = pop.groupby("cap_bucket")["index_position_value"].mean().sort_index()
    diffs = bucket_means.diff().dropna()
    if not (diffs >= 0).all():
        raise AssertionError(
            "stratified_sample: per-bucket mean market cap is NOT monotonically "
            "non-decreasing in bucket index -- qcut's ascending-by-value ordering "
            "assumption has been violated. This would silently invert the down-cap "
            f"reading of the sample (D-02). Bucket means: {bucket_means.to_dict()}"
        )

    bucket_bounds = pop.groupby("cap_bucket")["index_position_value"].agg(
        cap_bucket_min="min", cap_bucket_max="max"
    )
    bucket_sizes = pop.groupby("cap_bucket").size().to_dict()
    alloc = _allocate_target(bucket_sizes, target_size)

    rng = np.random.default_rng(seed)
    drawn_frames: list[pd.DataFrame] = []
    for bucket_idx in sorted(alloc):
        n_draw = alloc[bucket_idx]
        if n_draw <= 0:
            continue
        bucket_df = pop.loc[pop["cap_bucket"] == bucket_idx]
        chosen_positions = rng.choice(len(bucket_df), size=n_draw, replace=False)
        chosen = bucket_df.iloc[chosen_positions].copy()
        chosen["cap_bucket_min"] = bucket_bounds.loc[bucket_idx, "cap_bucket_min"]
        chosen["cap_bucket_max"] = bucket_bounds.loc[bucket_idx, "cap_bucket_max"]
        drawn_frames.append(chosen)

    if not drawn_frames:
        return _empty

    result = pd.concat(drawn_frames, ignore_index=True)
    return result[
        ["symbol", "name", "index_position_value", "cap_bucket", "cap_bucket_min", "cap_bucket_max"]
    ]


def _allocate_target(bucket_sizes: dict[int, int], target_size: int) -> dict[int, int]:
    """Deterministically allocate target_size draws across buckets.

    As-even-as-possible split; any remainder goes to the lowest-numbered (=
    smallest-market-cap) buckets -- a deliberate choice, not an artifact: a
    remainder of one or two names is worth spending on the down-cap segment the
    corpus has almost no coverage of. If a bucket's own population can't satisfy
    its allocation, the shortfall is redistributed to buckets with remaining
    capacity, iterating until satisfied or the population is exhausted. Consumes
    NO randomness -- allocation must stay reproducible independent of the RNG
    draw that follows it.
    """
    buckets = sorted(bucket_sizes)
    total_capacity = sum(bucket_sizes.values())
    to_place = min(target_size, total_capacity)

    alloc = dict.fromkeys(buckets, 0)
    open_buckets = set(buckets)

    while to_place > 0 and open_buckets:
        n_open = len(open_buckets)
        base, remainder = divmod(to_place, n_open)
        ordered_open = sorted(open_buckets)  # ascending = smallest-cap first
        placed_this_round = 0
        newly_closed = []
        for i, bucket_idx in enumerate(ordered_open):
            want = base + (1 if i < remainder else 0)
            capacity_left = bucket_sizes[bucket_idx] - alloc[bucket_idx]
            give = min(want, capacity_left)
            alloc[bucket_idx] += give
            placed_this_round += give
            if alloc[bucket_idx] >= bucket_sizes[bucket_idx]:
                newly_closed.append(bucket_idx)
        to_place -= placed_this_round
        for bucket_idx in newly_closed:
            open_buckets.discard(bucket_idx)
        if placed_this_round == 0:
            break  # no bucket has remaining capacity -- population exhausted

    return alloc


def _fetch_apr(cur: Any, key: str, default: Any) -> Any:
    """Fetch a live APR value from config_state (matches
    scripts/analysis/ic_sharpe_stride_bias_check.py's pattern) -- never a
    hardcoded snapshot.
    """
    cur.execute("SELECT config_value FROM config_state WHERE config_key = %s", (key,))
    row = cur.fetchone()
    return type(default)(row[0]) if row else default


def exclude_set_sha256(exclude: set[str]) -> str:
    """sha256 of the sorted exclude list, newline-joined.

    The exclude set is the live `instruments` table at draw time, so a count alone cannot
    reproduce a draw: the same seed and holdings hash give a different sample after any
    onboarding. Recording this hash makes the draw's full input set checkable (174 review
    IN-06).
    """
    return hashlib.sha256("\n".join(sorted(exclude)).encode()).hexdigest()


def _sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    digest.update(path.read_bytes())
    return digest.hexdigest()


def _print_bucket_summary(sample: pd.DataFrame, bucketed_pop: pd.DataFrame) -> None:
    """Print bucket idx / cap min / cap max / population count / drawn count,
    ascending by bucket index. `bucketed_pop` must be the SAME post-exclusion,
    qcut-bucketed frame the draw was made from (see _bucket_population()) -- a
    mismatched population would print a population count that doesn't
    correspond to the buckets that were actually drawn from.
    """
    print(
        "Per-bucket summary (bucket 0 = SMALLEST market-cap stratum, "
        "ascending by cap_bucket index):"
    )
    print(f"{'bucket':>6} {'cap_min':>16} {'cap_max':>16} {'population':>10} {'drawn':>6}")
    pop_counts = bucketed_pop.groupby("cap_bucket").size()
    for bucket_idx in sorted(sample["cap_bucket"].unique()):
        rows = sample.loc[sample["cap_bucket"] == bucket_idx]
        cap_min = rows["cap_bucket_min"].iloc[0]
        cap_max = rows["cap_bucket_max"].iloc[0]
        n_pop = pop_counts.get(bucket_idx, len(rows))
        print(f"{bucket_idx:>6} {cap_min:>16.2f} {cap_max:>16.2f} {n_pop:>10} {len(rows):>6}")


async def _gateway_preflight(settings: Settings) -> tuple[bool, str]:
    """Probe ib-gateway before the onboarding loop starts.

    onboard_instrument() awaits qualify_instrument(), which returns False (not
    raises) when there is no live Gateway connection -- so a stopped or
    logged-out gateway would not error out, it would silently reject every
    symbol one at a time and report a 100% rejection rate that looks like a
    data problem (T-174-50). Connects, issues one qualify_instrument() against a
    known-good existing corpus symbol read from `instruments`, and returns
    (ok, probe_symbol).
    """
    dsn = settings.database_url.replace("postgresql+asyncpg://", "postgresql://")
    with psycopg.connect(dsn) as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT symbol, base, contract_details FROM instruments "
            "WHERE is_active = true AND contract_details->>'asset_class' = 'equity' "
            "LIMIT 1"
        )
        row = cur.fetchone()
    if row is None:
        raise RuntimeError(
            "universe_expansion_stratified_sourcing: no existing active equity "
            "instrument found to use as the gateway pre-flight probe symbol."
        )
    probe_symbol, base, contract_details = row
    probe_instrument = Instrument(
        symbol=probe_symbol,
        base=base or probe_symbol,
        asset_class=AssetClass.EQUITY,
        exchange=contract_details.get("exchange", "SMART"),
        sector=contract_details.get("sector", ""),
        tick_size=contract_details.get("tick_size", 0.01),
        session_id=contract_details.get("session_id", "nyse"),
        point_value=contract_details.get("point_value", 1.0),
        provider_meta=contract_details.get("provider_meta") or {},
    )

    provider = IBKRProvider(
        host=settings.ib_host, port=settings.ib_port, client_id=_GATEWAY_PROBE_CLIENT_ID
    )
    connected = await provider.connect()
    if not connected:
        return False, probe_symbol
    try:
        ok = await provider.qualify_instrument(probe_instrument)
    finally:
        await provider.disconnect()
    return ok, probe_symbol


async def _run_commit(
    sample: pd.DataFrame, settings: Settings, timeframes: tuple[str, ...] | None
) -> dict[str, int]:
    """--commit mode: qualify + write every drawn symbol through
    onboard_instrument() (the sole sanctioned write path, D-08/T-174-02/T-174-03).
    Runs the gateway pre-flight probe first and aborts before the loop if it
    fails (T-174-50).
    """
    ok, probe_symbol = await _gateway_preflight(settings)
    if not ok:
        raise RuntimeError(
            "universe_expansion_stratified_sourcing: ib-gateway pre-flight probe "
            f"failed (qualify_instrument returned False for known-good symbol "
            f"{probe_symbol!r} via 127.0.0.1:7497). Aborting before the onboarding "
            "loop -- a stopped/logged-out gateway would otherwise silently reject "
            "every symbol and report a 100% rejection rate that looks like a data "
            "problem, not an infrastructure one. Check `docker ps --filter "
            "name=ib-gateway`."
        )

    provider = IBKRProvider(
        host=settings.ib_host, port=settings.ib_port, client_id=_GATEWAY_PROBE_CLIENT_ID
    )
    connected = await provider.connect()
    if not connected:
        raise RuntimeError(
            "universe_expansion_stratified_sourcing: ib-gateway connection lost "
            "between the pre-flight probe and the onboarding loop start."
        )

    n_onboarded = 0
    n_rejected = 0
    db = DatabaseManager(settings.database_url)
    await db.initialize()
    try:
        async with db.pool.acquire() as conn, conn.transaction():
            if timeframes is None:
                timeframes = await load_compute_timeframes(conn)  # once per run
            for row in sample.itertuples(index=False):
                instrument = Instrument(
                    symbol=row.symbol,
                    base=row.symbol,
                    name=row.name,
                    asset_class=AssetClass.EQUITY,
                    exchange="SMART",
                    sector="",
                    tick_size=0.01,
                    session_id="nyse",
                    point_value=1.0,
                    provider_meta={},
                )
                try:
                    await onboard_instrument(
                        conn,
                        instrument,
                        qualifier=provider,
                        tags=_SAMPLE_TAGS,
                        timeframes=timeframes,
                        metadata_skip_reason=(
                            "Phase 174 D-02 stratified sample -- issuer-level "
                            "metadata (listing_date/underlying_index/issuer) not "
                            "available from the IWV holdings export's narrow "
                            "symbol/name/index_position_value contract; a follow-on pass can "
                            "backfill this from a per-symbol data source if needed."
                        ),
                        compute_eligible=False,
                        live_tradeable=False,
                    )
                    n_onboarded += 1
                except OnboardingRejected:
                    n_rejected += 1
    finally:
        await provider.disconnect()
        await db.close()

    return {"n_onboarded": n_onboarded, "n_rejected": n_rejected}


async def _async_main(args: argparse.Namespace) -> int:
    settings = Settings()
    dsn = settings.database_url.replace("postgresql+asyncpg://", "postgresql://")
    with psycopg.connect(dsn) as conn, conn.cursor() as cur:
        seed = _fetch_apr(cur, "alpha.universe.stratified_sample_random_state", 42)
        bucket_count = _fetch_apr(cur, "alpha.universe.cap_bucket_count", 10)
        target_size = _fetch_apr(cur, "alpha.universe.target_sample_size", 0)
        cur.execute("SELECT symbol FROM instruments")
        exclude = {row[0] for row in cur.fetchall()}

    if target_size <= 0:
        print(
            "FAILED: alpha.universe.target_sample_size is 0 (UNSET). Per D-01, "
            "this phase does not lock a target instrument count -- Plan 11 must "
            "set this key from a measured ic_engine scale-up result before this "
            "script can draw a sample.",
            file=sys.stderr,
        )
        return 1

    holdings_sha256 = _sha256_of(args.holdings)
    population = parse_holdings(args.holdings)

    sample = stratified_sample(
        population, target_size=target_size, bucket_count=bucket_count, seed=seed, exclude=exclude
    )

    print(
        "Provenance:",
        {
            "holdings_file": str(args.holdings),
            "holdings_sha256": holdings_sha256,
            "stratified_sample_random_state": seed,
            "cap_bucket_count": bucket_count,
            "target_sample_size": target_size,
            "n_excluded": len(exclude),
            "exclude_set_sha256": exclude_set_sha256(exclude),
            "n_drawn": len(sample),
        },
    )

    if not args.commit:
        timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        dest = Path(f"/var/tmp/universe_expansion_stratified_sample_{timestamp}.csv")
        sample.to_csv(dest, index=False, quoting=csv.QUOTE_MINIMAL)
        print(f"Dry run -- wrote drawn list to {dest} (no database writes).")
        bucketed_pop = _bucket_population(population, bucket_count=bucket_count, exclude=exclude)
        _print_bucket_summary(sample, bucketed_pop)
        return 0

    timeframes = tuple(args.timeframes.split(",")) if args.timeframes else None
    result = await _run_commit(sample, settings, timeframes)
    print(
        "Commit run complete:",
        {
            "n_population": len(population),
            "n_excluded": len(exclude),
            "n_drawn": len(sample),
            **result,
        },
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Market-cap-stratified random sample from the Russell 3000 population "
            "(Phase 174 D-02). Dry-run by default -- writing is opt-in via --commit."
        )
    )
    parser.add_argument(
        "--holdings", type=Path, required=True, help="Path to a downloaded IWV holdings CSV."
    )
    add_write_mode_args(
        parser,
        dry_run="Dry-run only (default): draw the sample, write a CSV, make no database writes.",
        commit=(
            "Actually write to instruments/instrument_tags/instrument_metadata/"
            "backfill_status via onboard_instrument(). Off by default -- writing "
            "is opt-in, not opt-out. Plan 08 does NOT run this mode; Plan 12 owns "
            "the real run."
        ),
    )
    parser.add_argument(
        "--timeframes",
        default=None,
        help=(
            "Comma-separated timeframes seeded into backfill_status on commit (default: the "
            "APR compute stack, feature.factory.target_timeframes)."
        ),
    )
    args = parser.parse_args(argv)

    status = "success"
    try:
        import asyncio

        return_code = asyncio.run(_async_main(args))
    except Exception as error:
        status = "failure"
        _logger.error("universe_expansion_stratified_sourcing.failed", error=str(error))
        print(f"FAILED: {error}", file=sys.stderr)
        return 1
    finally:
        JOB_COMPLETED_TOTAL.add(
            1, {"job": "universe-expansion-stratified-sourcing", "status": status}
        )
        flush_and_shutdown_metrics()
    return return_code


if __name__ == "__main__":
    from src.observability.otel import OTelInitError, init_otel_providers

    try:
        init_otel_providers("universe-expansion-stratified-sourcing")
    except OTelInitError as error:
        print(f"[warn] OTel init failed -- metrics disabled: {error}")
    sys.exit(main())
