#!/usr/bin/env python3
"""
ops_broadcast_feature_audit.py -- empirical audit + persistence of which active
features are "broadcast" (identical across all symbols at a given bar_ts) vs
genuinely idiosyncratic (varies by symbol), vs inconclusive (no evidence either
way -- e.g. a rare event flag that never fired in the sampled window).

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

concept_registry.group_name (domain='feature') already has a 'macro' category (vix_z,
yield_slope_z, flight_quality) -- but 'session'/'calendar' features (e.g. dow_sin,
hour_of_day_cos, in_ny_session, power_hour) are ALSO derived purely from bar_ts, hence
equally broadcast, and are NOT captured by 'macro'. This script classifies EMPIRICALLY
(from actual feature_vectors data, not by trusting group_name), then cross-references
against group_name to confirm/deny the hypothesis and surface any surprises (a
feature broadcast but NOT in macro/session/calendar, or vice versa).

THREE-WAY VERDICT (Phase 173 / todo 270, 2026-08-25): `_classify_broadcast` returns
'broadcast' / 'idiosyncratic' / 'inconclusive', not a bool. The original boolean
contract had a real defect: a feature that is constant across symbols ONLY because
it never fired in the sampled window (e.g. `sweep_detected`, `manip_strength` --
rare, event-driven structural features) was indistinguishable from a genuine
bar_ts-derived broadcast signal (e.g. `dow_sin`, which is constant across symbols by
CONSTRUCTION, not by coincidence). The temporal-variance guard fixes this: a verdict
of 'broadcast' additionally requires the feature's representative value to differ
across at least two distinct bar_ts groups -- real temporal evidence that the
constancy comes from a bar_ts-derived function, not from "nothing happened to fire
in this narrow window." A feature that is constant on BOTH axes (cross-symbol AND
cross-bar_ts) carries zero evidence either way and is classified 'inconclusive',
never silently defaulted to 'broadcast'.

PERSISTENCE (--persist, Phase 173 / todo 270, 2026-08-25): this script now writes
its classification to `concept_registry.metadata->>'broadcast'` (JSONB merge, never
a full-row replace -- see `_PERSIST_UPDATE_SQL`), so Plan 03's cross-sectional-cell
exclusion and Plan 04's compute-time invariance assertion can both read one durable
source of truth instead of re-running this script or hand-maintaining a frozenset
(the cautionary example `CONTEXT_FEATURES` already is). This supersedes the original
"persistence is deferred ... premature (YAGNI)" framing below: Phase 173 is the
consumer that arrived.

The --persist write is scoped to EXACTLY this population -- `domain='feature'`,
`status='active'`, INNER JOINed to `concept_gate` (excludes migration 284's 2
gate-less tombstone rows, `new_high_flag`/`new_low_flag`) -- and computes a
CONSENSUS verdict per feature across every tf the run covered:
  - broadcast=true, evidence='measured_broadcast'    if 'broadcast' in >=1 tf AND
                                                          'idiosyncratic' in NO tf
  - broadcast=false, evidence='measured_idiosyncratic' if 'idiosyncratic' in >=1 tf
  - broadcast=false, evidence='inconclusive'          otherwise (every tf either
                                                          'inconclusive' or the
                                                          feature had insufficient
                                                          data in every tf run)
The 5 `status='candidate'` rows and the 2 gate-less tombstones deliberately never
receive a `broadcast` key at all -- Plan 03's read (`metadata->>'broadcast' =
'true'`) treats an absent key as not-broadcast, the correct conservative default
(feature stays in the per-symbol cell, i.e. today's behavior). An excluded row can
never silently become a broadcast row.

CAVEATS:
- A 'broadcast' classification relies on a sample of `--n-timestamps` bar_ts values
  (default 20) STRATIFIED evenly across the feature's full history (`_stratified_sample`),
  not just the most recent N. This is deliberate, found live during Phase 173 Task 3:
  a recency-only sample is fragile whenever the most recent stretch of history is
  itself degenerate -- this corpus's active universe is 100% equities (useRTH=True
  fetch) and intraday ingestion has been stalled since 2026-08-13, so the most-recent
  window alone would show zero temporal variance for in_ny_session/in_london_kz (both
  genuinely bar_ts-only functions) even though real off-RTH evidence exists earlier in
  history. A truly per-symbol feature might still appear broadcast if its rare,
  event-driven signal never fired anywhere in the stratified sample -- this is exactly
  the case the temporal-variance guard above is designed to catch and reclassify
  'inconclusive'. A larger --n-timestamps gives rare-event features a fairer chance to
  fire and produce real evidence.
- Features with fewer than `min_symbols` finite values total across the sampled
  bar_ts's (e.g. never implemented and always NULL, or legitimately sparse) are
  listed separately under "Insufficient data" and are never classified at all --
  not conflated with 'inconclusive' in the printed report, though both are treated
  identically (broadcast=false) by the --persist consensus above.

Usage:
    python scripts/ops/alpha/ops_broadcast_feature_audit.py
    python scripts/ops/alpha/ops_broadcast_feature_audit.py --tf 1h --n-timestamps 200
    python scripts/ops/alpha/ops_broadcast_feature_audit.py --n-timestamps 200 --persist
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

import asyncpg
import numpy as np

from services.ic_engine import _FEATURE_NAMES
from src.config.config_service import ConfigService
from src.config.settings import Settings
from src.core.service_utils import format_iso_ts

_TFS = ("5m", "15m", "1h", "1d")
_DEFAULT_N_TIMESTAMPS = 20
_DEFAULT_MIN_SYMBOLS = 10
_EXPECTED_BROADCAST_GROUPS = frozenset({"macro", "session", "calendar"})

# D-02's authoritative floor enumeration (CONTEXT.md, 32 individual field names --
# sin/cos pairs expanded, since D-02's "23" is a counting-convention artifact: pairs
# were counted as one logical field there). The empirical detector is the authority;
# this list is the FLOOR every one of these names must clear as broadcast=true after
# a --persist run, per planner_findings 1 in 173-01-PLAN.md.
_D02_ENUMERATED_BROADCAST_FEATURES = frozenset(
    {
        "dow_sin",
        "dow_cos",
        "month_position",
        "quarter_position",
        "days_to_month_end",
        "quarter_cycle_sin",
        "quarter_cycle_cos",
        "tdom_sin",
        "tdom_cos",
        "minute_of_hour_sin",
        "minute_of_hour_cos",
        "hour_of_day_sin",
        "hour_of_day_cos",
        "week_of_month_sin",
        "week_of_month_cos",
        "day_of_month_sin",
        "day_of_month_cos",
        "week_of_year_sin",
        "week_of_year_cos",
        "in_ny_session",
        "in_london_kz",
        "in_overlap",
        "power_hour",
        "opening_range",
        "vix_z",
        "yield_slope_z",
        "flight_quality",
        "tip_tlt_ret_z",
        "hyg_lqd_ret_z",
        "sb_corr_fast",
        "sb_corr_slow",
        "sb_corr_z",
    }
)

_CANDIDATE_TIMESTAMPS_SQL = """
    SELECT bar_ts FROM feature_vectors
    WHERE tf = $1
    GROUP BY bar_ts
    HAVING count(DISTINCT symbol) >= $2
    ORDER BY bar_ts
