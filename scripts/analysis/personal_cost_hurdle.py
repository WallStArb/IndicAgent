#!/usr/bin/env python3
"""Workstream 0b of docs/plans/2026-09-02-personal-scale-edge-determination-plan.md:
the personal-scale cost hurdle FUNCTION -- minimum viable IC as a function of horizon,
turnover, and spread, calibrated to a personal IBKR account rather than institutional
constraints.

Pre-registered assumptions (committed in the program doc BEFORE any candidate placement;
changing any of these after seeing a placement invalidates the placement):
- Spreads: Corwin-Schultz (2012) high-low estimator from existing 1d OHLC, per symbol,
  negative daily estimates floored at 0 (standard treatment), time-averaged.
- Spread validation: one-off live top-of-book via IBKRProvider.get_quote for ~20 liquid
  symbols. VALIDATED iff median (CS/live) ratio within [0.5, 3.0]. If the snapshot cannot
  be pulled or validation fails, the estimator is flagged UNVALIDATED and all hurdle
  numbers are reported across a spread sensitivity band (x0.5 / x1 / x2) -- conclusions
  that survive the whole band do not depend on the estimator being right; conclusions
  that don't are explicitly marked as not yet supportable.
- Commissions: IBKR tiered USD 0.0035/share; price assumption USD 50/share -> 0.7 bps
  per side (dominant ETFs trade USD 20-400; stated, not hidden).
- Impact: negligible at personal clips (100-1000 shares) in liquid ETFs; stated, not
  modeled.
- sigma target: 16% annualized cross-sectional LS vol (Grinold-style IR -> return
  conversion).
- Turnover: MEASURED, not assumed -- mean absolute cross-sectional rank change of a
  representative feature per H-day rebalance, per side, from actual feature_vectors
  ranks. Representative features: range_to_close (the strongest long-horizon family
  member) and ctf_momentum (the momentum family's canonical member), so the two families
  the program cares about each get their own turnover profile.
- Breadth: universe breadth from effective_breadth_diagnostic.py's measured ~4.5-8.4 x
  library effective rank from workstream 0a (passed via --library-rank; if not given,
  a sensitivity range 3-10 is used and labeled as such).

Hurdle math (standard fundamental-law accounting, stated so it can be checked):
  one_way_cost = spread/2 + commission_frac          (half-spread + commission each way)
  drag_annual  = (252/H) * 2 * TO_H * one_way_cost    (long + short legs, per rebalance)
  net_IR       = IC * sqrt(breadth_total) - drag_annual / sigma
  IC_min       = drag_annual / (sigma * sqrt(breadth_total))

Read-only against market_data_ohlcv_tradeable / feature_vectors; the live quote pull is
read-only against the gateway. No writes.
"""

from __future__ import annotations

import argparse
import asyncio
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
_HORIZONS = [1, 2, 5, 10]
_VALIDATION_SYMBOLS = [
    "SPY",
    "QQQ",
    "IWM",
    "DIA",
    "XLK",
    "XLF",
    "XLE",
    "XLU",
    "TLT",
    "IEF",
    "GLD",
    "SLV",
    "EEM",
    "EFA",
    "LQD",
    "HYG",
    "AAPL",
    "MSFT",
    "JPM",
    "XOM",
]
_CS_VALIDATION_BAND = (0.5, 3.0)
_SPREAD_SENSITIVITY_BAND = (0.5, 1.0, 2.0)


def _corwin_schultz_daily(high: np.ndarray, low: np.ndarray) -> np.ndarray:
    """Daily Corwin-Schultz spread estimates (negative floored at 0), length == len(high)."""
    log_hl = np.log(np.maximum(high, 1e-10) / np.maximum(low, 1e-10))
    beta = log_hl**2 + np.roll(log_hl, 1) ** 2
    beta[0] = log_hl[0] ** 2
    h2 = np.maximum(high, np.roll(high, 1))
    l2 = np.minimum(low, np.roll(low, 1))
    gamma = np.log(np.maximum(h2, 1e-10) / np.maximum(l2, 1e-10)) ** 2
    gamma[0] = log_hl[0] ** 2
    k = 3 - 2 * np.sqrt(2)
    alpha = (np.sqrt(2 * beta) - np.sqrt(beta)) / k - np.sqrt(gamma / k)
    spread = 2 * (np.exp(alpha) - 1) / (1 + np.exp(alpha))
    return np.clip(spread, 0.0, None)[1:]  # drop the roll-artifact first row


def _estimate_spreads(conn) -> pd.Series:
    with conn.cursor() as cur:
        cur.execute("""
            SELECT symbol, timestamp, high, low
            FROM market_data_ohlcv_tradeable
            WHERE timeframe = '1d' AND timestamp >= now() - interval '2 years'
            ORDER BY symbol, timestamp
            """)
        rows = cur.fetchall()
    df = pd.DataFrame(rows, columns=["symbol", "ts", "high", "low"])
    out = {}
    for symbol, g in df.groupby("symbol"):
        arr = g.sort_values("ts")[["high", "low"]].to_numpy()
        if len(arr) < 250:
            continue
        daily = _corwin_schultz_daily(arr[:, 0], arr[:, 1])
        out[symbol] = float(np.mean(daily))
    return pd.Series(out, name="cs_spread")


