#!/usr/bin/env python3
"""Generate IC Discovery Report — reads ensemble_weights, ensemble_alpha, alpha_events.

Produces two output files in docs/analysis/:
  - ic-discovery-report.json: structured metrics for machine consumption
  - ic-discovery-report.md:   human-readable discovery report

This is a READ-ONLY report generator — no INSERT, UPDATE, or CREATE statements.
Connects directly via asyncpg; no BaseBatch subclass (produces docs, not DB rows).

Output schema:
  - strata: per (symbol, tf, regime) count of passing features, weight vector,
    effective_n (from ensemble_weights)
  - emission_stats: per (symbol, tf) bars scored, events emitted, emission_rate
  - overall: total strata, total alpha events, mean/median effective_n,
    direction distribution (long/short), emission_rate

Usage:
    python services/generate_ic_discovery_report.py
"""

from __future__ import annotations

import asyncio
import json
import statistics
import sys
from datetime import UTC, datetime
from pathlib import Path

import asyncpg
import structlog

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.config.settings import Settings
from src.core.service_utils import setup_service_logging

setup_service_logging("logs/generate_ic_discovery_report.log")
_logger = structlog.get_logger(__name__)

_NO_DATA_MARKER = "NO DATA — corpus not yet populated"

_OUTPUT_DIR = project_root / "docs" / "analysis"

_APR_QUERY = "SELECT config_key, config_value FROM config_state WHERE config_key LIKE 'alpha.%'"


async def _load_apr(conn: asyncpg.Connection) -> dict[str, str]:
    rows = await conn.fetch(_APR_QUERY)
    return {r["config_key"]: r["config_value"] for r in rows}


async def _query_strata(conn: asyncpg.Connection, weight_version: str) -> list[dict]:
    """Per (symbol, tf, regime): passing feature count, weight vector, effective_n."""
    rows = await conn.fetch(
        """
        SELECT
            symbol,
            tf,
            regime,
            COUNT(*) AS n_features,
            AVG(effective_n) AS effective_n,
            JSON_AGG(
                JSON_BUILD_OBJECT(
                    'feature_name', feature_name,
                    'weight', weight,
                    'raw_weight', raw_weight,
                    'ic_sharpe', ic_sharpe
                )
                ORDER BY weight DESC
            ) AS features
        FROM ensemble_weights
        WHERE weight_version = $1
        GROUP BY symbol, tf, regime
        ORDER BY symbol, tf, regime
        """,
        weight_version,
    )
    strata = []
    for r in rows:
        features_raw = r["features"]
        if isinstance(features_raw, str):
            features_raw = json.loads(features_raw)
        strata.append(
            {
                "symbol": r["symbol"],
                "tf": r["tf"],
                "regime": r["regime"],
                "n_features": int(r["n_features"]),
                "effective_n": round(float(r["effective_n"]), 3) if r["effective_n"] else 0.0,
                "top_features": [
                    {
                        "feature_name": f["feature_name"],
                        "weight": round(float(f["weight"]), 4),
                        "raw_weight": round(float(f["raw_weight"]), 4),
                        "ic_sharpe": (
                            round(float(f["ic_sharpe"]), 4) if f.get("ic_sharpe") else None
                        ),
                    }
                    for f in features_raw[:10]
                ],
            }
        )
    return strata


async def _query_emission_stats(conn: asyncpg.Connection, weight_version: str) -> list[dict]:
    """Per (symbol, tf): bars scored (ensemble_alpha rows), events emitted (alpha_events)."""
    alpha_rows = await conn.fetch(
        """
        SELECT symbol, tf, COUNT(*) AS bars_scored
        FROM ensemble_alpha
        WHERE weight_version = $1
        GROUP BY symbol, tf
        ORDER BY symbol, tf
        """,
        weight_version,
    )
    event_rows = await conn.fetch(
        """
        SELECT symbol, tf, COUNT(*) AS events_emitted,
               SUM(CASE WHEN direction = 'long' THEN 1 ELSE 0 END) AS long_count,
               SUM(CASE WHEN direction = 'short' THEN 1 ELSE 0 END) AS short_count
        FROM alpha_events
        WHERE weight_version = $1
        GROUP BY symbol, tf
        ORDER BY symbol, tf
        """,
        weight_version,
    )
    # Build lookup: (symbol, tf) -> event data
    event_map: dict[tuple[str, str], dict] = {}
    for r in event_rows:
        event_map[(r["symbol"], r["tf"])] = {
            "events_emitted": int(r["events_emitted"]),
            "long_count": int(r["long_count"]),
            "short_count": int(r["short_count"]),
        }

    stats = []
    for r in alpha_rows:
        key = (r["symbol"], r["tf"])
        bars = int(r["bars_scored"])
        ev = event_map.get(key, {"events_emitted": 0, "long_count": 0, "short_count": 0})
        emissions = ev["events_emitted"]
        emission_rate = round(emissions / bars, 5) if bars > 0 else 0.0
        stats.append(
            {
                "symbol": r["symbol"],
                "tf": r["tf"],
                "bars_scored": bars,
                "events_emitted": emissions,
                "emission_rate": emission_rate,
                "long_count": ev["long_count"],
                "short_count": ev["short_count"],
            }
        )
    return stats


