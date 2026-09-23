#!/usr/bin/env python3
"""Re-verify RESEARCH.md Assumption A1 (Phase 176 Plan 01, Task 1) -- the claim that
`up_vol_body_diff`'s Spearman IC roughly doubles in earnings season (+0.0197 in-season
vs +0.0103 off-season) -- against the live corpus, on the CORRECTED 14-42-day window
(D-04). A prior research session attempted this and was blocked by an active
`decompress_chunk()` on `feature_vectors`; this script re-attempts the measurement with
a mandatory contention pre-check so it never compounds an in-progress corpus job.

Task 2 extends this module with a `--sweep` mode: the same in-season vs off-season
Spearman IC comparison applied across the entire 57-feature vol/volume family, with
BH-FDR correction applied exactly once across that fixed family via
`apply_bh_fdr(p_values, alpha)` (`src.intelligence.statistics.ic_math`, this project's
own primitive -- see `services/tag_calibrator.py`'s documented one-call-per-family
convention), so the result carries a stated multiple-comparisons denominator rather
than an implied one.

Corrected earnings-season window (D-04, supersedes the origin todo's 0-42 day window):
in-season iff START_DAYS <= days_since_quarter_end <= END_DAYS, with START_DAYS=14,
END_DAYS=42 by default; quarter ends are Mar 31 / Jun 30 / Sep 30 / Dec 31.

SQL identifier safety is two independent mechanisms, both mandatory: (1) an allow-list
membership check via `_validated_identifier` -- rejection is by allow-list membership,
never by character filtering; (2) parameterized composition via `psycopg.sql.Identifier`
inside `psycopg.sql.SQL(...).format(...)`. Every SQL template in this module is a plain
string literal, never an f-string -- the `{feat}`-style placeholders are consumed by
`sql.SQL.format`, not by Python string interpolation. Non-identifier values (`--tf`, the
window bounds) are passed as `%s`/named query parameters, never interpolated.
"""

from __future__ import annotations

import argparse
import dataclasses
import os
import sys
from collections.abc import Collection, Sequence
from datetime import date, datetime
from pathlib import Path
from typing import Any

_project_root = Path(__file__).resolve().parent.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

import numpy as np  # noqa: E402
import psycopg  # noqa: E402
from psycopg import sql  # noqa: E402
from psycopg.rows import dict_row  # noqa: E402
from scipy.stats import spearmanr  # noqa: E402

from src.intelligence.feature_factory import FeatureVector  # noqa: E402
from src.intelligence.statistics.ic_math import (  # noqa: E402
    apply_bh_fdr,
    fisher_z_difference_p,
)

# ---------------------------------------------------------------------------
# Pure window classifier -- the definition every later plan's production
# `_days_since_quarter_end`/`_earnings_season_flag` must match.
# ---------------------------------------------------------------------------

_QUARTER_END_MONTH_DAYS: tuple[tuple[int, int], ...] = ((3, 31), (6, 30), (9, 30), (12, 31))


def days_since_quarter_end(d: date) -> int:
    """Calendar days since the most recent quarter end (Mar 31/Jun 30/Sep 30/Dec 31),
    always >= 0. The quarter-end day itself returns 0. Pure function of `d` alone --
    no market-holiday table (matches this codebase's other calendar primitives).
    """
    quarter_ends = [
        date(y, m, day) for y in (d.year - 1, d.year) for m, day in _QUARTER_END_MONTH_DAYS
    ]
    last_qe = max(qe for qe in quarter_ends if qe <= d)
    return (d - last_qe).days


def is_earnings_season(d: date, start_days: int, end_days: int) -> bool:
    """True iff `d` falls START_DAYS-END_DAYS calendar days (inclusive on BOTH
    boundaries) after the most recent quarter end.
    """
    n = days_since_quarter_end(d)
    return start_days <= n <= end_days


# ---------------------------------------------------------------------------
# SQL identifier safety -- allow-list membership + psycopg.sql.Identifier.
# Both allow-lists are built by construction, never by hand.
# ---------------------------------------------------------------------------

_FEATURE_ALLOWLIST: frozenset[str] = frozenset(f.name for f in dataclasses.fields(FeatureVector))

