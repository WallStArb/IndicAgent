"""D-28 data bar check: assert the minimum data bar for daily attempts from the DB.

One line per condition, PASS or FAIL with the evidence count behind it, exit 0
only when every condition holds (T-185-16-01: no hard-coded pass; every verdict
is a predicate over stored evidence). A FAIL is the phase's open blocker in
front of daily attempts 3, 3b and 4, not something this script repairs.

Conditions (plan 185-16; 1, 3 and 4 made source-aware by 185-34):
  1 scrub_pass_complete      bar_scrub 'historical_pass_complete' fact for tf=1d, and
                             every one of the 72 todo-151 dry-run keys and the 15
                             legacy 1d keys (migration 381) resolved: quarantined (any
                             quarantine flag on the key), or replaced (the stored bar
                             is from a non-IBKR source, an ohlcv_revision row holds
                             the judged IBKR value, and the last 1d scrub fact
                             postdates every revision of the key, so the scrub judged
                             the new bar). Anything else is open; the evidence line
                             counts quarantined, replaced and open per key set, and
                             the replaced bars the tradeable view still hides by a
                             stale pre-381 price_sanity_status
  2 seam_audit_complete      bar_seam_audit 'seam_audit_complete' fact, and every
                             seam_audit corporate action carries split_seam
                             quarantine flags before its effective date unless a
                             later daily derivation batch re-derived the bars
  3 late_name_dispositions   every IBKR-sourced late 1d name resolves (moved /
                             verified_empty / reached_window_start); none left
                             unresolved (plan 14's classify_head, recomputed
                             from stored D1 answers). Late names with Tradier
                             history (any canonical tradier 1d bar, plan 185-48)
                             are excluded: their history before D comes from
                             Tradier, not the truncated IBKR route; the evidence
                             line counts them and names the excluded unresolved
                             ones
  4 no_pre_move_bars_visible no tradeable IBKR-source 1d bar of a moved name
                             predates its SMART head (moved names from the
                             IBKR-only ohlcv_venue_head, 185-28), unless
                             infra.bar_derivation.venue_bars_1d is true (plan 13
                             verdict: venue bars stay unused). Tradier consolidated
                             history before an IBKR venue move is real history
  5 dividend_coverage        Yahoo dividend coverage for at least 99 percent of
                             1d-eligible names and dividends.total_return imports
  (6 retired 2026-10-09: survivorship_apr_keys, the six alpha.survivorship.*
    seeds seeded by migration 382; owner: survivorship bias is not an issue,
    todo 514. Numbering is not renumbered: the gate runs six conditions,
    1-5 and 7.)
  7 inventory_is_active      D-03: no name in the moved-name inventory (the late
                             set) was soft-deleted; is_active stays true

Read-only. The 99 percent and the 72/15 known-answer counts are the D-28
contract itself (as fixed as plan 14's late cutoff), not tunables.
"""

from __future__ import annotations

import importlib
import json
import sys
from collections import Counter, defaultdict
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any, Literal

import psycopg

from scripts.ops.bars.ops_head_rerun import (
    _APR_VENUES,
    _late_names,
    _load_apr,
    _load_requests,
    classify_head,
    island_failed_unlisted,
)
from src.config.settings import Settings
from src.intelligence.bars.derivation import SOURCE_NAMED, SOURCE_VENUE
from src.intelligence.bars.sources import SOURCE_TRADIER

_REPO_ROOT = Path(__file__).resolve().parents[3]
_FIXTURE_PATH = _REPO_ROOT / "tests" / "fixtures" / "bars" / "corrupt_1d_dry_run_2026_09_26.txt"