async def _query_overall(
    conn: asyncpg.Connection, weight_version: str, strata: list[dict], emission_stats: list[dict]
) -> dict:
    """Overall summary metrics."""
    total_events = await conn.fetchval(
        "SELECT COUNT(*) FROM alpha_events WHERE weight_version = $1", weight_version
    )
    total_bars = await conn.fetchval(
        "SELECT COUNT(*) FROM ensemble_alpha WHERE weight_version = $1", weight_version
    )
    direction_rows = await conn.fetch(
        """
        SELECT direction, COUNT(*) AS cnt
        FROM alpha_events
        WHERE weight_version = $1
        GROUP BY direction
        """,
        weight_version,
    )
    direction_dist = {r["direction"]: int(r["cnt"]) for r in direction_rows}

    eff_ns = [s["effective_n"] for s in strata if s["effective_n"] > 0]
    mean_eff_n = round(statistics.mean(eff_ns), 3) if eff_ns else 0.0
    median_eff_n = round(statistics.median(eff_ns), 3) if eff_ns else 0.0

    total_events_int = int(total_events or 0)
    total_bars_int = int(total_bars or 0)
    overall_emission_rate = (
        round(total_events_int / total_bars_int, 5) if total_bars_int > 0 else 0.0
    )

    return {
        "weight_version": weight_version,
        "total_strata": len(strata),
        "total_alpha_events": total_events_int,
        "total_bars_scored": total_bars_int,
        "emission_rate": overall_emission_rate,
        "mean_effective_n": mean_eff_n,
        "median_effective_n": median_eff_n,
        "direction_distribution": direction_dist,
        "shadow_mode": True,
    }


def _build_json_report(
    generated_at: str,
    weight_version: str,
    strata: list[dict],
    emission_stats: list[dict],
    overall: dict,
    no_data: bool = False,
) -> dict:
    if no_data:
        return {
            "generated_at": generated_at,
            "weight_version": weight_version,
            "status": _NO_DATA_MARKER,
            "strata": [],
            "emission_stats": [],
            "overall": {
                "weight_version": weight_version,
                "total_strata": 0,
                "total_alpha_events": 0,
                "total_bars_scored": 0,
                "emission_rate": 0.0,
                "mean_effective_n": 0.0,
                "median_effective_n": 0.0,
                "direction_distribution": {},
                "shadow_mode": True,
            },
        }
    return {
        "generated_at": generated_at,
        "weight_version": weight_version,
        "status": "complete",
        "strata": strata,
        "emission_stats": emission_stats,
        "overall": overall,
    }


