#!/usr/bin/env python3
"""Extension of workstream 0b (personal_cost_hurdle.py) to the intraday tiers (5m, 15m,
1h) -- a gap surfaced 2026-09-13 scoping universe expansion (user question: "do we need
to reduce TFs? is 5m/1m really useful?"). Fable's review (consulted before writing this)
found the sharper question wasn't "does 5m have raw FDR-passing signal" (it does --
5m's FDR-pass rate is 2.05%, actually the HIGHEST of the four active tiers, vs 1d's
1.75%) but "has 5m's own TURNOVER-ADJUSTED economics ever been tested." It hadn't:
personal_cost_hurdle.py is hardcoded `tf = '1d'` in both its spread and turnover
queries, and the original workstream 0b never ran at any intraday tf.

NOT a re-derivation of 0b's spread anchor -- reuses the already-measured, already-
validated live median (1.4bp, `_LIVE_SPREAD_ANCHOR` from range_pct_fast_xs_ls_h5_
falsification.py / personal_edge_paper_screen.py). What's new here: (1) turnover
measured per-BAR (not per-calendar-date) at each intraday tf's own rank series, (2) the
annualization term generalized from "252 trading days / H calendar days" to "bars per
year / H bars", using each tf's REAL measured bars-per-trading-day (not an assumed
constant), and (3) the resulting IC_min compared directly against the REAL measured avg
IC at that tf's own `lookahead_bars` values already used in feature_ic_scores (5m:
1/6/12/39; 15m: 1/2/5/10; 1h: 1/2/20/60 -- read live from the table, not assumed).

Scoping/diagnostic, not a construction falsification -- no PASS/FAIL gate, no
concept_registry row. Produces a decision input for how to scope universe expansion's
TF stack, the same character as workstream 0a/0b's original measurements.

Read-only against feature_vectors / feature_ic_scores. No writes.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from services.backfill_feature_factory import _connect_db  # noqa: E402
from src.config.settings import Settings  # noqa: E402

_SIGMA_TARGET = 0.16
_COMMISSION_PER_SHARE = 0.0035
_ASSUMED_PRICE = 50.0
_COMMISSION_FRAC = _COMMISSION_PER_SHARE / _ASSUMED_PRICE
_LIVE_SPREAD_ANCHOR = 0.00014  # 1.4bp, measured 0b, validated against live quotes
_TRADING_DAYS_PER_YEAR = 252
_TFS = ("5m", "15m", "1h", "1d")
_TURNOVER_FEATURE = "range_to_close"  # 0b's strongest long-horizon family member
_UNIVERSE_BREADTHS = (4.5, 8.4)  # 0a's measured range
_LIBRARY_RANKS = (3.0, 10.0)  # 0b's sensitivity range when not pinned


def _fetch_ranks(conn, feature: str, tf: str) -> pd.DataFrame:
    """Per-bar cross-sectional rank (not per-calendar-date -- intraday rebalancing
    happens every N bars, not every N days). Streamed from a server-side cursor straight
    into a (bar x symbol) float32 matrix: 5m holds ~75M rows, far too many to fetchall."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT DISTINCT symbol FROM feature_vectors WHERE tf = %s ORDER BY symbol", (tf,)
        )
        symbols = [r[0] for r in cur.fetchall()]
        cur.execute(
            f"SELECT count(DISTINCT bar_ts) FROM feature_vectors "
            f"WHERE tf = %s AND {feature} IS NOT NULL",
            (tf,),
        )
        (n_bars,) = cur.fetchone()
    sym_idx = {s: i for i, s in enumerate(symbols)}
    mat = np.full((n_bars, len(symbols)), np.nan, dtype=np.float32)
    bar_index: list = []
    # A server-side cursor needs a transaction block; _connect_db's connection is autocommit.
    with conn.transaction(), conn.cursor(name=f"ranks_{tf}") as cur:
        cur.itersize = 1_000_000
        cur.execute(
            f"""
            SELECT bar_ts, symbol,
                   percent_rank() OVER (PARTITION BY bar_ts ORDER BY {feature}) AS rank
            FROM feature_vectors
            WHERE tf = %s AND {feature} IS NOT NULL
            ORDER BY bar_ts, symbol
            """,
            (tf,),
        )
        last_ts = None
        for bar_ts, symbol, rank in cur:
            if bar_ts != last_ts:
                bar_index.append(bar_ts)
                last_ts = bar_ts
            mat[len(bar_index) - 1, sym_idx[symbol]] = rank
    return pd.DataFrame(mat[: len(bar_index)], index=bar_index, columns=symbols)


def _turnover(ranks: pd.DataFrame, horizon_bars: int) -> float | None:
    """Mean absolute cross-sectional rank change per H-bar rebalance (per side).
    Identical logic to personal_cost_hurdle.py's _turnover -- generic over the index
    unit (bars here instead of calendar days)."""
    if len(ranks) <= horizon_bars + 5:
        return None
    diff = (ranks - ranks.shift(horizon_bars)).abs()
    vals = diff.dropna(how="all").to_numpy().ravel()
    vals = vals[~np.isnan(vals)]
    if len(vals) == 0:
        return None
    return float(vals.mean())


