#!/usr/bin/env python3
"""jump_diffusion_decomposition SPY pilot -- todo/idea: Signal-Extraction candidate,
pre-registered design: docs/research/measurement-jump-diffusion-decomposition.md.

Falsification bar: does a bipower-variation jump_ratio feature add incremental IC on
forward_returns.executable_open_to_open BEYOND the existing garch_ratio+hurst features
-- not whether it's predictive alone. Tested via partial Spearman IC
(ic_math.py::partial_spearman_ic), CI via a circular block bootstrap over the SAME
resampled index for both the raw and partial-IC computation (mirrors
_circular_block_bootstrap_ic's exact resampling mechanic -- see that function's
docstring for why re-ranking inside the loop, not outside, is the correctness-critical
step). Tested both pooled and per-regime, pre-specified before running (not decided
after seeing the pooled number).

Pilot scope only: SPY, tf=15m, full available history. Read-only diagnostic -- no
writes, no config_state changes, exit code always 0 (informational). Promotion to a
wider symbol set is a separate, later decision gated on this pilot clearing.

Construction guardrails (non-negotiable, see the pre-registration doc for why):
  1. Sub-bar returns come from market_data_ohlcv_tradeable only (via
     backfill_feature_factory._fetch_bars_from_db, already scoped to that view) --
     never the raw market_data_ohlcv table.
  2. At tf=1d the overnight gap would need excluding from the jump term; this pilot
     runs at tf=15m only, so that guardrail doesn't apply here, but is not silently
     forgotten -- a 1d run must not reuse this script unmodified.
  3. Pooled AND per-regime tests are both run and both reported -- deciding to only
     look at one after seeing the other would be regime-slicing p-hacking.
"""

from __future__ import annotations

import argparse
import bisect
import math
import sys
from datetime import UTC
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import numpy as np  # noqa: E402
import structlog  # noqa: E402

from services._batch_utils import cfg as _cfg  # noqa: E402
from services._batch_utils import load_config_service_sync  # noqa: E402
from services.backfill_feature_factory import _connect_db, _fetch_bars_from_db  # noqa: E402
from src.config.settings import Settings  # noqa: E402
from src.core.service_utils import setup_service_logging  # noqa: E402
from src.intelligence.statistics.ic_math import partial_spearman_ic  # noqa: E402

setup_service_logging("logs/jump_diffusion_decomposition_spy_pilot.log")
_logger = structlog.get_logger(__name__)

_SYMBOL = "SPY"
_TF = "15m"
_SUB_TF = "1m"


def _build_jump_ratio_series(sub_bars: list[dict], bar_ts_list: list) -> dict:
    """Bipower variation vs realized variance, per 15m bar, from its own 1m sub-bars.

    RV  = sum(r_i^2)                          -- realized variance
    BV  = (pi/2) * sum(|r_i| * |r_i-1|)        -- bipower variation, the diffusion part
    jump_ratio = max(0, RV - BV) / RV          -- bounded [0,1]; 0 = pure diffusion

    A 15m bar's constituent 1m returns are those whose bar-open timestamp falls in
    [bar_ts, bar_ts + 15m). Needs >= 3 sub-bar returns (2 consecutive-pair terms) to
    produce a non-degenerate BV; bars with fewer are skipped (no jump_ratio entry),
    not defaulted to 0.0 -- a missing measurement must not be silently reported as
    "pure diffusion."
    """
    sub_ts = [b["ts"] for b in sub_bars]
    sub_close = [b["close"] for b in sub_bars]
    result: dict = {}
    for i, bar_ts in enumerate(bar_ts_list):
        window_end = bar_ts_list[i + 1] if i + 1 < len(bar_ts_list) else None
        lo = bisect.bisect_left(sub_ts, bar_ts)
        hi = bisect.bisect_left(sub_ts, window_end) if window_end is not None else len(sub_ts)
        window_closes = sub_close[max(lo - 1, 0) : hi]
        if len(window_closes) < 4:  # need >=3 returns (4 closes) for a real BV
            continue
        rets = np.diff(np.log(np.asarray(window_closes, dtype=float)))
        rv = float(np.sum(rets**2))
        if rv <= 0.0:
            continue
        bv = float((math.pi / 2.0) * np.sum(np.abs(rets[1:]) * np.abs(rets[:-1])))
        jump_ratio = max(0.0, rv - bv) / rv
        result[bar_ts] = min(jump_ratio, 1.0)
    return result


