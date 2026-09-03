#!/usr/bin/env python3
"""alpha_score RESIDUAL SINGLE-SECURITY diagnostic @ 15m -- Pre-registration 2,
Amendment 1, of docs/plans/2026-09-02-personal-scale-edge-determination-plan.md
(AGY review archived at .planning/research/2026-09-03-agy-review-prereg2-residual-15m.md).

Mandate: todo 278 (closed 2026-08-08) -- the residual-stripping construction must
clear a properly-powered diagnostic before any authoritative gate under a new
gate_id. The two 2026-08-08 scripts tested adjacent questions (per-bar
cross-sectional rank IC, invariant to demeaning -> the portfolio question; and
raw-score single-security). THIS is the mandated test: does the per-bar
cross-sectionally demeaned alpha_score residual predict ITS OWN symbol's forward
return (time-series only, no cross-sectional ranking, no short leg)?

Locked design (Amendment 1; every quantity fixed before any run):
- family statistic = mean across family symbols of within-symbol Spearman
  IC(residual, return_mid); family = symbols with >= 100 measurement rows
- CI: circular moving-block bootstrap over trading DATES, block=5, synchronous
  across symbols (a date block carries every symbol's rows), B=2000
- null: panel-synchronous whole-DATE circular shift, ONE common k per replicate
  (k mod each symbol's own date count), N=1000; preserves within-date
  cross-sectional structure and time-of-day alignment, breaks only the
  residual -> own-return temporal alignment
- demeaning population is COMPLETION-BLIND: per-bar mean and symbol count over
  ALL alpha_events symbols present at the bar (>= 20 required); the
  forward_returns join (executable_open_to_open, complete_mid) gates measurement
  rows only, never the demeaning cross-section
- PASS (all four): (1) family ci_lower > 0; (2) null p < 0.05; (3) point
  estimate >= 0.0027 (0b most-favorable IC_min at 15m mid); (4) >= 10% of family
  symbols clear per-symbol date-shift nulls at BY-FDR alpha=0.05, positive
- RAW arm, pooled global-rank Spearman / pooled Pearson (277 comparability),
  per-regime table, temporal thirds, BH alongside BY: reported, never gated
- window: full persisted 15m IS panel (bar_ts < 2025-12-24) -- an IN-SAMPLE
  diagnostic of signal existence; the gate look stays the sole OOS arbiter

Read-only: no writes, no config changes, exit code always 0.

Post-run revision (2026-09-03, after the AGY script review archived at
.planning/research/2026-09-03-agy-review-prereg2-script.md): (a) sync_shift_null_p
gained score_override -- in the recorded run the RAW arm's null p tested the raw
observed statistic against RESIDUAL-shift nulls (mis-specified; raw arm is
reported-only and never gated, verdict unaffected); (b) random index generation
moved ahead of the thread pools (serial-then-compute, the production ic_math
convention) -- the recorded run drew rng.integers concurrently across threads, so
its resample-based numbers are valid draws but not bit-reproducible; (c) NaN
observed -> null_p=1.0 guards. The recorded run's numbers (program doc,
"Pre-registration 2 run") came from the pre-revision script; every gated verdict
condition is robust to all three (see the program doc's post-run review note).
"""

from __future__ import annotations

import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import numpy as np  # noqa: E402
import structlog  # noqa: E402
from scipy.stats import rankdata  # noqa: E402
from statsmodels.stats.multitest import multipletests  # noqa: E402

from services._batch_utils import cfg as _cfg  # noqa: E402
from services._batch_utils import load_config_service_sync  # noqa: E402
from services.backfill_feature_factory import _connect_db  # noqa: E402
from src.config.settings import Settings  # noqa: E402
from src.core.rng import hash_key_to_int  # noqa: E402
from src.core.service_utils import setup_service_logging  # noqa: E402
from src.intelligence.statistics.ic_math import (  # noqa: E402
    _circular_block_bootstrap_ic,
    apply_bh_fdr,
)

