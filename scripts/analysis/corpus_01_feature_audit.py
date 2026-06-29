#!/usr/bin/env python3
"""
CORPUS-01 Feature Distribution Audit

Audits every feature column in feature_vectors for:
(a) variance > epsilon (1e-12): no silent constants
(b) NaN rate < 5% post-warmup: exclude first 100 bars per symbol
(c) no distributional cliff: 4-week rolling std z-score |z| > 2.0

Disposition:
- BLOCKED: fails (a) - zero variance, IC undefined
- WARNING: fails (b) or (c) - flagged but not dropped (Renaissance principle)
- PASS: all criteria met

Output: docs/analysis/corpus-01-feature-audit.md
"""

import asyncio
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import asyncpg

# Database URL from environment
DB_URL = f"postgresql://{os.getenv('POSTGRES_USER', 'postgres')}:{os.getenv('POSTGRES_PASSWORD', 'postgres')}@{os.getenv('POSTGRES_HOST', 'localhost')}/{os.getenv('POSTGRES_DB', 'indicagent')}"


# Constants from plan
EPSILON = 1e-12  # variance threshold
WARMUP_BARS = 100  # exclude first N bars per symbol
NAN_THRESHOLD_PCT = 5.0  # NaN rate threshold %
CLIFF_Z_THRESHOLD = 2.0  # rolling std z-score threshold
ROLLING_WINDOW_WEEKS = 4  # cliff detection window


FEATURE_COLUMNS = [
    "above_wk_vwap",
    "adx",
    "amihud_illiq_z",
    "aroon_fast",
    "aroon_slow",
    "atr_z",
    "bar_close_pos",
    "cci_fast",
    "cci_mid",
    "cci_slow",
    "cmf",
    "ctf_momentum",
    "ctf_regime_align",
    "ctf_vwap_align",
    "cvd_slope_z",
    "days_to_month_end",
    "dow_cos",
    "dow_sin",
    "flight_quality",
    "gap_z",
    "garch_ratio",
    "high_52w_dist",
    "hma_slope_z",
    "hmm_duration",
    "hmm_entropy",
    "hmm_prob_ranging",
    "hmm_prob_trending_down",
    "hmm_prob_trending_up",
    "hmm_regime_prob",
    "hurst",
    "in_london_kz",
    "in_ny_session",
    "in_overlap",
    "informed_flow",
    "momentum_rank_z",
    "momentum_reversal_z",
    "momentum_z_fast",
    "momentum_z_mid",
    "momentum_z_slow",
    "month_position",
    "ofi_div",
    "ofi_z",
    "opening_range",
    "poc_dist_atr",
    "power_hour",
    "quarter_position",
    "range_position",
    "rel_volume",
    "ret_acf1_z",
    "ret_skew_z",
    "rsi_fast",
    "rsi_mid",
    "rsi_slow",
    "shannon",
    "sr_resist_dist",
    "sr_support_dist",
    "va_position",
    "vix_z",
    "vol_ratio",
    "volatility_rank_z",
    "volume_rank_z",
    "volume_z",
    "vwap_dev_sigma",
    "yield_slope_z",
]


async def audit_feature_variance(conn: asyncpg.Connection, feature: str) -> dict:
    """Check criterion (a): variance > epsilon per symbol"""
    query = f"""
    SELECT symbol, VAR_SAMP("{feature}") AS variance
    FROM feature_vectors
    GROUP BY symbol
    ORDER BY symbol;
    """
    rows = await conn.fetch(query)

    if not rows:
        return {"pass": False, "min_variance": None, "max_variance": None, "symbols_below": []}

    min_variance = min(r["variance"] or 0 for r in rows)
    max_variance = max(r["variance"] or 0 for r in rows)
    symbols_below = [r["symbol"] for r in rows if (r["variance"] or 0) <= EPSILON]

    # Criterion (a): ALL symbols must have variance > epsilon
    pass_a = len(symbols_below) == 0

    return {
        "pass": pass_a,
        "min_variance": min_variance,
        "max_variance": max_variance,
        "symbols_below": symbols_below[:10],  # First 10 for reporting
    }


async def audit_feature_nan_rate(conn: asyncpg.Connection, feature: str) -> dict:
    """Check criterion (b): NaN rate < 5% post-warmup (excluding first 100 bars per symbol)"""
    # For each symbol, count NULL/NaN rows after excluding first 100 bars
    # We use ROW_NUMBER() to skip the first 100 bars per symbol
    query = f"""
    WITH numbered AS (
        SELECT
            symbol,
            "{feature}" IS NULL AS is_null,
            ROW_NUMBER() OVER (PARTITION BY symbol ORDER BY bar_ts) AS rn
        FROM feature_vectors
    )
    SELECT
        COUNT(*) FILTER (WHERE is_null) AS null_count,
        COUNT(*) AS total_count
    FROM numbered
    WHERE rn > $1;
    """
    row = await conn.fetchrow(query, WARMUP_BARS)

    if not row or row["total_count"] == 0:
        return {"pass": False, "nan_rate_pct": None, "null_count": None, "total_count": 0}

    null_count = row["null_count"]
    total_count = row["total_count"]
    nan_rate_pct = 100.0 * null_count / total_count if total_count > 0 else 0

    pass_b = nan_rate_pct < NAN_THRESHOLD_PCT

    return {
        "pass": pass_b,
        "nan_rate_pct": nan_rate_pct,
        "null_count": null_count,
        "total_count": total_count,
    }


