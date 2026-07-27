"""Edge Source Thesis T3 falsification test, generalized across the CTF feature family.

Parameterized sibling of `t3_cross_sectional_long_short_ctf_momentum_check.py` -- same
identical methodology (day-clustered BCa/CLT bootstrap via `frame_gate_passes`, shuffled-
ranking null, todo 030 cost-hurdle sweep), applied to `ctf_vwap_align` and `ctf_regime_align`,
`ctf_momentum`'s two untested siblings from the same `_build_ctf_series()` function in
`services/backfill_feature_factory.py`. All three are already computed and sitting in
`feature_vectors` -- this costs zero new data collection or feature engineering, just a
column swap, in service of the "should we have multiple CTF-family features" question
(cheap-before-expensive: test what's already computed before inventing anything new).

Usage: .venv/bin/python scripts/analysis/t3_ctf_family_check.py <feature_name>
  feature_name in {ctf_momentum, ctf_vwap_align, ctf_regime_align}
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
_ALLOWED_FEATURES = frozenset({"ctf_momentum", "ctf_vwap_align", "ctf_regime_align"})
_DECILE_FRACTION = 0.10  # top/bottom 10% of the ranked equity universe per bar
_N_NULL_SHUFFLES = 40
_SHUFFLE_SEED = _DEFAULT_BOOTSTRAP_RANDOM_STATE

# todo 030's blended round-trip cost-floor convention (Step 0, "1bp liquid core, ~2-4bp sector
# ETFs, ~6-10bp illiquid international"). Tested as a sweep, not a single number, since the
# real portfolio would span this whole liquidity range across 80 symbols.
_COST_HURDLE_BPS_ROUND_TRIP = (1, 3, 5, 10)

_FV_SQL_TEMPLATE = """
    SELECT fv.symbol, fv.bar_ts, fv.{feature} AS feature_val,
           fr.return_fast, fr.return_slow
    FROM feature_vectors fv
    JOIN forward_returns fr
      ON fr.symbol = fv.symbol AND fr.tf = fv.tf AND fr.bar_ts = fv.bar_ts
    JOIN instruments i ON i.symbol = fv.symbol
    WHERE fv.tf = $1
      AND fv.{feature} IS NOT NULL
      AND fr.return_type = 'executable_open_to_open'
      AND fr.complete_fast = true
      AND fr.complete_slow = true
      AND i.is_active = true
      AND i.contract_details->>'asset_class' = 'equity'
    ORDER BY fv.bar_ts ASC
"""

_FEATURE_COL = "feature_val"


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
    """Precompute N within-bar_ts permutations of feature_col, once (same efficiency fix as
    the ctf_momentum script's 2026-07-26 /simplify pass)."""
    return [
        df.groupby("bar_ts")[feature_col]
        .transform(lambda s: rng.permutation(s.to_numpy()))
        .to_numpy()
        for _ in range(n_shuffles)
    ]


def _null_spread_from_shuffled_feature(
    df: pd.DataFrame, feature_col: str, return_col: str, shuffled_feature: np.ndarray
) -> float:
    shuffled = df.copy()
    shuffled[feature_col] = shuffled_feature
    spreads = _decile_spread_per_bar(shuffled, feature_col, return_col)
    if spreads.empty:
        return 0.0
    return float(spreads["spread"].mean())


def _legs_per_bar(
    df: pd.DataFrame, feature_col: str
) -> dict[pd.Timestamp, tuple[frozenset, frozenset]]:
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


def _cost_hurdle_check(
    df: pd.DataFrame, feature_name: str, return_col: str, scale_name: str
) -> None:
    legs = _legs_per_bar(df, _FEATURE_COL)
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
    df: pd.DataFrame,
    feature_name: str,
    return_col: str,
    scale_name: str,
    shuffled_feature_draws: list[np.ndarray],
) -> None:
    spreads = _decile_spread_per_bar(df, _FEATURE_COL, return_col)
    print(
        f"\n=== T3 spread portfolio: {feature_name}, tf={_TF}, scale={scale_name} ({return_col}) ===",
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
            _null_spread_from_shuffled_feature(df, _FEATURE_COL, return_col, shuffled_feature)
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

    print(f"\nVERDICT ({feature_name}, {scale_name}):", end=" ")
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
            f"{feature_name}."
        )

    _cost_hurdle_check(df, feature_name, return_col, scale_name)


async def main() -> None:
    if len(sys.argv) != 2 or sys.argv[1] not in _ALLOWED_FEATURES:
        print(f"Usage: {sys.argv[0]} <{'|'.join(sorted(_ALLOWED_FEATURES))}>")
        sys.exit(1)
    feature_name = sys.argv[1]

    settings = Settings()
    db_dsn = settings.database_url.replace("postgresql+asyncpg://", "postgresql://")
    conn = await asyncpg.connect(db_dsn)
    try:
        sql = _FV_SQL_TEMPLATE.format(feature=feature_name)
        rows = await conn.fetch(sql, _TF)
    finally:
        await conn.close()

    df = pd.DataFrame([dict(r) for r in rows])
    df["bar_ts"] = pd.to_datetime(df["bar_ts"], utc=True)
    print(
        f"Loaded {len(df)} equity {_TF} rows with non-null {feature_name} and complete forward returns.",
        flush=True,
    )
    print(
        f"Distinct symbols: {df['symbol'].nunique()}  Distinct bar_ts: {df['bar_ts'].nunique()}",
        flush=True,
    )

    rng = np.random.default_rng(_SHUFFLE_SEED)
    shuffled_feature_draws = _generate_shuffled_feature_draws(
        df, _FEATURE_COL, rng, _N_NULL_SHUFFLES
    )

    _run_one_scale(df, feature_name, "return_fast", "fast (lookahead=1)", shuffled_feature_draws)
    _run_one_scale(df, feature_name, "return_slow", "slow (lookahead=20)", shuffled_feature_draws)


if __name__ == "__main__":
    asyncio.run(main())
