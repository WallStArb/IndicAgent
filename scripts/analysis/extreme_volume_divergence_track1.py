#!/usr/bin/env python3
"""H-A extreme-volume divergence, Track 1 (signal existence).

Pre-registration: docs/plans/2026-09-06-extreme-volume-divergence-confirmed-reversal-prereg.md
("Construction spec", "Track 1", "Fixed quantities"). Every quantity below is pinned there.

H-A: a fresh `dist_window_fast` extreme made on light volume warns of a reversal against it.
Statistic, defined only on single-sided extreme bars (NaN elsewhere, including outside bars):
    extreme_volume_divergence = -extreme_proximity * volume_z
with extreme_proximity = +1 at a fresh low (bars_since_low_fast == 0), -1 at a fresh high.

Test: within-symbol Spearman IC against return_fast (gated) and return_mid (reported), family
statistic = equal-weighted mean over symbols with >= 100 measurement rows; synchronous
date-block bootstrap CI (B=2000); panel-synchronous whole-date circular-shift null on the FULL
dense 15m panel (N=1000; todo 372's fix, reviewed CORRECT 2026-09-11), so an extreme on date D
maps onto non-extreme dates under the shift; per-symbol BY-FDR from the asymptotic
t-approximation (`_p_values_from_ic`). Diurnal morning/afternoon sub-panel reported, ungated
(todo 372 finding 2: volume_z has no session detrending).

PASS (all five): bootstrap ci_lower > 0; null p < 0.05; positive family IC in 3/3 equal
calendar thirds; >= 10% of family symbols BY-significant with positive IC; family IC >= 0.003.

Read-only (default_transaction_read_only); in-sample only (bar_ts < alpha.validation.oos_start).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
from statsmodels.stats.multitest import multipletests

from scripts.analysis._date_panel import Panel, spearman
from src.core.rng import hash_key_to_int
from src.intelligence.statistics.ic_math import _p_values_from_ic

_TF = "15m"
_N_BOOT = 2000
_N_NULL = 1000
_MIN_ROWS = 100
_DATE_BLOCK = 5
PASS_RULE = {"alpha": 0.05, "qualifying_floor": 0.10, "ic_min": 0.003, "n_subperiods": 3}
_MORNING = (9 * 60 + 45, 11 * 60 + 30)  # bar open, America/New_York, inclusive
_AFTERNOON = (11 * 60 + 45, 15 * 60 + 45)

_FETCH_SQL = """
SELECT fv.bar_ts, fv.bars_since_low_fast, fv.bars_since_high_fast, fv.volume_z,
       fr.return_fast, fr.complete_fast, fr.return_mid, fr.complete_mid
FROM feature_vectors fv
JOIN forward_returns fr
  ON fr.symbol = fv.symbol AND fr.tf = fv.tf AND fr.bar_ts = fv.bar_ts
 AND fr.return_type = 'executable_open_to_open'
