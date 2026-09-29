"""Family 1 iteration 2 (exploration): conviction gating, prototyped outside the runner.

Question: does concentrating each slot's book on the names with the most extreme alpha raise the
edge per unit traded (E = mean E17 timing-series P&L per session / turnover per session)? The
runner has no gated construction (phase 187 ConstructionRule), so this script reuses its panel,
residual, member, volatility and E17 timing code and swaps in the weights.

Axes (docs/plans/2026-09-29-family1-iteration-2-conviction-gating.md):
  name gate  keep: the top and bottom `keep` fraction of valid names per side (0.5 = ungated).
  slot gate  slots: trade a slot only when its cross-sectional alpha dispersion is in the top
             `slots` fraction of the same slot's trailing distribution (1.0 = every slot).

Exploration only: reads no forward span (the panel ends before oos_start), writes no research_run
row, and is not a verdict.

    .venv/bin/python scripts/research/family1_conviction_gating.py \
        --spec research/specs/family1_h2.yaml --snapshot logs/research/snapshots/panel_<hash>
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, ".")

from src.intelligence.research import panel as panel_mod  # noqa: E402
from src.intelligence.research import transforms  # noqa: E402
from src.intelligence.research.evaluate import trade_mask  # noqa: E402
from src.intelligence.research.evidence import turnover_per_session  # noqa: E402
from src.intelligence.research.runner import (  # noqa: E402
    FACTOR_SPECS,
    _prepare_panel,
    _vol,
    compute_members,
    compute_residuals,
)
from src.intelligence.research.spec import load_spec_from_file  # noqa: E402
from src.intelligence.research.timing import hac_mean_test, timing_series  # noqa: E402

SESSIONS_PER_YEAR = 252
# Trailing sessions of the same slot that define a slot's dispersion distribution (causal).
SLOT_HISTORY_SESSIONS = 60
SLOT_HISTORY_MIN = 20


def gated_weights(
    alpha: np.ndarray, vol: np.ndarray, *, keep: float, coverage_floor: int, direction: float
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """(weights, has_position, dispersion). Centred rank / vol on the top and bottom `keep`
    fraction of valid names, each side scaled to 0.5 (dollar neutral, gross 1). keep = 0.5 is
    the runner's rank_vol_neutral. dispersion is the row's alpha standard deviation."""
    n, m = alpha.shape
    weights = np.zeros((n, m))
    has_position = np.zeros(n, dtype=bool)
    dispersion = np.full(n, np.nan)
    ok = np.isfinite(alpha) & np.isfinite(vol) & (vol > 0)
    for t in np.flatnonzero(ok.sum(axis=1) >= coverage_floor):
        idx = np.flatnonzero(ok[t])
        a = alpha[t, idx]
        k = idx.size
        rank = np.empty(k)
        order = np.argsort(a, kind="stable")
        sorted_a = a[order]
        start = 0
        while start < k:  # average ranks over ties, as the runner's kernel does
            stop = start + 1
            while stop < k and sorted_a[stop] == sorted_a[start]:
                stop += 1
            rank[order[start:stop]] = 0.5 * (start + stop - 1)
            start = stop
        centred = rank / (k - 1) - 0.5
        raw = direction * centred / vol[t, idx]
        rank_frac = rank / (k - 1)
        drop = (rank_frac > keep) & (rank_frac < 1.0 - keep)
        raw[drop] = 0.0
        pos = raw[raw > 0].sum()
        neg = -raw[raw < 0].sum()
        if pos <= 0 or neg <= 0:
            continue
        w = np.where(raw > 0, 0.5 * raw / pos, 0.5 * raw / neg)
        weights[t, idx] = w
        has_position[t] = True
        dispersion[t] = float(a.std())
    return weights, has_position, dispersion


def slot_gate(
    dispersion: np.ndarray, has_position: np.ndarray, *, bars_per_session: int, slots: float
) -> np.ndarray:
    """Rows to trade: dispersion at or above the (1 - slots) quantile of the same slot's previous
    SLOT_HISTORY_SESSIONS sessions. Causal: a row reads only earlier sessions' rows."""
    if slots >= 1.0:
        return has_position
    n = dispersion.shape[0]
    s_n = n // bars_per_session
    disp = dispersion.reshape(s_n, bars_per_session)
    out = np.zeros((s_n, bars_per_session), dtype=bool)
    for s in range(SLOT_HISTORY_MIN, s_n):
        hist = disp[max(0, s - SLOT_HISTORY_SESSIONS) : s]
        finite = np.isfinite(hist).sum(axis=0)
        with np.errstate(invalid="ignore"):
            thr = np.nanquantile(hist, 1.0 - slots, axis=0)
        out[s] = np.isfinite(disp[s]) & (finite >= SLOT_HISTORY_MIN) & (disp[s] >= thr)
    return out.reshape(-1) & has_position