def _circular_block_bootstrap_partial_ic(
    jump_raw: np.ndarray,
    return_raw: np.ndarray,
    control_raw: np.ndarray,
    block_size: int,
    n_boot: int,
    condition_max: float,
    rng: np.random.Generator,
) -> tuple[float, float, float]:
    """CI on partial_spearman_ic(jump_ratio, return; controls) via the same circular
    block-index construction as ic_math._circular_block_bootstrap_ic, re-implemented
    here because that function computes plain (non-partial) IC and partial IC needs a
    third resampled input (the controls) -- no existing function does this composition,
    same "one caller doesn't justify Ring-0 placement yet" precedent as todo 005's
    design doc uses for paired_delta_ic_bootstrap.

    Re-ranks (jump, return, AND controls) on the resampled block every iteration --
    the exact correctness property _circular_block_bootstrap_ic's docstring documents
    as the fix for its original 2026-06-26 removal bug. partial_spearman_ic does its
    own rank-transform internally, so this passes RAW resampled values into it, never
    pre-ranked ones.
    """
    n = len(jump_raw)
    n_blocks = math.ceil(n / block_size)
    offsets = np.arange(block_size)
    point_ic, _point_p, _point_n = partial_spearman_ic(
        jump_raw, return_raw, control_raw, condition_max
    )
    boot_ics = np.full(n_boot, np.nan)
    for b in range(n_boot):
        starts = rng.integers(0, n, size=n_blocks)
        idx = (starts[:, None] + offsets).ravel()[:n] % n
        ic_b, _p_b, _n_b = partial_spearman_ic(
            jump_raw[idx], return_raw[idx], control_raw[idx], condition_max
        )
        boot_ics[b] = ic_b
    finite = boot_ics[np.isfinite(boot_ics)]
    if len(finite) < n_boot * 0.9:
        _logger.warning(
            "bootstrap.high_degenerate_rate",
            n_degenerate=n_boot - len(finite),
            n_boot=n_boot,
        )
    ci_lower = float(np.percentile(finite, 2.5)) if len(finite) else float("nan")
    ci_upper = float(np.percentile(finite, 97.5)) if len(finite) else float("nan")
    return point_ic, ci_lower, ci_upper