_RETURN_COLUMN_CHOICES: tuple[str, ...] = (
    "return_fast",
    "return_mid",
    "return_slow",
    "return_extended",
)


# The swept family (D-01a). Family size is the BH-FDR denominator, fixed in source
# before any measurement runs -- adding or removing a name after seeing results would
# be the exact p-hacking this sweep exists to prevent. Derived from PLAN.md's interfaces
# block: five comment-delimited FEATURE_VECTOR_DOMAIN sections (42 names) plus the core
# quant vol/volume/order-flow atomics from that dict's opening block (15 names) = 57.
# Live-verified: every name below is a real FeatureVector field (58-name dedup check in
# TestVolVolumeFamily), and `up_vol_body_diff` (the A1 feature) is inside its own family,
# not compared against it.
#
# Deliberately EXCLUDED and why: `garch_ratio`/`ctf_regime_align` (tier `regime`,
# fitted-state features, not raw vol/volume observables); `canary_noise_*` (tier
# `control`, exist to be null); every `*_atr`-suffixed STRUCTURAL feature (price-distance
# measures normalized BY atr, not volatility observables themselves).
_VOL_VOLUME_FAMILY: frozenset[str] = frozenset(
    {
        # "Renaissance Primitives -- Volume Structure" (Phase 142.5 Plan 02, 12)
        "vol_acceleration",
        "dollar_vol_z",
        "vol_range_ratio",
        "vol_trend_ratio",
        "up_vol_ratio_fast",
        "up_vol_ratio_slow",
        "vol_percentile",
        "vol_persistence",
        "vol_std_z",
        "mfi_fast",
        "mfi_slow",
        "obv_z",
        # "Renaissance Primitives -- Realized Variance / Volatility" (Plan 03, 14)
        "realized_var_ratio_fast",
        "realized_var_ratio_slow",
        "range_to_close",
        "true_range_pct",
        "vol_of_vol",
        "high_low_corr",
        "variance_ratio_fast",
        "variance_ratio_slow",
        "vol_asymmetry_z",
        "bb_pct_b_fast",
        "bb_pct_b_slow",
        "hv_z_fast",
        "hv_z_slow",
        "hv_ratio",
        # "Renaissance Primitives -- Alternative Volatility Estimators" (Plan 04, 3)
        "parkinson_vol_z",
        "garman_klass_vol_z",
        "yang_zhang_vol_z",
        # "Renaissance Primitives -- Volatility Dynamics" (Plan 04, 5)
        "parkinson_vol_velocity",
        "garman_klass_vol_velocity",
        "yang_zhang_vol_velocity",
        "vol_velocity_z",
        "intraday_noise_ratio",
        # "Renaissance Primitives -- Price-Volume Interactions" (Plan 05.5, 8)
        "vol_body_product",
        "ret_vol_product_fast",
        "price_vol_corr_fast",
        "price_vol_corr_slow",
        "range_vol_product",
        "up_vol_body_diff",
        "ret_vol_ratio_fast",
        "vol_skew_product",
        # Core quant vol/volume/order-flow atomics (opening block, 15)
        "volume_z",
        "rel_volume",
        "ofi_z",
        "ofi_div",
        "cvd_slope_z",
        "vwap_dev_sigma",
        "atr_z",
        "vol_ratio",
        "volume_z_velocity",
        "ofi_z_velocity",
        "cvd_slope_z_velocity",
        "vwap_dev_sigma_velocity",
        "amihud_illiq_z",
        "volume_rank_z",
        "volatility_rank_z",
    }
)

_FAMILY_ORDER: tuple[str, ...] = tuple(sorted(_VOL_VOLUME_FAMILY))

# Breadth criterion B2 threshold (D-01a): >= 55% of sufficient-N symbols must agree in
# sign with the pooled effect. Minimum per-partition N to count a symbol as
# "sufficient" for the B2 sign-agreement denominator -- this project's own
# `sample_size >= 30` promotion-gate convention (CLAUDE.md `setup_performance`),
# reused here rather than inventing a new threshold.
_B2_MIN_SUFFICIENT_N = 30
_B2_MIN_AGREEMENT_FRACTION = 0.55
_B3_MAX_RAW_P = 0.05