setup_service_logging("logs/alpha_score_residual_single_security_15m.log")
_logger = structlog.get_logger(__name__)

_NAME = "alpha_score_residual_single_security_15m"
_TF = "15m"
_MIN_SYMBOLS_PER_BAR = 20
_MIN_BARS_PER_SYMBOL = 100
_DATE_BLOCK = 5
_N_NULL = 1000
_N_SHIFT = 1000
_FLOOR = 0.0027  # 0b most-favorable IC_min at 15m mid (Amendment 1 item 4)
_QUALIFYING_FLOOR = 0.10  # of family symbols, BY-FDR positive
_MAX_WORKERS = 8

_FETCH_SQL = f"""
WITH ev AS (
  SELECT ae.bar_ts, ae.symbol, ae.regime, ae.alpha_score,
         count(*) OVER (PARTITION BY ae.bar_ts) AS n_sym,
         avg(ae.alpha_score) OVER (PARTITION BY ae.bar_ts) AS bar_mean
  FROM alpha_events ae
  WHERE ae.tf = %s AND ae.bar_ts < '2025-12-24'
)
SELECT ev.symbol, ev.bar_ts, ev.regime, ev.alpha_score,
       ev.alpha_score - ev.bar_mean AS residual, fr.return_mid
FROM ev
JOIN forward_returns fr
  ON fr.symbol = ev.symbol AND fr.tf = %s AND fr.bar_ts = ev.bar_ts
 AND fr.return_type = 'executable_open_to_open' AND fr.complete_mid = true
WHERE ev.n_sym >= {_MIN_SYMBOLS_PER_BAR}
ORDER BY ev.symbol, ev.bar_ts
"""


def _spearman(x: np.ndarray, y: np.ndarray) -> float:
    if len(x) < 4 or np.std(x) < 1e-12 or np.std(y) < 1e-12:
        return float("nan")
    return float(np.corrcoef(rankdata(x), rankdata(y))[0, 1])


def _concat_ranges(src_starts: np.ndarray, counts: np.ndarray) -> np.ndarray:
    """Row indices for the concatenation of ranges [s_j, s_j + c_j). Vectorized."""
    tot = int(counts.sum())
    if tot == 0:
        return np.empty(0, dtype=np.int64)
    offsets = np.cumsum(counts) - counts
    return np.repeat(src_starts, counts) + np.arange(tot) - np.repeat(offsets, counts)


