"""E15 step 0 (signal-only): cross-sectional autocorrelation time of candidate family members.
Reads feature values only, no returns, vintage 1 (< 2025-12-24). tau = 1 + 2 * sum_k rho_k,
summed until rho first drops below 0.05 (initial positive sequence), lags in sessions."""

import asyncio

import asyncpg
import numpy as np
import pandas as pd

F9 = [
    "vwap_dev_sigma",
    "high_52w_dist",
    "rsi_slow",
    "aroon_slow",
    "price_percentile_slow",
    "stoch_k_slow",
    "dist_from_high_slow",
]
F10 = ["up_vol_ratio_fast", "ofi_z", "obv_z", "mfi_slow"]
DSN = "postgresql://postgres:postgres@localhost/indicagent"


def tau_of(wide: pd.DataFrame, max_lag: int) -> tuple[float, list[float]]:
    r = wide.rank(axis=1)
    r = r.sub(r.mean(axis=1), axis=0).div(r.std(axis=1), axis=0).to_numpy()
    rhos = []
    for k in range(1, max_lag + 1):
        a, b = r[:-k], r[k:]
        ok = ~(np.isnan(a) | np.isnan(b))
        num = np.where(ok, a * b, 0).sum(1)
        cnt = ok.sum(1)
        c = num[cnt > 20] / (cnt[cnt > 20] - 1)
        rhos.append(float(np.nanmean(c)))
    tau = 1.0
    for rho in rhos:
        if rho < 0.05:
            break
        tau += 2 * rho
    return tau, rhos


async def main():
    conn = await asyncpg.connect(DSN)
    out = []
    for f in F9 + F10:
        rows = await conn.fetch(
            f"select bar_ts::date d, symbol, {f} v from feature_vectors where tf='1d' and bar_ts < '2025-12-24' and {f} is not null"
        )
        df = pd.DataFrame(rows, columns=["d", "s", "v"]).pivot_table(
            index="d", columns="s", values="v"
        )
        tau, rhos = tau_of(df, 400)
        out.append(
            (f, "1d", len(df), round(tau, 1), [round(rhos[i], 2) for i in (0, 4, 20, 62, 251)])
        )
    for f in F10:
        rows = await conn.fetch(
            f"""select (bar_ts at time zone 'America/New_York')::date d, symbol, {f} v from feature_vectors
            where tf='5m' and bar_ts < '2025-12-24' and {f} is not null
            and to_char(bar_ts at time zone 'America/New_York','HH24:MI') = '13:00'"""
        )
        df = pd.DataFrame(rows, columns=["d", "s", "v"]).pivot_table(
            index="d", columns="s", values="v"
        )
        tau, rhos = tau_of(df, 60)
        out.append(
            (
                f,
                "5m@13:00 ET, lag in sessions",
                len(df),
                round(tau, 1),
                [round(rhos[i], 2) for i in (0, 4, 20)],
            )
        )
    await conn.close()
    for o in out:
        print(*o, sep=" | ")


asyncio.run(main())