"""
# concept_gate is INNER JOINed (not a bare domain='feature' filter) to exclude
# migration 284's 2 gate-less tombstone concept_registry rows -- matching
# services/ic_engine.py's _watermark_concept_registry / ConceptRegistryService's
# own _LOAD_CONCEPTS_SYNC_SQL semantics exactly (Phase 170 Plan 07, live-verified:
# both queries return the identical 249-row/md5 result with this join).
_CONCEPT_REGISTRY_SQL = """
    SELECT cr.name AS feature_name, cr.group_name, cr.status
    FROM concept_registry cr
    JOIN concept_gate cg ON cg.concept_id = cr.concept_id
    WHERE cr.domain = 'feature'
"""

# JSONB MERGE (never a full-row replace) -- `metadata || jsonb_build_object(...)`
# preserves every pre-existing key (tier, apr_namespace, formula_short,
# normalization, migrated_from, migrated_by) a production row already carries.
# Scope is the LOCKED target population (173-01-PLAN.md planner_findings 8): only
# active, gate-joined domain='feature' rows whose name is in the bucket being
# written. The concept_gate EXISTS check excludes migration 284's 2 gate-less
# tombstones; cr.status='active' excludes the 5 candidate rows -- both populations
# are asserted empty-of-the-broadcast-key by 173-01's Task 3 acceptance criteria.
_PERSIST_UPDATE_SQL = """
    UPDATE concept_registry cr
    SET metadata = cr.metadata || jsonb_build_object(
        'broadcast', $2::boolean,
        'broadcast_evidence', $3::text,
        'broadcast_detected_at', $4::text
    )
    WHERE cr.domain = 'feature' AND cr.status = 'active' AND cr.name = ANY($1)
      AND EXISTS (SELECT 1 FROM concept_gate cg WHERE cg.concept_id = cr.concept_id)
