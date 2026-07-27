"""Edge Source Thesis T3 falsification test (cross-sectional relative mispricing).

docs/research/data-edge-source-thesis.md T3: "cross-sectional long-short spread portfolios
built from feature rankings must show positive net return where per-symbol directional trades
on the same features don't." Todo 179 already falsified T2 (regime-conditional absolute
direction) exhaustively -- this script tests the structurally different, lower-IC-bar
construction docs/research/trade-construction-layer.md proposes: rank symbols cross-sectionally
at each bar, long the top decile, short the bottom decile, dollar-neutral.

Feature choice: `ctf_momentum` (cross-timeframe momentum alignment), selected from a live
feature_ic_scores query as the strongest, most cross-regime-consistent-sign symbol-varying
feature in the equity/15m corpus (ic_value ~0.10-0.13, positive sign in low_bear/high_bear/
high_neutral/high_bull/mid_bear alike) -- explicitly NOT a calendar/macro feature (those are
identical across symbols on a given bar and cannot be cross-sectionally ranked at all).

Reuses services/counterfactual_tracker.py's frame_gate_passes verbatim (same day-clustered
BCa/CLT bootstrap machinery as todo 179 and FRAME-04) -- no new statistics invented. Also
computes a shuffled-ranking null (trade-construction-layer.md's own required guard): the
construction must beat noise from dollar-neutral bucket formation alone, not just clear zero.

Cost-hurdle treatment (added 2026-07-26, ROADMAP Phase 167's first open item -- the prior
gross-only result cannot be scoped into a phase plan without this): applies todo 030's
blended round-trip cost-floor convention (~1bp liquid core, ~2-4bp sector ETFs, ~6-10bp
illiquid international) to the ACTUAL realized leg turnover of this specific construction --
more precise than todo 030's own median-IC-implied-E[R] method (built before this construction
existed to measure directly), since a spread portfolio only pays cost on the changed fraction
of each leg, not on every position every bar (trade-construction-layer.md's own point: a long-
short spread's cost dynamics differ from a directional trade's).

Usage: .venv/bin/python scripts/analysis/t3_cross_sectional_long_short_ctf_momentum_check.py
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import asyncpg  # noqa: E402

from services.counterfactual_tracker import (  # noqa: E402
    _DEFAULT_BOOTSTRAP_RANDOM_STATE,
    frame_gate_passes,
)
from src.config.settings import Settings  # noqa: E402

_TF = "15m"
_FEATURE = "ctf_momentum"
_DECILE_FRACTION = 0.10  # top/bottom 10% of the ranked equity universe per bar
_N_NULL_SHUFFLES = 40
_SHUFFLE_SEED = _DEFAULT_BOOTSTRAP_RANDOM_STATE

# todo 030's blended round-trip cost-floor convention (Step 0, "1bp liquid core, ~2-4bp sector
# ETFs, ~6-10bp illiquid international"). Tested as a sweep, not a single number, since the
# real portfolio would span this whole liquidity range across 80 symbols.
_COST_HURDLE_BPS_ROUND_TRIP = (1, 3, 5, 10)

_FV_SQL = """
    SELECT fv.symbol, fv.bar_ts, fv.ctf_momentum,
           fr.return_fast, fr.return_slow
    FROM feature_vectors fv
    JOIN forward_returns fr
      ON fr.symbol = fv.symbol AND fr.tf = fv.tf AND fr.bar_ts = fv.bar_ts
    JOIN instruments i ON i.symbol = fv.symbol
    WHERE fv.tf = $1
      AND fv.ctf_momentum IS NOT NULL
      AND fr.return_type = 'executable_open_to_open'
      AND fr.complete_fast = true
      AND fr.complete_slow = true
      AND i.is_active = true
      AND i.contract_details->>'asset_class' = 'equity'
    ORDER BY fv.bar_ts ASC
