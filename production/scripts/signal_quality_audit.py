#!/usr/bin/env python3
"""signal_quality_audit — Two-layer per-plugin signal quality audit.

Version: 1.0
Status: current
Last Updated: 2026-06-15

Layer 1 — Statistical IC table (D-13):
    For each plugin with >= 30 non-null pnl_r outcomes in signal_ledger:
    - hit_rate (pnl_r > 0 rate)
    - IC = Pearson corr(raw_confidence, pnl_r)
    - bootstrap 95% CI on hit_rate (10,000 resamples)
    - t-stat for IC vs 0
    - Equity/forex segment breakdown
    - Verdict: VALIDATED / NOISE CANDIDATE / ANTI-SIGNAL per D-13 thresholds

Layer 2 — Detection condition verifiability:
    For VALIDATED and NOISE CANDIDATE plugins from Layer 1:
    - Sample 50 signals from signal_ledger, join to intelligence_features
    - Check whether primary detection-condition fields are populated
    - Verdict: VERIFIABLE / PARTIAL / UNVERIFIABLE

Usage:
    .venv/bin/python production/scripts/signal_quality_audit.py
    .venv/bin/python production/scripts/signal_quality_audit.py --layer 1
    .venv/bin/python production/scripts/signal_quality_audit.py --layer 2
    .venv/bin/python production/scripts/signal_quality_audit.py --layer all

Exit codes:
    0 = audit complete
    1 = error
"""

from __future__ import annotations

import argparse
import asyncio
import math
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import asyncpg
import numpy as np

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_PROJECT_ROOT))

from src.config.config_service import ConfigService
from src.config.settings import Settings
from src.core.database_manager import DatabaseManager

# ---------------------------------------------------------------------------
# FOREX symbols - used for equity/forex segmentation
# ---------------------------------------------------------------------------

_FOREX_SYMBOLS = frozenset({"EURUSD", "USDCHF", "USDJPY", "GBPUSD", "AUDUSD", "USDCAD"})

# ---------------------------------------------------------------------------
# Layer 2 detection-condition feature field mapping
#
# Maps plugin name -> list of primary detection-condition feature keys.
# Derived by reading compute_full() primary gate checks in each plugin.
# Keys must be non-null for the signal to be mechanically verifiable.
#
# "MANUAL" sentinel = condition cannot be mapped to intelligence_features keys
# (e.g. relies purely on OHLCV arithmetic at signal time, not feature fields).
# ---------------------------------------------------------------------------

_PLUGIN_DETECTION_FIELDS: dict[str, list[str] | str] = {
    # Layer 1 qualifying plugins mapped here:
    "trad_DivergenceStack": [
        "rsi_div_bullish",
        "rsi_div_bearish",
        "macd_div_bullish",
        "macd_div_bearish",
    ],
    "trad_GapAnalysisSetup": "MANUAL",  # Gap detection uses raw OHLCV open[-1] vs close[-2] arithmetic
    "trad_AnchoredVWAPReversion": ["session_vwap_deviation_sigma", "session_vwap"],
    "trad_CVDDivergence": ["cvd_divergence", "cvd_slope_5bar"],
    "trad_LiquiditySweepReclaim": ["sweep_detected", "sweep_reclaimed", "sweep_type"],
    "trad_PatternCompletion": ["dt_db_pattern", "hs_pattern", "tri_breakout_bias"],
    "trad_OFIContinuation": ["ofi_ewma_20"],
    "trad_CHoCHReversal": ["choch_detected", "choch_direction"],
    "trad_FVGFill": ["fvg_type", "fvg_top", "fvg_bottom"],
    "trad_SupplyDemandSetup": [
        "in_demand_zone",
        "in_supply_zone",
        "nearest_demand_high",
        "nearest_demand_low",
    ],
    "trad_SqueezeExpansion": ["squeeze_fired", "squeeze_active"],
    "trad_TrendFollowing": ["trend_regime", "trend_confidence"],
}