class Panel:
    """Per-symbol date-block index structures over a row subset of the big arrays."""

    def __init__(
        self,
        symbol_ids: np.ndarray,
        dates: np.ndarray,  # int32 YYYYMMDD per row
        scores: np.ndarray,  # signal under test (residual or raw)
        returns: np.ndarray,
    ) -> None:
        self.scores = scores
        self.returns = returns
        self.calendar = np.unique(dates)
        n_cal = len(self.calendar)
        n_sym = int(symbol_ids.max()) + 1
        self.cal_start = np.zeros((n_sym, n_cal), dtype=np.int64)
        self.cal_len = np.zeros((n_sym, n_cal), dtype=np.int64)
        # per-symbol block (own-date) structures for the synchronous shift null
        self.sym_blocks: dict[int, tuple[np.ndarray, np.ndarray, slice]] = {}
        for s in np.unique(symbol_ids):
            rows = np.flatnonzero(symbol_ids == s)
            d_sym = dates[rows]
            uniq = np.unique(d_sym)
            first = np.searchsorted(d_sym, uniq)
            counts = np.diff(np.append(first, len(d_sym)))
            pos = np.searchsorted(self.calendar, uniq)
            self.cal_start[s, pos] = rows[first]
            self.cal_len[s, pos] = counts
            self.sym_blocks[int(s)] = (rows[first], counts, slice(rows[0], rows[-1] + 1))
        self.family = sorted(
            s
            for s, (_st, c, _sl) in self.sym_blocks.items()
            if int(c.sum()) >= _MIN_BARS_PER_SYMBOL
        )

    def _symbol_rows_for_dates(self, s: int, cal_idx: np.ndarray) -> np.ndarray:
        starts = self.cal_start[s, cal_idx]
        counts = self.cal_len[s, cal_idx]
        return _concat_ranges(starts, counts)

    def family_stat(self, score_override: np.ndarray | None = None) -> float:
        sc = self.scores if score_override is None else score_override
        vals = []
        for s in self.family:
            sl = self.sym_blocks[s][2]
            vals.append(_spearman(sc[sl], self.returns[sl]))
        vals = [v for v in vals if not np.isnan(v)]
        return float(np.mean(vals)) if vals else float("nan")

    def bootstrap_ci(
        self, rng: np.random.Generator, n_boot: int, score_override: np.ndarray | None = None
    ) -> tuple[float, float]:
        sc = self.scores if score_override is None else score_override
        n_cal = len(self.calendar)
        offsets = np.arange(_DATE_BLOCK)
        n_blocks = int(np.ceil(n_cal / _DATE_BLOCK))
        family_arr = np.array(self.family)
        # serial index generation, then threaded compute (production ic_math
        # convention): numpy Generators are not thread-safe
        block_starts = rng.integers(0, n_cal, size=(n_boot, n_blocks))

        def _one_rep(b: int) -> float:
            cal_idx = (block_starts[b][:, None] + offsets).ravel()[:n_cal] % n_cal
            vals = []
            for s in family_arr:
                rows = self._symbol_rows_for_dates(int(s), cal_idx)  # absolute indices
                if len(rows) < 4:
                    continue
                vals.append(_spearman(sc[rows], self.returns[rows]))
            vals = [v for v in vals if not np.isnan(v)]
            return float(np.mean(vals)) if vals else float("nan")

        with ThreadPoolExecutor(max_workers=_MAX_WORKERS) as pool:
            reps = list(pool.map(_one_rep, range(n_boot)))
        reps_arr = np.array([r for r in reps if not np.isnan(r)])
        return float(np.percentile(reps_arr, 2.5)), float(np.percentile(reps_arr, 97.5))

    def sync_shift_null_p(
        self,
        observed: float,
        rng: np.random.Generator,
        n_null: int,
        score_override: np.ndarray | None = None,
    ) -> float:
        if np.isnan(observed):
            return 1.0
        sc = self.scores if score_override is None else score_override
        n_cal = len(self.calendar)
        ks = rng.integers(1, n_cal, size=n_null)  # serial, then threaded compute

        def _one_rep(i: int) -> float:
            k = int(ks[i])
            vals = []
            for s in self.family:
                starts, counts, sl = self.sym_blocks[s]
                m = len(starts)
                perm = (np.arange(m) + k % m) % m
                # genuine block permutation: output block j = source block perm[j],
                # sourced blocks' OWN counts -> total length preserved, positions
                # pair each residual with a return from a different date
                idx = _concat_ranges(starts[perm], counts[perm])  # absolute indices
                vals.append(_spearman(sc[idx], self.returns[sl]))
            vals = [v for v in vals if not np.isnan(v)]
            return float(np.mean(vals)) if vals else float("nan")

        with ThreadPoolExecutor(max_workers=_MAX_WORKERS) as pool:
            reps = list(pool.map(_one_rep, range(n_null)))
        beat = sum(1 for r in reps if not np.isnan(r) and r >= observed)
        return (1 + beat) / (n_null + 1)


