#!/usr/bin/env python3
"""Pre-registration 1 falsification run: `range_pct_fast` XS-LS @ H=5.

Design is LOCKED by docs/plans/2026-09-02-personal-scale-edge-determination-plan.md,
section "Pre-registration 1 - range_pct_fast XS-LS @ H=5" (commit 9507829b9 as amended
by its Amendment 1 after the AGY review, all BEFORE this script ran). This docstring
restates every implementation-level decision not fully spelled there, made from
schema/precedent alone, not from a peek at results:

1. Panel. feature_vectors (tf=1d, range_pct_fast NOT NULL) LEFT JOIN forward_returns
   (tf=1d, return_type='executable_open_to_open') on (symbol, bar_ts), restricted to
   bar_ts < alpha.validation.oos_start (APR, read live from config_state; fail-loud if
   absent). Eligibility never conditions on the future: no complete_mid filter; a row
   whose forward return is missing stays in the panel and settles at 0 in the leg means
   (693 rows, all at the 2025-12 tail, verified pre-run). forward_returns is unique on
   (symbol, tf, bar_ts) so the LEFT JOIN cannot fan out; asserted anyway.

2. Returns. Stored log returns convert to simple (e^r - 1) before any averaging or cost
   arithmetic. Per-rebalance gross LS = mean(long simple) - mean(short simple). The
   equal-weight universe mean (ewm) over ALL eligible simple returns that date is the
   market-factor proxy for neutralization.

3. Rebalance calendar. Eligible dates = distinct bar_ts in the panel. Anchor = first
   date whose eligible cross-section is >= _MIN_CROSS_SECTION (20). Stride exactly 5
   positions in the sorted eligible-date list (non-overlapping 5-trading-day holds).
   Undersized dates after the anchor are skipped, counted, and omitted from the sample
   (no zero-fill); the stride continues on the global calendar. Offsets 0-4 from the
   anchor are each evaluated; offset 0 is primary, 1-4 are ungated robustness.

4. Legs. On each rebalance date: k = m // 5 where m = eligible symbol count. Long = top
   k by range_pct_fast, short = bottom k. Ties broken by symbol name (ascending),
   deterministic. Weights +1/k long, -1/k short.

5. Neutralization. Per phase, OLS gross_t = a + b*ewm_t over that phase's full
   rebalance series: b via centered sums, R^2 reported. neutralized_t = gross_t - b*ewm_t
   (mean = the intercept a). PASS criteria (a)/(c) run on neutralized net; raw
   gross/unneutralized numbers are reported alongside.

6. Costs. Equity $100k flat (no compounding), $50k per leg. Per-rebalance commission
   frac = max(_COMMISSION_FRAC, _MIN_COMMISSION / per-name notional) with per-name
   notional = 50k / k; the $0.35 minimum binds at quintile breadth (~3.2 bp/side at
   k=46). Turnover = one-way membership churn: 0.5 * sum_names |w_t - w_{t-1}|; the
   entry rebalance pays 1.0; terminal liquidation is not charged. drag_t(spread,
   borrow) = 2 * turnover_t * (spread/2 + commission_frac_t) + borrow, borrow charged
   per rebalance on short-leg notional, band {0.25, 0.5, 1.0} bp. Spread band
   {0.7, 1.4, 2.8} bp. Anchor cost = 1.4 bp spread + 0.5 bp borrow.

7. Inference. Circular block bootstrap of the mean (wrap-around block index per
   ic_math._circular_block_bootstrap_ic's convention), block_size=2 rebalances, B=2000,
   percentile 95% CI, applied to neutralized net at each of the 9 (spread, borrow)
   combinations; one RNG seeded once, combos in fixed order. Shuffled null: within each
   rebalance date, permute range_pct_fast across that date's eligible symbols (N=1000
   replicates), recompute the gross mean; one-sided empirical
   p = (1 + #{null >= observed}) / (N + 1). Seeds via src.core.rng.hash_key_to_int on
   fixed strings, never builtin hash().

8. PASS rule (pre-registered; all three, else DEAD):
   (a) neutralized-net CI lower bound > 0 at ALL 9 cost combinations,
   (b) shuffled-null p < 0.05 on the gross mean,
   (c) neutralized-net mean > 0 in 3/3 subperiods (rebalance-index thirds) at anchor
       cost.

9. Reported, never gated: beta/R^2, unneutralized gross CI, per-subperiod means, the
   5-offset robustness table (per-offset self-contained construction), skipped-day and
   settled-return counts, and per-symbol Spearman IC over each symbol's full eligible
   daily panel (feature vs return_mid; rank IC is invariant to the log->simple change,
   settled rows dropped from the attribution panel), CI via
   ic_math._circular_block_bootstrap_ic with the APR daily block size (the production
   CI path for daily panels), BH-FDR at alpha=0.05 across the symbol family.

Read-only. No writes: the verdict is transcribed into the program doc and
concept_registry (domain='construction') by a separate post-run step.

IMPORTANT: the OOS holdout (bar_ts >= oos_start) is NOT touched by this script. No
statistic of any kind is computed on it. The one-shot gate look happens only if this
run PASSes, per the amended OOS rule (all 5 stride phases, net at anchor cost, IS beta).
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from scipy.stats import rankdata  # noqa: E402

from scripts.analysis.personal_cost_hurdle import _COMMISSION_FRAC  # noqa: E402
from services.backfill_feature_factory import _connect_db  # noqa: E402
from src.config.settings import Settings  # noqa: E402
from src.core.rng import hash_key_to_int  # noqa: E402
from src.intelligence.statistics.ic_math import (  # noqa: E402
    _circular_block_bootstrap_ic,
    _p_values_from_ic,
    apply_bh_fdr,
)

# --- fixed quantities (pre-registration section "Fixed quantities", Amendment 1) ---
_MIN_CROSS_SECTION = 20
_QUINTILE = 5
_STRIDE = 5  # trading days
_N_OFFSETS = 5  # stride offsets evaluated; offset 0 is primary
_BLOCK_REBALANCES = 2  # bootstrap block, in rebalances (2 * 5 = 10 trading days)
_N_BOOT = 2000
_N_NULL = 1000
_ALPHA = 0.05
_N_SUBPERIODS = 3
_LIVE_SPREAD_ANCHOR = 0.0014  # 0b's measured median live spread, 1.4 bps
_SPREAD_MULTIPLIERS = (0.5, 1.0, 2.0)  # band {0.7, 1.4, 2.8} bp around the anchor
_BORROW_BAND = (0.25e-4, 0.5e-4, 1.0e-4)  # per rebalance, on short-leg notional
_ANCHOR_BORROW = 0.5e-4
_EQUITY = 100_000.0  # flat, no compounding
_LEG_NOTIONAL = _EQUITY / 2.0
_MIN_COMMISSION = 0.35  # IBKR order minimum, USD
_CONSTRUCTION = "range_pct_fast_xs_ls_h5"

_APR_KEYS = (
    "alpha.validation.oos_start",
    "alpha.ic.bootstrap_block_size.1d",  # per-symbol attribution CIs only (daily panel)
)


@dataclass
class Phase:
    """One stride offset's construction over the IS panel (docstring items 3-5)."""

    offset: int
    dates: list[pd.Timestamp]
    gross: np.ndarray
    ewm: np.ndarray
    neutralized: np.ndarray
    beta: float
    r2: float
    turnover: np.ndarray
    m: np.ndarray  # eligible cross-section size per rebalance
    k: np.ndarray  # leg size per rebalance, m // _QUINTILE
    n_skipped: int


