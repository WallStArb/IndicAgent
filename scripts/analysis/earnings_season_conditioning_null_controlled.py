#!/usr/bin/env python3
"""Todo 403: evaluate the pre-registered, dependence-robust earnings-season conditioning rule
against the persisted 176-08 feature_ic_scores rows. Read-only.

Rule and derivation: docs/research/earnings-season-conditioning-null-controlled-prereg.md.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import numpy as np  # noqa: E402
from scipy.stats import norm  # noqa: E402
from statsmodels.stats.multitest import multipletests  # noqa: E402

from services.backfill_feature_factory import _connect_db  # noqa: E402
from src.config.settings import Settings  # noqa: E402

_WINDOW = "2025-12-24 05:15:00+00"
_MIN_TRIPLES = 10
_MIN_UNITS = 30
_Q = 0.05
_Z975 = float(norm.ppf(0.975))

# Matched triples exactly as 176-08's Rule 2 (176-GATE-VERDICT.md Appendix A), carrying CIs.
_UNITS_SQL = f"""
WITH s AS (
    SELECT * FROM feature_ic_scores
    WHERE training_window_end = %(w)s AND regime_scope = 'earnings_season'
),
k AS (
    SELECT feature_name, tf, symbol, lookahead_bars,
           CASE WHEN regime LIKE '%%\\_\\_%%' THEN split_part(regime, '__', 1) ELSE '_pooled' END parent,
           CASE WHEN regime LIKE '%%\\_\\_%%' THEN 'cs' ELSE 'ps' END kind,
           max(ic_value)    FILTER (WHERE regime LIKE '%%in_season')  ic_in,
           max(ic_ci_lower) FILTER (WHERE regime LIKE '%%in_season')  lo_in,
           max(ic_ci_upper) FILTER (WHERE regime LIKE '%%in_season')  hi_in,
           max(ic_value)    FILTER (WHERE regime LIKE '%%off_season') ic_off,
           max(ic_ci_lower) FILTER (WHERE regime LIKE '%%off_season') lo_off,
           max(ic_ci_upper) FILTER (WHERE regime LIKE '%%off_season') hi_off
    FROM s GROUP BY 1, 2, 3, 4, 5, 6
),
t AS (
    SELECT k.feature_name, k.tf,
           sign(p.ic_value) * (k.ic_in - k.ic_off)
             / sqrt(power((k.hi_in - k.lo_in) / {2 * _Z975}, 2)
                  + power((k.hi_off - k.lo_off) / {2 * _Z975}, 2)) AS z
    FROM k
    JOIN feature_ic_scores p
      ON p.training_window_end = %(w)s AND p.feature_name = k.feature_name AND p.tf = k.tf
     AND p.symbol = k.symbol AND p.lookahead_bars = k.lookahead_bars AND p.regime = k.parent
     AND p.regime_scope = CASE WHEN k.kind = 'cs' THEN 'cross_sectional' ELSE 'pooled' END
    WHERE p.passes_fdr AND p.ic_value <> 0
      AND k.ic_in IS NOT NULL AND k.ic_off IS NOT NULL
      AND k.hi_in > k.lo_in AND k.hi_off > k.lo_off
)
SELECT feature_name, tf, count(*) n,
       percentile_cont(0.5) WITHIN GROUP (ORDER BY z) median_z
FROM t GROUP BY 1, 2
"""


def _arm(units: list[tuple], sign: int, label: str) -> dict[str, list[str]]:
    """sign=+1: in-season stronger; sign=-1: the mirror arm (d negated, so median z flips)."""
    zs = np.array([sign * u[3] for u in units])
    p = np.minimum(1.0, 2.0 * norm.sf(zs))
    reject = multipletests(p, alpha=_Q, method="fdr_by")[0]
    by_feature: dict[str, list[str]] = {}
    for u, r in zip(units, reject, strict=True):
        if r:
            by_feature.setdefault(u[0], []).append(u[1])
    print(f"\n[{label}] BY-significant units: {int(reject.sum())} of {len(units)}")
    for u, z, pv, r in sorted(zip(units, zs, p, reject, strict=True), key=lambda x: x[2])[:15]:
        print(
            f"  {u[0]:<40s} {u[1]:>4s} n={u[2]:<5d} median_z={z:+.3f} p_bound={pv:.2e} {'*' if r else ''}"
        )
    return by_feature


def main() -> None:
    conn = _connect_db(Settings())
    with conn.cursor() as cur:
        cur.execute(_UNITS_SQL, {"w": _WINDOW})
        rows = cur.fetchall()
    conn.close()

    units = [r for r in rows if r[2] >= _MIN_TRIPLES]
    print(
        f"(feature, tf) units with usable triples: {len(rows)}; eligible (n >= {_MIN_TRIPLES}): {len(units)}"
    )
    for tf in ("5m", "15m", "1h", "1d"):
        zs = [u[3] for u in units if u[1] == tf]
        if zs:
            print(f"  {tf:>4s}: {len(zs)} units, median of unit median_z = {np.median(zs):+.3f}")
    if len(units) < _MIN_UNITS:
        print("\nCONDITIONING_VERDICT=INSUFFICIENT_N")
        return

    in_arm = _arm(units, 1, "in-season stronger")
    mirror = _arm(units, -1, "mirror: off-season stronger")

    multi_tf = {f: tfs for f, tfs in in_arm.items() if len(tfs) >= 2}
    print(f"\nFeatures BY-significant in >= 2 tfs (in-season arm): {multi_tf or 'none'}")
    print(
        f"Mirror features in >= 2 tfs: { {f: t for f, t in mirror.items() if len(t) >= 2} or 'none'}"
    )
    print(f"\nCONDITIONING_VERDICT={'SHARPENS' if multi_tf else 'NOT_SHARPENED'}")


if __name__ == "__main__":
    main()