_SCRUB_MONITOR = ("bar_scrub", "historical_pass_complete", "tf=1d")
_SEAM_MONITOR = ("bar_seam_audit", "seam_audit_complete", None)
_VENUE_BARS_KEY = "infra.bar_derivation.venue_bars_1d"
_MIN_YAHOO_COVERAGE = 0.99
# The 1d sources whose prints the known answers judged and whose pre-move bars are truncation.
IBKR_1D_SOURCES: tuple[str, ...] = (SOURCE_NAMED, SOURCE_VENUE)
# The 15 1d keys migration 381 copied into legacy_price_sanity_status flags (its source:
# market_data_ohlcv.price_sanity_status = 'confirmed_corrupt', re-read 2026-10-07). Fixed here
# because 185-30 retired 12 of those flags when Tradier replaced the bars, so the flags can no
# longer name the set. Part of the D-28 contract, not a tunable.
LEGACY_1D_KEYS: tuple[tuple[str, str], ...] = (
    ("DBC", "2007-08-17T00:00:00Z"),
    ("DIA", "2009-06-02T00:00:00Z"),
    ("EDV", "2008-09-19T00:00:00Z"),
    ("EFA", "2008-09-29T00:00:00Z"),
    ("EWG", "2007-04-23T00:00:00Z"),
    ("FXI", "2007-02-27T00:00:00Z"),
    ("FXY", "2008-09-24T00:00:00Z"),
    ("GLD", "2007-09-10T00:00:00Z"),
    ("IWM", "2007-08-08T00:00:00Z"),
    ("RSP", "2007-08-01T00:00:00Z"),
    ("SPY", "2007-04-02T00:00:00Z"),
    ("VWO", "2007-05-02T00:00:00Z"),
    ("VWO", "2007-12-28T00:00:00Z"),
    ("XRT", "2007-09-18T00:00:00Z"),
    ("XRT", "2008-09-19T00:00:00Z"),
)
_EXPECTED_LEGACY_KEYS = 15
_UNRESOLVED_SAMPLE = 10

_FACT_SQL = """
SELECT passed, evaluated_at FROM integrity_monitor
WHERE monitor_type = %s AND metric_name = %s AND subject IS NOT DISTINCT FROM %s
ORDER BY evaluated_at DESC
LIMIT 1
"""

# One row per known-answer key: any quarantine flag (EXISTS, so a bar with several rules is
# one key), the stored row's source (raw table: the tradeable view also hides a bar by the
# pre-381 price_sanity_status, which the Tradier load left on 12 replaced legacy bars, so the
# view would misread a replaced key as missing), whether an ohlcv_revision row holds an IBKR
# value for the key, the latest load that revised it (compared with the scrub fact in
# known_answer_status), and whether the stored row still carries that stale status.
_KNOWN_ANSWER_SQL = """
SELECT k.symbol, k.ts,
  EXISTS (SELECT 1 FROM bar_quality_flag b
           WHERE b.symbol = k.symbol AND b.timeframe = '1d'
             AND b."timestamp" = k.ts AND b.quarantine) AS quarantined,
  m.source AS stored_source,
  EXISTS (SELECT 1 FROM ohlcv_revision r
           WHERE r.symbol = k.symbol AND r.timeframe = '1d'
             AND r."timestamp" = k.ts AND r.old_source = ANY(%s)) AS has_ibkr_revision,
  (SELECT MAX(l.loaded_at) FROM ohlcv_revision r JOIN ohlcv_load l USING (load_id)
    WHERE r.symbol = k.symbol AND r.timeframe = '1d'
      AND r."timestamp" = k.ts) AS last_revision_at,
  COALESCE(m.price_sanity_status = 'confirmed_corrupt', false) AS stale_status
FROM unnest(%s::text[], %s::timestamptz[]) AS k(symbol, ts)
LEFT JOIN market_data_ohlcv m
  ON m.symbol = k.symbol AND m.timeframe = '1d' AND m."timestamp" = k.ts
"""

# Late names with Tradier history (plan 185-48): any canonical 1d bar sourced from Tradier.
# Stored bars, not the open policy row: since 185-47 the open 1d default names IBKR, so a
# policy predicate would exclude nobody and widen condition 3 to every name the swap made late.
_TRADIER_HISTORY_LATE_SQL = """
/* tradier_history */
SELECT s.symbol FROM unnest(%s::text[]) AS s(symbol)
WHERE EXISTS (SELECT 1 FROM market_data_ohlcv_tradeable m
              WHERE m.symbol = s.symbol AND m.timeframe = '1d' AND m.source = %s)
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
  AND m.source = ANY(%s)
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


@dataclass(frozen=True)
class CheckResult:
    """One D-28 condition's verdict plus the evidence it was decided on."""

    condition: str
    ok: bool
    evidence: str