def _validated_identifier(name: str, allowed: Collection[str]) -> sql.Identifier:
    """Return `name` as a `psycopg.sql.Identifier` iff it is a member of `allowed`.

    Raises ValueError naming the rejected value otherwise. Rejection is by
    allow-list membership only, never by character filtering -- a string that
    happens to contain no special characters but isn't in `allowed` is rejected
    exactly the same as one that does.
    """
    if name not in allowed:
        raise ValueError(f"rejected identifier not in allow-list: {name!r}")
    return sql.Identifier(name)


# ---------------------------------------------------------------------------
# DB connection + contention guard (Pitfall 5: corpus DB contention is real).
# ---------------------------------------------------------------------------


def _connect() -> Any:
    """Open a psycopg connection. Password is read from PGPASSWORD only -- never
    an argparse flag, never a literal in a SQL string (CLAUDE.md DB-access
    convention: PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent).
    """
    return psycopg.connect(
        host=os.getenv("PGHOST", "localhost"),
        user=os.getenv("PGUSER", "postgres"),
        password=os.getenv("PGPASSWORD", "postgres"),
        dbname=os.getenv("PGDATABASE", "indicagent"),
    )


_CONTENTION_QUERY = """
    SELECT pid, state, wait_event, query_start, query
    FROM pg_stat_activity
    WHERE state = 'active'
      AND pid != pg_backend_pid()
      AND (
          query ILIKE '%decompress_chunk%'
          OR query ILIKE '%compress_chunk%'
          OR query ILIKE '%autovacuum%'
      )
      AND (
          query ILIKE '%feature_vectors%'
          OR query ILIKE '%_timescaledb_internal._hyper_%'
      )
"""


def _check_contention(conn: Any) -> list[dict[str, Any]]:
    """Query pg_stat_activity for active decompress_chunk/compress_chunk/autovacuum
    backends against feature_vectors or its internal hypertable chunks. No
    operator-supplied value reaches this query -- it is a plain literal.

    Excludes the caller's own backend pid (`pid != pg_backend_pid()`): this
    query's own literal text contains the substrings it searches for
    (`feature_vectors`, `autovacuum`), so without this exclusion it would
    self-match every single invocation while pg_stat_activity captures it
    mid-execution -- a false CONTENTION DETECTED on every run, found live
    during this plan's Task 3 execution.
    """
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(_CONTENTION_QUERY)
        return list(cur.fetchall())


def _print_contention_block(rows: Sequence[dict[str, Any]]) -> None:
    print("CONTENTION DETECTED")
    for row in rows:
        print(
            f"  pid={row['pid']} state={row['state']} "
            f"wait_event={row['wait_event']} query_start={row['query_start']}"
        )


# ---------------------------------------------------------------------------
# Partition-and-score -- shared by the single-feature path (Task 1) and the
# family sweep (Task 2). Returns (ic, n) per partition, never logs per row.
# ---------------------------------------------------------------------------


def _spearman_ic_n(x: np.ndarray, y: np.ndarray) -> tuple[float, int]:
    """Spearman IC and n for one (feature, partition) pair.

    NaN reported (not silently coerced to 0.0) for n<2 or a degenerate
    (zero-variance) input on either side -- an unmeasurable cell, not a
    genuine zero correlation.
    """
    finite = np.isfinite(x) & np.isfinite(y)
    x = x[finite]
    y = y[finite]
    n = len(x)
    if n < 2 or np.std(x) == 0 or np.std(y) == 0:
        return float("nan"), n
    ic, _ = spearmanr(x, y)
    return float(ic), n


def _partition_and_score(
    bar_dates: Sequence[date],
    feature_vals: np.ndarray,
    return_vals: np.ndarray,
    start_days: int,
    end_days: int,
) -> tuple[tuple[float, int], tuple[float, int]]:
    """Partition rows by is_earnings_season and compute (ic, n) per partition.

    Returns ((in_season_ic, in_season_n), (off_season_ic, off_season_n)).
    """
    mask = np.array([is_earnings_season(d, start_days, end_days) for d in bar_dates], dtype=bool)
    in_partition = _spearman_ic_n(feature_vals[mask], return_vals[mask])
    off_partition = _spearman_ic_n(feature_vals[~mask], return_vals[~mask])
    return in_partition, off_partition


# ---------------------------------------------------------------------------
# Single-feature A1 verdict decision -- pure, no DB.
# ---------------------------------------------------------------------------