# Intelligence features JSONB column that each field lives in
# Used to construct the SQL query for feature presence check
_FIELD_TO_COLUMN: dict[str, str] = {
    # pattern_detections
    "rsi_div_bullish": "pattern_detections",
    "rsi_div_bearish": "pattern_detections",
    "macd_div_bullish": "pattern_detections",
    "macd_div_bearish": "pattern_detections",
    "cvd_divergence": "pattern_detections",
    "dt_db_pattern": "pattern_detections",
    "hs_pattern": "pattern_detections",
    "tri_breakout_bias": "pattern_detections",
    "squeeze_fired": "pattern_detections",
    "squeeze_active": "pattern_detections",
    # technical_indicators
    "ofi_ewma_20": "technical_indicators",
    "trend_regime": "technical_indicators",
    "trend_confidence": "technical_indicators",
    "cvd_slope_5bar": "technical_indicators",
    "session_vwap_deviation_sigma": "technical_indicators",
    "session_vwap": "technical_indicators",
    # smc
    "fvg_type": "smc",
    "fvg_top": "smc",
    "fvg_bottom": "smc",
    "sweep_detected": "smc",
    "sweep_reclaimed": "smc",
    "sweep_type": "smc",
    "choch_detected": "smc",
    "choch_direction": "smc",
    "in_demand_zone": "smc",
    "in_supply_zone": "smc",
    "nearest_demand_high": "smc",
    "nearest_demand_low": "smc",
}


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class Layer1Result:
    plugin: str
    n_outcomes: int
    hit_rate: float
    ci_lower: float
    ci_upper: float
    ic: float | None
    ic_tstat: float | None
    avg_pnl_r: float | None
    n_forex: int
    n_equity: int
    avg_pnl_forex: float | None
    avg_pnl_equity: float | None
    verdict: str  # VALIDATED / NOISE CANDIDATE / ANTI-SIGNAL


@dataclass
class Layer2Result:
    plugin: str
    samples: int
    fields_populated_rate: float
    verdict: str  # VERIFIABLE / PARTIAL / UNVERIFIABLE
    notes: str = ""


# ---------------------------------------------------------------------------
# Bootstrap CI
# ---------------------------------------------------------------------------


def _bootstrap_hit_rate_ci(
    hits: np.ndarray,
    n_resamples: int = 10_000,
    ci: float = 0.95,
    rng: np.random.Generator | None = None,
) -> tuple[float, float]:
    """Bootstrap 95% CI on hit_rate via 10,000 resamples.

    Args:
        hits: 1-D boolean/int array (1 = win, 0 = loss)
        n_resamples: number of bootstrap samples
        ci: confidence interval width (default 0.95)
        rng: optional numpy random generator for reproducibility

    Returns:
        (lower, upper) CI bounds
    """
    if rng is None:
        rng = np.random.default_rng(42)
    n = len(hits)
    sample_means = np.empty(n_resamples)
    for i in range(n_resamples):
        idx = rng.integers(0, n, size=n)
        sample_means[i] = hits[idx].mean()
    alpha = (1.0 - ci) / 2.0
    lower = float(np.quantile(sample_means, alpha))
    upper = float(np.quantile(sample_means, 1.0 - alpha))
    return lower, upper


def _ic_tstat(ic: float, n: int) -> float | None:
    """Two-sided t-statistic for Pearson IC vs 0 with n-2 dof.

    Returns None if n <= 2 (undefined).
    """
    if n <= 2 or ic is None:
        return None
    denom = math.sqrt(max(0.0, (1.0 - ic**2) / (n - 2)))
    if denom == 0.0:
        return None
    return ic / denom


# ---------------------------------------------------------------------------
# Layer 1
# ---------------------------------------------------------------------------