# --- pure predicates ----------------------------------------------------------------


KnownAnswerStatus = Literal["quarantined", "replaced", "open"]


def known_answer_status(
    *,
    quarantined: bool,
    stored_source: str | None,
    has_ibkr_revision: bool,
    last_revision_at: datetime | None,
    scrub_at: datetime | None,
) -> KnownAnswerStatus:
    """One known-answer key: quarantined, replaced by a scrubbed bar of another source, or open.

    Replaced needs evidence (T-185-34-01): the bar research sees is not IBKR, an ohlcv_revision
    row keeps the judged IBKR value, and the 1d scrub fact postdates the key's last revision
    (otherwise the scrub never judged the bar now stored). A quarantine flag always wins.
    """
    if quarantined:
        return "quarantined"
    if (
        stored_source is not None
        and stored_source not in IBKR_1D_SOURCES
        and has_ibkr_revision
        and last_revision_at is not None
        and scrub_at is not None
        and last_revision_at < scrub_at
    ):
        return "replaced"
    return "open"


def scrub_condition(
    *,
    fact_passed: bool,
    fixture_total: int,
    fixture_quarantined: int,
    fixture_replaced: int,
    legacy_total: int,
    legacy_quarantined: int,
    legacy_replaced: int,
    replaced_hidden: int = 0,
) -> CheckResult:
    """Condition 1: the 1d scrub pass ran and every known answer is quarantined or replaced.

    replaced_hidden counts replaced bars the tradeable view still hides by a stale
    price_sanity_status: no defect is visible, so it does not fail the condition, but a
    clean bar research cannot see is reported, never silent."""
    fixture_open = fixture_total - fixture_quarantined - fixture_replaced
    legacy_open = legacy_total - legacy_quarantined - legacy_replaced
    ok = (
        fact_passed
        and fixture_total > 0
        and fixture_open == 0
        and legacy_total == _EXPECTED_LEGACY_KEYS
        and legacy_open == 0
    )
    return CheckResult(
        condition="scrub_pass_complete",
        ok=ok,
        evidence=(
            f"fact={fact_passed}; dry-run keys {fixture_total}: quarantined "
            f"{fixture_quarantined}, replaced {fixture_replaced}, open {fixture_open}; "
            f"legacy 1d keys {legacy_total} (expect {_EXPECTED_LEGACY_KEYS}): quarantined "
            f"{legacy_quarantined}, replaced {legacy_replaced}, open {legacy_open}; "
            f"replaced bars hidden by a stale price_sanity_status {replaced_hidden}"
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


def dispositions_condition(
    dispositions: Mapping[str, str], tradier_history: Collection[str] = ()
) -> CheckResult:
    """Condition 3: no IBKR-sourced late name is left unresolved.

    Late names with Tradier history are out of scope (185-34: orchestrator call 2026-10-06, pending
    owner review); they are counted and their unresolved names listed, never judged. Every
    unresolved IBKR-sourced name is named: the residue, not a sample."""
    owned = set(tradier_history)
    judged = {s: d for s, d in dispositions.items() if s not in owned}
    excluded = sorted(s for s in dispositions if s in owned)
    unresolved = sorted(s for s, d in judged.items() if d == "unresolved")
    excluded_unresolved = [s for s in excluded if dispositions[s] == "unresolved"]
    return CheckResult(
        condition="late_name_dispositions",
        ok=not unresolved,
        evidence=(
            f"IBKR-sourced late names {len(judged)}; unresolved {len(unresolved)}"
            + (f" ({', '.join(unresolved)})" if unresolved else "")
            + f"; Tradier-history excluded {len(excluded)}"
            + (
                f" (unresolved under IBKR answers: {', '.join(excluded_unresolved)})"
                if excluded_unresolved
                else ""
            )
        ),
    )


def premove_condition(*, n_pre_move_bars: int, venue_bars_1d: bool) -> CheckResult:
    """Condition 4: pre-move venue bars are not visible unless explicitly allowed."""
    ok = venue_bars_1d or n_pre_move_bars == 0
    return CheckResult(
        condition="no_pre_move_bars_visible",
        ok=ok,
        evidence=(
            f"IBKR-source pre-move 1d bars in tradeable view {n_pre_move_bars}; "
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


def _known_answer_counts(
    conn: Any, keys: Sequence[tuple[str, str]], scrub_at: datetime | None
) -> Counter[str]:
    """Status counts of one key set, plus `replaced_hidden` (replaced, stale status)."""
    rows = _rows(
        conn,
        _KNOWN_ANSWER_SQL,
        (list(IBKR_1D_SOURCES), [symbol for symbol, _ in keys], [ts for _, ts in keys]),
    )
    counts: Counter[str] = Counter()
    for _, _, quarantined, source, has_revision, revised_at, stale_status in rows:
        status = known_answer_status(
            quarantined=bool(quarantined),
            stored_source=source,
            has_ibkr_revision=bool(has_revision),
            last_revision_at=revised_at,
            scrub_at=scrub_at,
        )
        counts[status] += 1
        if status == "replaced" and stale_status:
            counts["replaced_hidden"] += 1
    return counts


def run_checks(conn: Any) -> list[CheckResult]:
    """Every D-28 condition, decided from stored evidence."""
    fixture_keys = parse_dry_run_keys(_FIXTURE_PATH.read_text())

    scrub_fact = _scalar(conn, _FACT_SQL, (_SCRUB_MONITOR[0], _SCRUB_MONITOR[1], _SCRUB_MONITOR[2]))
    seam_fact = _scalar(conn, _FACT_SQL, (_SEAM_MONITOR[0], _SEAM_MONITOR[1], _SEAM_MONITOR[2]))
    scrub_at = scrub_fact[1] if scrub_fact else None
    fixture = _known_answer_counts(conn, fixture_keys, scrub_at)
    legacy = _known_answer_counts(conn, LEGACY_1D_KEYS, scrub_at)

    actions = [
        (symbol, effective, recorded)
        for symbol, effective, recorded in _rows(conn, _SEAM_ACTION_SQL)
    ]
    split_seam_bars: dict[str, list[date]] = defaultdict(list)
    for symbol, flag_date in _rows(conn, _SPLIT_SEAM_SQL):
        split_seam_bars[symbol].append(flag_date)
    daily_batches = [row[0] for row in _rows(conn, _DAILY_BATCH_SQL)]

    late = _late_names(conn)
    apr = _load_apr(conn)
    venues = json.loads(apr.get(_APR_VENUES, "[]"))
    island_unlisted = island_failed_unlisted(apr)
    requests = _load_requests(conn, list(late))
    dispositions = {
        symbol: classify_head(
            requests[symbol], late[symbol], venues, island_failed_unlisted=island_unlisted
        )
        for symbol in late
    }
    tradier_history = {
        row[0] for row in _rows(conn, _TRADIER_HISTORY_LATE_SQL, (sorted(late), SOURCE_TRADIER))
    }

    pre_move = int(_scalar(conn, _PREMOVE_SQL, (list(IBKR_1D_SOURCES),))[0])
    covered, eligible, deactivated = _scalar(conn, _INVENTORY_SQL, (sorted(late),))
    venue_row = _scalar(conn, _VENUE_FLAG_SQL)
    venue_bars_1d = bool(venue_row and str(venue_row[0]).strip().lower() == "true")

    return [
        scrub_condition(
            fact_passed=bool(scrub_fact and scrub_fact[0]),
            fixture_total=len(fixture_keys),
            fixture_quarantined=fixture["quarantined"],
            fixture_replaced=fixture["replaced"],
            legacy_total=len(LEGACY_1D_KEYS),
            legacy_quarantined=legacy["quarantined"],
            legacy_replaced=legacy["replaced"],
            replaced_hidden=fixture["replaced_hidden"] + legacy["replaced_hidden"],
        ),
        seam_condition(
            fact_passed=bool(seam_fact and seam_fact[0]),
            actions=actions,
            split_seam_bars=dict(split_seam_bars),
            daily_batches=daily_batches,
        ),
        dispositions_condition(dispositions, tradier_history),
        premove_condition(n_pre_move_bars=pre_move, venue_bars_1d=venue_bars_1d),
        dividend_condition(
            covered=int(covered),
            eligible=int(eligible),
            total_return_importable=_total_return_importable(),
        ),
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