def _a1_verdict(in_ic: float, in_n: int, off_ic: float, off_n: int) -> str:
    """CONFIRMED when in-season |IC| >= 1.7x off-season |IC| and both n >= 1000;
    WEAKER when the ratio is in (1.1x, 1.7x) (including >= 1.7x with insufficient
    n on either side -- a real directional effect exists but n is too small to
    confirm with confidence); REFUTED when the ratio is <= 1.1x or the IC sign
    flips between partitions. BLOCKED is decided only on the contention-guard
    exit path in main(), never here.
    """
    if (
        np.isfinite(in_ic)
        and np.isfinite(off_ic)
        and in_ic != 0
        and off_ic != 0
        and np.sign(in_ic) != np.sign(off_ic)
    ):
        return "REFUTED"
    if not np.isfinite(in_ic) or not np.isfinite(off_ic):
        return "REFUTED"
    if off_ic == 0:
        ratio = float("inf") if in_ic != 0 else 1.0
    else:
        ratio = abs(in_ic) / abs(off_ic)
    if ratio >= 1.7 and in_n >= 1000 and off_n >= 1000:
        return "CONFIRMED"
    if ratio > 1.1:
        return "WEAKER"
    return "REFUTED"


# ---------------------------------------------------------------------------
# Family sweep -- pure decision helpers (no DB). apply_bh_fdr(p_values, alpha) is
# this project's own primitive, called exactly once per run over the full 57-length
# p-vector (services/tag_calibrator.py's documented one-call-per-family convention).
# ---------------------------------------------------------------------------


def _pooled_fisher_z(ics: Sequence[float], ns: Sequence[int]) -> tuple[float, int]:
    """Sample-size-weighted Fisher-z pooled average of per-symbol Spearman ICs.

    Weight is (n-3), matching ic_math._fisher_z_ci's own asymptotic-variance
    convention. Symbols with n<=3 or a non-finite IC contribute no weight to the
    pooled z (undefined arctanh variance / unmeasurable cell) but their n still
    counts toward the returned total_n (fisher_z_difference_p's own n argument is
    a raw sample-size denominator, not a weighted-contributor count).

    Returns (pooled_ic, total_n); pooled_ic is NaN if no symbol contributed weight.
    """
    weighted_z_sum = 0.0
    weight_sum = 0.0
    total_n = 0
    for ic, n in zip(ics, ns, strict=True):
        total_n += n
        if n <= 3 or not np.isfinite(ic):
            continue
        z = np.arctanh(np.clip(ic, -1 + 1e-10, 1 - 1e-10))
        w = n - 3
        weighted_z_sum += z * w
        weight_sum += w
    if weight_sum == 0:
        return float("nan"), total_n
    return float(np.tanh(weighted_z_sum / weight_sum)), total_n


def _sweep_verdict(survivors: Sequence[str], any_fdr_significant: bool) -> str:
    """Family-sweep verdict from the broad, FDR-surviving `survivors` list.

    CONFIRMED when survivors is non-empty AND includes `up_vol_body_diff`; WEAKER
    when survivors is non-empty but excludes it (D-01a's carve-out -- a real
    conditional effect exists, just not the one the origin todo advertised, and
    this is still a PROCEED for plans 176-04/05/06); REFUTED when survivors is
    empty. BLOCKED is decided only on the contention-guard exit path, never here.

    `any_fdr_significant` is accepted for call-site/logging symmetry with the
    breadth-report step (an FDR-significant-but-narrow feature is a real, distinct
    outcome worth recording even though it never reaches `survivors`) -- it does
    not change this function's three-way decision, which depends only on
    `survivors` per D-01a's stated rule.
    """
    del any_fdr_significant
    if not survivors:
        return "REFUTED"
    if "up_vol_body_diff" in survivors:
        return "CONFIRMED"
    return "WEAKER"


