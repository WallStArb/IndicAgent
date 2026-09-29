"""Family 1 iteration 3, question 4 (exploration, outside the runner): the closing slot on
liquid names, gross E and E net of a modeled entry cost, over a liquidity gate L x keep x member
x name-set grid (docs/plans/2026-09-29-family1-iteration-3-open-close-slots.md).

Liquidity gate L: each session, trade only names in the top L fraction of trailing 60-session
mean dollar volume (prior sessions only). Cost: half-spread per name is exp(a + b log dollar
volume), fitted on the measured spread sample (`docs/research/family1-spread-sample-2026-09-29.csv`,
column hs_close_window, dollar volume from each snapshot's last 60 sessions). The closing slot
pays half the traded-weight-averaged entry half-spread per unit traded; the close exit is an
auction. Not a verdict; reads no forward span; writes no `research_run` row.

    .venv/bin/python scripts/research/family1_liquid_close.py --spec research/specs/family1_h2.yaml \
        --sets 233=<snapshot>:<residual cache>,201=<snapshot>:<residual cache>
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, ".")
sys.path.insert(0, str(Path(__file__).parent))

import family1_conviction_gating as gating  # noqa: E402
from family1_slot_profile import CLOSE_ROW, load_residuals  # noqa: E402

from src.intelligence.research import panel as panel_mod  # noqa: E402
from src.intelligence.research.evaluate import trade_mask  # noqa: E402
from src.intelligence.research.evidence import turnover_per_session  # noqa: E402
from src.intelligence.research.runner import _prepare_panel, _vol, compute_members  # noqa: E402
from src.intelligence.research.spec import load_spec_from_file  # noqa: E402
from src.intelligence.research.timing import timing_series  # noqa: E402

DVOL_WINDOW_SESSIONS = 60
SPREAD_CSV = Path("docs/research/family1-spread-sample-2026-09-29.csv")


def session_dollar_volume(panel) -> np.ndarray:
    """(sessions, names): sum over a session's bars of close x volume."""
    n = panel.close.shape[0] // panel.bars_per_session
    grid = (panel.close * panel.volume).reshape(n, panel.bars_per_session, -1)
    return np.nansum(grid, axis=1)


def trailing_mean(values: np.ndarray, window: int) -> np.ndarray:
    """Row s is the mean of rows s - window .. s - 1 (NaN before `window` rows)."""
    out = np.full(values.shape, np.nan)
    for s in range(window, values.shape[0]):
        out[s] = np.nanmean(values[s - window : s], axis=0)
    return out


def fit_cost_model(panels: list, spread: pd.Series) -> tuple[float, float]:
    """(a, b) of log half-spread = a + b log dollar volume over the sampled names."""
    pts = []
    for panel in panels:
        recent = session_dollar_volume(panel)[-DVOL_WINDOW_SESSIONS:]
        for j, symbol in enumerate(panel.symbols):
            level = np.nanmean(recent[:, j])
            if symbol in spread.index and level > 0:
                pts.append((np.log(level), np.log(spread[symbol])))
    arr = np.array(pts)
    b, a = np.polyfit(arr[:, 0], arr[:, 1], 1)
    return float(a), float(b)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--spec", required=True)
    ap.add_argument("--sets", required=True, help="name=snapshot:cache,name=snapshot:cache")
    ap.add_argument("--members", default="same_slot_mean5,same_slot_mean20")
    ap.add_argument("--levels", default="1.0,0.5,0.25,0.1")
    ap.add_argument("--keeps", default="0.5,0.2")
    ap.add_argument("--spread-csv", default=str(SPREAD_CSV))
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    spec = load_spec_from_file(Path(args.spec)).model
    cfg = spec.scoring.evaluation_config()
    spread = pd.read_csv(args.spread_csv, index_col="symbol")["hs_close_window"]
    sets = {}
    for item in args.sets.split(","):
        name, rest = item.split("=")
        snapshot, cache = rest.split(":")
        panel, _ = _prepare_panel(
            spec, panel_mod.load(Path(snapshot)), source_hash=None, symbols=None
        )
        sets[name] = (panel, Path(cache))
    a, b = fit_cost_model([p for p, _ in sets.values()], spread)
    print(f"cost fit a {a:.3f} b {b:.3f} names {len(spread)}", flush=True)

    rows = []
    for set_name, (panel, cache) in sets.items():
        bps = panel.bars_per_session
        bar, fwd = load_residuals(spec, panel, cache)
        members = compute_members(spec, bar, bars_per_session=bps)
        vol = _vol(spec, bar, bps)
        trade = trade_mask(panel.timestamps, cfg) & panel.valid
        sess_dates = panel.timestamps.reshape(-1, bps)[:, 0].astype("datetime64[D]")
        close_row = np.tile(np.arange(bps), trade.shape[0] // bps) == CLOSE_ROW
        trailing = trailing_mean(session_dollar_volume(panel), DVOL_WINDOW_SESSIONS)
        rows_dvol = np.repeat(trailing, bps, axis=0)
        pred_hs = np.exp(a + b * np.log(np.where(rows_dvol > 0, rows_dvol, np.nan)))
        for level in [float(x) for x in args.levels.split(",")]:
            if level < 1.0:
                keep_mask = trailing >= np.nanquantile(trailing, 1 - level, axis=1)[:, None]
            else:
                keep_mask = np.isfinite(trailing)
            mask_rows = np.repeat(keep_mask, bps, axis=0)
            for m in spec.members:
                if m.name not in args.members.split(","):
                    continue
                alpha = np.where(mask_rows, members[m.name], np.nan)
                gated_vol = np.where(mask_rows, vol, np.nan)
                for keep in [float(k) for k in args.keeps.split(",")]:
                    w, has_pos, _ = gating.gated_weights(
                        alpha,
                        gated_vol,
                        keep=keep,
                        coverage_floor=spec.construction.coverage_floor,
                        direction=float(spec.construction.direction),
                    )
                    gate = has_pos & close_row
                    series = timing_series(
                        w,
                        fwd,
                        gate,
                        trade,
                        bars_per_session=bps,
                        warmup_sessions=cfg.warmup_sessions,
                        memory_sessions=m.slot_history_sessions,
                    )
                    turn = turnover_per_session(w, gate, trade, bps)
                    summary = gating.summarize(series, turn, sess_dates, cfg.sub_periods)
                    at = np.flatnonzero(gate)
                    weight = np.abs(w[at])
                    cost_row = (
                        0.5 * (weight * np.nan_to_num(pred_hs[at])).sum(axis=1) / weight.sum(axis=1)
                    )
                    dates = sess_dates[at // bps]
                    per_sub = [
                        float(
                            np.nanmean(
                                cost_row[
                                    (dates >= np.datetime64(lo)) & (dates <= np.datetime64(hi))
                                ]
                            )
                        )
                        for lo, hi in cfg.sub_periods
                    ]
                    cost = float(np.nanmean(cost_row))
                    row = {
                        "set": set_name,
                        "level": level,
                        "keep": keep,
                        "member": m.name,
                        "names_per_side": int(np.nanmean((w[at] > 0).sum(axis=1))),
                        "E": summary["E_bp_per_unit"],
                        "t": summary["t"],
                        "cost": cost,
                        "net": summary["E_bp_per_unit"] - cost,
                        "net_by_subperiod": [
                            None if e is None else e - c
                            for e, c in zip(summary["E_by_subperiod"], per_sub, strict=True)
                        ],
                    }
                    rows.append(row)
                    print(json.dumps(row), flush=True)
    if args.out:
        Path(args.out).write_text(json.dumps(rows, indent=1))


if __name__ == "__main__":
    main()