WHERE fv.symbol = $1 AND fv.tf = '15m' AND fv.bar_ts < $2
ORDER BY fv.bar_ts
"""


def h_a_statistic(
    bars_since_low: np.ndarray, bars_since_high: np.ndarray, volume_z: np.ndarray
) -> np.ndarray:
    low = bars_since_low == 0
    high = bars_since_high == 0
    proximity = np.where(low & ~high, 1.0, np.where(high & ~low, -1.0, np.nan))
    return -proximity * volume_z


def per_symbol_table(panel: Panel) -> list[dict]:
    rows = []
    for s in panel.family:
        sl = panel.sym_blocks[s][2]
        x, y = panel.scores[sl], panel.returns[sl]
        n = int((np.isfinite(x) & np.isfinite(y)).sum())
        ic = spearman(x, y)
        p = float(_p_values_from_ic(np.array([ic]), n)[0]) if np.isfinite(ic) else 1.0
        rows.append({"symbol_id": int(s), "n": n, "ic": ic, "p": p})
    return rows


def qualifying_fraction(table: list[dict], alpha: float) -> float:
    if not table:
        return 0.0
    reject = multipletests([r["p"] for r in table], alpha=alpha, method="fdr_by")[0]
    return float(sum(bool(rej) and r["ic"] > 0 for rej, r in zip(reject, table)) / len(table))


def verdict(
    *, ci_lower: float, null_p: float, sub_ics: list[float], qual_frac: float, family_ic: float
) -> dict:
    criteria = {
        "ci_lower_gt_0": ci_lower > 0,
        "null_p_lt_alpha": null_p < PASS_RULE["alpha"],
        "positive_in_all_subperiods": len(sub_ics) == PASS_RULE["n_subperiods"]
        and all(v > 0 for v in sub_ics),
        "qualifying_fraction_ge_floor": qual_frac >= PASS_RULE["qualifying_floor"],
        "family_ic_ge_min": family_ic >= PASS_RULE["ic_min"],
    }
    return {"pass": all(criteria.values()), "criteria": criteria}


def diurnal_masks(bar_ts_utc: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Morning and afternoon row masks from bar open times (UTC datetime64), in New York time."""
    import pandas as pd

    local = pd.DatetimeIndex(bar_ts_utc).tz_localize("UTC").tz_convert("America/New_York")
    minute = np.asarray(local.hour * 60 + local.minute)
    return (
        (minute >= _MORNING[0]) & (minute <= _MORNING[1]),
        (minute >= _AFTERNOON[0]) & (minute <= _AFTERNOON[1]),
    )


def _masked_family_stat(panel: Panel, mask: np.ndarray) -> float:
    return panel.family_stat(score_override=np.where(mask, panel.scores, np.nan))


def run_track1(
    panel: Panel, *, n_boot: int, n_null: int, seed: int, bar_ts_utc: np.ndarray | None = None
) -> dict:
    family_ic = panel.family_stat()
    ci = panel.bootstrap_ci(np.random.default_rng(seed), n_boot)
    null_p = panel.sync_shift_null_p(family_ic, np.random.default_rng(seed + 1), n_null)
    thirds = np.array_split(panel.calendar, PASS_RULE["n_subperiods"])
    sub_ics = [_masked_family_stat(panel, np.isin(panel.dates, part)) for part in thirds]
    table = per_symbol_table(panel)
    qual = qualifying_fraction(table, PASS_RULE["alpha"])
    out = {
        "family_ic": family_ic,
        "ci": list(ci),
        "null_p": null_p,
        "sub_ics": sub_ics,
        "qualifying_fraction": qual,
        "n_family": len(panel.family),
        "verdict": verdict(
            ci_lower=ci[0], null_p=null_p, sub_ics=sub_ics, qual_frac=qual, family_ic=family_ic
        ),
    }
    if bar_ts_utc is not None:  # reported, never gated
        morning, afternoon = diurnal_masks(bar_ts_utc)
        out["diurnal"] = {
            "morning_ic": _masked_family_stat(panel, morning),
            "afternoon_ic": _masked_family_stat(panel, afternoon),
        }
    return out


async def _fetch(dsn: str, only: list[str] | None = None) -> tuple[dict[str, np.ndarray], str]:
    """All 15m in-sample rows, converted per symbol as each fetch lands (peak memory stays at
    the pool's in-flight symbols, not the whole 24M-row result)."""
    from scripts.analysis.sleeve_walk_forward.snapshot import read_only_pool

    pool = await read_only_pool(dsn)
    try:
        async with pool.acquire() as conn:
            oos = await conn.fetchval(
                "SELECT config_value::timestamptz FROM config_state WHERE config_key = 'alpha.validation.oos_start'"
            )
            symbols = [
                r[0]
                for r in await conn.fetch(
                    "SELECT DISTINCT symbol FROM feature_vectors WHERE tf = '15m' AND bar_ts < $1 ORDER BY symbol",
                    oos,
                )
            ]
            if only is not None:
                symbols = [s for s in symbols if s in set(only)]

        async def one(sym: str) -> dict[str, np.ndarray] | None:
            async with pool.acquire() as c:
                rows = await c.fetch(_FETCH_SQL, sym, oos)
            if not rows:
                return None
            grid = np.array([tuple(r)[1:] for r in rows], dtype=object)
            num = np.where(grid == None, np.nan, grid).astype(float)  # noqa: E711
            return {
                "symbol": np.full(len(rows), sym),
                "bar_ts": np.array(
                    [r[0].replace(tzinfo=None) for r in rows], dtype="datetime64[m]"
                ),
                "low": num[:, 0],
                "high": num[:, 1],
                "volume_z": num[:, 2],
                "return_fast": num[:, 3],
                "complete_fast": num[:, 4] == 1,
                "return_mid": num[:, 5],
                "complete_mid": num[:, 6] == 1,
            }

        blocks = [b for b in await asyncio.gather(*(one(s) for s in symbols)) if b is not None]
    finally:
        await pool.close()
    return {k: np.concatenate([b[k] for b in blocks]) for k in blocks[0]}, str(oos)


