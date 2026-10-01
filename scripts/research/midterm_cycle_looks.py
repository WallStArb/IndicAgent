"""Midterm presidential-cycle looks on S&P 500 history (descriptive, outside the runner).

Reproduces the numbers recorded in `docs/ideas/signal-political-policy-regime.md`:

- `look2`: the pre-registered look. Mean 6-month log return from election day, midterm years minus
  all other years, 1928-2025; one-sided permutation p (100,000 draws), bootstrap 95% interval,
  both halves; 12-month and cycle-phase means reported, not tested. Seed 20261001.
- `look3`: the exploratory window scan. 24 cells (entry -3..+2 months from election day, horizon
  3/6/9/12 months), family-wise p against the max permutation z over all cells (20,000 draws),
  plus monthly increments. Seed 20261002.
- `robust`: median excess, leave-one-out range (with a permutation p for the worst drop) and the
  drop-top-3 excess for four cells. Seed 20261003.

Data: `YAHOO_GSPC_CLOSE` (price-only) from `economic_series_observation_current`. Election day is
the Tuesday after the first Monday in November; a window runs from the last close at or before its
start to the last close at or before its end. Reads no forward span, writes nothing.

    .venv/bin/python scripts/research/midterm_cycle_looks.py look2|look3|robust
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import date, timedelta

import asyncpg
import numpy as np
import pandas as pd

sys.path.insert(0, ".")

from src.config.settings import Settings  # noqa: E402

SERIES_ID = "YAHOO_GSPC_CLOSE"
YEARS = list(range(1928, 2026))
MIDTERMS = [y for y in YEARS if y % 2 == 0 and y % 4 != 0]


async def _load_closes() -> pd.Series:
    dsn = Settings().database_url.replace("postgresql+asyncpg://", "postgresql://")
    conn = await asyncpg.connect(dsn)
    try:
        rows = await conn.fetch(
            "SELECT observation_date, value FROM economic_series_observation_current"
            " WHERE series_id = $1 ORDER BY observation_date",
            SERIES_ID,
        )
    finally:
        await conn.close()
    return pd.Series(
        {pd.Timestamp(r["observation_date"]): float(r["value"]) for r in rows}
    ).sort_index()


def election_day(year: int) -> pd.Timestamp:
    d = date(year, 11, 2)  # the Tuesday after the first Monday is the first Tuesday from Nov 2
    while d.weekday() != 1:
        d += timedelta(days=1)
    return pd.Timestamp(d)


def window_return(closes: pd.Series, year: int, entry_months: int, horizon_months: int) -> float:
    start = election_day(year) + pd.DateOffset(months=entry_months)
    end = start + pd.DateOffset(months=horizon_months)
    if end > closes.index[-1] or start < closes.index[0]:
        return np.nan
    return float(np.log(closes.loc[:end].iloc[-1] / closes.loc[:start].iloc[-1]))


def look2(closes: pd.Series) -> None:
    r6 = pd.Series({y: window_return(closes, y, 0, 6) for y in YEARS})
    r12 = pd.Series({y: window_return(closes, y, 0, 12) for y in YEARS}).dropna()
    assert r6.notna().all() and len(MIDTERMS) == 24
    others = [y for y in YEARS if y not in MIDTERMS]

    def diff(r: pd.Series, m: list[int]) -> float:
        return r[m].mean() - r.drop(m).mean()

    obs = diff(r6, MIDTERMS)
    rng = np.random.default_rng(20261001)
    vals = r6.to_numpy()
    n = len(vals)
    perm = np.empty(100_000)
    for b in range(len(perm)):
        idx = rng.choice(n, 24, replace=False)
        perm[b] = vals[idx].mean() - np.delete(vals, idx).mean()
    p = (perm >= obs).mean()
    boot = [
        rng.choice(r6[MIDTERMS].to_numpy(), len(MIDTERMS)).mean()
        - rng.choice(r6[others].to_numpy(), len(others)).mean()
        for _ in range(10_000)
    ]
    lo, hi = np.percentile(boot, [2.5, 97.5])
    h1 = diff(r6.loc[1928:1976], [y for y in MIDTERMS if y <= 1976])
    h2 = diff(r6.loc[1977:2025], [y for y in MIDTERMS if y >= 1977])
    print(
        f"6m: midterm {r6[MIDTERMS].mean():+.3f}, others {r6[others].mean():+.3f}, difference {obs:+.3f}"
    )
    print(
        f"permutation one-sided p {p:.4f}; bootstrap 95% [{lo:+.3f}, {hi:+.3f}]; halves {h1:+.3f} {h2:+.3f}"
    )
    passed = p < 0.05 and obs > 0 and h1 > 0 and h2 > 0
    print("PASS CRITERION MET" if passed else "NOT SHOWN")
    print(
        f"midterm windows positive {(r6[MIDTERMS] > 0).sum()}/24; others {(r6[others] > 0).mean():.0%}"
    )
    m12 = [y for y in MIDTERMS if y in r12.index]
    print(f"descriptive 12m: midterm {r12[m12].mean():+.3f}, others {r12.drop(m12).mean():+.3f}")
    for k, name in {0: "presidential", 1: "post-election", 2: "midterm", 3: "pre-election"}.items():
        ys = [y for y in YEARS if y % 4 == k]
        print(
            f"  {name:14s} 6m {r6[ys].mean():+.3f}  12m {r12[[y for y in ys if y in r12.index]].mean():+.3f}"
        )


def look3(closes: pd.Series) -> None:
    cells = [(e, h) for e in (-3, -2, -1, 0, 1, 2) for h in (3, 6, 9, 12)]
    grid = np.array([[window_return(closes, y, e, h) for (e, h) in cells] for y in YEARS])
    is_mid = np.isin(np.array(YEARS), MIDTERMS)

    def diffs(mask: np.ndarray) -> np.ndarray:
        return np.nanmean(grid[mask], axis=0) - np.nanmean(grid[~mask], axis=0)

    obs = diffs(is_mid)
    rng = np.random.default_rng(20261002)
    perm = np.empty((20_000, len(cells)))
    for b in range(len(perm)):
        m = np.zeros(len(YEARS), bool)
        m[rng.choice(len(YEARS), 24, replace=False)] = True
        perm[b] = diffs(m)
    sd = perm.std(axis=0)
    max_z = (perm / sd).max(axis=1)
    print("entry, horizon (months): excess | z | raw p | family-wise p")
    for i, (e, h) in enumerate(cells):
        z = obs[i] / sd[i]
        print(
            f"  {e:+d} {h:2d}: {obs[i]:+.3f} | {z:4.1f} | {(perm[:, i] >= obs[i]).mean():.4f} | {(max_z >= z).mean():.4f}"
        )

    def monthly(offsets: range) -> str:
        out = []
        for k in offsets:
            a = np.array([window_return(closes, y, k, 1) for y in YEARS])
            out.append(np.nanmean(a[is_mid]) - np.nanmean(a[~is_mid]))
        return " ".join(f"{x * 100:+.1f}" for x in out)

    print("monthly excess before election day, months -6..-1:", monthly(range(-6, 0)))
    print("monthly excess after election day, months 1..12:", monthly(range(0, 12)))


def robust(closes: pd.Series) -> None:
    yrs = np.array(YEARS)
    is_mid = np.isin(yrs, MIDTERMS)
    rng = np.random.default_rng(20261003)
    for e, h in [(0, 6), (-1, 9), (-1, 6), (-2, 12)]:
        r = np.array([window_return(closes, y, e, h) for y in YEARS])
        obs = np.nanmean(r[is_mid]) - np.nanmean(r[~is_mid])
        med = np.nanmedian(r[is_mid]) - np.nanmedian(r[~is_mid])
        loo = sorted(
            (
                (y, np.nanmean(r[is_mid & (yrs != y)]) - np.nanmean(r[(yrs != y) & ~is_mid]))
                for y in MIDTERMS
            ),
            key=lambda t: t[1],
        )
        worst = loo[0][0]
        keep = yrs != worst
        rk, mk = r[keep], is_mid[keep]
        o = np.nanmean(rk[mk]) - np.nanmean(rk[~mk])
        hits = 0
        for _ in range(20_000):
            m = np.zeros(len(rk), bool)
            m[rng.choice(len(rk), mk.sum(), replace=False)] = True
            hits += (np.nanmean(rk[m]) - np.nanmean(rk[~m])) >= o
        top = sorted(((y, r[YEARS.index(y)]) for y in MIDTERMS), key=lambda t: -t[1])[:5]
        drop3 = is_mid & ~np.isin(yrs, [y for y, _ in top[:3]])
        print(
            f"entry {e:+d} h {h}: mean {obs * 100:+.1f}, median {med * 100:+.1f}; leave-one-out {loo[0][1] * 100:+.1f}"
            f" (drop {worst}, p {hits / 20_000:.4f}) to {loo[-1][1] * 100:+.1f};"
            f" drop top 3 {(np.nanmean(r[drop3]) - np.nanmean(r[~is_mid])) * 100:+.1f}"
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("look", choices=["look2", "look3", "robust"])
    args = parser.parse_args()
    closes = asyncio.run(_load_closes())
    {"look2": look2, "look3": look3, "robust": robust}[args.look](closes)


if __name__ == "__main__":
    main()