def _is_broad(
    sign_agreement_fraction: float,
    jackknife_signs: Sequence[int],
    jackknife_ps: Sequence[float],
    pooled_sign: int,
) -> bool:
    """Breadth criteria B2 + B3 (D-01a) for one FDR-surviving feature.

    B2: sign_agreement_fraction (fraction of sufficient-N symbols whose per-symbol
    sign of (|in-season IC| - |off-season IC|) matches the pooled sign) must be
    >= _B2_MIN_AGREEMENT_FRACTION.

    B3: leave-one-symbol-out jackknife refits on the five highest-row-count
    symbols must each leave the pooled sign unchanged (jackknife_signs[i] ==
    pooled_sign) and the raw pooled p-value strictly below _B3_MAX_RAW_P.

    A feature clearing B1 (FDR significance, decided by the caller before this
    function is invoked) but failing B2 or B3 here is FDR-significant-but-narrow
    and must NOT enter SWEEP_SURVIVORS.
    """
    if sign_agreement_fraction < _B2_MIN_AGREEMENT_FRACTION:
        return False
    for sign, p_value in zip(jackknife_signs, jackknife_ps, strict=True):
        if sign != pooled_sign or p_value >= _B3_MAX_RAW_P:
            return False
    return True


# ---------------------------------------------------------------------------
# Family sweep -- corpus query + driver (Task 2).
# ---------------------------------------------------------------------------

_SWEEP_TEMPLATE = sql.SQL("""
    SELECT fv.bar_ts, {features}, fr.{ret} AS return_value
    FROM feature_vectors fv
    INNER JOIN forward_returns fr
        ON fr.symbol = fv.symbol
        AND fr.tf = fv.tf
        AND fr.bar_ts = fv.bar_ts
        AND fr.return_type = 'executable_open_to_open'
    WHERE fv.symbol = %(symbol)s
      AND fv.tf = %(tf)s
      AND fr.{ret} IS NOT NULL
    ORDER BY fv.bar_ts
    """)


@dataclasses.dataclass
class _SymbolFeaturePartition:
    """One symbol's in-season/off-season Spearman IC + n for one feature."""

    ic_in: float
    n_in: int
    ic_off: float
    n_off: int


def _fetch_symbols(conn: Any) -> list[str]:
    with conn.cursor() as cur:
        cur.execute("SELECT DISTINCT symbol FROM feature_vectors ORDER BY symbol")
        return [row[0] for row in cur.fetchall()]


def _fetch_symbol_sweep_rows(
    conn: Any, symbol: str, tf: str, return_id: sql.Identifier
) -> tuple[list[date], np.ndarray, np.ndarray]:
    """Fetch one symbol's bar dates / 57-feature matrix / return column for `tf`.

    Never a wide full-corpus fetch (CLAUDE.md): one query per symbol, accumulating
    scalar (symbol, feature) partition statistics only -- no per-symbol matrix is
    retained past this call's caller loop iteration.
    """
    feature_identifiers = [
        sql.SQL("fv.{}").format(_validated_identifier(name, allowed=_VOL_VOLUME_FAMILY))
        for name in _FAMILY_ORDER
    ]
    features_sql = sql.SQL(", ").join(feature_identifiers)
    query = _SWEEP_TEMPLATE.format(features=features_sql, ret=return_id)
    with conn.cursor() as cur:
        cur.execute(query, {"symbol": symbol, "tf": tf})
        rows = cur.fetchall()
    if not rows:
        return [], np.empty((0, len(_FAMILY_ORDER))), np.empty(0)
    bar_dates = [_as_date(r[0]) for r in rows]
    feature_matrix = np.array(
        [[np.nan if v is None else v for v in r[1 : 1 + len(_FAMILY_ORDER)]] for r in rows],
        dtype=np.float64,
    )
    return_vector = np.array([np.nan if r[-1] is None else r[-1] for r in rows], dtype=np.float64)
    return bar_dates, feature_matrix, return_vector


