#!/usr/bin/env python3
"""Todo 170: `volatility_pct` substitution test for `rates` at 15m/5m.

Phase 144's D-05 gate found F2 triggered for `rates` at 15m and 5m -- neither per-symbol HMM
nor the `rates` cross-sectional (curve_credit) label separates IC there. Per
`docs/research/fable-2026-07-07-phase144-conditioning-decision.md` Section 4, F2 is the
pre-registered build trigger for a factor-augmented HMM challenger, but ONLY pending
confirmation that `volatility_pct` hasn't already separately passed its own substitution gate
-- a cheaper candidate dimension that might resolve the gap without a heavier model build.

Protocol (`docs/research/stratification-dimension-unification.md` lines 290-309, "zero-schema-
change first probe"): compute the candidate on a small symbol set (not a full corpus run),
stamp it onto existing data, and compare IC Sharpe stratified by (existing_dimension_state,
candidate_state) jointly against the incumbent-only baseline. Pass criterion: IC Sharpe
increases by more than 10% in at least one joint cell, with N > 20,000 bars in that cell.

`volatility_pct` does not exist as a named column anywhere in this codebase (todo 170's own
finding -- `volatility_rank_z` is a stubbed, unimplemented placeholder, always NULL, see todo
103). This script computes it fresh, exactly as the research doc describes ("expanding
percentile rank of realized vol"): `yang_zhang_vol_z` (a real, live, non-null Renaissance-
primitive volatility estimator already in `feature_vectors`) run through
`causal_rank.causal_expanding_rank` (the same shared, look-ahead-safe rank helper todo 092's
fix uses for breadth_frac/curve_z/credit_z), then tercile-bucketed at 0.33/0.67 -- the same
convention todo 092 established.

Existing dimension tested against: `rates`' cross-sectional curve_credit label (`market_regimes`,
regime_group='rates') -- the side F2 found deficient. Symbol universe: all 12 `rates`-routed
symbols (`fi_*` instrument_tags), not a further-thinned 3-5 -- rates only has 12 total, so this
is already the small-scope probe the doc asks for, not the "full corpus run" it warns against.
Feature set: 113 of the 116 `quant`-domain columns in `FEATURE_VECTOR_DOMAIN`
(`src/intelligence/feature_factory.py`) -- excludes calendar/macro (identical across symbols
per bar, same reasoning T3's script used) and control (canaries). Also excludes "structural"
domain entirely (VP/SR, Phase 163 -- confirmed 100% NULL on historical rows, todo 176) and 3
unimplemented "quant" stubs (`momentum_rank_z`/`volatility_rank_z`/`volume_rank_z`, confirmed
100% NULL, todo 103) -- both confirmed live during this script's own development, not assumed.

**Deliberate methodological simplification, disclosed, not hidden:** IC Sharpe here uses
non-overlapping windows over the row sequence within each cell directly (same formula as
`ic_math.py`'s `_compute_ic_rolling_metrics`: mean(window ICs) / std(window ICs), same
APR-configured window size and min-windows gate, read live from `config_state` not
hardcoded), but WITHOUT `ic_engine`'s lookahead-aware subsampling stride. This is a fair
comparison for THIS script's purpose (baseline and candidate cells are both computed under
the identical simplification, so the relative "+10%" pass criterion is unaffected), but the
absolute IC Sharpe numbers here should not be cited as production-equivalent -- only the
relative comparison this test exists to make.

Usage: .venv/bin/python scripts/analysis/todo170_volatility_pct_substitution_test.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import asyncpg  # noqa: E402

from src.config.settings import Settings  # noqa: E402
from src.intelligence.feature_factory import FEATURE_VECTOR_DOMAIN  # noqa: E402
from src.intelligence.regime_signals.causal_rank import causal_expanding_rank  # noqa: E402
from src.intelligence.statistics.ic_math import compute_ic_vectorized  # noqa: E402

_TFS = ("15m", "5m")  # the two tfs F2 triggered on
_REGIME_GROUP = "rates"
_VOL_TERCILE_LOW = 0.33
_VOL_TERCILE_HIGH = 0.67
_N_BARS_GATE = 20_000
_SHARPE_UPLIFT_PASS = 1.10  # ">10% increase"
_N_NULL_SHUFFLES = 20
_NULL_SHUFFLE_SEED = 20260727  # this script's own date-derived seed, not a production APR key

# "structural" domain (VP/SR, Phase 163) is NULL on every historical row (todo 176, confirmed
# live 2026-07-27: 100% null for rates/15m) -- excluded entirely, not a partial-availability
# feature. `momentum_rank_z`/`volatility_rank_z`/`volume_rank_z` are unimplemented stubs within
# "quant" (todo 103, confirmed live: 100% null) -- also excluded. Every remaining "quant"
# feature confirmed 0% null for rates/15m during this script's development.
_UNIMPLEMENTED_STUBS = frozenset({"momentum_rank_z", "volatility_rank_z", "volume_rank_z"})
_FEATURE_COLS = sorted(
    k for k, v in FEATURE_VECTOR_DOMAIN.items() if v == "quant" and k not in _UNIMPLEMENTED_STUBS
)

_SQL_TEMPLATE = """
    SELECT fv.symbol, fv.bar_ts, fv.yang_zhang_vol_z,
           {feature_cols},
           fr.return_fast, fr.return_slow,
           mr.regime_label AS curve_credit_label
    FROM feature_vectors fv
    JOIN forward_returns fr
      ON fr.symbol = fv.symbol AND fr.tf = fv.tf AND fr.bar_ts = fv.bar_ts
    JOIN market_regimes mr
      ON mr.regime_group = $1 AND mr.tf = fv.tf AND mr.ts = fv.bar_ts
    WHERE fv.tf = $2
      AND fv.symbol = ANY($3::text[])
      AND fv.yang_zhang_vol_z IS NOT NULL
      AND fr.return_type = 'executable_open_to_open'
      AND fr.complete_fast = true
      AND fr.complete_slow = true
    ORDER BY fv.symbol, fv.bar_ts ASC
