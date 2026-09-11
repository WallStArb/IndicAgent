#!/usr/bin/env python3
"""cointegrated_pairs_residual -- same-sector single-equity screen (graveyard #5
reconsideration, Stage 1/2 only).

Origin: the original pilot (docs/research/measurement-cointegrated-pairs-residual.md,
scripts/analysis/cointegrated_pairs_residual_pilot.py) tested 6 hand-picked, broad
sector/asset-class ETF pairs -- 0/6 cointegrate (Stage 1). That verdict stands for
what was tested. But it is the ONLY search ever done: the 182-equity universe was
never screened at any scale. Classical pairs-trading's actual sweet spot is
same-industry SINGLE NAMES (tight fundamental linkage) -- broad ETFs have a
structural reason to fail (creation/redemption arbitrage smooths away exactly the
dislocations a stat-arb strategy needs). This script is that untried screen, Stages
1-2 only (Engle-Granger + split-sample stability); Stages 3-5 (OU fit, falsification
bar, cost gate) run only for pairs that survive both, per the original design's own
staged gating.

Reconsideration record: docs/research/2026-09-11-strategic-plans-features-ensemble-
construction.md (graveyard #5); memory project_strategic_plans_2026_09_11.

Locked design (every quantity fixed before any pair result is seen):
- Universe: symbols tagged `single_name_equity` in `instrument_tags` (ITR, an
  existing tag -- not invented for this test), grouped by the existing
  `instruments.contract_details->>'sector'` field.
- Candidate pairs: every same-sector pair where the sector has >= 2 tagged members --
  economically motivated (tight fundamental linkage), not a blind ~16,500-pair
  (C(231,2)) fishing expedition across the whole universe -- keeps the multiple-
  testing correction tractable and the candidates individually defensible.
  Sub-sector granularity is used AS TAGGED (e.g. `healthcare_biotech` kept separate
  from `healthcare`): finer granularity means TIGHTER economic linkage for a pairs
  screen specifically -- the opposite of graveyard #3's bucketing goal, which wanted
  coarser groups for statistical power, not closer linkage.
- Data sufficiency: a pair is tested only if it has >= 500 in-sample (pre-2024-01-01)
  AND >= 100 OOS (post-2024-01-01) overlapping daily-close trading days. Insufficient
  pairs are reported separately, never silently dropped or counted as a Stage-1
  failure -- keeps the FDR family well-defined (only pairs that were genuinely
  testable are in it).
- Stage 1 (in-sample cointegration): `statsmodels.tsa.stattools.coint`, trend="c",
  autolag="aic", split_date=2024-01-01 -- IDENTICAL methodology and split date to the
  original 6-ETF-pair pilot, reused verbatim via import (_engle_granger, _split,
  _daily_log_closes), not reimplemented.
- Correction: BY-FDR across ALL tested pairs' Stage 1 p-values. The original 6-pair
  pilot needed no correction at n=6; this screen tests ~450+ pairs and needs it --
  this is the entire point of restricting to same-sector single names rather than a
  blind full-universe scan (keeps the family small enough that FDR still has power).
- Stage 2 (split-sample stability): re-run Engle-Granger on the OOS (post-2024-01-01)
  window, restricted to pairs surviving corrected Stage 1 only. A pair must
  cointegrate in BOTH halves to qualify -- matches the item's own pre-registered
  refinement ("cointegrates in both halves, not just pooled").
- Qualifying pair: BY-FDR-corrected Stage 1 p < fdr_alpha AND Stage 2 (OOS,
  uncorrected -- already conditioned on surviving the corrected family test) p < 0.05.
- Fast-kill (pre-registered): if the qualifying rate is statistically
  indistinguishable from what BY-FDR's own false-discovery control already implies
  (i.e., 0, or a handful requiring no further explanation), that is a STRONGER,
  structural conclusion than the original 0/6 -- cointegration is genuinely rare in
  this corpus/era regardless of granularity, and the construction type closes for
  good. Do NOT proceed to Stages 3-5 on any survivor without first checking the
  survivor count is not itself just chance.

Read-only: no writes, no config changes, exit code always 0.
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import numpy as np  # noqa: E402
from statsmodels.stats.multitest import multipletests  # noqa: E402

from scripts.analysis.cointegrated_pairs_residual_pilot import (  # noqa: E402
    _daily_log_closes,
    _engle_granger,
    _split,
)
from services._batch_utils import cfg as _cfg  # noqa: E402
from services._batch_utils import load_config_service_sync  # noqa: E402
from services.backfill_feature_factory import _connect_db  # noqa: E402
from src.config.settings import Settings  # noqa: E402
from src.core.service_utils import setup_service_logging  # noqa: E402

setup_service_logging("logs/cointegrated_pairs_residual_same_sector_screen.log")

_NAME = "cointegrated_pairs_residual_same_sector_screen"
_SPLIT_DATE = date(2024, 1, 1)  # identical to the original pilot -- data-availability
# choice, not re-tuned for this screen
_MIN_IN_SAMPLE_DAYS = 500
_MIN_OOS_DAYS = 100

_SECTOR_SQL = """
SELECT it.symbol, i.contract_details->>'sector' AS sector
FROM instrument_tags it
JOIN instruments i ON i.symbol = it.symbol
WHERE it.tag = 'single_name_equity'
ORDER BY 1
"""


def _candidate_pairs(conn) -> dict[str, list[tuple[str, str]]]:
    with conn.cursor() as cur:
        cur.execute(_SECTOR_SQL)
        rows = cur.fetchall()
    by_sector: dict[str, list[str]] = {}
    for symbol, sector in rows:
        by_sector.setdefault(sector, []).append(symbol)
    pairs_by_sector: dict[str, list[tuple[str, str]]] = {}
    for sector, symbols in by_sector.items():
        symbols = sorted(symbols)
        if len(symbols) < 2:
            continue
        pairs_by_sector[sector] = [
            (symbols[i], symbols[j])
            for i in range(len(symbols))
            for j in range(i + 1, len(symbols))
        ]
    return pairs_by_sector


def main() -> None:
    settings = Settings()
    conn = _connect_db(settings)
    apr = load_config_service_sync(conn)
    fdr_alpha = float(_cfg(apr._cache, "alpha.ic.fdr_alpha", 0.05))

    pairs_by_sector = _candidate_pairs(conn)
    total_candidates = sum(len(v) for v in pairs_by_sector.values())
    print(f"{_NAME} -- split_date={_SPLIT_DATE}, fdr_alpha={fdr_alpha}")
    print(f"{len(pairs_by_sector)} sectors, {total_candidates} candidate same-sector pairs\n")

    all_symbols = sorted({s for pairs in pairs_by_sector.values() for pair in pairs for s in pair})
    print(f"Fetching daily log closes for {len(all_symbols)} symbols ...")
    closes: dict[str, tuple[list[date], np.ndarray]] = {}
    for sym in all_symbols:
        closes[sym] = _daily_log_closes(conn, sym)
    conn.close()

    tested: list[dict] = []
    skipped_insufficient = 0
    for sector, pairs in pairs_by_sector.items():
        for sym_a, sym_b in pairs:
            dates_a, close_a = closes[sym_a]
            dates_b, close_b = closes[sym_b]
            if dates_a != dates_b:
                common = sorted(set(dates_a) & set(dates_b))
                idx_a = {d: i for i, d in enumerate(dates_a)}
                idx_b = {d: i for i, d in enumerate(dates_b)}
                a = np.array([close_a[idx_a[d]] for d in common])
                b = np.array([close_b[idx_b[d]] for d in common])
                dates_common = common
            else:
                a, b, dates_common = close_a, close_b, dates_a

            a_in, a_out = _split(dates_common, a, _SPLIT_DATE)
            b_in, b_out = _split(dates_common, b, _SPLIT_DATE)
            if len(a_in) < _MIN_IN_SAMPLE_DAYS or len(a_out) < _MIN_OOS_DAYS:
                skipped_insufficient += 1
                continue

            stage1 = _engle_granger(a_in, b_in)
            tested.append(
                {
                    "sector": sector,
                    "pair": f"{sym_a}/{sym_b}",
                    "a_in": a_in,
                    "b_in": b_in,
                    "a_out": a_out,
                    "b_out": b_out,
                    "n_in": len(a_in),
                    "n_out": len(a_out),
                    "stage1_p": stage1.p_value,
                }
            )

    print(
        f"{len(tested)} pairs tested (Stage 1), {skipped_insufficient} skipped (insufficient data)\n"
    )

    stage1_ps = [t["stage1_p"] for t in tested]
    reject_by, p_corr, _, _ = multipletests(stage1_ps, alpha=fdr_alpha, method="fdr_by")
    for t, rej, pc in zip(tested, reject_by, p_corr):
        t["stage1_reject_by"] = bool(rej)
        t["stage1_by_p"] = float(pc)

    stage1_survivors = [t for t in tested if t["stage1_reject_by"]]
    print(f"--- Stage 1 (BY-FDR corrected, alpha={fdr_alpha}) ---")
    print(f"{len(stage1_survivors)}/{len(tested)} pairs survive corrected Stage 1\n")
    for t in sorted(stage1_survivors, key=lambda r: r["stage1_by_p"]):
        print(
            f"  {t['sector']}: {t['pair']} raw_p={t['stage1_p']:.5f} BY_p={t['stage1_by_p']:.5f} "
            f"n_in={t['n_in']} n_out={t['n_out']}"
        )

    print("\n--- Stage 2 (OOS split-sample stability, uncorrected -- conditioned on Stage 1) ---")
    qualifying = []
    for t in stage1_survivors:
        stage2 = _engle_granger(t["a_out"], t["b_out"])
        t["stage2_p"] = stage2.p_value
        t["qualifies"] = stage2.p_value < 0.05
        print(
            f"  {t['sector']}: {t['pair']} stage2_p={stage2.p_value:.5f} "
            f"{'QUALIFIES' if t['qualifies'] else 'FAIL (not OOS-stable)'}"
        )
        if t["qualifies"]:
            qualifying.append(t)

    print(
        f"\nqualifying pairs (Stage 1 BY-FDR pass AND Stage 2 OOS pass): {len(qualifying)}/{len(tested)}"
    )
    verdict = "OPEN -- proceed to Stage 3+" if qualifying else "FAST-KILL"
    print(f"\nVERDICT: {verdict}")
    if not qualifying:
        print(
            "  Per pre-registration: 0 pairs survive both a BY-FDR-corrected in-sample "
            "cointegration test AND independent OOS reconfirmation, across "
            f"{len(tested)} economically-motivated same-sector single-name candidates. "
            "This is a stronger, structural conclusion than the original 0/6: "
            "cointegration is genuinely rare in this corpus/era regardless of "
            "granularity. Close the construction type for good -- do not narrow "
            "further (e.g. to sub-industry). Update construction-verdict-ledger.md."
        )
    else:
        print(
            f"  {len(qualifying)} pair(s) survive both stages -- proceed to Stage 3 (OU fit) "
            "for these only, per the original pilot's staged design. Do not skip Stages "
            "3-5; a PASS here is not itself a tradeable construction."
        )


if __name__ == "__main__":
    main()
