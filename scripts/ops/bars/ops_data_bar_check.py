"""D-28 data bar check: assert the minimum data bar for daily attempts from the DB.

One line per condition, PASS or FAIL with the evidence count behind it, exit 0
only when every condition holds (T-185-16-01: no hard-coded pass; every verdict
is a predicate over stored evidence). A FAIL is the phase's open blocker in
front of daily attempts 3, 3b and 4, not something this script repairs.

Conditions (plan 185-16):
  1 scrub_pass_complete      bar_scrub 'historical_pass_complete' fact for tf=1d,
                             all 72 todo-151 dry-run keys plus the 15 legacy 1d
                             keys quarantined
  2 seam_audit_complete      bar_seam_audit 'seam_audit_complete' fact, and every
                             seam_audit corporate action carries split_seam
                             quarantine flags before its effective date unless a
                             later daily derivation batch re-derived the bars
  3 late_name_dispositions   every late 1d name resolves (moved /
                             verified_empty / reached_window_start); none left
                             unresolved (plan 14's classify_head, recomputed
                             from stored D1 answers)
  4 no_pre_move_bars_visible no tradeable 1d bar of a moved name predates its
                             SMART head, unless infra.bar_derivation.venue_bars_1d
                             is true (plan 13 verdict: venue bars stay unused)
  5 dividend_coverage        Yahoo dividend coverage for at least 99 percent of
                             1d-eligible names and dividends.total_return imports
  6 survivorship_apr_keys    the six alpha.survivorship.* seeds present
                             (migration 382)
  7 inventory_is_active      D-03: no name in the moved-name inventory (the late
                             set) was soft-deleted; is_active stays true

Read-only. The 99 percent, the 72/15 known-answer counts and the six keys are
the D-28 contract itself (as fixed as plan 14's late cutoff), not tunables.
"""

from __future__ import annotations

import importlib
import json
import sys
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any

import psycopg

from scripts.ops.bars.ops_head_rerun import (
    _APR_VENUES,
    _late_names,
    _load_apr,
    _load_requests,
    classify_head,
)
from src.config.settings import Settings

_REPO_ROOT = Path(__file__).resolve().parents[3]
_FIXTURE_PATH = _REPO_ROOT / "tests" / "fixtures" / "bars" / "corrupt_1d_dry_run_2026_09_26.txt"

_SCRUB_MONITOR = ("bar_scrub", "historical_pass_complete", "tf=1d")
_SEAM_MONITOR = ("bar_seam_audit", "seam_audit_complete", None)
_VENUE_BARS_KEY = "infra.bar_derivation.venue_bars_1d"
_MIN_YAHOO_COVERAGE = 0.99
_EXPECTED_LEGACY_KEYS = 15
_SURVIVORSHIP_KEYS = (
    "alpha.survivorship.delisting_return.nasdaq",
    "alpha.survivorship.delisting_return.nyse_amex",
    "alpha.survivorship.hazard.nasdaq_annual",
    "alpha.survivorship.hazard.nyse_amex_annual",
    "alpha.survivorship.haircut.small_cap_annual",
    "alpha.survivorship.trading_days_per_year",
)
_UNRESOLVED_SAMPLE = 10

_FACT_SQL = """
SELECT passed FROM integrity_monitor
WHERE monitor_type = %s AND metric_name = %s AND subject IS NOT DISTINCT FROM %s
ORDER BY evaluated_at DESC
LIMIT 1
"""

# Distinct keys, not rows: the flag PK includes rule, so one bar can carry
# several quarantine rules (three of the 72 keys carry two).
_FIXTURE_QUARANTINE_SQL = """
SELECT COUNT(DISTINCT (b.symbol, b."timestamp")) AS quarantined
FROM unnest(%s::text[], %s::timestamptz[]) AS k(symbol, ts)
JOIN bar_quality_flag b
  ON b.symbol = k.symbol AND b.timeframe = '1d'
 AND b."timestamp" = k.ts AND b.quarantine
"""