def _build_markdown_report(
    generated_at: str,
    weight_version: str,
    strata: list[dict],
    emission_stats: list[dict],
    overall: dict,
    no_data: bool = False,
) -> str:
    lines = [
        "# IC Discovery Report — Phase 139 Ensemble Alpha",
        "",
        f"**Generated:** {generated_at}",
        f"**Weight version:** `{weight_version}`",
        "**Mode:** Shadow (no live execution)",
        "",
    ]
    if no_data:
        lines += [
            "## Status",
            "",
            f"> **{_NO_DATA_MARKER}**",
            "",
            "Corpus tables (ensemble_weights, ensemble_alpha, alpha_events) are empty.",
            "Run `ensemble_builder.py` and `alpha_emitter.py` after the full corpus data",
            "pipeline (Phase 138 P8) completes.",
        ]
        return "\n".join(lines)

    # Overall summary
    dir_dist = overall.get("direction_distribution", {})
    long_pct = (
        round(100 * dir_dist.get("long", 0) / overall["total_alpha_events"], 1)
        if overall["total_alpha_events"] > 0
        else 0
    )
    short_pct = (
        round(100 * dir_dist.get("short", 0) / overall["total_alpha_events"], 1)
        if overall["total_alpha_events"] > 0
        else 0
    )
    lines += [
        "## Overall Summary",
        "",
        "| Metric | Value |",
        "| ------ | ----- |",
        f"| Total strata with weights | {overall['total_strata']} |",
        f"| Total bars scored | {overall['total_bars_scored']:,} |",
        f"| Total alpha events emitted | {overall['total_alpha_events']:,} |",
        f"| Overall emission rate | {overall['emission_rate']:.2%} |",
        f"| Mean effective N | {overall['mean_effective_n']:.1f} |",
        f"| Median effective N | {overall['median_effective_n']:.1f} |",
        f"| Long events | {dir_dist.get('long', 0):,} ({long_pct}%) |",
        f"| Short events | {dir_dist.get('short', 0):,} ({short_pct}%) |",
        "",
    ]

    # Strata table
    lines += [
        "## Strata Summary",
        "",
        "| Symbol | TF | Regime | Features | Effective N |",
        "| ------ | -- | ------ | -------- | ----------- |",
    ]
    for s in strata:
        lines.append(
            f"| {s['symbol']} | {s['tf']} | {s['regime']} | {s['n_features']} | {s['effective_n']:.1f} |"
        )
    lines.append("")

    # Emission rates per (symbol, tf)
    lines += [
        "## Emission Rates by Symbol × Timeframe",
        "",
        "| Symbol | TF | Bars Scored | Events | Emission Rate | Long | Short |",
        "| ------ | -- | ----------- | ------ | ------------- | ---- | ----- |",
    ]
    for e in emission_stats:
        lines.append(
            f"| {e['symbol']} | {e['tf']} | {e['bars_scored']:,} | {e['events_emitted']:,} "
            f"| {e['emission_rate']:.2%} | {e['long_count']:,} | {e['short_count']:,} |"
        )
    lines.append("")

    # Top features per stratum (first 5 strata to keep report concise)
    lines += ["## Top Features by Stratum (Sample)", ""]
    shown = 0
    for s in strata:
        if shown >= 8:
            remaining = len(strata) - shown
            if remaining > 0:
                lines.append(f"*... {remaining} more strata omitted for brevity ...*")
            break
        lines.append(f"### {s['symbol']} / {s['tf']} / {s['regime']}")
        lines.append(f"Effective N = {s['effective_n']:.1f} | Features = {s['n_features']}")
        lines.append("")
        lines.append("| Feature | Weight | IC Sharpe |")
        lines.append("| ------- | ------ | --------- |")
        for f in s["top_features"][:5]:
            sharpe_str = f"{f['ic_sharpe']:.3f}" if f.get("ic_sharpe") else "—"
            lines.append(f"| {f['feature_name']} | {f['weight']:.4f} | {sharpe_str} |")
        lines.append("")
        shown += 1

    # Effective N distribution note
    lines += [
        "## Effective N Distribution",
        "",
        f"Mean: {overall['mean_effective_n']:.1f}  Median: {overall['median_effective_n']:.1f}",
        "",
        "Effective N represents the number of independently-informative features",
        "after Ledoit-Wolf shrinkage and cluster deflation. Values >= 3.0 are required",
        "before alpha events are emitted (the `alpha.ensemble.effective_n_gate` APR key).",
        "",
        "## Notes",
        "",
        "- This report covers the **4-symbol validation corpus** (SPY/TLT/XLF/QQQ × 4 TFs).",
        "  Full 58-ETF corpus run is pending (Phase 138 P8 full backfill).",
        "- All events are in **shadow mode** — no live execution or position sizing.",
        "- Weights are version `v1` derived via Ledoit-Wolf shrinkage + cluster deflation.",
        "- Direction-aware CI gate applied: long events require alpha_ci_lower > 0;",
        "  short events require alpha_ci_upper < 0.",
    ]
    return "\n".join(lines)


async def main() -> None:
    _logger.info("generate_ic_discovery_report.start")
    settings = Settings()
    db_dsn = settings.database_url.replace("postgresql+asyncpg://", "postgresql://")

    pool = await asyncpg.create_pool(db_dsn, min_size=1, max_size=5)
    try:
        async with pool.acquire() as conn:
            cfg = await _load_apr(conn)
            weight_version = cfg.get("alpha.ensemble.weight_version", "v1")

            # Check if tables have data
            n_weights = await conn.fetchval("SELECT COUNT(*) FROM ensemble_weights")
            n_alpha = await conn.fetchval("SELECT COUNT(*) FROM ensemble_alpha")
            n_events = await conn.fetchval("SELECT COUNT(*) FROM alpha_events")

            no_data = int(n_weights or 0) == 0 and int(n_alpha or 0) == 0

            _logger.info(
                "generate_ic_discovery_report.corpus_check",
                n_weights=n_weights,
                n_alpha=n_alpha,
                n_events=n_events,
                no_data=no_data,
            )

            if no_data:
                strata = []
                emission_stats = []
                overall: dict = {}
            else:
                strata = await _query_strata(conn, weight_version)
                emission_stats = await _query_emission_stats(conn, weight_version)
                overall = await _query_overall(conn, weight_version, strata, emission_stats)
    finally:
        await pool.close()

    generated_at = datetime.now(UTC).isoformat()
    _OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # Build and write JSON report
    json_report = _build_json_report(
        generated_at, weight_version, strata, emission_stats, overall, no_data=no_data
    )
    json_path = _OUTPUT_DIR / "ic-discovery-report.json"
    json_path.write_text(json.dumps(json_report, indent=2, default=str))
    _logger.info("generate_ic_discovery_report.json_written", path=str(json_path))

    # Build and write Markdown report
    md_report = _build_markdown_report(
        generated_at, weight_version, strata, emission_stats, overall, no_data=no_data
    )
    md_path = _OUTPUT_DIR / "ic-discovery-report.md"
    md_path.write_text(md_report)
    _logger.info("generate_ic_discovery_report.md_written", path=str(md_path))

    _logger.info(
        "generate_ic_discovery_report.complete",
        strata=len(strata),
        emission_stats=len(emission_stats),
        no_data=no_data,
    )


if __name__ == "__main__":
    asyncio.run(main())