def _run_sweep(conn: Any, args: argparse.Namespace) -> None:
    return_id = _validated_identifier(args.return_column, allowed=set(_RETURN_COLUMN_CHOICES))

    symbols = _fetch_symbols(conn)
    per_symbol: dict[str, dict[str, _SymbolFeaturePartition]] = {}
    row_counts: dict[str, int] = {}

    for symbol in symbols:
        bar_dates, feature_matrix, return_vector = _fetch_symbol_sweep_rows(
            conn, symbol, args.tf, return_id
        )
        n_rows = len(return_vector)
        if n_rows == 0:
            continue
        row_counts[symbol] = n_rows
        mask = np.array(
            [is_earnings_season(d, args.start_days, args.end_days) for d in bar_dates],
            dtype=bool,
        )
        per_symbol[symbol] = {}
        for j, feat_name in enumerate(_FAMILY_ORDER):
            col = feature_matrix[:, j]
            ic_in, n_in = _spearman_ic_n(col[mask], return_vector[mask])
            ic_off, n_off = _spearman_ic_n(col[~mask], return_vector[~mask])
            per_symbol[symbol][feat_name] = _SymbolFeaturePartition(ic_in, n_in, ic_off, n_off)

    if not per_symbol:
        print("SWEEP_SURVIVORS=NONE")
        print("SWEEP_VERDICT=REFUTED (no rows returned for any symbol)")
        return

    top5_symbols = sorted(row_counts, key=lambda s: row_counts[s], reverse=True)[:5]

    p_values: list[float] = []
    pooled: dict[str, dict[str, float]] = {}
    for feat_name in _FAMILY_ORDER:
        ics_in = [per_symbol[s][feat_name].ic_in for s in per_symbol]
        ns_in = [per_symbol[s][feat_name].n_in for s in per_symbol]
        ics_off = [per_symbol[s][feat_name].ic_off for s in per_symbol]
        ns_off = [per_symbol[s][feat_name].n_off for s in per_symbol]
        pooled_in, total_n_in = _pooled_fisher_z(ics_in, ns_in)
        pooled_off, total_n_off = _pooled_fisher_z(ics_off, ns_off)
        p_value = fisher_z_difference_p(pooled_in, total_n_in, pooled_off, total_n_off)
        p_values.append(p_value if np.isfinite(p_value) else 1.0)
        pooled[feat_name] = {
            "pooled_in": pooled_in,
            "n_in": total_n_in,
            "pooled_off": pooled_off,
            "n_off": total_n_off,
        }

    # Exactly ONE apply_bh_fdr call per run, over the full 57-length p-vector --
    # never per timeframe, per subfamily, or per feature (D-01a / tag_calibrator.py
    # convention).
    reject, p_corrected = apply_bh_fdr(p_values, alpha=0.05)

    survivors: list[str] = []
    print(
        "feature,pooled_in_ic,n_in,pooled_off_ic,n_off,raw_p,corrected_p,fdr_reject,"
        "b2_agreement,broad"
    )
    for idx, feat_name in enumerate(_FAMILY_ORDER):
        row = pooled[feat_name]
        fdr_reject = bool(reject[idx])
        agreement: float | None = None
        broad: bool | None = None
        if fdr_reject:
            pooled_diff_sign = int(np.sign(abs(row["pooled_in"]) - abs(row["pooled_off"])))
            diffs = [
                abs(per_symbol[s][feat_name].ic_in) - abs(per_symbol[s][feat_name].ic_off)
                for s in per_symbol
                if per_symbol[s][feat_name].n_in >= _B2_MIN_SUFFICIENT_N
                and per_symbol[s][feat_name].n_off >= _B2_MIN_SUFFICIENT_N
            ]
            agreement = (
                sum(1 for d in diffs if np.sign(d) == pooled_diff_sign) / len(diffs)
                if diffs
                else 0.0
            )

            jackknife_signs: list[int] = []
            jackknife_ps: list[float] = []
            for drop_symbol in top5_symbols:
                remaining = [s for s in per_symbol if s != drop_symbol]
                jk_in, jk_n_in = _pooled_fisher_z(
                    [per_symbol[s][feat_name].ic_in for s in remaining],
                    [per_symbol[s][feat_name].n_in for s in remaining],
                )
                jk_off, jk_n_off = _pooled_fisher_z(
                    [per_symbol[s][feat_name].ic_off for s in remaining],
                    [per_symbol[s][feat_name].n_off for s in remaining],
                )
                jk_p = fisher_z_difference_p(jk_in, jk_n_in, jk_off, jk_n_off)
                jackknife_signs.append(int(np.sign(abs(jk_in) - abs(jk_off))))
                jackknife_ps.append(jk_p if np.isfinite(jk_p) else 1.0)

            broad = _is_broad(agreement, jackknife_signs, jackknife_ps, pooled_diff_sign)
            if broad:
                survivors.append(feat_name)

        print(
            f"{feat_name},{row['pooled_in']!r},{row['n_in']},{row['pooled_off']!r},"
            f"{row['n_off']},{p_values[idx]!r},{p_corrected[idx]!r},{fdr_reject},"
            f"{agreement!r},{broad!r}"
        )

    verdict = _sweep_verdict(survivors, any(reject))
    survivors_str = ",".join(survivors) if survivors else "NONE"
    print(f"SWEEP_SURVIVORS={survivors_str}")
    print(f"SWEEP_VERDICT={verdict}")