def _panel(
    data: dict[str, np.ndarray], ret_key: str, complete_key: str
) -> tuple[Panel, np.ndarray]:
    keep = data[complete_key] & np.isfinite(data[ret_key])
    sym_names, sym_ids = np.unique(data["symbol"][keep], return_inverse=True)
    ts = data["bar_ts"][keep]
    order = np.lexsort((ts, sym_ids))
    # Days since epoch: a monotone calendar key (a 15m session sits inside one UTC day).
    dates = ts[order].astype("datetime64[D]").astype(np.int64)
    stat = h_a_statistic(data["low"][keep], data["high"][keep], data["volume_z"][keep])[order]
    panel = Panel(
        sym_ids[order],
        dates,
        stat,
        data[ret_key][keep][order],
        min_rows=_MIN_ROWS,
        date_block=_DATE_BLOCK,
    )
    return panel, ts[order]


def main(argv: list[str] | None = None) -> int:
    from src.config.settings import Settings
    from src.core.service_utils import setup_service_logging

    parser = argparse.ArgumentParser(description="H-A extreme-volume divergence, Track 1")
    parser.add_argument("--out-dir", type=Path, default=Path("logs/extreme_volume"))
    parser.add_argument(
        "--smoke",
        nargs="+",
        metavar="SYMBOL",
        help="plumbing check only: these symbols, B = N = 50, output labeled smoke, no verdict",
    )
    args = parser.parse_args(argv)
    setup_service_logging("logs/extreme_volume_divergence_track1.log")
    dsn = Settings().database_url.replace("postgresql+asyncpg://", "postgresql://")
    data, oos = asyncio.run(_fetch(dsn, args.smoke))
    n_boot, n_null = (50, 50) if args.smoke else (_N_BOOT, _N_NULL)
    seed = hash_key_to_int("extreme_volume_divergence_h_a")
    primary_panel, primary_ts = _panel(data, "return_fast", "complete_fast")
    primary = run_track1(
        primary_panel, n_boot=n_boot, n_null=n_null, seed=seed, bar_ts_utc=primary_ts
    )
    mid_panel, mid_ts = _panel(data, "return_mid", "complete_mid")
    secondary = run_track1(mid_panel, n_boot=n_boot, n_null=n_null, seed=seed, bar_ts_utc=mid_ts)
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"], capture_output=True, text=True
    ).stdout.strip()
    result = {
        "hypothesis": "H-A extreme_volume_divergence",
        "tf": _TF,
        "oos_start": oos,
        "smoke": bool(args.smoke),
        "git_commit": commit,
        "run_at": datetime.now(UTC).isoformat(),
        "primary_return_fast_gated": primary,
        "secondary_return_mid_reported": secondary,
    }
    args.out_dir.mkdir(parents=True, exist_ok=True)
    kind = "smoke" if args.smoke else "track1"
    path = args.out_dir / f"h_a_{kind}_{datetime.now(UTC):%Y%m%dT%H%M%SZ}.json"
    path.write_text(json.dumps(result, indent=2, default=float))
    print(path)
    label = (
        "SMOKE, no verdict" if args.smoke else ("PASS" if primary["verdict"]["pass"] else "FAIL")
    )
    print(
        f"H-A Track 1: {label} "
        f"(family IC {primary['family_ic']:.5f}, CI {primary['ci']}, null p {primary['null_p']:.4f})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
