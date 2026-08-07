"""Todo 243 follow-up, 5m: how much did the CTF join fix (commit 42c69b93) move ctf_momentum's
actual IC at the highest-frequency tf this corpus measures?

Same measurement as ctf_momentum_join_fix_ic_impact_spy_1h.py (1h pilot: old-join
point_ic=+0.0517 -> new-join point_ic=-0.0159, paired-diff CI [0.0626, 0.0730]) and
..._15m.py. 5m's CTF HTF is 1h (FeatureFactoryConfig.ctf_higher_tf_map), same as 15m -- the
join's lookahead window is bounded by a 1h HTF bar (up to 55min), not a full day.

Both paths reuse the real production functions unmodified (see the 1h script's docstring for
the OLD/NEW join mechanics -- unchanged here, only _TF/_HTF_TF differ).

Bootstrap block_size=78 matches live `alpha.ic.bootstrap_block_size.5m` (config_state,
confirmed 2026-08-03), same per-tf convention as the 15m script and the
nonlinear_interaction_combiner replication scripts.

Usage: .venv/bin/python scripts/analysis/ctf_momentum_join_fix_ic_impact_spy_5m.py
"""

from __future__ import annotations

import bisect
import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import numpy as np
import psycopg

from scripts.analysis._nonlinear_interaction_combiner_shared import (  # noqa: E402
    bootstrap_ic_stats,
    paired_bootstrap_ic_difference,
)
from services.backfill_feature_factory import (  # noqa: E402
    _build_ctf_series,
    _fetch_bars_from_db,
    _rekey_ctf_series_to_actual_close,
)
from src.config.settings import Settings  # noqa: E402

_SYMBOL = "SPY"
_TF = "5m"
_HTF_TF = "1h"
_RSI_MID_PERIOD = 14  # live config_state value for feature.period.rsi.mid as of 2026-08-03
_BOOTSTRAP_BLOCK_SIZE = 78  # live alpha.ic.bootstrap_block_size.5m
_N_BOOT = 500
_BOOTSTRAP_SEED = 42

_FETCH_FORWARD_RETURNS_SQL = """
SELECT bar_ts, return_fast
FROM forward_returns
WHERE symbol = %s AND tf = %s
  AND return_type = 'executable_open_to_open'
  AND complete_fast = true
ORDER BY bar_ts ASC
"""


@dataclass(frozen=True)
class _MinimalConfig:
    """Stand-in for FeatureFactoryConfig -- _build_ctf_series only reads rsi_mid_period."""

    rsi_mid_period: int


def _join_ctf_momentum(ctf_by_ts: dict, ltf_bar_ts: list) -> np.ndarray:
    """Verbatim copy of FeatureFactory.compute_batch's bisect join (feature_factory.py:6923-6935),
    extracting only ctf_momentum (index 0 of the stored tuple)."""
    ctf_ts_list = sorted(ctf_by_ts.keys())
    out = np.empty(len(ltf_bar_ts), dtype=float)
    for i, bar_ts in enumerate(ltf_bar_ts):
        idx = bisect.bisect_right(ctf_ts_list, bar_ts) - 1
        out[i] = ctf_by_ts[ctf_ts_list[idx]][0] if idx >= 0 else 0.0
    return out


def main() -> None:
    settings = Settings()
    conn = psycopg.connect(settings.database_url)
    conn.autocommit = True

    print(f"Fetching {_SYMBOL} {_HTF_TF} (HTF) and {_TF} (LTF) bars...")
    htf_bars = _fetch_bars_from_db(conn, _SYMBOL, _HTF_TF)
    ltf_bars = _fetch_bars_from_db(conn, _SYMBOL, _TF)
    print(f"  {_HTF_TF}: {len(htf_bars)} bars, {_TF}: {len(ltf_bars)} bars")

    config = _MinimalConfig(rsi_mid_period=_RSI_MID_PERIOD)
    old_ctf_by_ts = _build_ctf_series(htf_bars, config)
    new_ctf_by_ts = _rekey_ctf_series_to_actual_close(old_ctf_by_ts, _TF, _HTF_TF)
    print(f"  ctf series: {len(old_ctf_by_ts)} old-keyed entries, {len(new_ctf_by_ts)} rekeyed")

    ltf_bar_ts = [b["ts"] for b in ltf_bars]
    old_scores_full = _join_ctf_momentum(old_ctf_by_ts, ltf_bar_ts)
    new_scores_full = _join_ctf_momentum(new_ctf_by_ts, ltf_bar_ts)

    print(f"Fetching {_SYMBOL} {_TF} executable_open_to_open forward returns...")
    with conn.cursor() as cur:
        cur.execute(_FETCH_FORWARD_RETURNS_SQL, (_SYMBOL, _TF))
        fr_rows = cur.fetchall()
    fr_by_ts = {r[0] if r[0].tzinfo else r[0]: float(r[1]) for r in fr_rows if r[1] is not None}
    print(f"  {len(fr_by_ts)} forward-return rows")

    old_scores, new_scores, actual = [], [], []
    for i, bar_ts in enumerate(ltf_bar_ts):
        ret = fr_by_ts.get(bar_ts)
        if ret is None:
            continue
        old_scores.append(old_scores_full[i])
        new_scores.append(new_scores_full[i])
        actual.append(ret)

    old_scores_arr = np.array(old_scores)
    new_scores_arr = np.array(new_scores)
    actual_arr = np.array(actual)
    n = len(actual_arr)
    print(f"  {n} rows with a joined forward return")

    if n < 50:
        print(f"ABORT: n={n} too small for a meaningful bootstrap (need >= 50).")
        return

    old_stats = bootstrap_ic_stats(
        old_scores_arr, actual_arr, _BOOTSTRAP_BLOCK_SIZE, _N_BOOT, _BOOTSTRAP_SEED
    )
    new_stats = bootstrap_ic_stats(
        new_scores_arr, actual_arr, _BOOTSTRAP_BLOCK_SIZE, _N_BOOT, _BOOTSTRAP_SEED
    )
    paired = paired_bootstrap_ic_difference(
        old_scores_arr, new_scores_arr, actual_arr, _BOOTSTRAP_BLOCK_SIZE, _N_BOOT, _BOOTSTRAP_SEED
    )

    print("=" * 80)
    print(f"{_SYMBOL} {_TF} ctf_momentum: OLD (buggy) join vs NEW (fixed) join, n={n}")
    print("=" * 80)
    print(
        f"OLD join   point_ic={old_stats['point_ic']:.4f}  "
        f"CI=[{old_stats['ci_lower']:.4f}, {old_stats['ci_upper']:.4f}]  "
        f"passes={old_stats['passes']}"
    )
    print(
        f"NEW join   point_ic={new_stats['point_ic']:.4f}  "
        f"CI=[{new_stats['ci_lower']:.4f}, {new_stats['ci_upper']:.4f}]  "
        f"passes={new_stats['passes']}"
    )
    print(
        f"PAIRED diff (old-new)  point_diff={paired['point_diff']:.4f}  "
        f"CI=[{paired['ci_lower']:.4f}, {paired['ci_upper']:.4f}]  "
        f"old_significantly_better={paired['a_significantly_better']}  "
        f"new_significantly_better={paired['b_significantly_better']}"
    )
    print("=" * 80)


if __name__ == "__main__":
    main()