"""


async def _fetch_rates_symbols(conn: asyncpg.Connection) -> list[str]:
    rows = await conn.fetch(
        "SELECT DISTINCT symbol FROM instrument_tags WHERE tag LIKE 'fi\\_%' ORDER BY symbol"
    )
    return [r["symbol"] for r in rows]


async def _fetch_sharpe_config(conn: asyncpg.Connection) -> tuple[int, int]:
    """Live APR values, not code defaults -- matches this project's convention of trusting
    observed config_state over settings.py fallbacks."""
    row = await conn.fetchrow(
        "SELECT config_value FROM config_state WHERE config_key = 'alpha.ic.sharpe_window_size_subsampled'"
    )
    window_size = int(row["config_value"]) if row else 100
    row = await conn.fetchrow(
        "SELECT config_value FROM config_state WHERE config_key = 'alpha.ic.sharpe_min_windows'"
    )
    min_windows = int(row["config_value"]) if row else 30
    return window_size, min_windows


def _volatility_pct_bucket(vol_pct: float) -> str:
    if vol_pct < _VOL_TERCILE_LOW:
        return "vol_low"
    if vol_pct > _VOL_TERCILE_HIGH:
        return "vol_high"
    return "vol_mid"


def _ic_sharpe(
    X: np.ndarray, y: np.ndarray, window_size: int, min_windows: int
) -> tuple[np.ndarray, int]:
    """Mean(window ICs) / std(window ICs) over non-overlapping windows -- same formula as
    ic_math.py's _compute_ic_rolling_metrics, deliberately simplified subsampling (see module
    docstring). Returns (per-feature sharpe array, n_windows)."""
    n = len(y)
    n_windows_possible = n // window_size
    if n_windows_possible < min_windows:
        return np.full(X.shape[1], np.nan), n_windows_possible

    window_ics = []
    for w in range(n_windows_possible):
        start, end = w * window_size, (w + 1) * window_size
        wx, wy = X[start:end], y[start:end]
        window_ics.append(compute_ic_vectorized(wx, wy))
    window_ics_arr = np.array(window_ics)  # [n_windows, n_features]
    mean_ic = window_ics_arr.mean(axis=0)
    std_ic = window_ics_arr.std(axis=0)
    sharpe = np.where(std_ic > 1e-10, mean_ic / std_ic, np.nan)
    return sharpe, n_windows_possible


async def main() -> None:
    rng = np.random.default_rng(_NULL_SHUFFLE_SEED)
    settings = Settings()
    db_dsn = settings.database_url.replace("postgresql+asyncpg://", "postgresql://")
    conn = await asyncpg.connect(db_dsn)
    try:
        rates_symbols = await _fetch_rates_symbols(conn)
        window_size, min_windows = await _fetch_sharpe_config(conn)
        print(
            f"rates symbols ({len(rates_symbols)}): {rates_symbols}\n"
            f"IC Sharpe window_size={window_size} min_windows={min_windows} (live APR values)\n"
        )

        for tf in _TFS:
            feature_cols_sql = ", ".join(f"fv.{c}" for c in _FEATURE_COLS)
            sql = _SQL_TEMPLATE.format(feature_cols=feature_cols_sql)
            rows = await conn.fetch(sql, _REGIME_GROUP, tf, rates_symbols)
            if not rows:
                print(f"=== tf={tf}: no rows, skipping ===\n")
                continue

            df = pd.DataFrame([dict(r) for r in rows])
            df["bar_ts"] = pd.to_datetime(df["bar_ts"], utc=True)

            # volatility_pct: causal expanding rank of yang_zhang_vol_z, per symbol (never
            # pooled across symbols -- would leak cross-symbol information into a per-symbol
            # rank at a point in time before that symbol's own history justifies it).
            df["volatility_pct"] = df.groupby("symbol")["yang_zhang_vol_z"].transform(
                lambda s: causal_expanding_rank(s)
            )
            df["vol_bucket"] = df["volatility_pct"].apply(_volatility_pct_bucket)
            df = df.sort_values("bar_ts").reset_index(drop=True)

            print(
                f"=== tf={tf}: {len(df)} rows, {df['symbol'].nunique()} symbols, "
                f"{df['curve_credit_label'].nunique()} curve_credit labels ==="
            )

            for return_col in ("return_fast", "return_slow"):
                print(f"\n--- scale={return_col} ---")
                X_all = df[_FEATURE_COLS].to_numpy(dtype=float)
                y_all = df[return_col].to_numpy(dtype=float)

                baseline_sharpe_by_label: dict[str, np.ndarray] = {}
                for label, group in df.groupby("curve_credit_label"):
                    idx = group.index.to_numpy()
                    sharpe, n_windows = _ic_sharpe(X_all[idx], y_all[idx], window_size, min_windows)
                    baseline_sharpe_by_label[label] = sharpe
                    n_valid = int(np.sum(~np.isnan(sharpe)))
                    print(
                        f"  BASELINE curve_credit={label:<16} n={len(idx):>7} "
                        f"n_windows={n_windows:>4} median|sharpe|={np.nanmedian(np.abs(sharpe)):.4f} "
                        f"(n_features_with_signal={n_valid}/{len(_FEATURE_COLS)})"
                    )

                print()
                observed_max_uplift_count = 0
                any_n_gate_cleared = False
                for (label, vol_bucket), group in df.groupby(["curve_credit_label", "vol_bucket"]):
                    idx = group.index.to_numpy()
                    n = len(idx)
                    sharpe, n_windows = _ic_sharpe(X_all[idx], y_all[idx], window_size, min_windows)
                    baseline = baseline_sharpe_by_label.get(label)
                    if baseline is None:
                        continue
                    with np.errstate(invalid="ignore", divide="ignore"):
                        uplift = np.abs(sharpe) / np.abs(baseline)
                    n_cells_passing_uplift = int(
                        np.sum((uplift >= _SHARPE_UPLIFT_PASS) & ~np.isnan(uplift))
                    )
                    gate_n = n >= _N_BARS_GATE
                    if gate_n:
                        any_n_gate_cleared = True
                        observed_max_uplift_count = max(
                            observed_max_uplift_count, n_cells_passing_uplift
                        )
                    flag = (
                        "candidate"
                        if gate_n and n_cells_passing_uplift > 0
                        else ("n<20k, not a real gate outcome" if not gate_n else "no uplift")
                    )
                    print(
                        f"  JOINT curve_credit={label:<16} vol_bucket={vol_bucket:<8} n={n:>7} "
                        f"n_windows={n_windows:>4} n_features_uplift>10%={n_cells_passing_uplift:>3}/"
                        f"{len(_FEATURE_COLS)} [{flag}]"
                    )

                # Shuffled-ranking null (same discipline as every other falsifier script in
                # this project, e.g. t3_cross_sectional_long_short_ctf_momentum_check.py):
                # a broad "uplift" across many features when subdividing into smaller,
                # temporally-scattered sub-cells can be a pure partitioning artifact (smaller,
                # less contiguous windows can mechanically reduce inter-window serial
                # correlation, inflating Sharpe) -- NOT evidence volatility_pct carries real
                # information, unless it beats what a RANDOM same-shaped partition also
                # produces. Shuffle vol_bucket WITHIN each curve_credit_label group (preserves
                # each label's own bucket-size distribution), repeat the identical uplift-count
                # computation.
                null_max_counts = []
                for _ in range(_N_NULL_SHUFFLES):
                    shuffled_bucket = df.groupby("curve_credit_label")["vol_bucket"].transform(
                        lambda s: rng.permutation(s.to_numpy())
                    )
                    draw_max = 0
                    for (label, _bucket), group in df.groupby(
                        ["curve_credit_label", shuffled_bucket]
                    ):
                        idx = group.index.to_numpy()
                        if len(idx) < _N_BARS_GATE:
                            continue
                        sharpe, _ = _ic_sharpe(X_all[idx], y_all[idx], window_size, min_windows)
                        baseline = baseline_sharpe_by_label.get(label)
                        if baseline is None:
                            continue
                        with np.errstate(invalid="ignore", divide="ignore"):
                            uplift = np.abs(sharpe) / np.abs(baseline)
                        draw_max = max(
                            draw_max,
                            int(np.sum((uplift >= _SHARPE_UPLIFT_PASS) & ~np.isnan(uplift))),
                        )
                    null_max_counts.append(draw_max)

                null_arr = np.array(null_max_counts)
                null_p = (
                    float(np.mean(null_arr >= observed_max_uplift_count))
                    if any_n_gate_cleared
                    else 1.0
                )
                print(
                    f"\nShuffled-bucket null ({_N_NULL_SHUFFLES} draws): observed max "
                    f"n_features_uplift>10%={observed_max_uplift_count}, null mean="
                    f"{null_arr.mean():.1f} max={null_arr.max()}  P(null >= observed)={null_p:.3f}"
                )

                genuine_pass = (
                    any_n_gate_cleared and observed_max_uplift_count > 0 and null_p < 0.05
                )
                print(
                    f"\nVERDICT (tf={tf}, scale={return_col}): "
                    + (
                        "PASSES -- at least one joint (curve_credit, volatility_pct) cell clears "
                        "N>20,000, shows >10% IC Sharpe uplift, AND beats the shuffled-bucket "
                        "null (not explained by partitioning into smaller cells alone). "
                        "volatility_pct is a real candidate; revisit before building the "
                        "factor-augmented HMM challenger."
                        if genuine_pass
                        else "FAILS -- either no joint cell clears N>20,000 with real uplift, or "
                        "the apparent uplift does not beat what a random same-shaped partition "
                        "also produces (partitioning artifact, not real volatility_pct "
                        "information). volatility_pct does not resolve rates' F2 gap on its own."
                    )
                )
            print()
    finally:
        await conn.close()


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())