"""


def _classify_broadcast(values_by_bar_ts: dict[Any, np.ndarray], epsilon: float) -> str:
    """Classify a feature's per-bar_ts cross-symbol value arrays into one of three
    verdicts.

    'idiosyncratic': ANY bar_ts group's finite cross-symbol spread (max - min)
    exceeds epsilon. This check runs FIRST and returns immediately -- an
    idiosyncratic verdict is never downgraded to 'inconclusive' by the
    temporal-variance guard below.

    'broadcast': every group's cross-symbol spread is within epsilon (or has fewer
    than 2 finite values, hence nothing to compare) AND the temporal-variance guard
    passes -- at least two distinct bar_ts groups have a representative (first
    finite) value that differs by more than epsilon. This is the real evidence that
    the feature is bar_ts-derived (e.g. dow_sin varies across bar_ts even though
    it's constant across symbols at any single bar_ts).

    'inconclusive': the temporal-variance guard fails -- fewer than 2 groups
    contributed a representative value (including the empty-input and
    single-group cases), or every representative value is identical (a globally
    constant feature, e.g. a rare event flag that never fired in this sample
    window -- the sweep_detected/manip_strength false-positive case this guard
    exists to catch). Absence of contradicting evidence is NOT evidence of
    broadcast structure, so the classifier abstains rather than defaulting to
    'broadcast'.
    """
    representatives: list[float] = []
    for values in values_by_bar_ts.values():
        finite = values[np.isfinite(values)]
        if len(finite) >= 2 and (np.nanmax(finite) - np.nanmin(finite)) > epsilon:
            return "idiosyncratic"
        if len(finite) >= 1:
            representatives.append(float(finite[0]))

    if len(representatives) < 2:
        return "inconclusive"

    if (max(representatives) - min(representatives)) > epsilon:
        return "broadcast"
    return "inconclusive"


def _count_finite_values_total(values_by_bar_ts: dict[Any, np.ndarray]) -> int:
    """Count total finite (non-NaN) values across all bar_ts groups."""
    total = 0
    for values in values_by_bar_ts.values():
        finite = values[np.isfinite(values)]
        total += len(finite)
    return total


def _stratified_sample(all_bar_ts: list[Any], n: int) -> list[Any]:
    """Pick up to `n` bar_ts values evenly spaced across the FULL sorted history,
    not just the most recent n.

    Found live during Phase 173 Task 3 (todo 270, 2026-08-25): a recency-only
    sample is fragile whenever the most recent stretch of history is itself
    degenerate. Confirmed live: this corpus's active universe is 100% equities
    (useRTH=True fetch), and intraday ingestion has been stalled since
    2026-08-13, so the most-recent-200-timestamps window contains ONLY
    regular-trading-hours bars -- in_ny_session/in_london_kz read as constant
    (zero temporal evidence) in that window despite being genuinely bar_ts-only
    functions (verified via src/intelligence/feature_factory.py -- same
    zero-symbol-parameter signature as in_overlap/power_hour, which DO classify
    correctly). Real off-RTH evidence exists earlier in history (e.g.
    in_ny_session=0 rows with 220+ symbols as recently as 2026-03-06) -- a
    stratified sample surfaces it; a recency-only sample cannot.
    """
    if len(all_bar_ts) <= n or n <= 0:
        return all_bar_ts
    step = len(all_bar_ts) / n
    indices = sorted({min(int(i * step), len(all_bar_ts) - 1) for i in range(n)})
    return [all_bar_ts[i] for i in indices]


def _consensus_verdict(tf_verdicts: list[str]) -> tuple[bool, str]:
    """Reduce a feature's per-tf verdicts (across every tf this run covered, in
    which the feature had sufficient data to be classified at all) to the
    --persist consensus contract: broadcast=true only if 'broadcast' fired in at
    least one tf AND 'idiosyncratic' fired in none. A feature 'idiosyncratic'
    anywhere is broadcast=false. A feature with no 'broadcast'/'idiosyncratic'
    verdict at all (either every tf was 'inconclusive', or the feature had
    insufficient data in every tf and never entered `tf_verdicts`) is
    broadcast=false with evidence='inconclusive', so the abstention is legible
    rather than indistinguishable from a measured negative.
    """
    if "idiosyncratic" in tf_verdicts:
        return False, "measured_idiosyncratic"
    if "broadcast" in tf_verdicts:
        return True, "measured_broadcast"
    return False, "inconclusive"


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--tf", choices=_TFS, default=None, help="Restrict to one timeframe.")
    parser.add_argument("--n-timestamps", type=int, default=_DEFAULT_N_TIMESTAMPS)
    parser.add_argument("--min-symbols", type=int, default=_DEFAULT_MIN_SYMBOLS)
    parser.add_argument(
        "--persist",
        action="store_true",
        default=False,
        help=(
            "Write the consensus classification to concept_registry.metadata->>'broadcast' "
            "for every active, gate-joined domain='feature' row this run classified. "
            "Default off -- the script stays read-only unless explicitly asked."
        ),
    )
    return parser.parse_args()


async def _persist_verdicts(
    pool: asyncpg.Pool, verdicts_by_feature: dict[str, list[str]]
) -> dict[str, int]:
    """Write the consensus classification for every feature in `verdicts_by_feature`,
    grouped into 3 buckets (one UPDATE per bucket, scoped by _PERSIST_UPDATE_SQL's
    locked predicate) and stamped with the current UTC time. Returns counts of rows
    the database actually reported as affected per bucket, so a shortfall against
    the requested name count is visible to the caller rather than silently
    swallowed."""
    detected_at = format_iso_ts(datetime.now(UTC))

    buckets: dict[tuple[bool, str], list[str]] = {}
    for feature, tf_verdicts in verdicts_by_feature.items():
        broadcast, evidence = _consensus_verdict(tf_verdicts)
        buckets.setdefault((broadcast, evidence), []).append(feature)

    affected_by_bucket: dict[str, int] = {}
    for (broadcast, evidence), names in buckets.items():
        result = await pool.execute(_PERSIST_UPDATE_SQL, names, broadcast, evidence, detected_at)
        # asyncpg execute() returns a command tag string, e.g. "UPDATE 5".
        n_affected = int(result.split()[-1])
        affected_by_bucket[evidence] = affected_by_bucket.get(evidence, 0) + n_affected
        if n_affected != len(names):
            print(
                f"  WARNING: bucket broadcast={broadcast} evidence={evidence} requested "
                f"{len(names)} rows but the UPDATE affected {n_affected} -- a classified "
                "name is not in the target population (not active, not gate-joined, or "
                "not domain='feature'). Investigate before trusting this run's persisted "
                "population."
            )

    return affected_by_bucket


async def main() -> int:
    args = _parse_args()
    settings = Settings()
    dsn = settings.database_url.replace("postgresql+asyncpg://", "postgresql://")
    pool = await asyncpg.create_pool(dsn=dsn)

    try:
        config_service = ConfigService(database_url=dsn, pool=pool)
        await config_service.initialize()
        epsilon = await config_service.get("alpha.ic.broadcast_variance_threshold", default=1e-9)

        registry_rows = await pool.fetch(_CONCEPT_REGISTRY_SQL)
        status_by_feature = {r["feature_name"]: r["status"] for r in registry_rows}
        group_by_feature = {r["feature_name"]: r["group_name"] for r in registry_rows}
        active_features = [f for f in _FEATURE_NAMES if status_by_feature.get(f) == "active"]
        feature_cols_sql = ", ".join(f'"{f}"' for f in active_features)

        tfs = (args.tf,) if args.tf else _TFS
        print("# Broadcast-Feature Audit\n")
        print(
            f"Classifying {len(active_features)} active features per tf as 'broadcast' "
            "(identical across every symbol at a bar_ts AND varies across bar_ts -- real "
            "temporal evidence), 'idiosyncratic' (varies by symbol), or 'inconclusive' "
            "(no evidence either way, e.g. constant on both axes -- treat as NOT broadcast). "
            f"epsilon={epsilon} (alpha.ic.broadcast_variance_threshold), "
            f"min_symbols={args.min_symbols}, n_timestamps={args.n_timestamps}. A broadcast "
            "feature pooled cross-sectionally has severe pseudo-replication exposure in any "
            "significance test that treats (symbol, bar_ts) pairs as independent -- see "
            "todo 203/270. See docstring for caveats on rare-event features and sampling "
            "window bias.\n"
        )

        verdicts_by_feature: dict[str, list[str]] = {f: [] for f in active_features}

        for tf in tfs:
            candidate_rows = await pool.fetch(_CANDIDATE_TIMESTAMPS_SQL, tf, args.min_symbols)
            all_bar_ts = [r["bar_ts"] for r in candidate_rows]
            bar_ts_list = _stratified_sample(all_bar_ts, args.n_timestamps)
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
            idiosyncratic_features = []
            inconclusive_features = []
            for f in active_features:
                values_dict = {
                    ts: np.array(v, dtype=np.float64) for ts, v in values_by_feature[f].items()
                }
                if _count_finite_values_total(values_dict) < args.min_symbols:
                    insufficient_data_features.append(f)
                    continue
                verdict = _classify_broadcast(values_dict, epsilon)
                verdicts_by_feature[f].append(verdict)
                if verdict == "broadcast":
                    broadcast_features.append(f)
                elif verdict == "idiosyncratic":
                    idiosyncratic_features.append(f)
                else:
                    inconclusive_features.append(f)

            print(f"## tf={tf} ({len(bar_ts_list)} timestamps sampled, {len(rows)} rows)\n")
            print(f"Broadcast features ({len(broadcast_features)}):")
            for f in sorted(broadcast_features):
                group = group_by_feature.get(f, "?")
                flag = "" if group in _EXPECTED_BROADCAST_GROUPS else "  <-- UNEXPECTED GROUP"
                print(f"  {f:<32} group={group}{flag}")
            print()

            if inconclusive_features:
                print(f"Inconclusive features ({len(inconclusive_features)}):")
                print("  (constant on both axes in this sample window -- no temporal evidence ")
                print("   of bar_ts-derived structure; NOT persisted as broadcast; see docstring)")
                for f in sorted(inconclusive_features):
                    group = group_by_feature.get(f, "?")
                    print(f"  {f:<32} group={group}")
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
            "not tagged macro/session/calendar in concept_registry -- worth checking whether "
            "it's mis-tagged or genuinely should carry this exposure warning.\n"
            "An 'inconclusive' feature may reflect 'no event occurred in this recent sample "
            "window' rather than genuine idiosyncrasy -- a larger --n-timestamps gives rare "
            "events a fairer chance to fire.\n"
        )

        if args.persist:
            print("## Persisting consensus classification (--persist)\n")
            affected_by_evidence = await _persist_verdicts(pool, verdicts_by_feature)
            total_requested = len(verdicts_by_feature)
            total_affected = sum(affected_by_evidence.values())
            for evidence, count in sorted(affected_by_evidence.items()):
                print(f"  {evidence:<24} {count} rows")
            print(f"  {'total':<24} {total_affected} rows (requested {total_requested})")
            print()

            missing_d02 = sorted(
                name
                for name in _D02_ENUMERATED_BROADCAST_FEATURES
                if _consensus_verdict(verdicts_by_feature.get(name, []))[0] is not True
            )
            if missing_d02:
                print(
                    "  HARD STOP CANDIDATE: the following D-02-enumerated names did NOT "
                    "come out broadcast=true this run -- Plan 03 cannot be planned around "
                    "an unexplained gap:"
                )
                for name in missing_d02:
                    print(f"    {name}")
            else:
                print("  All 32 D-02-enumerated names classified broadcast=true. Floor cleared.")
            print()
        else:
            print("This report is informational only (no writes) -- pass --persist to write.")

        return 0
    finally:
        await pool.close()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