def _per_symbol_table(panel: Panel) -> list[dict]:
    """Per-symbol IC, block-bootstrap CI, and date-shift null p (independent ks)."""

    def _one_symbol(s: int) -> dict:
        starts, counts, sl = panel.sym_blocks[s]
        x = panel.scores[sl].reshape(-1, 1)
        y = panel.returns[sl]
        ic = _spearman(panel.scores[sl], y)
        if np.isnan(ic):
            return {  # degenerate series: uninformative, never significant
                "symbol": int(s),
                "n": int(counts.sum()),
                "ic": ic,
                "ci_lower": float("nan"),
                "ci_upper": float("nan"),
                "null_p": 1.0,
            }
        rng_ci = np.random.default_rng(hash_key_to_int(f"{_NAME}_ci_{s}"))
        ci_lo, ci_hi = _circular_block_bootstrap_ic(x, y, 26, 2000, rng_ci)
        rng_n = np.random.default_rng(hash_key_to_int(f"{_NAME}_null_{s}"))
        m = len(starts)
        if m < 2:
            null_p = 1.0
        else:
            beat = 0
            for _ in range(_N_SHIFT):
                perm = (np.arange(m) + int(rng_n.integers(1, m))) % m
                idx = _concat_ranges(starts[perm], counts[perm])  # absolute indices
                null_ic = _spearman(panel.scores[idx], y)
                if not np.isnan(null_ic) and null_ic >= ic:
                    beat += 1
            null_p = (1 + beat) / (_N_SHIFT + 1)
        out = {
            "symbol": int(s),
            "n": int(counts.sum()),
            "ic": ic,
            "ci_lower": float(ci_lo[0]),
            "ci_upper": float(ci_hi[0]),
            "null_p": null_p,
        }
        return out

    with ThreadPoolExecutor(max_workers=_MAX_WORKERS) as pool:
        return list(pool.map(_one_symbol, panel.family))