_LEGACY_SQL = """
SELECT COUNT(*) FROM bar_quality_flag
WHERE rule = 'legacy_price_sanity_status' AND quarantine AND timeframe = '1d'
"""

_SEAM_ACTION_SQL = """
SELECT symbol, effective_date, recorded_at FROM corporate_action
WHERE inferred_by = 'seam_audit'
ORDER BY effective_date
"""

_SPLIT_SEAM_SQL = """
SELECT symbol, ("timestamp" AT TIME ZONE 'UTC')::date AS flag_date
FROM bar_quality_flag
WHERE rule = 'split_seam' AND quarantine AND timeframe = '1d'
"""

_DAILY_BATCH_SQL = """
SELECT started_at FROM bar_derivation_batch
WHERE stage = 'daily' AND status = 'completed'
"""

_PREMOVE_SQL = """
WITH heads AS (
    SELECT symbol, MIN(smart_head_date) AS smart_head
    FROM ohlcv_venue_head
    WHERE pre_move
    GROUP BY symbol
)
SELECT COUNT(*) AS pre_move_bars
FROM market_data_ohlcv_tradeable m
JOIN heads h USING (symbol)
WHERE m.timeframe = '1d' AND m."timestamp" < h.smart_head
"""

_INVENTORY_SQL = """
SELECT
  (SELECT COUNT(*) FROM instruments i
     WHERE i.compute_eligible_1d = true
       AND EXISTS (SELECT 1 FROM dividend_event_coverage c
                    WHERE c.symbol = i.symbol AND c.source = 'yahoo')) AS covered,
  (SELECT COUNT(*) FROM instruments WHERE compute_eligible_1d = true) AS eligible,
  (SELECT COUNT(*) FROM instruments WHERE symbol = ANY(%s) AND NOT is_active) AS deactivated
"""

_VENUE_FLAG_SQL = (
    "SELECT config_value FROM config_state WHERE config_key = 'infra.bar_derivation.venue_bars_1d'"
)

_SURVIVORSHIP_SQL = "SELECT config_key FROM config_state WHERE config_key = ANY(%s)"


@dataclass(frozen=True)
class CheckResult:
    """One D-28 condition's verdict plus the evidence it was decided on."""

    condition: str
    ok: bool
    evidence: str


# --- pure predicates ----------------------------------------------------------------


def scrub_condition(
    *, fact_passed: bool, fixture_total: int, fixture_quarantined: int, legacy_quarantined: int
) -> CheckResult:
    """Condition 1: the 1d scrub pass ran and its known answers are quarantined."""
    ok = (
        fact_passed
        and fixture_total > 0
        and fixture_quarantined == fixture_total
        and legacy_quarantined >= _EXPECTED_LEGACY_KEYS
    )
    return CheckResult(
        condition="scrub_pass_complete",
        ok=ok,
        evidence=(
            f"fact={fact_passed}; dry-run keys quarantined {fixture_quarantined}/{fixture_total}; "
            f"legacy 1d keys quarantined {legacy_quarantined} (>= {_EXPECTED_LEGACY_KEYS})"
        ),
    )


def seam_condition(
    *,
    fact_passed: bool,
    actions: list[tuple[str, date, datetime]],
    split_seam_bars: dict[str, list[date]],
    daily_batches: list[datetime],
) -> CheckResult:
    """Condition 2: seam audit ran and every inferred split is flagged pre-seam.

    An action passes when its symbol has a quarantined split_seam flag dated
    before the action's effective date, or a completed daily derivation batch
    started after the action was recorded (the batch re-derived the bars, so
    the flags are the batch's business). Batch-level because the batch does not
    record per-symbol detail.
    """
    uncovered = [
        symbol
        for symbol, effective, recorded in actions
        if not any(flag < effective for flag in split_seam_bars.get(symbol, ()))
        and not any(start > recorded for start in daily_batches)
    ]
    ok = fact_passed and not uncovered
    return CheckResult(
        condition="seam_audit_complete",
        ok=ok,
        evidence=(
            f"fact={fact_passed}; seam_audit actions {len(actions)}; "
            f"without pre-seam split_seam flags {len(uncovered)}"
            + (f" (e.g. {', '.join(sorted(uncovered)[:_UNRESOLVED_SAMPLE])})" if uncovered else "")
        ),
    )