"""


def _decile_spread_per_bar(df: pd.DataFrame, feature_col: str, return_col: str) -> pd.DataFrame:
    """One row per bar_ts: dollar-neutral top-decile-minus-bottom-decile spread return.

    Equal-weight legs (trade-construction-layer.md's deliberately minimal v1 design -- no
    vol-scaling, no Kelly, no risk model). Bars with too few symbols to form a real decile
    on each side (n < 10, i.e. fewer than 1 symbol per leg at 10%) are dropped, not zero-filled.
    """
    records = []
    for bar_ts, group in df.groupby("bar_ts"):
        n = len(group)
        n_leg = max(1, int(round(n * _DECILE_FRACTION)))
        if n < 2 * n_leg:
            continue
        ranked = group.sort_values(feature_col)
        short_leg = ranked.iloc[:n_leg]
        long_leg = ranked.iloc[-n_leg:]
        spread = float(long_leg[return_col].mean() - short_leg[return_col].mean())
        records.append({"bar_ts": bar_ts, "spread": spread, "n": n})
    return pd.DataFrame.from_records(records)


def _generate_shuffled_feature_draws(
    df: pd.DataFrame, feature_col: str, rng: np.random.Generator, n_shuffles: int
) -> list[np.ndarray]:
    """Precompute N within-bar_ts permutations of feature_col, once. The permutation doesn't
    depend on which return scale is being tested, so both scales reuse the identical N draws
    instead of each independently re-shuffling and re-splitting deciles (efficiency review,
    2026-07-26 /simplify pass -- this was the dominant cost in the script)."""
    return [
        df.groupby("bar_ts")[feature_col]
        .transform(lambda s: rng.permutation(s.to_numpy()))
        .to_numpy()
        for _ in range(n_shuffles)
    ]


def _null_spread_from_shuffled_feature(
    df: pd.DataFrame, feature_col: str, return_col: str, shuffled_feature: np.ndarray
) -> float:
    """One shuffled-ranking draw's mean spread, given an already-permuted feature array (see
    _generate_shuffled_feature_draws). Under the null, the ranking carries no information --
    any nonzero result here is a pure construction artifact (todo 179 discipline: same guard
    as this project's every other permutation-null check)."""
    shuffled = df.copy()
    shuffled[feature_col] = shuffled_feature
    spreads = _decile_spread_per_bar(shuffled, feature_col, return_col)
    if spreads.empty:
        return 0.0
    return float(spreads["spread"].mean())


def _legs_per_bar(
    df: pd.DataFrame, feature_col: str
) -> dict[pd.Timestamp, tuple[frozenset, frozenset]]:
    """One (short_leg, long_leg) symbol-set pair per bar_ts -- the same decile split
    _decile_spread_per_bar uses, but keyed by bar_ts so turnover (leg membership CHANGE
    bar-to-bar) can be measured directly."""
    legs = {}
    for bar_ts, group in df.groupby("bar_ts"):
        n = len(group)
        n_leg = max(1, int(round(n * _DECILE_FRACTION)))
        if n < 2 * n_leg:
            continue
        ranked = group.sort_values(feature_col)
        legs[bar_ts] = (
            frozenset(ranked.iloc[:n_leg]["symbol"]),
            frozenset(ranked.iloc[-n_leg:]["symbol"]),
        )
    return legs


def _cost_hurdle_check(df: pd.DataFrame, return_col: str, scale_name: str) -> None:
    """Todo 030 cost-floor treatment applied to THIS construction's actual turnover (not a
    flat per-trade cost): only the changed fraction of each leg incurs a trade each bar."""
    legs = _legs_per_bar(df, _FEATURE)
    bar_tss = sorted(legs.keys())
    if len(bar_tss) < 2:
        print(f"\n=== Cost hurdle ({scale_name}): insufficient bars, skipping ===")
        return

    one_way_turnovers = [0.0]
    for i in range(1, len(bar_tss)):
        prev_short, prev_long = legs[bar_tss[i - 1]]
        cur_short, cur_long = legs[bar_tss[i]]
        n_leg = len(cur_long)
        long_changed = len(cur_long - prev_long) / n_leg
        short_changed = len(cur_short - prev_short) / n_leg
        one_way_turnovers.append((long_changed + short_changed) / 2)
    turnover_series = pd.Series(one_way_turnovers, index=bar_tss)

    spread_records = []
    for bar_ts, group in df.groupby("bar_ts"):
        if bar_ts not in legs:
            continue
        short_syms, long_syms = legs[bar_ts]
        long_ret = group[group["symbol"].isin(long_syms)][return_col].mean()
        short_ret = group[group["symbol"].isin(short_syms)][return_col].mean()
        spread_records.append({"bar_ts": bar_ts, "spread": long_ret - short_ret})
    spread_df = pd.DataFrame(spread_records).set_index("bar_ts").reindex(bar_tss)

    gross_mean = float(spread_df["spread"].mean())
    print(f"\n=== Cost hurdle ({scale_name}): todo 030 blended cost-floor sweep ===")
    print(
        f"mean one-way leg turnover/bar={turnover_series.mean():.4f}  "
        f"median={turnover_series.median():.4f}  gross_mean_spread={gross_mean * 10000:.2f} bps/bar"
    )
    for cost_bps in _COST_HURDLE_BPS_ROUND_TRIP:
        cost_per_bar = (cost_bps / 10000) * turnover_series
        net_mean = float((spread_df["spread"] - cost_per_bar).mean())
        print(
            f"  cost_hurdle={cost_bps}bp round-trip: net_mean_spread="
            f"{net_mean * 10000:.3f} bps/bar  (survives: {net_mean > 0})"
        )


def _run_one_scale(
    df: pd.DataFrame, return_col: str, scale_name: str, shuffled_feature_draws: list[np.ndarray]
) -> None:
    spreads = _decile_spread_per_bar(df, _FEATURE, return_col)
    print(
        f"\n=== T3 spread portfolio: {_FEATURE}, tf={_TF}, scale={scale_name} ({return_col}) ===",
        flush=True,
    )
    print(f"bars with a valid decile split: {len(spreads)}")
    if spreads.empty:
        print("insufficient data -- skipping")
        return

    cluster_ids = spreads["bar_ts"].dt.date.tolist()
    pnl_r_values = spreads["spread"].tolist()
    n_clusters = len(set(cluster_ids))
    passes, ci_lower, ci_upper = frame_gate_passes(
        pnl_r_values,
        cluster_ids,
        min_n=1,
        bootstrap_max_n=5000,
        bootstrap_batch=1000,
        bootstrap_random_state=_DEFAULT_BOOTSTRAP_RANDOM_STATE,
    )
    mean_spread = float(np.mean(pnl_r_values))
    print(
        f"n_bars={len(pnl_r_values)}  n_day_clusters={n_clusters}  "
        f"mean_spread={mean_spread:.8f}  ci_lower={ci_lower:.8f}  ci_upper={ci_upper:.8f}  "
        f"passes={passes}"
    )

    null_means_list = []
    for i, shuffled_feature in enumerate(shuffled_feature_draws):
        null_means_list.append(
            _null_spread_from_shuffled_feature(df, _FEATURE, return_col, shuffled_feature)
        )
        if (i + 1) % 5 == 0:
            print(f"  ...shuffle {i + 1}/{_N_NULL_SHUFFLES} done", flush=True)
    null_means = np.array(null_means_list)
    null_p = float(np.mean(null_means >= mean_spread))
    print(
        f"shuffled-ranking null ({_N_NULL_SHUFFLES} draws): "
        f"mean={null_means.mean():.8f}  std={null_means.std():.8f}  "
        f"P(null >= observed)={null_p:.4f}"
    )

    print(f"\nVERDICT ({scale_name}):", end=" ")
    if passes and null_p < 0.05:
        print(
            "PASSES real bootstrap CI (ci_lower > 0) AND clears the shuffled-ranking null "
            "(construction, not artifact) -- genuine T3 candidate, worth a closer look."
        )
    elif passes and null_p >= 0.05:
        print(
            "Bootstrap CI clears zero, but the shuffled-ranking null cannot be distinguished "
            "from the observed result -- likely a dollar-neutral construction artifact, not "
            "real ranking signal. Do not treat as a T3 pass."
        )
    else:
        print(
            "Does not clear its own bootstrap CI (ci_lower <= 0) -- T3 fails at this scale for "
            f"{_FEATURE}, same as T2's per-symbol absolute-direction result."
        )

    _cost_hurdle_check(df, return_col, scale_name)


async def main() -> None:
    settings = Settings()
    db_dsn = settings.database_url.replace("postgresql+asyncpg://", "postgresql://")
    conn = await asyncpg.connect(db_dsn)
    try:
        rows = await conn.fetch(_FV_SQL, _TF)
    finally:
        await conn.close()

    df = pd.DataFrame([dict(r) for r in rows])
    df["bar_ts"] = pd.to_datetime(df["bar_ts"], utc=True)
    print(
        f"Loaded {len(df)} equity {_TF} rows with non-null {_FEATURE} and complete forward returns.",
        flush=True,
    )
    print(
        f"Distinct symbols: {df['symbol'].nunique()}  Distinct bar_ts: {df['bar_ts'].nunique()}",
        flush=True,
    )

    rng = np.random.default_rng(_SHUFFLE_SEED)
    shuffled_feature_draws = _generate_shuffled_feature_draws(df, _FEATURE, rng, _N_NULL_SHUFFLES)

    _run_one_scale(df, "return_fast", "fast (lookahead=1)", shuffled_feature_draws)
    _run_one_scale(df, "return_slow", "slow (lookahead=20)", shuffled_feature_draws)


if __name__ == "__main__":
    asyncio.run(main())
