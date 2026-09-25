#!/usr/bin/env python3
"""Residual breadth diagnostic: step 0 of docs/plans/2026-09-25-alpha-research-architecture.md.

How many independent bets does the compute_eligible universe carry at 1d, 1h and 15m once
common moves are removed? Effective breadth is the participation ratio of the return
correlation matrix's eigenvalues (effective_breadth_diagnostic.py's method), reported for:

- raw returns;
- market residuals: each name regressed on the equal-weighted universe return;
- market + sector residuals: also on the leave-one-out equal-weighted return of its
  `contract_details->>'sector'` group (groups of 3 or more names; others get market only);
- the eigenvalue tail after the top K principal components of the raw correlation matrix;
- a noise ceiling: raw returns with each column's time order permuted independently, which
  shows how much of the measured breadth sample size alone allows (Marchenko-Pastur).

Returns are in-session only for intraday tfs: the first bar of a session is its own
open-to-close, later bars are close-to-close, so overnight gaps never enter. Correlations are
pairwise-complete over overlapping observations, computed with masked matrix products.
Loadings are full-sample: a diagnostic of structure, not a causal residual for a test.

Read-only (default_transaction_read_only on). Window ends before alpha.validation.oos_start.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from scripts.analysis.effective_breadth_diagnostic import _participation_ratio_breadth  # noqa: E402
from scripts.analysis.sleeve_walk_forward.config import DEFAULT_CONFIG  # noqa: E402
from scripts.analysis.sleeve_walk_forward.snapshot import read_only_pool  # noqa: E402
from src.config.settings import Settings, dimension_where_clause  # noqa: E402
from src.intelligence.research.factors import leave_one_out_mean  # noqa: E402

_PC_TAIL_K = (1, 3, 5, 10, 20)
_MIN_SECTOR_SIZE = 3
_MIN_OVERLAP = 100
_SEED = 0

_UNIVERSE_SQL = (
    "SELECT i.symbol, coalesce(nullif(i.contract_details->>'sector', ''), '') "
    f"FROM instruments i WHERE {dimension_where_clause('compute', 'i')} ORDER BY i.symbol"
)
_OOS_START_SQL = (
    "SELECT config_value FROM config_state WHERE config_key = 'alpha.validation.oos_start'"
)
_BARS_SQL = (
    "SELECT timestamp, open, close FROM market_data_ohlcv_tradeable "
    "WHERE symbol = $1 AND timeframe = $2 AND timestamp >= $3 AND timestamp < $4 "
    "ORDER BY timestamp"
)


def bar_returns(ts: pd.DatetimeIndex, open_: np.ndarray, close: np.ndarray, tf: str) -> pd.Series:
    """Log returns; intraday bars never span the overnight gap."""
    with np.errstate(invalid="ignore", divide="ignore"):
        log_close = np.log(np.where(close > 0, close, np.nan))
        log_open = np.log(np.where(open_ > 0, open_, np.nan))
    r = np.empty(len(ts))
    r[0] = np.nan
    r[1:] = log_close[1:] - log_close[:-1]
    if tf != "1d":
        session = ts.tz_convert("America/New_York").normalize()
        first = np.ones(len(ts), dtype=bool)
        first[1:] = session[1:] != session[:-1]
        r[first] = log_close[first] - log_open[first]
    return pd.Series(r, index=ts)


async def fetch_panel(dsn: str, tf: str, start: str, end: str) -> tuple[pd.DataFrame, pd.Series]:
    pool = await read_only_pool(dsn)
    try:
        oos_start = await pool.fetchval(_OOS_START_SQL)
        if not oos_start:
            raise RuntimeError("alpha.validation.oos_start missing, refusing to run")
        lo, hi = pd.Timestamp(start, tz="UTC"), pd.Timestamp(end, tz="UTC")
        if hi > pd.Timestamp(oos_start, tz="UTC"):
            raise RuntimeError(f"--end {end} passes alpha.validation.oos_start {oos_start}")
        universe = await pool.fetch(_UNIVERSE_SQL)

        async def one(symbol: str) -> tuple[str, pd.Series]:
            rows = await pool.fetch(_BARS_SQL, symbol, tf, lo, hi)
            if not rows:
                return symbol, pd.Series(dtype=float)
            ts = pd.DatetimeIndex([r["timestamp"] for r in rows])
            o = np.array([r["open"] for r in rows], dtype=float)
            c = np.array([r["close"] for r in rows], dtype=float)
            return symbol, bar_returns(ts, o, c, tf)

        results = await asyncio.gather(*(one(r[0]) for r in universe))
    finally:
        await pool.close()
    panel = pd.DataFrame({s: r for s, r in results if len(r)}).sort_index()
    sectors = pd.Series({r[0]: r[1] for r in universe})
    return panel, sectors.reindex(panel.columns)


def pairwise_corr(x: np.ndarray) -> np.ndarray:
    """Pairwise-complete correlation of demeaned columns via masked products."""
    mask = np.isfinite(x)
    x0 = np.where(mask, x - np.nanmean(x, axis=0), 0.0)
    m = mask.astype(float)
    cross = x0.T @ x0
    sq = (x0**2).T @ m  # [i, j]: sum of x_i^2 over rows where j is also observed
    overlap = m.T @ m
    with np.errstate(invalid="ignore", divide="ignore"):
        corr = cross / np.sqrt(sq * sq.T)
    corr[overlap < _MIN_OVERLAP] = 0.0
    np.fill_diagonal(corr, 1.0)
    return corr


def residualize(x: np.ndarray, factors: list[np.ndarray]) -> np.ndarray:
    """Per column OLS on the given factor columns (each [T, N] or [T]) over finite rows."""
    out = np.full_like(x, np.nan)
    for j in range(x.shape[1]):
        cols = [f if f.ndim == 1 else f[:, j] for f in factors]
        design = np.column_stack([np.ones(len(x)), *cols])
        ok = np.isfinite(x[:, j]) & np.all(np.isfinite(design), axis=1)
        if ok.sum() < _MIN_OVERLAP:
            continue
        beta, *_ = np.linalg.lstsq(design[ok], x[ok, j], rcond=None)
        out[ok, j] = x[ok, j] - design[ok] @ beta
    return out


def group_ids(labels: tuple[str, ...], min_size: int) -> np.ndarray:
    """int [m]: a group id for names in a label group of at least min_size, -1 otherwise ('' is
    no group)."""
    labels = np.asarray(labels, dtype=object)
    out = np.full(len(labels), -1)
    for g, label in enumerate(sorted({x for x in labels if x})):
        members = labels == label
        if members.sum() >= min_size:
            out[members] = g
    return out


def breadth(corr: np.ndarray) -> dict[str, float]:
    n_eff, n = _participation_ratio_breadth(pd.DataFrame(corr))
    off = corr[~np.eye(n, dtype=bool)]
    eig = np.clip(np.sort(np.linalg.eigvalsh(corr))[::-1], 0.0, None)
    return {
        "n": n,
        "n_eff": round(n_eff, 1),
        "avg_pairwise_corr": round(float(off.mean()), 4),
        "top1_share": round(float(eig[0] / eig.sum()), 3),
    }


def pc_tail(corr: np.ndarray) -> dict[str, float]:
    eig = np.clip(np.sort(np.linalg.eigvalsh(corr))[::-1], 0.0, None)
    return {
        f"k{k}": round(float(eig[k:].sum() ** 2 / (eig[k:] ** 2).sum()), 1)
        for k in _PC_TAIL_K
        if k < len(eig)
    }


def measure(panel: pd.DataFrame, sectors: pd.Series, min_coverage: float) -> dict:
    keep = panel.notna().mean() >= min_coverage
    panel = panel.loc[:, keep]
    x = panel.to_numpy()
    sec = sectors.reindex(panel.columns).fillna("").to_numpy()
    market = np.nanmean(x, axis=1)
    raw_corr = pairwise_corr(x)
    rng = np.random.default_rng(_SEED)
    shuffled = np.column_stack([rng.permutation(x[:, j]) for j in range(x.shape[1])])
    loo = leave_one_out_mean(x, group_ids(tuple(sec), _MIN_SECTOR_SIZE))
    has_sector = np.isfinite(loo).any(axis=0)
    resid_ms = residualize(x, [market, np.where(has_sector, loo, 0.0)])
    return {
        "symbols": int(x.shape[1]),
        "dropped_low_coverage": int((~keep).sum()),
        "observations": int(x.shape[0]),
        "median_coverage": round(float(panel.notna().mean().median()), 3),
        "raw": breadth(raw_corr),
        "market_residual": breadth(pairwise_corr(residualize(x, [market]))),
        "market_sector_residual": breadth(pairwise_corr(resid_ms)),
        "raw_pc_tail": pc_tail(raw_corr),
        "noise_ceiling": breadth(pairwise_corr(shuffled)),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--tf", nargs="+", default=["1d", "1h", "15m"])
    parser.add_argument("--start", default="2019-01-01")
    parser.add_argument(
        "--end", default="2025-12-24", help="exclusive; checked against alpha.validation.oos_start"
    )
    parser.add_argument("--min-coverage", type=float, default=0.8)
    parser.add_argument("--sleeve-only", action="store_true", help="phase 179's 13 symbols")
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args()
    dsn = Settings().database_url.replace("postgresql+asyncpg://", "postgresql://")
    report = {"window": [args.start, args.end], "min_coverage": args.min_coverage, "tf": {}}
    for tf in args.tf:
        panel, sectors = asyncio.run(fetch_panel(dsn, tf, args.start, args.end))
        if args.sleeve_only:
            panel = panel.loc[:, [s for s in DEFAULT_CONFIG.sleeve if s in panel.columns]]
        report["tf"][tf] = measure(panel, sectors, args.min_coverage)
        print(tf, json.dumps(report["tf"][tf]), flush=True)
    if args.out:
        args.out.write_text(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
