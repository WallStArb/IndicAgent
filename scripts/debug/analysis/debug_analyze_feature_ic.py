#!/usr/bin/env python3
"""
debug_analyze_feature_ic.py — v3.0 corpus pipeline IC analysis and reporting

Reads feature_ic_scores table and produces IC distribution analysis by feature,
timeframe, and regime, including FDR and walk-forward validation results.
Run after corpus pipeline completion to review feature predictive quality.
Requires feature_ic_scores table populated with IC data.
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import structlog

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from src.config.settings import Settings
from src.core.service_utils import setup_service_logging

setup_service_logging("logs/analyze_feature_ic.log")
_logger = structlog.get_logger(__name__)
settings = Settings()

_OUTPUT_DIR = project_root / "docs" / "analysis"
_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def _get_latest_training_window(conn) -> str | None:
    """Get the latest training_window_end from feature_ic_scores."""
    with conn.cursor() as cur:
        cur.execute("SELECT MAX(training_window_end) FROM feature_ic_scores")
        result = cur.fetchone()
        return result[0] if result and result[0] else None


def _overall_ic_summary(conn, training_window_end: str) -> dict[str, Any]:
    """Overall IC distribution statistics."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT
                COUNT(*) as n_obs,
                AVG(ic_value) as mean_ic,
                PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY ic_value) as median_ic,
                PERCENTILE_CONT(0.25) WITHIN GROUP (ORDER BY ic_value) as p25_ic,
                PERCENTILE_CONT(0.75) WITHIN GROUP (ORDER BY ic_value) as p75_ic,
                STDDEV(ic_value) as stddev_ic,
                COUNT(*) FILTER (WHERE ic_value > 0) as n_positive,
                COUNT(*) FILTER (WHERE ic_value < 0) as n_negative,
                COUNT(*) FILTER (WHERE passes_fdr = true) as n_passes_fdr,
                COUNT(*) FILTER (WHERE passes_walkforward = true) as n_passes_wf
            FROM feature_ic_scores
            WHERE training_window_end = %s AND ic_value IS NOT NULL
            """,
            (training_window_end,),
        )
        row = cur.fetchone()
        return {
            "n_obs": row[0],
            "mean_ic": round(float(row[1]), 4) if row[1] else None,
            "median_ic": round(float(row[2]), 4) if row[2] else None,
            "p25_ic": round(float(row[3]), 4) if row[3] else None,
            "p75_ic": round(float(row[4]), 4) if row[4] else None,
            "stddev_ic": round(float(row[5]), 4) if row[5] else None,
            "n_positive": row[6],
            "n_negative": row[7],
            "n_passes_fdr": row[8],
            "n_passes_wf": row[9],
            "pct_passes_fdr": round(row[8] / row[0] * 100, 2) if row[0] else 0,
        }


def _ic_by_feature(conn, training_window_end: str) -> list[dict]:
    """IC statistics per feature."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT
                feature_name,
                COUNT(*) as n_obs,
                AVG(ic_value) as mean_ic,
                PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY ic_value) as median_ic,
                AVG(ic_sharpe) as mean_ic_sharpe,
                COUNT(*) FILTER (WHERE passes_fdr = true) as n_passes_fdr,
                COUNT(*) FILTER (WHERE passes_walkforward = true) as n_passes_wf,
                AVG(effective_n) as mean_effective_n
            FROM feature_ic_scores
            WHERE training_window_end = %s AND ic_value IS NOT NULL
            GROUP BY feature_name
            ORDER BY mean_ic DESC
            """,
            (training_window_end,),
        )
        features = []
        for row in cur.fetchall():
            features.append(
                {
                    "feature_name": row[0],
                    "n_obs": row[1],
                    "mean_ic": round(float(row[2]), 4) if row[2] else None,
                    "median_ic": round(float(row[3]), 4) if row[3] else None,
                    "mean_ic_sharpe": round(float(row[4]), 4) if row[4] else None,
                    "n_passes_fdr": row[5],
                    "n_passes_wf": row[6],
                    "pct_passes_fdr": round(row[5] / row[1] * 100, 2) if row[1] else 0,
                    "mean_effective_n": round(float(row[7]), 2) if row[7] else None,
                }
            )
        return features


def _ic_by_timeframe(conn, training_window_end: str) -> list[dict]:
    """IC statistics per timeframe."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT
                tf,
                COUNT(*) as n_obs,
                AVG(ic_value) as mean_ic,
                PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY ic_value) as median_ic,
                AVG(ic_sharpe) as mean_ic_sharpe,
                COUNT(*) FILTER (WHERE passes_fdr = true) as n_passes_fdr
            FROM feature_ic_scores
            WHERE training_window_end = %s AND ic_value IS NOT NULL
            GROUP BY tf
            ORDER BY tf
            """,
            (training_window_end,),
        )
        tfs = []
        for row in cur.fetchall():
            tfs.append(
                {
                    "tf": row[0],
                    "n_obs": row[1],
                    "mean_ic": round(float(row[2]), 4) if row[2] else None,
                    "median_ic": round(float(row[3]), 4) if row[3] else None,
                    "mean_ic_sharpe": round(float(row[4]), 4) if row[4] else None,
                    "n_passes_fdr": row[5],
                }
            )
        return tfs


def _ic_by_regime(conn, training_window_end: str) -> list[dict]:
    """IC statistics per regime (excluding pooled)."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT
                regime,
                COUNT(*) as n_obs,
                AVG(ic_value) as mean_ic,
                PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY ic_value) as median_ic,
                COUNT(*) FILTER (WHERE passes_fdr = true) as n_passes_fdr
            FROM feature_ic_scores
            WHERE training_window_end = %s AND ic_value IS NOT NULL AND is_pooled = false
            GROUP BY regime
            ORDER BY mean_ic DESC
            """,
            (training_window_end,),
        )
        regimes = []
        for row in cur.fetchall():
            regimes.append(
                {
                    "regime": row[0],
                    "n_obs": row[1],
                    "mean_ic": round(float(row[2]), 4) if row[2] else None,
                    "median_ic": round(float(row[3]), 4) if row[3] else None,
                    "n_passes_fdr": row[4],
                }
            )
        return regimes


def _generate_markdown(
    training_window_end: str,
    overall: dict,
    by_feature: list[dict],
    by_tf: list[dict],
    by_regime: list[dict],
) -> str:
    """Generate markdown report."""
    lines = [
        "# Feature IC Analysis Report",
        "",
        f"**Generated:** {datetime.now(UTC).isoformat()}",
        f"**Training window end:** {training_window_end}",
        "",
        "## Overall Summary",
        "",
        "| Metric | Value |",
        "| ------ | ----- |",
        f"| Total IC observations | {overall['n_obs']:,} |",
        f"| Mean IC | {overall['mean_ic']} |",
        f"| Median IC | {overall['median_ic']} |",
        f"| 25th percentile | {overall['p25_ic']} |",
        f"| 75th percentile | {overall['p75_ic']} |",
        f"| Std dev | {overall['stddev_ic']} |",
        f"| Positive IC | {overall['n_positive']:,} ({overall['n_positive']/overall['n_obs']*100:.1f}%) |",
        f"| Negative IC | {overall['n_negative']:,} ({overall['n_negative']/overall['n_obs']*100:.1f}%) |",
        f"| Passes FDR | {overall['n_passes_fdr']:,} ({overall['pct_passes_fdr']}%) |",
        f"| Passes walk-forward | {overall['n_passes_wf']:,} |",
        "",
        "## IC by Timeframe",
        "",
        "| TF | Obs | Mean IC | Median IC | Mean IC Sharpe | Passes FDR |",
        "| -- | --- | -------- | ----------- | -------------- | ---------- |",
    ]

    for tf in by_tf:
        lines.append(
            f"| {tf['tf']} | {tf['n_obs']:,} | {tf['mean_ic']} | {tf['median_ic']} | "
            f"{tf['mean_ic_sharpe']} | {tf['n_passes_fdr']:,} |"
        )

    lines.extend(
        [
            "",
            "## IC by Regime (excluding pooled)",
            "",
            "| Regime | Obs | Mean IC | Median IC | Passes FDR |",
            "| ------ | --- | -------- | ----------- | ---------- |",
        ]
    )

    for regime in by_regime:
        lines.append(
            f"| {regime['regime']} | {regime['n_obs']:,} | {regime['mean_ic']} | "
            f"{regime['median_ic']} | {regime['n_passes_fdr']:,} |"
        )

    lines.extend(
        [
            "",
            "## Top 20 Features by Mean IC",
            "",
            "| Feature | Obs | Mean IC | Median IC | Mean IC Sharpe | Passes FDR | Passes WF | Eff N |",
            "| ------- | --- | -------- | ----------- | -------------- | ---------- | --------- | ------- |",
        ]
    )

    for feat in by_feature[:20]:
        lines.append(
            f"| {feat['feature_name']} | {feat['n_obs']:,} | {feat['mean_ic']} | "
            f"{feat['median_ic']} | {feat['mean_ic_sharpe']} | {feat['n_passes_fdr']:,} | "
            f"{feat['n_passes_wf']:,} | {feat['mean_effective_n']} |"
        )

    lines.extend(
        [
            "",
            "---",
            "",
            "*Generated by analyze_feature_ic.py*",
        ]
    )

    return "\n".join(lines)


def main():
    import psycopg2

    from src.core.database_manager import get_connection_params

    conn = psycopg2.connect(**get_connection_params(settings.database_url))

    try:
        training_window_end = _get_latest_training_window(conn)
        if not training_window_end:
            _logger.error("No data found in feature_ic_scores")
            print("ERROR: No data found in feature_ic_scores. Has corpus pipeline completed?")
            return

        _logger.info("Analyzing feature IC scores", training_window_end=training_window_end)

        overall = _overall_ic_summary(conn, training_window_end)
        by_feature = _ic_by_feature(conn, training_window_end)
        by_tf = _ic_by_timeframe(conn, training_window_end)
        by_regime = _ic_by_regime(conn, training_window_end)

        # Generate markdown report
        report = _generate_markdown(training_window_end, overall, by_feature, by_tf, by_regime)

        # Write report
        output_file = _OUTPUT_DIR / "feature_ic_analysis.md"
        output_file.write_text(report)
        _logger.info("Report written", output_file=str(output_file))

        # Write JSON for machine consumption
        json_file = _OUTPUT_DIR / "feature_ic_analysis.json"
        import json

        json_file.write_text(
            json.dumps(
                {
                    "training_window_end": training_window_end,
                    "overall": overall,
                    "by_feature": by_feature,
                    "by_tf": by_tf,
                    "by_regime": by_regime,
                },
                indent=2,
                default=str,
            )
        )
        _logger.info("JSON written", json_file=str(json_file))

        print("\n✓ Analysis complete:")
        print(f"  - {output_file}")
        print(f"  - {json_file}")
        print("\nKey findings:")
        print(f"  - {overall['n_obs']:,} IC observations")
        print(f"  - Mean IC: {overall['mean_ic']}")
        print(f"  - {overall['pct_passes_fdr']}% pass FDR")
        print(f"  - Top feature: {by_feature[0]['feature_name']} (IC: {by_feature[0]['mean_ic']})")

    finally:
        conn.close()


if __name__ == "__main__":
    main()