def _report_cell(
    label: str,
    jump: np.ndarray,
    ret: np.ndarray,
    controls: np.ndarray,
    *,
    block_size: int,
    n_boot: int,
    condition_max: float,
    rng: np.random.Generator,
    min_reliable_n: int,
) -> None:
    n = len(jump)
    if n < min_reliable_n:
        print(
            f"{label}: n={n} < min_reliable_n={min_reliable_n} -- INSUFFICIENT, not reported as a result"
        )
        return
    point_ic, ci_lo, ci_hi = _circular_block_bootstrap_partial_ic(
        jump, ret, controls, block_size, n_boot, condition_max, rng
    )
    crosses_zero = ci_lo <= 0.0 <= ci_hi
    verdict = (
        "NO EFFECT (CI crosses zero)"
        if crosses_zero
        else ("POSITIVE" if point_ic > 0 else "NEGATIVE")
    )
    print(f"{label}: n={n} partial_ic={point_ic:.5f} ci=[{ci_lo:.5f}, {ci_hi:.5f}] -> {verdict}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--n-boot", type=int, default=None, help="Override alpha.ic.bootstrap_resamples"
    )
    parser.add_argument("--seed", type=int, default=42, help="Bootstrap RNG seed (reproducibility)")
    args = parser.parse_args()

    settings = Settings()
    conn = _connect_db(settings)
    apr = load_config_service_sync(conn)
    apr_dict = apr._cache

    block_size = int(_cfg(apr_dict, f"alpha.ic.bootstrap_block_size.{_TF}", 26))
    n_boot = args.n_boot or int(_cfg(apr_dict, "alpha.ic.bootstrap_resamples", 2000))
    condition_max = float(_cfg(apr_dict, "alpha.ic.partial_control_condition_max", 1000.0))
    min_reliable_n = int(_cfg(apr_dict, "alpha.ic.min_reliable_n", 100))

    print(f"jump_diffusion_decomposition SPY pilot -- tf={_TF}")
    print(
        f"block_size={block_size} n_boot={n_boot} condition_max={condition_max} min_reliable_n={min_reliable_n}"
    )

    print("Fetching 1m sub-bars (for bipower variation) ...")
    sub_bars = _fetch_bars_from_db(conn, _SYMBOL, _SUB_TF)
    print(f"  {len(sub_bars)} 1m bars")

    print("Fetching 15m bars (for bar-boundary timestamps) ...")
    bars_15m = _fetch_bars_from_db(conn, _SYMBOL, _TF)
    bar_ts_15m = [b["ts"] for b in bars_15m]
    print(f"  {len(bars_15m)} 15m bars")

    print("Computing jump_ratio per 15m bar from 1m sub-bars ...")
    jump_by_ts = _build_jump_ratio_series(sub_bars, bar_ts_15m)
    print(
        f"  {len(jump_by_ts)}/{len(bar_ts_15m)} bars produced a jump_ratio (rest skipped, <4 sub-bars)"
    )

    print(
        "Fetching feature_vectors (garch_ratio, hurst, regime) and forward_returns (return_mid) ..."
    )
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT fv.bar_ts, fv.garch_ratio, fv.hurst, fv.regime,
                   fr.return_mid
            FROM feature_vectors fv
            JOIN forward_returns fr
              ON fr.symbol = fv.symbol AND fr.tf = fv.tf AND fr.bar_ts = fv.bar_ts
             AND fr.return_type = 'executable_open_to_open'
             AND fr.complete_mid = true
            WHERE fv.symbol = %s AND fv.tf = %s
              AND fv.garch_ratio IS NOT NULL AND fv.hurst IS NOT NULL
            ORDER BY fv.bar_ts
            """,
            (_SYMBOL, _TF),
        )
        rows = cur.fetchall()
    print(
        f"  {len(rows)} feature_vectors x forward_returns rows (complete_mid, garch/hurst non-null)"
    )

    bar_ts_col, garch_col, hurst_col, regime_col, ret_col, jump_col = [], [], [], [], [], []
    for bar_ts, garch, hurst, regime, ret in rows:
        bar_ts = bar_ts if bar_ts.tzinfo else bar_ts.replace(tzinfo=UTC)
        jr = jump_by_ts.get(bar_ts)
        if jr is None:
            continue
        bar_ts_col.append(bar_ts)
        garch_col.append(garch)
        hurst_col.append(hurst)
        regime_col.append(regime)
        ret_col.append(ret)
        jump_col.append(jr)

    n_joined = len(jump_col)
    print(f"  {n_joined} rows after joining jump_ratio (final analysis population)")
    if n_joined < min_reliable_n:
        print(
            f"INSUFFICIENT: joined population {n_joined} < min_reliable_n={min_reliable_n}. Exiting."
        )
        return

    jump_arr = np.asarray(jump_col, dtype=float)
    ret_arr = np.asarray(ret_col, dtype=float)
    controls_arr = np.column_stack(
        [np.asarray(garch_col, dtype=float), np.asarray(hurst_col, dtype=float)]
    )
    regime_arr = np.asarray(regime_col, dtype=object)

    print(
        "\n--- Falsification bar: partial IC of jump_ratio on return_mid, controlling for garch_ratio+hurst ---\n"
    )

    rng = np.random.default_rng(args.seed)
    _report_cell(
        "POOLED",
        jump_arr,
        ret_arr,
        controls_arr,
        block_size=block_size,
        n_boot=n_boot,
        condition_max=condition_max,
        rng=rng,
        min_reliable_n=min_reliable_n,
    )

    print()
    for regime_label in sorted(set(regime_arr.tolist())):
        mask = regime_arr == regime_label
        _report_cell(
            f"regime={regime_label}",
            jump_arr[mask],
            ret_arr[mask],
            controls_arr[mask],
            block_size=block_size,
            n_boot=n_boot,
            condition_max=condition_max,
            rng=rng,
            min_reliable_n=min_reliable_n,
        )

    print(
        "\nVerdict rule (pre-registered): if the pooled CI and every regime CI cross zero, "
        "jump_diffusion_decomposition is dead -- jump_ratio adds nothing beyond garch_ratio+hurst on this pilot."
    )
    conn.close()


if __name__ == "__main__":
    main()