def dispositions_condition(dispositions: dict[str, str]) -> CheckResult:
    """Condition 3: no late name is left unresolved."""
    unresolved = sorted(s for s, d in dispositions.items() if d == "unresolved")
    return CheckResult(
        condition="late_name_dispositions",
        ok=not unresolved,
        evidence=(
            f"late names {len(dispositions)}; unresolved {len(unresolved)}"
            + (f" (e.g. {', '.join(unresolved[:_UNRESOLVED_SAMPLE])})" if unresolved else "")
        ),
    )


def premove_condition(*, n_pre_move_bars: int, venue_bars_1d: bool) -> CheckResult:
    """Condition 4: pre-move venue bars are not visible unless explicitly allowed."""
    ok = venue_bars_1d or n_pre_move_bars == 0
    return CheckResult(
        condition="no_pre_move_bars_visible",
        ok=ok,
        evidence=(
            f"pre-move 1d bars in tradeable view {n_pre_move_bars}; "
            f"venue_bars_1d={'true' if venue_bars_1d else 'false'}"
        ),
    )


def dividend_condition(
    *, covered: int, eligible: int, total_return_importable: bool
) -> CheckResult:
    """Condition 5: Yahoo dividend coverage plus the total-return adjuster."""
    share = covered / eligible if eligible else 0.0
    ok = total_return_importable and eligible > 0 and share >= _MIN_YAHOO_COVERAGE
    return CheckResult(
        condition="dividend_coverage",
        ok=ok,
        evidence=(
            f"yahoo coverage {covered}/{eligible} ({share:.1%}, needs >= {_MIN_YAHOO_COVERAGE:.0%}); "
            f"total_return importable={total_return_importable}"
        ),
    )


def survivorship_condition(present: set[str]) -> CheckResult:
    """Condition 6: all six alpha.survivorship.* seeds exist (migration 382)."""
    missing = [key for key in _SURVIVORSHIP_KEYS if key not in present]
    return CheckResult(
        condition="survivorship_apr_keys",
        ok=not missing,
        evidence=f"present {len(_SURVIVORSHIP_KEYS) - len(missing)}/{len(_SURVIVORSHIP_KEYS)}"
        + (f"; missing {', '.join(missing)}" if missing else ""),
    )


def is_active_condition(*, deactivated: int) -> CheckResult:
    """Condition 7 (D-03): no inventory name was soft-deleted."""
    return CheckResult(
        condition="inventory_is_active",
        ok=deactivated == 0,
        evidence=f"inventory names with is_active false: {deactivated}",
    )


def summarize(results: list[CheckResult]) -> int:
    """Exit code: 0 only when every condition passed."""
    return 0 if all(result.ok for result in results) else 1


def parse_dry_run_keys(text: str) -> tuple[tuple[str, str], ...]:
    """(symbol, timestamp) pairs of the 1d CONFIRMED_CORRUPT and MARKET_EVENT keys.

    The todo-151 dry-run report is markdown tables under section headers; the
    AMBIGUOUS table is excluded by design (0 of those keys quarantine).
    """
    keys: list[tuple[str, str]] = []
    section = ""
    for line in text.splitlines():
        if line.startswith("## "):
            section = line[3:].strip()
            continue
        if not section.startswith(("CONFIRMED_CORRUPT", "MARKET_EVENT")) or not line.startswith(
            "|"
        ):
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) < 3 or cells[0] == "symbol" or set(cells[0]) <= {"-", " "}:
            continue
        symbol, tf, timestamp = cells[0], cells[1], cells[2]
        if tf == "1d":
            keys.append((symbol, timestamp))
    return tuple(keys)