def _load_apr(cur) -> dict[str, str]:
    cur.execute(
        "SELECT config_key, config_value FROM config_state WHERE config_key = ANY(%s)",
        (list(_APR_KEYS),),
    )
    rows = dict(cur.fetchall())
    missing = [k for k in _APR_KEYS if k not in rows or not rows[k]]
    if missing:
        raise RuntimeError(f"APR keys missing/empty, refusing to run: {missing}")
    return rows


def _block_bootstrap_mean(
    series: np.ndarray, block_size: int, n_boot: int, rng: np.random.Generator
) -> tuple[float, float, float]:
    """Circular block bootstrap of a mean. Same wrap-around block construction as
    ic_math._circular_block_bootstrap_ic (blocks may wrap past the end, `% n`),
    applied to a 1-D return series instead of paired (X, Y) ranks."""
    n = len(series)
    n_blocks = int(np.ceil(n / block_size))
    offsets = np.arange(block_size)
    means = np.empty(n_boot)
    for b in range(n_boot):
        starts = rng.integers(0, n, n_blocks)
        idx = (starts[:, None] + offsets).ravel()[:n] % n
        means[b] = series[idx].mean()
    lo, hi = np.percentile(means, [2.5, 97.5])
    return float(series.mean()), float(lo), float(hi)