async def _live_quote_ratios(
    cs: pd.Series, settings: Settings
) -> tuple[dict[str, float], dict[str, float], bool]:
    """Live top-of-book spread / price for validation symbols via the sanctioned provider
    path (all ib_async logic lives in src/providers/ibkr.py per CLAUDE.md -- this script
    only drives the provider's own public methods). Client ID 48: one-off diagnostic,
    within the <= 50 cap, clear of the 40 backfill / 35 provider defaults.

    Returns ({symbol: CS/live ratio}, {symbol: live spread fraction}, gateway_reachable).
    The live spread LEVELS matter even when validation fails: per the pre-registered rule,
    a failed CS validation means the estimator is unusable and live-derived spreads are
    the anchor; the ratio dict then documents the correction factor, not a pass."""
    from src.config.settings import get_active_contracts
    from src.providers.ibkr import IBKRProvider

    provider = IBKRProvider(host="127.0.0.1", port=7497, client_id=48, settings=settings)
    ratios: dict[str, float] = {}
    live_spreads: dict[str, float] = {}
    try:
        if not await provider.connect():
            return ratios, live_spreads, False
        instruments = {i.symbol: i for i in get_active_contracts(settings)}
        for symbol in _VALIDATION_SYMBOLS:
            if symbol not in cs.index or symbol not in instruments:
                continue
            try:
                if not await provider.qualify_instrument(instruments[symbol]):
                    continue
                quote = await provider.get_quote(symbol, timeout_sec=10)
            except Exception:
                continue
            if not quote:
                continue
            bid, ask = quote.get("bid"), quote.get("ask")
            if not bid or not ask or bid <= 0 or ask <= 0 or ask <= bid:
                continue
            live_spread = (ask - bid) / ((ask + bid) / 2)
            if live_spread > 0:
                live_spreads[symbol] = float(live_spread)
                ratios[symbol] = float(cs[symbol] / live_spread)
        return ratios, live_spreads, True
    finally:
        await provider.disconnect()


def _fetch_ranks(conn, feature: str) -> pd.DataFrame:
    with conn.cursor() as cur:
        cur.execute(f"""
            SELECT bar_ts::date AS d, symbol,
                   percent_rank() OVER (PARTITION BY bar_ts::date ORDER BY {feature}) AS rank
            FROM feature_vectors
            WHERE tf = '1d' AND {feature} IS NOT NULL
            ORDER BY d, symbol
            """)
        rows = cur.fetchall()
    return pd.DataFrame(rows, columns=["d", "symbol", "rank"]).pivot_table(
        index="d", columns="symbol", values="rank", aggfunc="last"
    )


