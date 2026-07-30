#!/usr/bin/env python3
"""
ops_broadcast_feature_audit.py -- empirical audit of which active features are
"broadcast" (identical across all symbols at a given bar_ts) vs genuinely
idiosyncratic (varies by symbol).

Motivated by todo 203: canary_noise_gaussian/uniform/near_constant were found seeded
by (bar_ts, base_seed) only, no symbol -- bit-identical across every symbol at a
timestamp, confirmed live (fixed by this same session's plan, Task 1). But vix_z/
yield_slope_z were ALSO confirmed bit-identical across symbols -- correctly, since
they're legitimately single macro series broadcast to every row. Any significance
test that pools symbols together (this project's own ic_engine.py
_compute_cross_sectional_tf, or an ad hoc diagnostic doing the same) treats a
broadcast feature's (symbol, bar_ts) pairs as if they were independent observations,
when the true independent draw count per bar_ts is 1, not n_symbols -- severe
pseudo-replication, inflating apparent significance for ANY feature with this
structure, whether or not the underlying relationship is real.

feature_registry.group_name already has a 'macro' category (vix_z, yield_slope_z,
flight_quality) -- but 'session'/'calendar' features (e.g. dow_sin, hour_of_day_cos,
in_ny_session, power_hour) are ALSO derived purely from bar_ts, hence equally
broadcast, and are NOT captured by 'macro'. This script classifies EMPIRICALLY (from
actual feature_vectors data, not by trusting group_name), then cross-references
against group_name to confirm/deny the hypothesis and surface any surprises (a
feature broadcast but NOT in macro/session/calendar, or vice versa).

Read-only, no persistence -- classification is a printed report only. Whether/how to
make this classification durable (a feature_registry column) is deferred to whoever
builds a broadcast-aware significance test (a separate, real methodology decision,
not mechanical) -- building schema/persistence with no current consumer would be
premature (YAGNI).

CAVEATS:
- A 'broadcast' classification relies on a recent-window sample (default 20 most recent
  bar_ts) to detect structure. A truly per-symbol feature might appear broadcast if its
  rare, event-driven signal didn't fire in this narrow window. Features flagged as
  'broadcast' with low data density or known event-driven semantics should be treated
  as inconclusive, not confirmed.
- Features with fewer than `min_symbols` finite values total across the sampled
  bar_ts's (e.g. never implemented and always NULL, or legitimately sparse) are listed
  separately under "Insufficient data" and should not be conflated with structurally
  broadcast features.

Usage:
    python scripts/ops/alpha/ops_broadcast_feature_audit.py
    python scripts/ops/alpha/ops_broadcast_feature_audit.py --tf 1h --n-timestamps 20
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

import asyncpg
import numpy as np

from services.ic_engine import _FEATURE_NAMES
from src.config.settings import Settings

_TFS = ("5m", "15m", "1h", "1d")
_DEFAULT_N_TIMESTAMPS = 20
_DEFAULT_MIN_SYMBOLS = 10
_BROADCAST_EPSILON = 1e-9
_EXPECTED_BROADCAST_GROUPS = frozenset({"macro", "session", "calendar"})

_SAMPLE_TIMESTAMPS_SQL = """
    SELECT bar_ts FROM feature_vectors
    WHERE tf = $1
    GROUP BY bar_ts
    HAVING count(DISTINCT symbol) >= $2
    ORDER BY bar_ts DESC
    LIMIT $3