def _bars_per_trading_day(conn, tf: str) -> float:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT count(*)::float / count(DISTINCT bar_ts::date)
            FROM feature_vectors WHERE tf = %s AND symbol = 'SPY'
            """,
            (tf,),
        )
        (val,) = cur.fetchone()
    return float(val)


def _lookahead_bars_for_tf(conn, tf: str) -> list[int]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT DISTINCT lookahead_bars FROM feature_ic_scores
            WHERE tf = %s AND is_pooled AND symbol = 'POOLED' AND reliable
              AND regime_scope <> 'earnings_season'
            ORDER BY lookahead_bars
            """,
            (tf,),
        )
        return [r[0] for r in cur.fetchall()]


def _measured_ic_at(conn, tf: str, lookahead_bars: int) -> tuple[float | None, int]:
    """Mean |ic_value| and count across FDR-passing pooled cells at this exact
    (tf, lookahead_bars) -- the real measured signal mass to compare IC_min against."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT avg(abs(ic_value)), count(*)
            FROM feature_ic_scores
            WHERE tf = %s AND lookahead_bars = %s
              AND is_pooled AND symbol = 'POOLED' AND reliable
              AND ic_ci_lower > 0 AND passes_fdr
              AND regime_scope <> 'earnings_season'
            """,
            (tf, lookahead_bars),
        )
        avg_ic, n = cur.fetchone()
    return (float(avg_ic) if avg_ic is not None else None, int(n))


def main() -> None:
    settings = Settings()
    conn = _connect_db(settings)

    print(f"Spread anchor (reused from 0b, live-validated): {_LIVE_SPREAD_ANCHOR * 1e4:.1f}bp")
    one_way = _LIVE_SPREAD_ANCHOR / 2 + _COMMISSION_FRAC
    print(f"One-way cost (half-spread + commission): {one_way * 1e4:.2f}bp")

    header = (
        f"\n{'tf':>4s} {'H(bars)':>8s} {'bars/day':>9s} {'TO':>6s} {'ann.rebal/yr':>13s} "
        f"{'lib_rank':>8s} {'bets':>6s} {'IC_min':>8s} {'measured_avg_ic':>16s} "
        f"{'n_cells':>8s} {'clears?':>8s} {'IC_min/ic':>10s}"
    )
    print(header)

    # Todo 389 pre-registered rule: a cell is a deletion candidate only if it fails the hurdle
    # by at least 5x at EVERY grid point, i.e. min over the grid of IC_min / measured >= 5.
    min_margin: dict[tuple[str, int], float] = {}
    for tf in _TFS:
        bars_per_day = _bars_per_trading_day(conn, tf)
        bars_per_year = _TRADING_DAYS_PER_YEAR * bars_per_day
        ranks = _fetch_ranks(conn, _TURNOVER_FEATURE, tf)
        horizons = _lookahead_bars_for_tf(conn, tf)

        for h in horizons:
            to = _turnover(ranks, h)
            if to is None:
                print(f"{tf:>4s} {h:>8d}  turnover unavailable (insufficient bars) -- skipped")
                continue
            measured_ic, n_cells = _measured_ic_at(conn, tf, h)
            rebal_per_year = bars_per_year / h
            drag = rebal_per_year * 2 * to * one_way
            for lib_rank in _LIBRARY_RANKS:
                for ub in _UNIVERSE_BREADTHS:
                    bets = lib_rank * ub
                    ic_min = drag / (_SIGMA_TARGET * np.sqrt(bets))
                    clears = (
                        "YES"
                        if (measured_ic is not None and measured_ic > ic_min)
                        else ("NO" if measured_ic is not None else "n/a")
                    )
                    ic_str = f"{measured_ic:.4f}" if measured_ic is not None else "n/a"
                    margin = ic_min / measured_ic if measured_ic else float("nan")
                    # No measured IC means nothing to judge: never a deletion candidate.
                    if measured_ic:
                        key = (tf, h)
                        min_margin[key] = min(min_margin.get(key, float("inf")), margin)
                    print(
                        f"{tf:>4s} {h:>8d} {bars_per_day:>9.2f} {to:>6.3f} "
                        f"{rebal_per_year:>13.1f} {lib_rank:>8.0f} {bets:>6.0f} "
                        f"{ic_min:>8.4f} {ic_str:>16s} {n_cells:>8d} {clears:>8s} {margin:>10.2f}"
                    )
    conn.close()

    print("\nMin IC_min/measured over the 2x2 grid (>= 5 on every point = fails uniformly by 5x):")
    for (tf, h), m in min_margin.items():
        verdict = "FAILS_UNIFORMLY_5X" if m >= 5 else "KEEP"
        print(f"  {tf:>4s} H={h:<4d} min_margin={m:8.2f}  {verdict}")

    print(
        "\nReading this table: IC_min is the gross cross-sectional IC a construction must "
        "exceed at that (tf, horizon, turnover, breadth) to break even, using the SAME "
        "live-validated 1.4bp spread anchor and cost model as 0b's 1d table -- only the "
        "annualization and turnover measurement are tf-native (bars, not calendar days). "
        "'measured_avg_ic' is the real mean |IC| across FDR-passing pooled cells at that "
        "exact (tf, lookahead_bars) in feature_ic_scores, not an assumption. This is a "
        "scoping diagnostic for the universe-expansion TF-stack decision, not a "
        "construction falsification -- no PASS/FAIL gate, no concept_registry row."
    )


if __name__ == "__main__":
    main()