def main() -> None:
    settings = Settings()
    conn = _connect_db(settings)
    apr = load_config_service_sync(conn)
    apr_dict = apr._cache
    n_boot = int(_cfg(apr_dict, "alpha.ic.bootstrap_resamples", 2000))
    fdr_alpha = float(_cfg(apr_dict, "alpha.ic.fdr_alpha", 0.05))
    block_size = int(_cfg(apr_dict, "alpha.ic.bootstrap_block_size.15m", 26))
    print(f"{_NAME} -- tf={_TF}, IS panel (bar_ts < 2025-12-24), IN-SAMPLE diagnostic")
    print(
        f"n_boot={n_boot} n_null={_N_NULL} n_shift={_N_SHIFT} date_block={_DATE_BLOCK} "
        f"per_symbol_block={block_size} floor={_FLOOR} qualifying_floor={_QUALIFYING_FLOOR:.0%}"
    )

    print("\nStreaming panel (completion-blind demeaning in SQL) ...")
    sym_code: dict[str, int] = {}
    reg_code: dict[str | None, int] = {None: 0}
    chunks = {k: [] for k in ("sym", "date", "resid", "raw", "ret", "reg")}
    n_fetched = 0
    with conn.transaction():  # server-side cursor requires a transaction block
        with conn.cursor(name="diag_fetch") as cur:
            cur.itersize = 200_000
            cur.execute(_FETCH_SQL, (_TF, _TF))
            while True:
                batch = cur.fetchmany(200_000)
                if not batch:
                    break
                n_fetched += len(batch)
                n = len(batch)
                sym = np.empty(n, dtype=np.int16)
                for i, (symbol, bar_ts, regime, raw, resid, ret) in enumerate(batch):
                    code = sym_code.setdefault(symbol, len(sym_code))
                    sym[i] = code
                    reg_code.setdefault(regime, len(reg_code))
                chunks["sym"].append(sym)
                chunks["date"].append(
                    np.array(
                        [r[1].year * 10000 + r[1].month * 100 + r[1].day for r in batch],
                        dtype=np.int32,
                    )
                )
                chunks["reg"].append(np.array([reg_code[r[2]] for r in batch], dtype=np.int8))
                chunks["raw"].append(np.array([r[3] for r in batch], dtype=np.float64))
                chunks["resid"].append(np.array([r[4] for r in batch], dtype=np.float64))
                chunks["ret"].append(np.array([r[5] for r in batch], dtype=np.float64))
    conn.close()
    print(f"  {n_fetched:,} measurement rows, {len(sym_code)} symbols")
    code_to_sym = {v: k for k, v in sym_code.items()}
    code_to_reg = {v: k for k, v in reg_code.items()}

    A = {k: np.concatenate(v) for k, v in chunks.items()}
    panel = Panel(A["sym"], A["date"], A["resid"], A["ret"])
    print(f"  family: {len(panel.family)} symbols with >= {_MIN_BARS_PER_SYMBOL} rows")
    print(f"  calendar: {len(panel.calendar)} trading dates")

    print("\n--- RESIDUAL (per-bar cross-sectionally demeaned; gated) ---")
    resid_stat = panel.family_stat()
    rng_boot = np.random.default_rng(hash_key_to_int(f"{_NAME}_boot"))
    resid_lo, resid_hi = panel.bootstrap_ci(rng_boot, n_boot)
    rng_null = np.random.default_rng(hash_key_to_int(f"{_NAME}_null"))
    resid_p = panel.sync_shift_null_p(resid_stat, rng_null, _N_NULL)
    print(
        f"family stat (mean per-symbol Spearman IC) = {resid_stat:.5f}\n"
        f"date-block bootstrap CI = [{resid_lo:.5f}, {resid_hi:.5f}]\n"
        f"panel-synchronous date-shift null p = {resid_p:.4f}"
    )

    print("\n--- RAW alpha_score (comparison arm; never gated) ---")
    raw_stat = panel.family_stat(score_override=A["raw"])
    rng_boot_raw = np.random.default_rng(hash_key_to_int(f"{_NAME}_boot_raw"))
    raw_lo, raw_hi = panel.bootstrap_ci(rng_boot_raw, n_boot, score_override=A["raw"])
    rng_null_raw = np.random.default_rng(hash_key_to_int(f"{_NAME}_null_raw"))
    raw_p = panel.sync_shift_null_p(raw_stat, rng_null_raw, _N_NULL, score_override=A["raw"])
    print(f"family stat = {raw_stat:.5f}  CI = [{raw_lo:.5f}, {raw_hi:.5f}]  null p = {raw_p:.4f}")

    pooled_spearman = _spearman(A["resid"], A["ret"])
    pooled_pearson = float(np.corrcoef(A["resid"], A["ret"])[0, 1])
    print(
        f"\n277-comparability sidecars (reported only): pooled global-rank Spearman "
        f"{pooled_spearman:.5f}, pooled Pearson {pooled_pearson:.5f}\n"
        f"(277 measured pooled Pearson +0.00453 on the OOS window; Amendment 1: the pooled "
        f"statistic is cross-sectionally dominated -- zero time-series content)"
    )

    print("\n--- Per-symbol family (RESIDUAL) ---")
    table = _per_symbol_table(panel)
    by_reject_by = multipletests([t["null_p"] for t in table], alpha=fdr_alpha, method="fdr_by")
    by_reject_bh = apply_bh_fdr([t["null_p"] for t in table], fdr_alpha)
    n_qual_by = sum(1 for t, r in zip(table, by_reject_by[0]) if r and t["ic"] > 0)
    n_qual_bh = sum(1 for t, r in zip(table, by_reject_bh[0]) if r and t["ic"] > 0)
    n_ci_pos = sum(1 for t in table if t["ci_lower"] > 0)
    n_neg_by = sum(1 for t, r in zip(table, by_reject_by[0]) if r and t["ic"] < 0)
    for t, rby, pc in zip(table, by_reject_by[0], by_reject_by[1]):
        if rby and t["ic"] > 0:
            print(
                f"  {code_to_sym[t['symbol']]}: n={t['n']} ic={t['ic']:.4f} "
                f"ci=[{t['ci_lower']:.4f}, {t['ci_upper']:.4f}] null_p={t['null_p']:.4f} "
                f"BY_p={pc:.4f} QUALIFIES"
            )
    frac = n_qual_by / len(table) if table else 0.0
    print(
        f"\nqualifying (BY-FDR alpha={fdr_alpha}, positive): {n_qual_by}/{len(table)} "
        f"({frac:.1%})  [floor {_QUALIFYING_FLOOR:.0%}]\n"
        f"qualifying (BH, positive): {n_qual_bh}/{len(table)}   "
        f"ci_lower>0 count (script-2 shape): {n_ci_pos}/{len(table)}\n"
        f"significantly NEGATIVE (BY): {n_neg_by}/{len(table)}"
    )

    print("\n--- Per-regime table (reported; BH-FDR across regimes) ---")
    regime_results = []
    reg_labels = sorted(c for c in np.unique(A["reg"]) if code_to_reg[c] is not None)
    for c in reg_labels:
        mask = A["reg"] == c
        sub = Panel(A["sym"][mask], A["date"][mask], A["resid"][mask], A["ret"][mask])
        stat = sub.family_stat()
        rng_r = np.random.default_rng(hash_key_to_int(f"{_NAME}_reg_{c}_boot"))
        lo, hi = sub.bootstrap_ci(rng_r, n_boot)
        rng_rn = np.random.default_rng(hash_key_to_int(f"{_NAME}_reg_{c}_null"))
        p = sub.sync_shift_null_p(stat, rng_rn, _N_NULL)
        print(
            f"  regime={code_to_reg[c]}: family={len(sub.family)} stat={stat:.5f} "
            f"CI=[{lo:.5f}, {hi:.5f}] null_p={p:.4f}"
        )
        regime_results.append((code_to_reg[c], p))
    if regime_results:
        rej, pcorr = apply_bh_fdr([p for (_l, p) in regime_results], fdr_alpha)
        for (label, _p), r, pc in zip(regime_results, rej, pcorr):
            print(f"  BH: regime={label}: null_p_corrected={pc:.4f} passes_fdr={bool(r)}")

    print("\n--- Temporal thirds (reported) ---")
    cal = panel.calendar
    for i in range(3):
        lo_d, hi_d = cal[i * len(cal) // 3], cal[(i + 1) * len(cal) // 3 - 1]
        mask = (A["date"] >= lo_d) & (A["date"] <= hi_d)
        sub = Panel(A["sym"][mask], A["date"][mask], A["resid"][mask], A["ret"][mask])
        stat = sub.family_stat()
        rng_t = np.random.default_rng(hash_key_to_int(f"{_NAME}_third_{i}"))
        lo, hi = sub.bootstrap_ci(rng_t, n_boot)
        print(
            f"  third {i + 1} [{lo_d}-{hi_d}]: family={len(sub.family)} stat={stat:.5f} CI=[{lo:.5f}, {hi:.5f}]"
        )

    c1 = resid_lo > 0
    c2 = resid_p < 0.05
    c3 = resid_stat >= _FLOOR
    c4 = frac >= _QUALIFYING_FLOOR
    verdict = "PASS" if all((c1, c2, c3, c4)) else "FAIL"
    print(
        f"\nVERDICT RULE (Amendment 1): (1) ci_lower>0: {c1} ({resid_lo:.5f}); "
        f"(2) null_p<0.05: {c2} ({resid_p:.4f}); (3) point>=floor: {c3} "
        f"({resid_stat:.5f} vs {_FLOOR}); (4) qualifying>={_QUALIFYING_FLOOR:.0%}: "
        f"{c4} ({frac:.1%})"
    )
    if c3 and resid_stat < 0.0164:  # 0b worst-case band at 15m mid, for the report line
        print("  note: point estimate is inside the 0b band (best 0.0027 ... worst 0.0164):")
        print("  statistically real but economically band-dependent; a successor pre-reg")
        print("  must measure actual turnover before any gate claim.")
    print(f"\nVERDICT: {verdict}")


if __name__ == "__main__":
    main()