async def run_layer1(
    pool: asyncpg.Pool,
    cfg: ConfigService,
    min_outcomes: int = 30,
) -> list[Layer1Result]:
    """Run Layer 1 statistical IC audit.

    Reads D-13 thresholds from APR, then fetches per-plugin stats and
    computes bootstrap CI + verdict for each qualifying plugin.
    """
    # Warm cache for threshold keys
    ic_validated_floor = await cfg.get("threshold.signal_audit.ic_validated_floor", 0.02)
    ic_anti_signal_ceil = await cfg.get("threshold.signal_audit.ic_anti_signal_ceiling", -0.02)
    hit_rate_valid_floor = await cfg.get("threshold.signal_audit.hit_rate_validated_floor", 0.45)
    hit_rate_anti_ceil = await cfg.get("threshold.signal_audit.hit_rate_anti_signal_ceiling", 0.45)

    ic_validated_floor = float(ic_validated_floor)
    ic_anti_signal_ceil = float(ic_anti_signal_ceil)
    hit_rate_valid_floor = float(hit_rate_valid_floor)
    hit_rate_anti_ceil = float(hit_rate_anti_ceil)

    # Aggregate stats query - uses signal_ledger + signal_outcomes join via signal_ledger view
    sql = """
        SELECT
            sl.setup_plugin,
            count(*) FILTER (WHERE so.pnl_r IS NOT NULL) AS n_outcomes,
            avg(CASE WHEN so.pnl_r > 0 THEN 1.0 ELSE 0.0 END)
                FILTER (WHERE so.pnl_r IS NOT NULL) AS hit_rate,
            corr(sl.raw_confidence, so.pnl_r) AS ic,
            avg(so.pnl_r) AS avg_pnl_r,
            count(*) FILTER (WHERE sl.symbol = ANY($1) AND so.pnl_r IS NOT NULL) AS n_forex,
            count(*) FILTER (WHERE sl.symbol != ALL($1) AND so.pnl_r IS NOT NULL) AS n_equity,
            avg(so.pnl_r) FILTER (WHERE sl.symbol = ANY($1)) AS avg_pnl_forex,
            avg(so.pnl_r) FILTER (WHERE sl.symbol != ALL($1)) AS avg_pnl_equity
        FROM signal_ledger sl
        LEFT JOIN signal_outcomes so ON sl.signal_id = so.signal_id
        GROUP BY sl.setup_plugin
        HAVING count(*) FILTER (WHERE so.pnl_r IS NOT NULL) >= $2
        ORDER BY corr(sl.raw_confidence, so.pnl_r) DESC NULLS LAST
    """
    forex_list = list(_FOREX_SYMBOLS)
    rows = await pool.fetch(sql, forex_list, min_outcomes)

    # Fetch raw hit arrays per plugin for bootstrap CI
    hit_sql = """
        SELECT sl.setup_plugin, CASE WHEN so.pnl_r > 0 THEN 1 ELSE 0 END AS hit
        FROM signal_ledger sl
        JOIN signal_outcomes so ON sl.signal_id = so.signal_id
        WHERE so.pnl_r IS NOT NULL
        ORDER BY sl.setup_plugin
    """
    hit_rows = await pool.fetch(hit_sql)

    # Group hit arrays by plugin
    plugin_hits: dict[str, list[int]] = {}
    for row in hit_rows:
        plugin_hits.setdefault(row["setup_plugin"], []).append(row["hit"])

    rng = np.random.default_rng(42)
    results: list[Layer1Result] = []

    for row in rows:
        plugin = row["setup_plugin"]
        n = int(row["n_outcomes"])
        hit_rate = float(row["hit_rate"]) if row["hit_rate"] is not None else 0.0
        ic = float(row["ic"]) if row["ic"] is not None else None
        avg_pnl_r = float(row["avg_pnl_r"]) if row["avg_pnl_r"] is not None else None
        n_forex = int(row["n_forex"]) if row["n_forex"] is not None else 0
        n_equity = int(row["n_equity"]) if row["n_equity"] is not None else 0
        avg_pnl_forex = float(row["avg_pnl_forex"]) if row["avg_pnl_forex"] is not None else None
        avg_pnl_equity = float(row["avg_pnl_equity"]) if row["avg_pnl_equity"] is not None else None

        # Bootstrap CI on hit_rate
        hits_arr = np.array(plugin_hits.get(plugin, []), dtype=float)
        if len(hits_arr) >= 2:
            ci_lower, ci_upper = _bootstrap_hit_rate_ci(hits_arr, rng=rng)
        else:
            ci_lower, ci_upper = hit_rate, hit_rate

        # IC t-stat
        ic_tstat = _ic_tstat(ic, n) if ic is not None else None

        # D-13 verdict logic
        if ic is not None and ic < ic_anti_signal_ceil:
            verdict = "ANTI-SIGNAL"
        elif ci_upper < hit_rate_anti_ceil:
            verdict = "ANTI-SIGNAL"
        elif ic is not None and ic > ic_validated_floor and ci_lower > hit_rate_valid_floor:
            verdict = "VALIDATED"
        else:
            verdict = "NOISE CANDIDATE"

        results.append(
            Layer1Result(
                plugin=plugin,
                n_outcomes=n,
                hit_rate=hit_rate,
                ci_lower=ci_lower,
                ci_upper=ci_upper,
                ic=ic,
                ic_tstat=ic_tstat,
                avg_pnl_r=avg_pnl_r,
                n_forex=n_forex,
                n_equity=n_equity,
                avg_pnl_forex=avg_pnl_forex,
                avg_pnl_equity=avg_pnl_equity,
                verdict=verdict,
            )
        )

    return results


