"""V4: harness fidelity against production (pre-registration section 10).

Refit at T = 2025-12-24 on the S0 snapshot in fidelity mode (production's feature mask, no
section 5 exclusions, no embargo, production's window end and stored completeness flags), then
compare every pooled 1d row with production's feature_ic_scores for the same
(feature_name, regime, lookahead_bars) at that window, earnings-season rows excluded.

Deterministic fields must match to 1e-6 (integers and flags exactly). The only RNG draw in the
cell code is the bootstrap's block starts, so ic_ci_lower, ic_ci_upper and passes_ci_gate are
RNG-dependent: their differences are reported and pinned in the addendum, never gated here.
bh_adjusted_p and passes_fdr are excluded (D1: the FDR family differs by design).

The refit's wall-clock time is the "compute measured for one refit" the addendum needs.

Run: python -m scripts.analysis.sleeve_walk_forward.v4 --snapshot DIR [--out-dir DIR]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import time
from datetime import UTC, datetime
from pathlib import Path

import numpy as np

from scripts.analysis.sleeve_walk_forward.config import DEFAULT_CONFIG
from scripts.analysis.sleeve_walk_forward.refit import run_refit
from scripts.analysis.sleeve_walk_forward.snapshot import load_snapshot, verify_snapshot

_TOL = 1e-6
DETERMINISTIC_FLOAT = (
    "ic_value",
    "ic_sharpe",
    "ic_sharpe_hac",
    "ic_sortino",
    "ic_win_rate",
    "sign_hit_rate",
    "magnitude_conditional_ic",
    "p_value",
)
DETERMINISTIC_EXACT = (
    "n_independent",
    "cluster_id",
    "reliable",
    "passes_walkforward",
    "wf_fold_count",
    "wf_pass_count",
    "ic_sign",
    "ic_sharpe_n_windows",
)
RNG_FIELDS = ("ic_ci_lower", "ic_ci_upper", "passes_ci_gate")
_PROD_SQL = (
    "SELECT feature_name, regime, lookahead_bars, "
    + ", ".join((*DETERMINISTIC_FLOAT, *DETERMINISTIC_EXACT, *RNG_FIELDS))
    + " FROM feature_ic_scores WHERE tf = '1d' AND symbol = 'POOLED' AND is_pooled"
    " AND regime <> '_pooled' AND regime_scope <> 'earnings_season'"
    " AND training_window_end = $1"
)


def _key(r: dict) -> tuple:
    return (r["feature_name"], r["regime"], int(r["lookahead_bars"]))


def _num(v) -> float:
    return float("nan") if v is None else float(v)


def compare_rows(harness: list[dict], production: list[dict]) -> dict:
    h = {_key(r): r for r in harness}
    p = {_key(r): r for r in production}
    common = sorted(set(h) & set(p))
    det: dict[str, dict] = {}
    for f in DETERMINISTIC_FLOAT:
        a = np.array([_num(h[k][f]) for k in common])
        b = np.array([_num(p[k][f]) for k in common])
        both_nan = np.isnan(a) & np.isnan(b)
        diff = np.where(both_nan, 0.0, np.abs(a - b))
        bad = (diff > _TOL) | (np.isnan(a) != np.isnan(b))
        det[f] = {"n_bad": int(bad.sum()), "max_abs": float(np.nanmax(diff)) if len(diff) else 0.0}
    for f in DETERMINISTIC_EXACT:
        bad = [k for k in common if h[k][f] != p[k][f]]
        det[f] = {"n_bad": len(bad), "examples": [list(k) for k in bad[:5]]}
    rng: dict[str, dict] = {}
    for f in RNG_FIELDS:
        if f == "passes_ci_gate":
            rng[f] = {"n_differ": sum(h[k][f] != p[k][f] for k in common)}
            continue
        diff = np.array([abs(_num(h[k][f]) - _num(p[k][f])) for k in common])
        diff = diff[np.isfinite(diff)]
        rng[f] = {
            "max_abs": float(diff.max()) if len(diff) else 0.0,
            "p50_abs": float(np.percentile(diff, 50)) if len(diff) else 0.0,
            "p99_abs": float(np.percentile(diff, 99)) if len(diff) else 0.0,
        }
    only_h = sorted(set(h) - set(p))
    only_p = sorted(set(p) - set(h))
    return {
        "n_common": len(common),
        "keys_equal": not only_h and not only_p,
        "only_harness": [list(k) for k in only_h],
        "only_production": [list(k) for k in only_p],
        "deterministic_ok": all(v["n_bad"] == 0 for v in det.values()),
        "deterministic": det,
        "rng": rng,
    }


async def _production_rows(dsn: str, window: datetime) -> list[dict]:
    from scripts.analysis.sleeve_walk_forward.snapshot import read_only_pool

    pool = await read_only_pool(dsn)
    try:
        async with pool.acquire() as conn:
            return [dict(r) for r in await conn.fetch(_PROD_SQL, window)]
    finally:
        await pool.close()


def main(argv: list[str] | None = None) -> int:
    from src.config.settings import Settings

    parser = argparse.ArgumentParser(description="V4: harness fidelity against production")
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, default=Path("logs/phase179"))
    args = parser.parse_args(argv)
    verify_snapshot(args.snapshot)
    snap = load_snapshot(args.snapshot)
    window = datetime.fromisoformat(snap.manifest["oos_start"])
    t0 = time.monotonic()
    refit = run_refit(
        snap,
        snap.sessions[-1],
        DEFAULT_CONFIG,
        frozenset(),
        fidelity_window_end=np.datetime64(window.date(), "D"),
    )
    seconds = time.monotonic() - t0
    dsn = Settings().database_url.replace("postgresql+asyncpg://", "postgresql://")
    production = asyncio.run(_production_rows(dsn, window))
    harness = [r for r in refit.ic_rows if r["symbol"] == "POOLED"]
    out = {
        "snapshot": str(args.snapshot),
        "window": window.isoformat(),
        "refit_seconds": seconds,
        "n_harness": len(harness),
        "n_production": len(production),
        **compare_rows(harness, production),
    }
    args.out_dir.mkdir(parents=True, exist_ok=True)
    path = args.out_dir / f"v4_{datetime.now(UTC):%Y%m%dT%H%M%SZ}.json"
    path.write_text(json.dumps(out, indent=2, default=str))
    print(path)
    print(
        f"V4: keys_equal={out['keys_equal']} deterministic_ok={out['deterministic_ok']} "
        f"common={out['n_common']} harness={len(harness)} production={len(production)} "
        f"refit={seconds:.0f}s"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