def _turnover_series(symbols_per_date: list[np.ndarray]) -> np.ndarray:
    """One-way turnover per rebalance transition (docstring item 6):
    0.5 * sum_names |w_{t+1} - w_t|; the first rebalance pays full entry (1.0)."""
    legs: list[dict[str, float]] = []
    for syms in symbols_per_date:
        k = len(syms) // _QUINTILE  # leg size; syms holds the full eligible cross-section
        w: dict[str, float] = {}
        for s in syms[-k:]:  # long leg = tail (top k by feature)
            w[s] = 1.0 / k
        for s in syms[:k]:  # short leg = head (bottom k)
            w[s] = w.get(s, 0.0) - 1.0 / k
        legs.append(w)

    out = np.empty(len(legs))
    for t in range(len(legs)):
        if t == 0:
            out[t] = 1.0  # entry from cash
            continue
        prev, cur = legs[t - 1], legs[t]
        names = set(prev) | set(cur)
        out[t] = 0.5 * sum(abs(cur.get(s, 0.0) - prev.get(s, 0.0)) for s in names)
    return out


def _build_phase(panel: pd.DataFrame, offset: int) -> Phase:
    """Walk the eligible-date calendar at _STRIDE from anchor+offset (docstring items
    3-5); returns the gross/ewm/neutralized series with cost inputs."""
    # DatetimeIndex (not np.sort on .unique()) so keys stay tz-aware Timestamps,
    # matching the groupby keys used for by_date lookups.
    dates = pd.DatetimeIndex(panel["bar_ts"].unique()).sort_values()
    by_date = {ts: g for ts, g in panel.groupby("bar_ts", sort=False)}

    counts = panel.groupby("bar_ts")["symbol"].nunique()
    anchor = counts[counts >= _MIN_CROSS_SECTION].index.min()
    if pd.isna(anchor):
        raise RuntimeError("no rebalance date meets the min cross-section floor")

    phase_dates: list[pd.Timestamp] = []
    gross_list: list[float] = []
    ewm_list: list[float] = []
    symbols_per_date: list[np.ndarray] = []
    n_skipped = 0

    start_pos = int(np.searchsorted(dates, anchor)) + offset
    for pos in range(start_pos, len(dates), _STRIDE):
        g = by_date[dates[pos]]
        if len(g) < _MIN_CROSS_SECTION:
            n_skipped += 1
            continue
        # Deterministic tie-break: sort by (feature, symbol), take bottom/top k.
        g = g.sort_values(["range_pct_fast", "symbol"], kind="mergesort")
        k = len(g) // _QUINTILE
        if k < 1:
            n_skipped += 1
            continue
        rets = g["ret"].to_numpy()
        gross_list.append(rets[-k:].mean() - rets[:k].mean())
        ewm_list.append(rets.mean())
        symbols_per_date.append(g["symbol"].to_numpy())
        phase_dates.append(dates[pos])

    gross = np.array(gross_list)
    ewm = np.array(ewm_list)
    x = ewm - ewm.mean()
    y = gross - gross.mean()
    ss_x = float((x * x).sum())
    beta = float((x * y).sum() / ss_x) if ss_x > 0 else 0.0
    ss_tot = float((y * y).sum())
    r2 = 1.0 - float(((y - beta * x) ** 2).sum()) / ss_tot if ss_tot > 0 else float("nan")
    m = np.array([len(s) for s in symbols_per_date], dtype=int)

    return Phase(
        offset=offset,
        dates=phase_dates,
        gross=gross,
        ewm=ewm,
        neutralized=gross - beta * ewm,
        beta=beta,
        r2=r2,
        turnover=_turnover_series(symbols_per_date),
        m=m,
        k=m // _QUINTILE,
        n_skipped=n_skipped,
    )


def _commission_frac(k: np.ndarray) -> np.ndarray:
    """Per-side commission fraction: the larger of the per-share tier and the $0.35
    order minimum against per-name notional (docstring item 6)."""
    per_name = _LEG_NOTIONAL / k
    return np.maximum(_COMMISSION_FRAC, _MIN_COMMISSION / per_name)


def _drag(phase: Phase, spread: float, borrow: float) -> np.ndarray:
    return 2.0 * phase.turnover * (spread / 2.0 + _commission_frac(phase.k)) + borrow