# ---------------------------------------------------------------------------
# Layer 2
# ---------------------------------------------------------------------------


async def run_layer2(
    pool: asyncpg.Pool,
    cfg: ConfigService,
    layer1_results: list[Layer1Result],
    n_samples: int = 50,
) -> list[Layer2Result]:
    """Run Layer 2 detection-condition verifiability audit.

    For VALIDATED and NOISE CANDIDATE plugins from Layer 1, samples 50 signals
    and checks required feature-field presence in intelligence_features.
    """
    verifiable_floor = await cfg.get("threshold.signal_audit.verifiable_population_floor", 0.90)
    partial_floor = await cfg.get("threshold.signal_audit.partial_population_floor", 0.50)
    verifiable_floor = float(verifiable_floor)
    partial_floor = float(partial_floor)

    # Only audit VALIDATED and NOISE CANDIDATE plugins
    audit_plugins = [r for r in layer1_results if r.verdict in ("VALIDATED", "NOISE CANDIDATE")]

    results: list[Layer2Result] = []

    for l1 in audit_plugins:
        plugin = l1.plugin
        detection_fields = _PLUGIN_DETECTION_FIELDS.get(plugin)

        if detection_fields == "MANUAL":
            # Detection relies purely on OHLCV arithmetic - cannot map to feature fields
            results.append(
                Layer2Result(
                    plugin=plugin,
                    samples=0,
                    fields_populated_rate=1.0,
                    verdict="VERIFIABLE",
                    notes="Detection condition is OHLCV arithmetic (open vs close); not dependent on intelligence_features fields.",
                )
            )
            continue

        if detection_fields is None:
            # No mapping defined - mark for manual review
            results.append(
                Layer2Result(
                    plugin=plugin,
                    samples=0,
                    fields_populated_rate=0.0,
                    verdict="UNVERIFIABLE",
                    notes="No feature field mapping defined for this plugin; manual review required.",
                )
            )
            continue

        # Sample signals for this plugin with a join to intelligence_features
        sample_sql = """
            SELECT
                sl.symbol,
                sl.timestamp,
                sl.timeframe,
                f.technical_indicators,
                f.pattern_detections,
                f.regime_features,
                f.confluence_scores,
                f.smc,
                f.cross_timeframe_context,
                f.market_context
            FROM signal_ledger sl
            JOIN intelligence_features f
                ON sl.symbol = f.symbol
                AND sl.timestamp = f.ts
                AND sl.timeframe = f.tf
            WHERE sl.setup_plugin = $1
            ORDER BY sl.timestamp DESC
            LIMIT $2
        """
        sample_rows = await pool.fetch(sample_sql, plugin, n_samples)
        actual_samples = len(sample_rows)

        if actual_samples == 0:
            results.append(
                Layer2Result(
                    plugin=plugin,
                    samples=0,
                    fields_populated_rate=0.0,
                    verdict="UNVERIFIABLE",
                    notes="No signals found with matching intelligence_features rows.",
                )
            )
            continue

        # Count how many samples have ALL required fields populated and non-null
        populated_count = 0
        for row in sample_rows:
            # Build merged feature dict from all JSONB columns
            all_features: dict[str, Any] = {}
            for col in (
                "technical_indicators",
                "pattern_detections",
                "regime_features",
                "confluence_scores",
                "smc",
                "cross_timeframe_context",
                "market_context",
            ):
                col_data = row[col]
                if col_data is not None:
                    all_features.update(col_data)

            all_present = all(all_features.get(fld) is not None for fld in detection_fields)
            if all_present:
                populated_count += 1

        fields_populated_rate = populated_count / actual_samples

        if fields_populated_rate >= verifiable_floor:
            verdict = "VERIFIABLE"
        elif fields_populated_rate >= partial_floor:
            verdict = "PARTIAL"
        else:
            verdict = "UNVERIFIABLE"

        notes = f"Fields checked: {', '.join(detection_fields)}"
        results.append(
            Layer2Result(
                plugin=plugin,
                samples=actual_samples,
                fields_populated_rate=fields_populated_rate,
                verdict=verdict,
                notes=notes,
            )
        )

    return results


# ---------------------------------------------------------------------------
# Print helpers
# ---------------------------------------------------------------------------


def _fmt(val: float | None, decimals: int = 4) -> str:
    if val is None:
        return "N/A"
    return f"{val:.{decimals}f}"