"""
_FEATURE_REGISTRY_SQL = "SELECT feature_name, group_name, status FROM feature_registry"


def _classify_broadcast(values_by_bar_ts: dict[Any, np.ndarray], epsilon: float) -> bool:
    """True if EVERY bar_ts group's cross-symbol values are identical within
    `epsilon` (max - min <= epsilon) -- i.e. a 'broadcast' feature, indistinguishable
    from a single value duplicated across every symbol. Groups with fewer than 2
    finite values are skipped (nothing to compare); an empty input is vacuously
    broadcast (no evidence against it)."""
    for values in values_by_bar_ts.values():
        finite = values[np.isfinite(values)]
        if len(finite) < 2:
            continue
        if (np.nanmax(finite) - np.nanmin(finite)) > epsilon:
            return False
    return True


def _count_finite_values_total(values_by_bar_ts: dict[Any, np.ndarray]) -> int:
    """Count total finite (non-NaN) values across all bar_ts groups."""
    total = 0
    for values in values_by_bar_ts.values():
        finite = values[np.isfinite(values)]
        total += len(finite)
    return total


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tf", choices=_TFS, default=None, help="Restrict to one timeframe.")
    parser.add_argument("--n-timestamps", type=int, default=_DEFAULT_N_TIMESTAMPS)
    parser.add_argument("--min-symbols", type=int, default=_DEFAULT_MIN_SYMBOLS)
    return parser.parse_args()


async def main() -> int:
    args = _parse_args()
    settings = Settings()
    dsn = settings.database_url.replace("postgresql+asyncpg://", "postgresql://")
    pool = await asyncpg.create_pool(dsn=dsn)

    try:
        registry_rows = await pool.fetch(_FEATURE_REGISTRY_SQL)
        status_by_feature = {r["feature_name"]: r["status"] for r in registry_rows}
        group_by_feature = {r["feature_name"]: r["group_name"] for r in registry_rows}
        active_features = [f for f in _FEATURE_NAMES if status_by_feature.get(f) == "active"]
        feature_cols_sql = ", ".join(f'"{f}"' for f in active_features)

        tfs = (args.tf,) if args.tf else _TFS
        print("# Broadcast-Feature Audit\n")
        print(
            f"Classifying {len(active_features)} active features per tf as 'broadcast' "
            "(identical across every symbol at a bar_ts), 'idiosyncratic' (varies by "
            f"symbol), or 'insufficient data'. epsilon={_BROADCAST_EPSILON}, min_symbols="
            f"{args.min_symbols}, n_timestamps={args.n_timestamps}. A broadcast feature "
            "pooled cross-sectionally has severe pseudo-replication exposure in any "
            "significance test that treats (symbol, bar_ts) pairs as independent -- see "
            "todo 203. See docstring for caveats on rare-event features and sampling "
            "window bias.\n"
        )

        for tf in tfs:
            ts_rows = await pool.fetch(
                _SAMPLE_TIMESTAMPS_SQL, tf, args.min_symbols, args.n_timestamps
            )
            bar_ts_list = [r["bar_ts"] for r in ts_rows]
            if not bar_ts_list:
                print(f"## tf={tf}: no bar_ts with >= {args.min_symbols} symbols -- skipped\n")
                continue

            rows = await pool.fetch(
                f"""
                SELECT bar_ts, symbol, {feature_cols_sql}
                FROM feature_vectors
                WHERE tf = $1 AND bar_ts = ANY($2::timestamptz[])
                """,
                tf,
                bar_ts_list,
            )

            values_by_feature: dict[str, dict[Any, list[float]]] = {
                f: {ts: [] for ts in bar_ts_list} for f in active_features
            }
            for r in rows:
                for f in active_features:
                    values_by_feature[f][r["bar_ts"]].append(r[f])

            # Separate features by data availability, then classify -- each feature's
            # values are converted to arrays once and reused for both checks.
            insufficient_data_features = []
            broadcast_features = []
            for f in active_features:
                values_dict = {
                    ts: np.array(v, dtype=np.float64) for ts, v in values_by_feature[f].items()
                }
                if _count_finite_values_total(values_dict) < args.min_symbols:
                    insufficient_data_features.append(f)
                elif _classify_broadcast(values_dict, _BROADCAST_EPSILON):
                    broadcast_features.append(f)

            print(f"## tf={tf} ({len(bar_ts_list)} timestamps sampled, {len(rows)} rows)\n")
            print(f"Broadcast features ({len(broadcast_features)}):")
            for f in sorted(broadcast_features):
                group = group_by_feature.get(f, "?")
                flag = "" if group in _EXPECTED_BROADCAST_GROUPS else "  <-- UNEXPECTED GROUP"
                print(f"  {f:<32} group={group}{flag}")
            print()

            if insufficient_data_features:
                print(f"Insufficient data ({len(insufficient_data_features)}):")
                print(
                    "  (fewer than min_symbols finite values total -- likely unimplemented/always-null,"
                )
                print("   not evidence of broadcast structure; see docstring caveat)")
                for f in sorted(insufficient_data_features):
                    group = group_by_feature.get(f, "?")
                    print(f"  {f:<32} group={group}")
                print()

        print(
            "---\nA feature listed with '<-- UNEXPECTED GROUP' is broadcast in the data but "
            "not tagged macro/session/calendar in feature_registry -- worth checking whether "
            "it's mis-tagged or genuinely should carry this exposure warning.\n"
            "A feature flagged as broadcast but with low data density or known event-driven "
            "semantics may reflect 'no event occurred in this recent sample window' rather than "
            "genuine bar_ts-level broadcast structure -- treat such cases as inconclusive.\n"
            "This report is informational only (no writes) -- see script docstring for why "
            "persistence is deferred."
        )
        return 0
    finally:
        await pool.close()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