def summarize(series: np.ndarray, turnover: float, session_dates: np.ndarray, subs) -> dict:
    x = series[np.isfinite(series)]
    hac = hac_mean_test(series)
    sd = float(x.std(ddof=1))
    out = {
        "mean_bp": float(x.mean() * 1e4),
        "sharpe": float(x.mean() / sd * np.sqrt(SESSIONS_PER_YEAR)) if sd > 0 else float("nan"),
        "t": float(hac.t),
        "turnover": turnover,
        "E_bp_per_unit": float(x.mean() * 1e4 / turnover) if turnover > 0 else float("nan"),
    }
    per = []
    for a, b in subs:
        sel = (
            np.isfinite(series)
            & (session_dates >= np.datetime64(a))
            & (session_dates <= np.datetime64(b))
        )
        per.append(
            float(series[sel].mean() * 1e4 / turnover) if sel.any() and turnover > 0 else None
        )
    out["E_by_subperiod"] = per
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--spec", required=True)
    ap.add_argument("--snapshot", required=True)
    ap.add_argument("--members", default="same_slot_mean5,same_slot_mean20")
    ap.add_argument("--keeps", default="0.5,0.3,0.2,0.1,0.05")
    ap.add_argument("--slots", default="1.0,0.5,0.25")
    ap.add_argument("--cache", default=None, help="directory caching residuals between runs")
    ap.add_argument("--out", default=None, help="write the grid as JSON")
    args = ap.parse_args()

    loaded = load_spec_from_file(Path(args.spec))
    spec = loaded.model
    panel = panel_mod.load(Path(args.snapshot))
    panel, _ = _prepare_panel(spec, panel, source_hash=None, symbols=None)
    bps = panel.bars_per_session
    transform = transforms.resolve(spec.panel.transform)
    cache = Path(args.cache) if args.cache else None
    if cache and (cache / "bar.npy").exists():
        bar, fwd = np.load(cache / "bar.npy"), np.load(cache / "fwd.npy")
    else:
        res = compute_residuals(
            panel,
            horizon=spec.horizon,
            factor_spec=FACTOR_SPECS[spec.factor_spec],
            transform=transform,
        )
        bar, fwd = res.bar, res.fwd
        if cache:
            cache.mkdir(parents=True, exist_ok=True)
            np.save(cache / "bar.npy", bar)
            np.save(cache / "fwd.npy", fwd)
    members = compute_members(spec, bar, bars_per_session=bps)
    vol = _vol(spec, bar, bps)
    cfg = spec.scoring.evaluation_config()
    trade = trade_mask(panel.timestamps, cfg) & panel.valid
    sess_dates = panel.timestamps.reshape(-1, bps)[:, 0].astype("datetime64[D]")
    wanted = args.members.split(",")
    rows = []
    for m in spec.members:
        if m.name not in wanted:
            continue
        alpha = members[m.name]
        for keep in [float(k) for k in args.keeps.split(",")]:
            w, has_pos, disp = gated_weights(
                alpha,
                vol,
                keep=keep,
                coverage_floor=spec.construction.coverage_floor,
                direction=float(spec.construction.direction),
            )
            for slots in [float(s) for s in args.slots.split(",")]:
                gate = slot_gate(disp, has_pos, bars_per_session=bps, slots=slots)
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
                r = {"member": m.name, "keep": keep, "slots": slots}
                r.update(summarize(series, turn, sess_dates, cfg.sub_periods))
                rows.append(r)
                print(json.dumps(r), flush=True)
    if args.out:
        Path(args.out).write_text(json.dumps(rows, indent=1))


if __name__ == "__main__":
    main()