def print_layer1_table(results: list[Layer1Result]) -> None:
    print("\n=== LAYER 1 — IC LEAGUE TABLE ===\n")
    header = (
        f"{'Plugin':<32} {'N':>6} {'HitRate':>8} "
        f"{'CI_Lo':>7} {'CI_Hi':>7} {'IC':>8} {'tStat':>7} "
        f"{'AvgR':>7} {'nFX':>5} {'nEQ':>6} "
        f"{'AvgFX':>7} {'AvgEQ':>7} {'Verdict':<16}"
    )
    print(header)
    print("-" * len(header))
    for r in results:
        print(
            f"{r.plugin:<32} {r.n_outcomes:>6} {_fmt(r.hit_rate, 4):>8} "
            f"{_fmt(r.ci_lower, 4):>7} {_fmt(r.ci_upper, 4):>7} {_fmt(r.ic, 5):>8} {_fmt(r.ic_tstat, 2):>7} "
            f"{_fmt(r.avg_pnl_r, 4):>7} {r.n_forex:>5} {r.n_equity:>6} "
            f"{_fmt(r.avg_pnl_forex, 4):>7} {_fmt(r.avg_pnl_equity, 4):>7} {r.verdict:<16}"
        )


def print_layer2_table(results: list[Layer2Result]) -> None:
    print("\n=== LAYER 2 — DETECTION VERIFIABILITY TABLE ===\n")
    header = f"{'Plugin':<32} {'Samples':>8} {'FieldPopRate':>12} {'Verdict':<14} Notes"
    print(header)
    print("-" * 90)
    for r in results:
        print(
            f"{r.plugin:<32} {r.samples:>8} {_fmt(r.fields_populated_rate, 4):>12} "
            f"{r.verdict:<14} {r.notes}"
        )


def print_summary(layer1: list[Layer1Result], layer2: list[Layer2Result]) -> None:
    validated = sum(1 for r in layer1 if r.verdict == "VALIDATED")
    noise = sum(1 for r in layer1 if r.verdict == "NOISE CANDIDATE")
    anti = sum(1 for r in layer1 if r.verdict == "ANTI-SIGNAL")
    verifiable = sum(1 for r in layer2 if r.verdict == "VERIFIABLE")
    partial = sum(1 for r in layer2 if r.verdict == "PARTIAL")
    unverifiable = sum(1 for r in layer2 if r.verdict == "UNVERIFIABLE")
    print("\n=== SUMMARY ===\n")
    print(f"Layer 1 — {len(layer1)} plugins with >= 30 outcomes:")
    print(f"  VALIDATED:       {validated}")
    print(f"  NOISE CANDIDATE: {noise}")
    print(f"  ANTI-SIGNAL:     {anti}")
    if layer2:
        print(f"\nLayer 2 — {len(layer2)} plugins audited for detection verifiability:")
        print(f"  VERIFIABLE:   {verifiable}")
        print(f"  PARTIAL:      {partial}")
        print(f"  UNVERIFIABLE: {unverifiable}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


async def main() -> int:
    parser = argparse.ArgumentParser(
        description="Two-layer signal quality audit: IC league table + detection verifiability"
    )
    parser.add_argument(
        "--layer",
        choices=["1", "2", "all"],
        default="all",
        help="Which audit layer(s) to run (default: all)",
    )
    args = parser.parse_args()

    settings = Settings()
    db = DatabaseManager(settings.database_url)
    await db.initialize()

    cfg = ConfigService(settings.database_url, pool=db.pool)
    await cfg.initialize()

    layer1_results: list[Layer1Result] = []
    layer2_results: list[Layer2Result] = []

    try:
        if args.layer in ("1", "all"):
            print("Running Layer 1 — IC league table...")
            layer1_results = await run_layer1(db.pool, cfg)
            print_layer1_table(layer1_results)

        if args.layer in ("2", "all"):
            if not layer1_results:
                # Layer 2 called standalone — need Layer 1 data without printing it
                layer1_results = await run_layer1(db.pool, cfg)
            print("\nRunning Layer 2 — Detection verifiability...")
            layer2_results = await run_layer2(db.pool, cfg, layer1_results)
            print_layer2_table(layer2_results)

        if args.layer == "all":
            print_summary(layer1_results, layer2_results)

        print("\nAudit complete.")
        return 0

    except Exception as error:
        print(f"\nERROR: {error}", file=sys.stderr)
        raise
    finally:
        await db.close()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