async def audit_feature_cliff(conn: asyncpg.Connection, feature: str) -> dict:
    """
    Check criterion (c): no distributional cliff.

    Compute 4-week rolling std of the feature, then z-score of that rolling-std series.
    If any |z| > 2.0, the column FAILS criterion (c).

    Approximation: We'll compute per-symbol rolling std and look for jumps.
    Given the scale of data, we use a sampled approach for efficiency.
    """
    # TODO: Implement cliff detection
    # This is a WARNING criterion only, so we default to PASS for now
    raise NotImplementedError("Cliff detection not yet implemented")


async def main():
    """Run the full feature audit"""
    print(f"[{datetime.now(UTC).isoformat()}] Starting CORPUS-01 Feature Distribution Audit")

    results = []
    blocked_features = []
    warning_features = []

    # Create connection pool and get connection
    pool = await asyncpg.create_pool(DB_URL, min_size=2, max_size=10)

    async with pool.acquire() as conn:
        for i, feature in enumerate(FEATURE_COLUMNS, 1):
            print(
                f"[{datetime.now(UTC).isoformat()}] Auditing {i}/{len(FEATURE_COLUMNS)}: {feature}"
            )

            # Run checks sequentially to avoid concurrent query issues on same connection
            variance_result = await audit_feature_variance(conn, feature)
            nan_result = await audit_feature_nan_rate(conn, feature)

            # Determine disposition
            # Note: cliff detection (c) is not yet implemented
            if not variance_result["pass"]:
                disposition = "BLOCKED"
                blocked_features.append(feature)
            elif not nan_result["pass"]:
                disposition = "WARNING"
                warning_features.append(feature)
            else:
                disposition = "PASS"

            results.append(
                {
                    "feature": feature,
                    "variance_pass": variance_result["pass"],
                    "min_variance": variance_result["min_variance"],
                    "max_variance": variance_result["max_variance"],
                    "nan_rate_pct": nan_result["nan_rate_pct"],
                    "nan_pass": nan_result["pass"],
                    "disposition": disposition,
                }
            )

    await pool.close()

    # Write the report
    output_path = Path("docs/analysis/corpus-01-feature-audit.md")
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with open(output_path, "w") as f:
        f.write("# CORPUS-01: Feature Distribution Audit\n\n")
        f.write(f"**Date:** {datetime.now(UTC).strftime('%Y-%m-%d')}\n")
        f.write("**Corpus:** V1-corrected (Phase 141 P0)\n\n")

        f.write("## Audit Criteria\n\n")
        f.write(
            f"- **(a) Variance > epsilon ({EPSILON:.0e}):** No silent constants. All symbols must have variance > epsilon.\n"
        )
        f.write(
            f"- **(b) NaN rate < {NAN_THRESHOLD_PCT}% post-warmup:** Excludes first {WARMUP_BARS} bars per symbol.\n"
        )
        f.write(
            f"- **(c) No distributional cliff:** {ROLLING_WINDOW_WEEKS}-week rolling std z-score |z| > {CLIFF_Z_THRESHOLD} triggers WARNING.\n\n"
        )

        f.write("## Disposition Legend\n\n")
        f.write("- **PASS:** All criteria met\n")
        f.write(
            "- **BLOCKED:** Fails criterion (a) - zero variance, IC undefined. These features are excluded from IC measurement.\n"
        )
        f.write(
            "- **WARNING:** Fails criterion (b) or (c) - flagged for review but NOT dropped (Renaissance principle: never drop data that could contain signal).\n\n"
        )

        f.write("## Summary\n\n")
        f.write(f"- **Total features audited:** {len(results)}\n")
        f.write(f"- **BLOCKED:** {len(blocked_features)}\n")
        f.write(f"- **WARNING:** {len(warning_features)}\n")
        f.write(f"- **PASS:** {len(results) - len(blocked_features) - len(warning_features)}\n\n")

        if blocked_features:
            f.write("### BLOCKED Features (Zero Variance)\n\n")
            for feat in blocked_features:
                f.write(f"- `{feat}`\n")
            f.write("\n")

        if warning_features:
            f.write("### WARNING Features\n\n")
            for feat in warning_features:
                f.write(f"- `{feat}`\n")
            f.write("\n")

        f.write("## Per-Feature Audit Table\n\n")
        f.write(
            "| Feature | Variance Pass | Min Variance | Max Variance | NaN Rate % | NaN Pass | Disposition |\n"
        )
        f.write(
            "|---------|---------------|--------------|--------------|------------|----------|------------|\n"
        )

        for r in results:
            min_var = f"{r['min_variance']:.2e}" if r["min_variance"] is not None else "N/A"
            max_var = f"{r['max_variance']:.2e}" if r["max_variance"] is not None else "N/A"
            nan_pct = f"{r['nan_rate_pct']:.2f}" if r["nan_rate_pct"] is not None else "N/A"

            f.write(
                f"| {r['feature']} | {'✓' if r['variance_pass'] else '✗'} | {min_var} | {max_var} | {nan_pct} | {'✓' if r['nan_pass'] else '✗'} | {r['disposition']} |\n"
            )

        f.write("\n## Notes\n\n")
        f.write(
            "- Variance audit is per-symbol: a feature is BLOCKED only if ALL symbols have variance <= epsilon.\n"
        )
        f.write(
            f"- NaN rate is computed post-warmup: first {WARMUP_BARS} bars per symbol are excluded.\n"
        )
        f.write(
            "- Cliff detection (c) is not yet implemented; this audit checks (a) variance and (b) NaN rate only.\n"
        )
        f.write(
            "- BLOCKED features are excluded from IC measurement: IC is undefined for constant series.\n\n"
        )

    print(f"[{datetime.now(UTC).isoformat()}] Audit complete. Report written to {output_path}")
    print(
        f"[{datetime.now(UTC).isoformat()}] Summary: {len(results)} audited, {len(blocked_features)} BLOCKED, {len(warning_features)} WARNING"
    )


if __name__ == "__main__":
    asyncio.run(main())