def _shuffled_null(
    prepared: list[tuple[np.ndarray, np.ndarray, int]], rng: np.random.Generator
) -> np.ndarray:
    """Within-date permutation null on the gross mean (docstring item 7)."""
    null_means = np.empty(_N_NULL)
    for b in range(_N_NULL):
        total = 0.0
        for feat, rets, k in prepared:
            r = rets[np.argsort(rng.permutation(feat), kind="mergesort")]
            total += r[-k:].mean() - r[:k].mean()
        null_means[b] = total / len(prepared)
    return null_means


def main() -> None:
    settings = Settings()
    conn = _connect_db(settings)

    with conn.cursor() as cur:
        apr = _load_apr(cur)
        oos_start = pd.Timestamp(apr["alpha.validation.oos_start"])
        daily_block = int(apr["alpha.ic.bootstrap_block_size.1d"])
        cur.execute(
            """
            SELECT fv.bar_ts, fv.symbol, fv.range_pct_fast, fr.return_mid
            FROM feature_vectors fv
            LEFT JOIN forward_returns fr
              ON fr.symbol = fv.symbol AND fr.bar_ts = fv.bar_ts AND fr.tf = fv.tf
             AND fr.return_type = 'executable_open_to_open'
            WHERE fv.tf = '1d'
              AND fv.range_pct_fast IS NOT NULL
              AND fv.bar_ts < %s
            """,
            (oos_start,),
        )
        panel = pd.DataFrame(
            cur.fetchall(), columns=["bar_ts", "symbol", "range_pct_fast", "return_mid"]
        )
    conn.close()

    if panel.duplicated(["bar_ts", "symbol"]).any():
        raise RuntimeError("panel fan-out: (bar_ts, symbol) not unique after LEFT JOIN")
    n_settled = int(panel["return_mid"].isna().sum())
    panel["ret"] = np.expm1(panel["return_mid"].fillna(0.0).to_numpy())

    print(f"panel rows: {len(panel):,}  symbols: {panel['symbol'].nunique()}")
    print(f"settled-at-zero returns: {n_settled:,}")
    print(
        f"IS window: {panel['bar_ts'].min()} .. {panel['bar_ts'].max()}  "
        f"(oos_start={oos_start})"
    )

    phases = [_build_phase(panel, off) for off in range(_N_OFFSETS)]
    primary = phases[0]
    boot_rng = np.random.default_rng(hash_key_to_int(f"{_CONSTRUCTION}_is_boot"))

    print(
        f"\nprimary phase (offset 0): rebalances {len(primary.dates)}  "
        f"skipped undersized: {primary.n_skipped}"
    )
    print(f"cross-section: min {primary.m.min()}  median {int(np.median(primary.m))}")
    print(
        f"one-way turnover: mean {primary.turnover.mean():.3f}  "
        f"median {np.median(primary.turnover):.3f}"
    )
    comm_bp = _commission_frac(primary.k) * 1e4
    print(
        f"commission: min {comm_bp.min():.2f}  median {np.median(comm_bp):.2f}  "
        f"max {comm_bp.max():.2f} bp/side"
    )
    print(
        f"neutralization: beta {primary.beta:+.4f}  R2 {primary.r2:.3f}  "
        f"gross mean {primary.gross.mean():+.6f}  "
        f"intercept {primary.neutralized.mean():+.6f}"
    )

    m, lo, hi = _block_bootstrap_mean(primary.gross, _BLOCK_REBALANCES, _N_BOOT, boot_rng)
    print(f"gross (unneutralized)  mean {m:+.6f}  CI [{lo:+.6f}, {hi:+.6f}]")

    # --- primary: neutralized net at each of the 9 cost combinations ---
    spread_levels = tuple(_LIVE_SPREAD_ANCHOR * mult for mult in _SPREAD_MULTIPLIERS)
    print("\nneutralized net, block bootstrap CIs (block=2, B=2000):")
    pass_a = True
    for spread in spread_levels:
        for borrow in _BORROW_BAND:
            net = primary.neutralized - _drag(primary, spread, borrow)
            m, lo, hi = _block_bootstrap_mean(net, _BLOCK_REBALANCES, _N_BOOT, boot_rng)
            cleared = lo > 0.0
            pass_a = pass_a and cleared
            print(
                f"  spread {spread * 1e4:.1f}bp borrow {borrow * 1e4:.2f}bp: "
                f"mean {m:+.6f}  CI [{lo:+.6f}, {hi:+.6f}]  "
                f"lower>0: {'YES' if cleared else 'NO'}"
            )

    # --- shuffled null on gross ---
    by_date = {ts: g for ts, g in panel.groupby("bar_ts", sort=False)}
    prepared = [
        (
            by_date[ts]["range_pct_fast"].to_numpy(),
            by_date[ts]["ret"].to_numpy(),
            len(by_date[ts]) // _QUINTILE,
        )
        for ts in primary.dates
    ]
    null_rng = np.random.default_rng(hash_key_to_int(f"{_CONSTRUCTION}_is_null"))
    null_means = _shuffled_null(prepared, null_rng)
    p_null = (1 + int((null_means >= primary.gross.mean()).sum())) / (_N_NULL + 1)
    pass_b = p_null < _ALPHA
    print(
        f"\nshuffled null: p = {p_null:.4f}  "
        f"(null mean {null_means.mean():+.6f}, sd {null_means.std():.6f})  "
        f"p<{_ALPHA}: {'YES' if pass_b else 'NO'}"
    )

    # --- subperiod stability at anchor cost ---
    anchor_net = primary.neutralized - _drag(primary, _LIVE_SPREAD_ANCHOR, _ANCHOR_BORROW)
    splits = np.array_split(np.arange(len(anchor_net)), _N_SUBPERIODS)
    sub_means = [anchor_net[ix].mean() for ix in splits]
    pass_c = all(s > 0.0 for s in sub_means)
    for i, (ix, s) in enumerate(zip(splits, sub_means), 1):
        print(
            f"subperiod {i}: {primary.dates[ix[0]].date()} .. "
            f"{primary.dates[ix[-1]].date()}  net(anchor) mean {s:+.6f}"
        )
    print(f"stability (3/3 positive net at anchor): {'YES' if pass_c else 'NO'}")

    # --- stride-offset robustness (reported, never gated) ---
    print("\nstride-offset robustness (ungated; per-offset self-contained OLS, " "net at anchor):")
    for ph in phases:
        net = ph.neutralized - _drag(ph, _LIVE_SPREAD_ANCHOR, _ANCHOR_BORROW)
        m, lo, hi = _block_bootstrap_mean(net, _BLOCK_REBALANCES, _N_BOOT, boot_rng)
        print(
            f"  offset {ph.offset}: n {len(ph.dates)}  gross {ph.gross.mean():+.6f}  "
            f"beta {ph.beta:+.4f}  net mean {m:+.6f}  CI [{lo:+.6f}, {hi:+.6f}]"
        )

    # --- per-symbol attribution (reported, never gated) ---
    print("\nper-symbol attribution (BH-FDR across symbols, reported only):")
    ic_rows = []
    for symbol, g in panel.groupby("symbol"):
        g = g.dropna(subset=["return_mid"])  # settled rows carry no observed return
        if len(g) < 100:  # too few pairs for a meaningful per-symbol IC
            continue
        x = g["range_pct_fast"].to_numpy().reshape(-1, 1)
        y = g["return_mid"].to_numpy()
        point_ic = float(np.corrcoef(rankdata(x).ravel(), rankdata(y))[0, 1])
        ci_lo, _ = _circular_block_bootstrap_ic(
            x,
            y,
            daily_block,
            _N_BOOT,
            rng=np.random.default_rng(hash_key_to_int(f"{_CONSTRUCTION}_attrib_{symbol}")),
            max_workers=1,
        )
        p_val = float(_p_values_from_ic(np.array([point_ic]), n=len(x))[0])
        ic_rows.append((symbol, point_ic, float(ci_lo[0]), p_val, len(g)))
    attrib = pd.DataFrame(ic_rows, columns=["symbol", "ic", "ci_lo", "p", "n"]).sort_values(
        "ic", ascending=False
    )
    reject, _ = apply_bh_fdr(list(attrib["p"]), _ALPHA)
    attrib["passes_fdr"] = reject
    print(f"  symbols with CI lower bound > 0: {(attrib['ci_lo'] > 0).sum()}/{len(attrib)}")
    print(f"  symbols passing BH-FDR: {int(reject.sum())}/{len(attrib)}")
    print(attrib.head(5).to_string(index=False))
    print(attrib.tail(5).to_string(index=False))

    # --- verdict ---
    verdict = "PASS" if (pass_a and pass_b and pass_c) else "DEAD"
    print(f"\n{'=' * 60}")
    print(
        f"VERDICT: {verdict}  "
        f"(a neutralized-net CI>0 all 9 combos: {'Y' if pass_a else 'N'}, "
        f"b null p<0.05: {'Y' if pass_b else 'N'}, "
        f"c stability 3/3: {'Y' if pass_c else 'N'})"
    )


if __name__ == "__main__":
    main()
