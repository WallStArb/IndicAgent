#!/usr/bin/env python3
"""Cheapest honest first test of cross-TF signal fusion as a NEW construction paradigm,
per Fable's review 2026-09-13 (consulted after the user asked whether universe
expansion should come with a TF-stack reduction, which surfaced that no construction
in this program has ever combined signals ACROSS timeframes -- every one of the 14
verdicted constructions is single-TF; alpha_events itself is keyed strictly
(symbol, tf, bar_ts) with no cross-TF fusion mechanism in the live path).

Fable's framing, adopted here: "untried" is not evidence of promise on its own -- most
untried ideas are untried because they're bad. The falsifiable question underneath is
whether a coarse-TF read and a fine-TF read of the SAME underlying factor are
empirically decorrelated (real, new information) or just the same handful of signals
re-expressed at different sampling rates with correlated noise (no new breadth). Phase
148 already found 100% sign co-firing across 15m/1h/1d for one construction
(alpha_score) -- a bad omen this script must be honest about, not paper over.

NOT a construction falsification, NOT a pre-registration -- a screen, same status and
discipline as personal_edge_paper_screen.py (0c): it shortlists a direction worth a
real pre-registration, or it closes the direction next to the other 14 DEAD/FAIL
verdicts and does not get revisited under a different framing (Fable's own guardrail
against goalpost-moving after a kill criterion has fired).

Method: for two of this program's independently-confirmed signal families (0a:
momentum and range/vol are the two families with genuinely independent IC-profile
correlation, mean cross-family corr -0.003) -- momentum_z_fast and range_pct_fast --
align

CORRECTION (same session): the first run of this script used `ctf_momentum`, which
turned out to be the WRONG feature choice for this question -- `ctf_momentum` ("CTF" =
Cross-TimeFrame) is not computed independently per tf; per `ctf_higher_tf_map`
(feature_factory.py) it is a HIGHER-timeframe value READ DOWN into lower-tf rows via a
bisect lookup (5m and 15m both read from 1h; 1h reads from 1d; only 1d is
self-referential/native). That first run's 15m-vs-5m correlation came back EXACTLY
1.0000 -- not "very high", literally identical, because both are reading the identical
upstream 1h value. This is not a cross-TF fusion test at all when using ctf_momentum --
it's an internal-consistency check of an ALREADY-EXISTING broadcast mechanism, and it
revealed something worth recording separately (the codebase already fuses HTF context
into LTF feature rows at the feature-computation level, contradicting the "zero
cross-TF fusion anywhere" claim made earlier the same session, which was only true at
the alpha_score/ensemble_trainer level, not the feature level). `momentum_z_fast`
verified clean (no ctf/htf/bisect reference anywhere in its computation path) and used
instead -- the results below are the corrected, unconfounded run.
each coarse-TF bar's value against the fine-TF's LAST bar covering the same calendar
date (a pure informational-overlap comparison: does the fine-grained read agree with
the coarse-grained read of the SAME underlying quantity at the SAME point in time, not
a predictive claim -- lookahead is not a concern here because nothing is being traded
or scored against a forward return). Report both Spearman correlation (pooled across
all symbol-dates) and sign-agreement rate for all 6 TF-pair combinations
(1d-1h, 1d-15m, 1d-5m, 1h-15m, 1h-5m, 15m-5m), for both features -- no cherry-picking a
favorable pairing.

Read-only. No writes -- a screen, no concept_registry row, no PASS/FAIL gate.
"""

from __future__ import annotations

import sys
from itertools import combinations
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from scipy.stats import spearmanr  # noqa: E402

from services.backfill_feature_factory import _connect_db  # noqa: E402
from src.config.settings import Settings  # noqa: E402

_TFS = ("1d", "1h", "15m", "5m")  # coarse to fine, for readable pair ordering
_FEATURES = ("momentum_z_fast", "range_pct_fast")  # both verified TF-native, no
# ctf/htf broadcast dependency -- see module docstring's correction note


def _fetch_last_bar_per_date(conn, feature: str, tf: str) -> pd.DataFrame:
    """One row per (symbol, date): the value at that symbol's LAST bar of the day at
    this tf -- for 1d itself this is just the bar's own value (one bar per date)."""
    with conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT DISTINCT ON (symbol, bar_ts::date)
                   symbol, bar_ts::date AS d, {feature} AS val
            FROM feature_vectors
            WHERE tf = %s AND {feature} IS NOT NULL
            ORDER BY symbol, bar_ts::date, bar_ts DESC
            """,
            (tf,),
        )
        rows = cur.fetchall()
    return pd.DataFrame(rows, columns=["symbol", "d", "val"])


def _compare(coarse: pd.DataFrame, fine: pd.DataFrame) -> tuple[float, float, int]:
    merged = coarse.merge(fine, on=["symbol", "d"], suffixes=("_coarse", "_fine"))
    if len(merged) < 100:
        return float("nan"), float("nan"), len(merged)
    rho, _ = spearmanr(merged["val_coarse"], merged["val_fine"])
    sign_agree = float((np.sign(merged["val_coarse"]) == np.sign(merged["val_fine"])).mean())
    return float(rho), sign_agree, len(merged)


def main() -> None:
    settings = Settings()
    conn = _connect_db(settings)

    print(
        f"{'feature':14s} {'coarse':>6s} {'fine':>6s} {'n_pairs':>10s} {'spearman_rho':>13s} {'sign_agree':>11s}"
    )

    for feature in _FEATURES:
        by_tf = {tf: _fetch_last_bar_per_date(conn, feature, tf) for tf in _TFS}
        for coarse_tf, fine_tf in combinations(_TFS, 2):
            rho, sign_agree, n = _compare(by_tf[coarse_tf], by_tf[fine_tf])
            print(
                f"{feature:14s} {coarse_tf:>6s} {fine_tf:>6s} {n:>10d} "
                f"{rho:>13.4f} {sign_agree:>11.3f}"
            )

    conn.close()
    print(
        "\nReference point (Fable's framing): Phase 148 already measured 100% sign "
        "co-firing across 15m/1h/1d for alpha_score -- a construction confirmed to be "
        "one systematic directional bet re-expressed at different sampling rates, not "
        "independent breadth. Sign-agreement rates near that ceiling here mean the same "
        "is true of these underlying feature families; cross-TF fusion would not add "
        "new information, only new infrastructure cost. A materially lower agreement "
        "rate (real decorrelation) is the actual green light for a real pre-registration "
        "on the DIVERGENCE framing Fable specifically flagged as the untried shape "
        "(betting when coarse and fine reads disagree, not confirm) -- not a generic "
        "'combine timeframes' construction, which risks re-discovering Phase 148's "
        "failure mode under a new name."
    )


if __name__ == "__main__":
    main()