def _turnover(ranks: pd.DataFrame, horizon: int) -> float | None:
    """Mean absolute cross-sectional rank change per H-day rebalance (per side)."""
    if len(ranks) <= horizon + 5:
        return None
    diff = (ranks - ranks.shift(horizon)).abs()
    vals = diff.dropna(how="all").to_numpy().ravel()
    vals = vals[~np.isnan(vals)]
    if len(vals) == 0:
        return None
    return float(vals.mean())


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--library-rank",
        type=float,
        default=None,
        help="Library effective rank from workstream 0a. Default: sensitivity range 3-10.",
    )
    parser.add_argument(
        "--skip-live",
        action="store_true",
        help="Skip the live top-of-book validation pull (gateway unavailable). "
        "Hurdle numbers then carry the UNVALIDATED banner + sensitivity band.",
    )
    args = parser.parse_args()

    settings = Settings()
    conn = _connect_db(settings)

    print("Estimating Corwin-Schultz spreads from 1d OHLC (trailing 2y)...")
    cs = _estimate_spreads(conn)
    print(
        f"  {len(cs)} symbols; median CS spread = {cs.median():.5f} "
        f"({cs.median() * 1e4:.1f} bps), p25 = {cs.quantile(0.25) * 1e4:.1f} bps, "
        f"p75 = {cs.quantile(0.75) * 1e4:.1f} bps"
    )

    validated = False
    live_spreads: dict[str, float] = {}
    ratios: dict[str, float] = {}
    live_cache = Path(
        "/tmp/claude-1000/-home-bg-dev-indicagent/5af34462-07c3-4b71-b9d6-45b9df7e00c8/scratchpad/0b_live_quotes.json"
    )
    if not args.skip_live:
        if live_cache.exists():
            import json

            cached = json.loads(live_cache.read_text())
            live_spreads = cached.get("live_spreads", {})
            ratios = cached.get("ratios", {})
            print(f"\nLive quotes loaded from cache ({len(live_spreads)} symbols) -- no re-pull.")
        else:
            print(
                f"\nPulling live top-of-book for {len(_VALIDATION_SYMBOLS)} validation symbols..."
            )
            try:
                ratios, live_spreads, reachable = asyncio.run(_live_quote_ratios(cs, settings))
            except Exception as error:
                print(f"  Live pull failed ({type(error).__name__}: {error}) -- UNVALIDATED path.")
                ratios, live_spreads, reachable = {}, {}, False
            if reachable and live_spreads:
                import json

                live_cache.parent.mkdir(parents=True, exist_ok=True)
                live_cache.write_text(json.dumps({"live_spreads": live_spreads, "ratios": ratios}))
        if live_spreads:
            live_med_bp = float(np.median(list(live_spreads.values()))) * 1e4
            print(f"  {len(live_spreads)} live quotes; median live spread = {live_med_bp:.1f} bps")
            lo, hi = _CS_VALIDATION_BAND
            med_ratio = float(np.median(list(ratios.values()))) if ratios else None
            if med_ratio is not None:
                validated = lo <= med_ratio <= hi
                print(
                    f"  median CS/live = {med_ratio:.2f} -> "
                    f"{'VALIDATED' if validated else 'FAILED'} (pre-registered band [{lo}, {hi}])"
                )
    else:
        print("\n--skip-live: UNVALIDATED path, no live anchor.")

    print("\nMeasuring turnover from actual cross-sectional ranks...")
    turnover_by_feature: dict[str, dict[int, float]] = {}
    for feature in ("range_to_close", "ctf_momentum"):
        try:
            ranks = _fetch_ranks(conn, feature)
        except Exception as error:
            print(f"  {feature}: unavailable ({type(error).__name__}) -- skipped")
            continue
        turnover_by_feature[feature] = {}
        for h in _HORIZONS:
            to = _turnover(ranks, h)
            if to is not None:
                turnover_by_feature[feature][h] = to
        pretty = ", ".join(
            f"H{h}={to:.3f}" for h, to in sorted(turnover_by_feature[feature].items())
        )
        print(f"  {feature}: {pretty}")
    conn.close()

    # Spread anchor, per the pre-registered fallback ladder:
    #   validated CS -> CS median; CS failed/unavailable but live quotes exist -> LIVE
    #   median (estimator declared unusable, live levels are the anchor, correction factor
    #   recorded); neither -> CS median with the strongest caveat.
    if validated:
        spread_med = float(cs.median())
        anchor = "CS (validated)"
    elif live_spreads:
        spread_med = float(np.median(list(live_spreads.values())))
        anchor = "LIVE top-of-book (CS estimator FAILED validation -- unusable)"
    else:
        spread_med = float(cs.median())
        anchor = "CS (UNVALIDATED, no live anchor)"
    print(f"\nSpread anchor: {anchor}; median = {spread_med * 1e4:.1f} bps")

    spreads = [spread_med] if validated else [spread_med * m for m in _SPREAD_SENSITIVITY_BAND]
    if not validated:
        print(f"Sensitivity band: {[f'{s * 1e4:.1f}bp' for s in spreads]}")

    library_ranks = [args.library_rank] if args.library_rank else [3.0, 10.0]
    universe_breadths = (4.5, 8.4)

    print(f"\n{'=' * 100}")
    print(
        f"PERSONAL-SCALE IC HURDLE (sigma={_SIGMA_TARGET:.0%}, commission={_COMMISSION_FRAC * 1e4:.1f}bp/side "
        f"at ${_ASSUMED_PRICE:.0f}/sh) -- {'VALIDATED' if validated else 'UNVALIDATED (sensitivity band)'}"
    )
    print(f"{'=' * 100}")
    header = f"{'feature':16s} {'H':>3s} {'TO':>6s} {'spread':>8s} {'lib_rank':>8s} {'bets':>6s} {'IC_min':>8s}"
    print(header)
    for feature, tos in turnover_by_feature.items():
        for h, to in sorted(tos.items()):
            for spread in spreads:
                for lib_rank in library_ranks:
                    for ub in universe_breadths:
                        bets = lib_rank * ub
                        one_way = spread / 2 + _COMMISSION_FRAC
                        drag = (252 / h) * 2 * to * one_way
                        ic_min = drag / (_SIGMA_TARGET * np.sqrt(bets))
                        print(
                            f"{feature:16s} {h:>3d} {to:>6.3f} {spread * 1e4:>7.1f}bp "
                            f"{lib_rank:>8.0f} {bets:>6.0f} {ic_min:>8.4f}"
                        )
    print(
        "\nReading this table: IC_min is the gross cross-sectional IC a construction must "
        "exceed to break even at that horizon/turnover/spread/breadth. Compare against "
        "measured avg ICs in feature_ic_scores at the same horizon (e.g. the range/vol "
        "family's ~0.03-0.055 at H=5-10). Rows where measured IC > IC_min across the whole "
        "sensitivity band are supportable WITHOUT the spread estimator being validated."
    )


if __name__ == "__main__":
    main()