# ---------------------------------------------------------------------------
# Single-feature corpus query + runner.
# ---------------------------------------------------------------------------

_SINGLE_FEATURE_TEMPLATE = sql.SQL("""
    SELECT fv.bar_ts, fv.{feat} AS feature_value, fr.{ret} AS return_value
    FROM feature_vectors fv
    INNER JOIN forward_returns fr
        ON fr.symbol = fv.symbol
        AND fr.tf = fv.tf
        AND fr.bar_ts = fv.bar_ts
        AND fr.return_type = 'executable_open_to_open'
    WHERE fv.tf = %(tf)s
      AND fv.{feat} IS NOT NULL
      AND fr.{ret} IS NOT NULL
    ORDER BY fv.bar_ts
    """)


def _run_single_feature(conn: Any, args: argparse.Namespace) -> None:
    feature_id = _validated_identifier(args.feature, allowed=_FEATURE_ALLOWLIST)
    return_id = _validated_identifier(args.return_column, allowed=set(_RETURN_COLUMN_CHOICES))
    query = _SINGLE_FEATURE_TEMPLATE.format(feat=feature_id, ret=return_id)
    print("Composed query (values not substituted):")
    print(query.as_string(conn))

    with conn.cursor() as cur:
        cur.execute(query, {"tf": args.tf})
        rows = cur.fetchall()

    if not rows:
        print(f"A1_VERDICT=REFUTED (no rows returned for feature={args.feature!r} tf={args.tf!r})")
        return

    bar_dates = [_as_date(r[0]) for r in rows]
    feature_vals = np.array([r[1] for r in rows], dtype=np.float64)
    return_vals = np.array([r[2] for r in rows], dtype=np.float64)

    (in_ic, in_n), (off_ic, off_n) = _partition_and_score(
        bar_dates, feature_vals, return_vals, args.start_days, args.end_days
    )
    verdict = _a1_verdict(in_ic, in_n, off_ic, off_n)

    ratio = abs(in_ic) / abs(off_ic) if off_ic not in (0, float("nan")) else float("nan")
    print(f"In-season IC: {in_ic!r} (n={in_n})")
    print(f"Off-season IC: {off_ic!r} (n={off_n})")
    print(f"Ratio (|in|/|off|): {ratio!r}")
    print(f"A1_VERDICT={verdict}")


def _as_date(bar_ts: Any) -> date:
    if isinstance(bar_ts, datetime):
        return bar_ts.date()
    if isinstance(bar_ts, date):
        return bar_ts
    raise TypeError(f"unexpected bar_ts type: {type(bar_ts)!r}")


# ---------------------------------------------------------------------------
# main()
# ---------------------------------------------------------------------------


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start-days", type=int, default=14)
    parser.add_argument("--end-days", type=int, default=42)
    parser.add_argument("--feature", default="up_vol_body_diff")
    parser.add_argument("--tf", default="1d")
    parser.add_argument("--return-column", default="return_fast", choices=_RETURN_COLUMN_CHOICES)
    parser.add_argument("--skip-contention-check", action="store_true")
    parser.add_argument(
        "--sweep",
        action="store_true",
        help="Sweep the full 57-feature vol/volume family with BH-FDR + breadth "
        "test instead of measuring a single --feature.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)

    conn = _connect()
    try:
        if not args.skip_contention_check:
            contention_rows = _check_contention(conn)
            if contention_rows:
                _print_contention_block(contention_rows)
                if args.sweep:
                    print("SWEEP_VERDICT=BLOCKED")
                    print("SWEEP_SURVIVORS=NONE")
                else:
                    print("A1_VERDICT=BLOCKED")
                return 2
        if args.sweep:
            _run_sweep(conn, args)
        else:
            _run_single_feature(conn, args)
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