def _total_return_importable() -> bool:
    try:
        module = importlib.import_module("src.intelligence.research.dividends")
    except Exception as error:  # noqa: BLE001 - the check reports, never raises
        print(f"dividends module import failed: {error}", file=sys.stderr)
        return False
    return hasattr(module, "total_return")


# --- gather and run -----------------------------------------------------------------


def _connect() -> Any:
    return psycopg.connect(Settings().database_url, autocommit=True)


def _scalar(conn: Any, sql: str, params: tuple = ()) -> Any:
    with conn.cursor() as cur:
        cur.execute(sql, params)
        return cur.fetchone()


def _rows(conn: Any, sql: str, params: tuple = ()) -> list[tuple]:
    with conn.cursor() as cur:
        cur.execute(sql, params)
        return cur.fetchall()


def run_checks(conn: Any) -> list[CheckResult]:
    """Every D-28 condition, decided from stored evidence."""
    fixture_keys = parse_dry_run_keys(_FIXTURE_PATH.read_text())

    scrub_fact = _scalar(conn, _FACT_SQL, (_SCRUB_MONITOR[0], _SCRUB_MONITOR[1], _SCRUB_MONITOR[2]))
    seam_fact = _scalar(conn, _FACT_SQL, (_SEAM_MONITOR[0], _SEAM_MONITOR[1], _SEAM_MONITOR[2]))
    fixture_quarantined = int(
        _scalar(
            conn,
            _FIXTURE_QUARANTINE_SQL,
            ([symbol for symbol, _ in fixture_keys], [ts for _, ts in fixture_keys]),
        )[0]
    )
    legacy = int(_scalar(conn, _LEGACY_SQL)[0])

    actions = [
        (symbol, effective, recorded)
        for symbol, effective, recorded in _rows(conn, _SEAM_ACTION_SQL)
    ]
    split_seam_bars: dict[str, list[date]] = defaultdict(list)
    for symbol, flag_date in _rows(conn, _SPLIT_SEAM_SQL):
        split_seam_bars[symbol].append(flag_date)
    daily_batches = [row[0] for row in _rows(conn, _DAILY_BATCH_SQL)]

    late = _late_names(conn)
    venues = json.loads(_load_apr(conn).get(_APR_VENUES, "[]"))
    requests = _load_requests(conn, list(late))
    dispositions = {
        symbol: classify_head(requests[symbol], late[symbol], venues) for symbol in late
    }

    pre_move = int(_scalar(conn, _PREMOVE_SQL)[0])
    covered, eligible, deactivated = _scalar(conn, _INVENTORY_SQL, (sorted(late),))
    venue_row = _scalar(conn, _VENUE_FLAG_SQL)
    venue_bars_1d = bool(venue_row and str(venue_row[0]).strip().lower() == "true")
    survivorship_rows = _rows(conn, _SURVIVORSHIP_SQL, (list(_SURVIVORSHIP_KEYS),))

    return [
        scrub_condition(
            fact_passed=bool(scrub_fact and scrub_fact[0]),
            fixture_total=len(fixture_keys),
            fixture_quarantined=fixture_quarantined,
            legacy_quarantined=legacy,
        ),
        seam_condition(
            fact_passed=bool(seam_fact and seam_fact[0]),
            actions=actions,
            split_seam_bars=dict(split_seam_bars),
            daily_batches=daily_batches,
        ),
        dispositions_condition(dispositions),
        premove_condition(n_pre_move_bars=pre_move, venue_bars_1d=venue_bars_1d),
        dividend_condition(
            covered=int(covered),
            eligible=int(eligible),
            total_return_importable=_total_return_importable(),
        ),
        survivorship_condition({row[0] for row in survivorship_rows}),
        is_active_condition(deactivated=int(deactivated)),
    ]


def main() -> None:
    with _connect() as conn:
        results = run_checks(conn)
    for result in results:
        print(f"{'PASS' if result.ok else 'FAIL'} {result.condition}: {result.evidence}")
    failed = sum(1 for result in results if not result.ok)
    print(f"{len(results) - failed}/{len(results)} conditions pass")
    sys.exit(summarize(results))


if __name__ == "__main__":
    main()
