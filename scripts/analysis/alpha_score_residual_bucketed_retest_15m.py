#!/usr/bin/env python3
"""alpha_score RESIDUAL SINGLE-SECURITY -- BUCKETED retest of condition (d), @ 15m.

Origin: `alpha_score_residual_single_security_15m.py` (Amendment 1) FAILED solely on
condition (4) -- 0/231 symbols individually cleared per-symbol BY-FDR positive, despite
the family statistic clearing conditions (1)-(3) (ci_lower>0, null_p<0.05, point >= 0b
floor), a null-shift p=0.0020, and stability across three ~6.3-year temporal thirds. A
small, uniformly-diffuse per-symbol effect is exactly the signature of a real family-level
effect that is too weak to survive 231-way multiple-testing correction while potentially
surviving a much smaller number of pre-registered GROUP tests. No such bucketed
(coarser-than-per-symbol) version of condition (d) has ever been run -- this script is
that retest, and ONLY that retest. Conditions (1)-(3) are not re-litigated here.

Reconsideration record: `docs/research/2026-09-11-strategic-plans-features-ensemble-
construction.md` (graveyard #3); memory `project_strategic_plans_2026_09_11`.

Locked design (every quantity fixed before looking at any bucket-level result):
- Bucket assignment: `instruments.contract_details->>'sector'` (an existing ingestion-time
  field, not invented for this test), mapped through the FIXED dict `_SECTOR_TO_BUCKET`
  below into 8 GICS-superclass-style buckets, chosen purely from category-name semantics
  with zero visibility into any IC number. A raw sector value absent from the dict raises
  (never silently defaults) -- forces an explicit, reviewable addition rather than a
  post-hoc placement decision. Symbols with NULL sector (24 of 231, mostly non-equity /
  broad-market wrappers already caught by `macro_diversified` where classifiable) are
  EXCLUDED from the bucketed family -- there is no principled ex-ante placement for an
  unclassified name, and forcing one would reopen exactly the post-hoc-boundary risk this
  test is designed to avoid. Reported as a limitation, not silently dropped.
- Per-bucket statistic, CI, and null: IDENTICAL machinery to the family-level arm of the
  parent script -- `Panel.family_stat` / `Panel.bootstrap_ci` / `Panel.sync_shift_null_p`,
  run on a sub-`Panel` built from the bucket's rows only (same pattern the parent script
  already uses for its per-regime and temporal-thirds tables). This reuses the todo-372-
  fixed panel-synchronous shift null verbatim -- no independent null implementation.
- Correction: BY-FDR across the (at most 8) bucket-level null p-values -- NOT the 231-way
  per-symbol family. This is the entire point of the retest: fewer, ex-ante, economically
  motivated hypotheses.
- Bucket "qualifies": BY-FDR-corrected null_p < alpha AND bucket stat > 0 (mirrors the
  per-symbol condition (d) definition exactly, at bucket granularity).
- PASS (this retest only): >= 2 of ~8 buckets qualify. FAST-KILL: 0-1 of ~8 buckets
  qualify -- abandon immediately, do NOT chase finer bucket granularities afterward (the
  fast-kill criterion was set before this script ran, per the reconsideration doc).
- On todo 372 (panel-synchronous null-shift fix, 2026-09-10): reasoned (not yet
  independently reviewed -- AGY/Codex were rate-limited) to have LOW impact on this
  construction's own record specifically, because the residual score is already
  cross-sectionally demeaned per bar before the null runs (the common-mode structure the
  bug's panel-desynchronization risk applies to is already stripped by construction) and
  this is a dense near-daily panel (low active-date-count variance across symbols, unlike
  the sparse event panels where the bug was found). Proceeding without waiting on
  independent review per the reconsideration doc's explicit instruction; flagged, not
  hidden.

Read-only: no writes, no config changes, exit code always 0.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import numpy as np  # noqa: E402
import structlog  # noqa: E402
from statsmodels.stats.multitest import multipletests  # noqa: E402

from scripts.analysis.alpha_score_residual_single_security_15m import (  # noqa: E402
    _FETCH_SQL,
    _MIN_BARS_PER_SYMBOL,
    _N_NULL,
    _TF,
    Panel,
)
from services._batch_utils import cfg as _cfg  # noqa: E402
from services._batch_utils import load_config_service_sync  # noqa: E402
from services.backfill_feature_factory import _connect_db  # noqa: E402
from src.config.settings import Settings  # noqa: E402
from src.core.rng import hash_key_to_int  # noqa: E402
from src.core.service_utils import setup_service_logging  # noqa: E402

setup_service_logging("logs/alpha_score_residual_bucketed_retest_15m.log")
_logger = structlog.get_logger(__name__)

_NAME = "alpha_score_residual_bucketed_retest_15m"
_QUALIFYING_MIN_BUCKETS = 2  # PASS if >= this many of ~8 buckets clear; else fast-kill

# Locked 2026-09-11, before any bucket-level IC was computed. Source values are the
# full observed set of `instruments.contract_details->>'sector'` strings over the 231
# symbols present in the alpha_events 15m family (verified via a live distribution
# query at design time). Grouped by GICS-superclass-style economic similarity only.
_SECTOR_TO_BUCKET: dict[str, str] = {
    "technology": "technology",
    "healthcare": "healthcare",
    "healthcare_biotech": "healthcare",
    "biotech": "healthcare",
    "financials": "financials",
    "real_estate": "financials",
    "mortgage_reit": "financials",
    "preferred_securities": "financials",
    "consumer_discretionary": "consumer",
    "consumer_staples": "consumer",
    "defensive_yield": "consumer",
    "industrials": "industrials_transports",
    "industrials_trucking": "industrials_transports",
    "industrials_rail": "industrials_transports",
    "transports": "industrials_transports",
    "transports_airline": "industrials_transports",
    "transports_platform": "industrials_transports",
    "energy": "energy_materials",
    "energy_midstream": "energy_materials",
    "clean_energy": "energy_materials",
    "materials_mining": "energy_materials",
    "materials_chemicals": "energy_materials",
    "materials_agriculture": "energy_materials",
    "materials": "energy_materials",
    "materials_mining_uranium": "energy_materials",
    "uranium_miners": "energy_materials",
    "gold_miners": "energy_materials",
    "agribusiness": "energy_materials",
    "communication_services": "communication_utilities",
    "communications": "communication_utilities",
    "utilities": "communication_utilities",
    "utilities_water": "communication_utilities",
    "crypto": "macro_diversified",
    "equity": "macro_diversified",
    "commodity": "macro_diversified",
    "fx": "macro_diversified",
    "international": "macro_diversified",
    "broad_market": "macro_diversified",
    "factor": "macro_diversified",
    "factor_market_neutral": "macro_diversified",
    "emerging_markets": "macro_diversified",
    "municipal_bonds": "macro_diversified",
    "rates": "macro_diversified",
    "convertible": "macro_diversified",
    "fixed_income": "macro_diversified",
    "tips": "macro_diversified",
    "high_beta": "macro_diversified",
    "credit": "macro_diversified",
}

_SECTOR_FETCH_SQL = "SELECT symbol, contract_details->>'sector' AS sector FROM instruments"


def main() -> None:
    settings = Settings()
    conn = _connect_db(settings)
    apr = load_config_service_sync(conn)
    apr_dict = apr._cache
    n_boot = int(_cfg(apr_dict, "alpha.ic.bootstrap_resamples", 2000))
    fdr_alpha = float(_cfg(apr_dict, "alpha.ic.fdr_alpha", 0.05))
    print(f"{_NAME} -- tf={_TF}, bucketed retest of condition (d) only")
    print(f"n_null={_N_NULL} n_boot={n_boot} fdr_alpha={fdr_alpha}")

    print("\nStreaming panel (completion-blind demeaning in SQL) ...")
    sym_code: dict[str, int] = {}
    chunks = {k: [] for k in ("sym", "date", "resid", "ret")}
    n_fetched = 0
    with conn.transaction():
        with conn.cursor(name="bucket_fetch") as cur:
            cur.itersize = 200_000
            cur.execute(_FETCH_SQL, (_TF, _TF))
            while True:
                batch = cur.fetchmany(200_000)
                if not batch:
                    break
                n_fetched += len(batch)
                n = len(batch)
                sym = np.empty(n, dtype=np.int16)
                for i, (symbol, _bar_ts, _regime, _raw, _resid, _ret) in enumerate(batch):
                    code = sym_code.setdefault(symbol, len(sym_code))
                    sym[i] = code
                chunks["sym"].append(sym)
                chunks["date"].append(
                    np.array(
                        [r[1].year * 10000 + r[1].month * 100 + r[1].day for r in batch],
                        dtype=np.int32,
                    )
                )
                chunks["resid"].append(np.array([r[4] for r in batch], dtype=np.float64))
                chunks["ret"].append(np.array([r[5] for r in batch], dtype=np.float64))
    print(f"  {n_fetched:,} measurement rows, {len(sym_code)} symbols")

    with conn.cursor() as cur:
        cur.execute(_SECTOR_FETCH_SQL)
        sector_by_symbol = dict(cur.fetchall())
    conn.close()

    A = {k: np.concatenate(v) for k, v in chunks.items()}
    full_panel = Panel(A["sym"], A["date"], A["resid"], A["ret"])
    print(f"  full family: {len(full_panel.family)} symbols with >= {_MIN_BARS_PER_SYMBOL} rows")

    code_to_sym = {v: k for k, v in sym_code.items()}
    bucket_of_code: dict[int, str | None] = {}
    unmapped: set[str] = set()
    n_null_sector = 0
    for code, symbol in code_to_sym.items():
        sector = sector_by_symbol.get(symbol)
        if sector is None:
            bucket_of_code[code] = None
            n_null_sector += 1
            continue
        bucket = _SECTOR_TO_BUCKET.get(sector)
        if bucket is None:
            unmapped.add(sector)
            bucket_of_code[code] = None
            continue
        bucket_of_code[code] = bucket
    if unmapped:
        raise ValueError(
            f"{_NAME}: sector value(s) not in the pre-registered _SECTOR_TO_BUCKET map: "
            f"{sorted(unmapped)} -- this is exactly the post-hoc-boundary risk the "
            f"pre-registration forbids; extend the map deliberately, do not auto-bucket."
        )
    print(
        f"  {n_null_sector} symbols excluded (NULL sector, no ex-ante bucket) -- "
        "reported, not gated"
    )

    buckets = sorted(set(bucket_of_code.values()) - {None})
    print(f"  {len(buckets)} buckets: {buckets}")

    results = []
    for bucket in buckets:
        codes_in_bucket = np.array(
            [c for c, b in bucket_of_code.items() if b == bucket], dtype=np.int64
        )
        row_mask = np.isin(A["sym"], codes_in_bucket)
        sub = Panel(
            A["sym"][row_mask], A["date"][row_mask], A["resid"][row_mask], A["ret"][row_mask]
        )
        n_syms_total = len(codes_in_bucket)
        n_syms_family = len(sub.family)
        stat = sub.family_stat()
        rng_boot = np.random.default_rng(hash_key_to_int(f"{_NAME}_{bucket}_boot"))
        lo, hi = sub.bootstrap_ci(rng_boot, n_boot)
        rng_null = np.random.default_rng(hash_key_to_int(f"{_NAME}_{bucket}_null"))
        p = sub.sync_shift_null_p(stat, rng_null, _N_NULL)
        results.append(
            {
                "bucket": bucket,
                "n_syms_total": n_syms_total,
                "n_syms_family": n_syms_family,
                "stat": stat,
                "ci_lower": lo,
                "ci_upper": hi,
                "null_p": p,
            }
        )
        print(
            f"  {bucket}: n_syms={n_syms_family}/{n_syms_total} stat={stat:.5f} "
            f"CI=[{lo:.5f}, {hi:.5f}] null_p={p:.4f}"
        )

    print("\n--- BY-FDR across bucket-level null p-values (the retest of condition d) ---")
    null_ps = [r["null_p"] for r in results if not np.isnan(r["stat"])]
    valid = [r for r in results if not np.isnan(r["stat"])]
    if null_ps:
        reject_by, p_corr, _, _ = multipletests(null_ps, alpha=fdr_alpha, method="fdr_by")
    else:
        reject_by, p_corr = np.array([]), np.array([])
    n_qualify = 0
    for r, rej, pc in zip(valid, reject_by, p_corr):
        qualifies = bool(rej) and r["stat"] > 0
        n_qualify += int(qualifies)
        print(
            f"  {r['bucket']}: null_p={r['null_p']:.4f} BY_p={pc:.4f} "
            f"reject={bool(rej)} stat>0={r['stat'] > 0} QUALIFIES={qualifies}"
        )

    frac = n_qualify / len(valid) if valid else 0.0
    verdict = "PASS" if n_qualify >= _QUALIFYING_MIN_BUCKETS else "FAST-KILL"
    print(
        f"\nqualifying buckets: {n_qualify}/{len(valid)} ({frac:.1%})  "
        f"[fast-kill threshold: <= 1]"
    )
    print(f"\nVERDICT: {verdict}")
    if verdict == "FAST-KILL":
        print(
            "  Per pre-registration: abandon the bucketed-retest line for "
            "alpha_score_residual_single_security_15m. Do not chase finer bucket "
            "granularities. Update construction-verdict-ledger.md."
        )
    else:
        print(
            "  Per pre-registration: this is a genuine, non-fast-killed positive "
            "signal at bucket granularity -- escalate to a full write-up before any "
            "gate claim (this diagnostic alone is not a gate pass)."
        )


if __name__ == "__main__":
    main()
