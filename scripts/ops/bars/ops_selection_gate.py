"""The selection gate: canonical selected from raw equals canonical, row for row (phase 191 plan 07).

Design: docs/plans/2026-10-12-unified-raw-bar-table-design.md step 5 and D-191-C. Nothing reads
the new path until this gate is clean. The gate is a standing proof that canonical is a pure
function of raw plus policy; plans 12, 13 and 14 run it again against the v2 table and the swapped
table (`--target`).

Modes (exactly one):

--compare       per (symbol, timeframe): canonical vendor rows against the selection of
                `ohlcv_raw` by the SAME pure function the live writer uses
                (src/intelligence/bars/selection.py, session rule and policy spans included).
                Month digests localize; only a month whose digest differs gets a row-level diff
                (exact dict equality is the confirmation, so a digest collision cannot hide a
                difference). The report totals are zero iff the sets are identical.
--emit-spans    per series, the minimal date-contiguous ranking spans that make the selection
                equal canonical (rankings tried: the timeframe default, the default with the
                other vendor as fallback, the other vendor first, the other vendor alone), as
                candidate bar_source_policy rows. A date no ranking can reproduce is a BLOCKER
                (exit 2): no span resolves it, and the gate is never weakened to hide it.
--apply-spans   write the candidate rows of --spans files through ops_source_policy.insert_row
                (the policy table's one writer); dry run unless --apply.
--idempotence   run the live selection writer over a spread of names inside a transaction that
                is always rolled back and report rows inserted or replaced (must be 0 for names
                that already match; --exclude-report leaves the not-clean series out of the
                spread, and --symbols names the ones to probe instead).
--merge         total several shard reports into one verdict.
--locate-unsourced
                raw rows that no old store holds a key for (plan 04's balance check counted a
                dozen per window, never located): per symbol, the (timeframe, vendor, kind)
                groups whose raw row count exceeds the distinct keys of archive, canonical vendor
                rows (non-1d) and observation (1d), then the rows themselves.

Canonical read contract: `--target TABLE` (default market_data_ohlcv) is introspected once
through information_schema and must carry (vendor, kind) columns; the label-column read path
was deleted in plan 191-13 when canonical swapped `source` for the pair.

Last-wins (owner decision 2026-10-14, D-191-N): raw holds every vendor's latest answer and no
value is refused or held, so canonical must equal the selection exactly; any difference is real.
Session choices: a session taken from the fallback, held whole by no vendor, or holding fewer
slots than the calendar grid is counted (`sessions_fallback`, `sessions_incomplete`,
`sessions_partial`), and its bar_session_choice row (migration 480) must equal the selection's
choice (`session_choices_unrecorded` is residue).

Basis-change review (fourth review of 191-07, finding 2): every restatement flag with a
basis-change signature (price_ratio, volume_ratio, time_shift) that no reviewer has marked
(scripts/ops/bars/ops_restatement_review.py) is counted, whatever its series
(`unreviewed_basis_flags`, read once per run over the whole table), and is residue: a re-serve on
a new basis landed last-wins and canonical may mix bases until someone has looked.

Exit codes: 0 clean (canonical equals the selection exactly); 1 real differences or canonical
rows the gate never compared (a derived vendor row in a direct timeframe); 2 BLOCKER
(--emit-spans: a date no ranking reproduces); 3
residue (a canonical session mixing vendors, a session choice the durable record does not hold,
or an unreviewed basis-change restatement flag): not clean, nothing may resume on it.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import re
import struct
import sys
import time
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

project_root = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(project_root))

import psycopg  # noqa: E402

from services.bar_selection import DIRECT_TIMEFRAMES, select_and_write  # noqa: E402
from services.ohlcv_ingress_contract import read_unreviewed_basis  # noqa: E402
from src.config.config_service import ConfigService  # noqa: E402
from src.config.settings import get_settings  # noqa: E402
from src.intelligence.bars.selection import (  # noqa: E402
    Candidate,
    PolicyRow,
    select_slots,
    session_date,
)
from src.intelligence.bars.vendor_kind import (  # noqa: E402
    LABEL_TO_VENDOR_KIND,
    VENDOR_DERIVED,
    observation_kind,
)

_LOG_DIR = project_root / "logs"
_BATCH_ROWS_KEY = "infra.ohlcv_observation.copy_batch_rows"
_TIMEOUT_KEY = "infra.raw_backfill.statement_timeout_s"
_PLAN = "191-07"
SPAN_REASON = "reproduces canonical (selection gate, plan 191-07)"
DEFAULT_TIMEFRAMES = ("1m", "5m", "4h")
BAR_SECONDS = {"1m": 60, "5m": 300, "4h": 14400}  # bar lengths, not tunables
_FAR_PAST = datetime(1990, 1, 1, tzinfo=UTC)
_FAR_FUTURE = datetime(2100, 1, 1, tzinfo=UTC)
_MATCH_KEY = "infra.selection_gate.request_load_match_s"
_SAFE_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

# difference kinds
ONLY_CANONICAL = "only_canonical"
ONLY_SELECTED = "only_selected"
VENDOR_KIND = "vendor_kind"
VALUE = "value"
REAL = "real"
EXIT_CLEAN, EXIT_REAL, EXIT_BLOCKER, EXIT_RESIDUE = 0, 1, 2, 3

Values = tuple  # (open, high, low, close, volume)
VK = tuple[str, str]  # (vendor, kind)
Row = tuple[VK, Values]
Key = tuple[datetime, str, str]  # (timestamp, vendor, kind)


# --------------------------------------------------------------------------------------
# Pure core
# --------------------------------------------------------------------------------------


def utc_date(ts: datetime) -> date:
    """ohlcv_load.requested_start/end are the UTC dates of the load's first and last stamps."""
    return ts.astimezone(UTC).date()


def classify(canonical: Row | None, selected: Row | None) -> tuple[str, str] | None:
    """(difference kind, class) of one slot, None when the slot matches. Every difference is
    real: raw holds each vendor's latest answer (D-191-N) and canonical is its selection."""
    if canonical is None and selected is None:
        return None
    if canonical is not None and selected is not None and canonical == selected:
        return None
    if canonical is None:
        kind = ONLY_SELECTED
    elif selected is None:
        kind = ONLY_CANONICAL
    elif canonical[0] != selected[0]:
        kind = VENDOR_KIND
    else:
        kind = VALUE
    return kind, REAL


def month_key(ts: datetime) -> str:
    stamp = ts.astimezone(UTC)
    return f"{stamp.year:04d}-{stamp.month:02d}"


_ROW_STRUCT = struct.Struct("<q4dq")


def month_digests(rows: Mapping[datetime, Row]) -> dict[str, tuple[int, str]]:
    """Per UTC month: (row count, blake2b-128 hex of the rows in time order).

    The digest covers timestamp, (vendor, kind) and the five values; two maps with equal digests
    and counts in every month are identical for all practical purposes, and the gate still
    confirms a differing month row by row.
    """
    by_month: dict[str, list[datetime]] = defaultdict(list)
    for ts in rows:
        by_month[month_key(ts)].append(ts)
    out: dict[str, tuple[int, str]] = {}
    for month, stamps in by_month.items():
        h = hashlib.blake2b(digest_size=16)
        for ts in sorted(stamps):
            (vendor, kind), values = rows[ts]
            o, hi, lo, c, v = values
            h.update(f"{vendor}\x1f{kind}\x1e".encode())
            h.update(_ROW_STRUCT.pack(int(ts.timestamp()), o, hi, lo, c, -1 if v is None else v))
        out[month] = (len(stamps), h.hexdigest())
    return out


@dataclass
class SeriesDiff:
    """The row-level result for one (symbol, timeframe)."""

    symbol: str
    timeframe: str
    n_canonical: int = 0
    n_selected: int = 0
    n_months: int = 0
    n_months_digest_mismatch: int = 0
    skipped_null_volume: int = 0
    off_grid: int = 0
    unselected: int = 0
    kinds: Counter = field(default_factory=Counter)  # (kind, class) -> count
    samples: list[dict[str, Any]] = field(default_factory=list)
    unexplained_dates: Counter = field(default_factory=Counter)  # session date -> real diffs
    # canonical rows of the series whose source label is outside the vendor map (never compared)
    unmapped_canonical: int = 0
    # canonical sessions holding rows of more than one vendor (second review of 191-07,
    # finding 3): selection takes a session whole from one vendor, so any is residue
    mixed_vendor_sessions: int = 0
    # the selection's session choices (not differences): sessions taken whole from a fallback,
    # sessions no vendor held whole, and the slots the latter left out
    sessions_fallback: int = 0
    sessions_incomplete: int = 0
    session_dropped_slots: int = 0
    # sessions the chosen vendor holds only partly against the calendar's regular-hours grid
    # (third review of 191-07, finding 4): counted, a property of the data, not residue
    sessions_partial: int = 0
    # sessions whose bar_session_choice row (migration 480) disagrees with the selection's
    # choice, or is missing or stale: residue, the durable record must equal the selection
    session_choices_unrecorded: int = 0

    @property
    def n_real(self) -> int:
        return sum(n for (_, cls), n in self.kinds.items() if cls == REAL)

    def class_counts(self) -> dict[str, int]:
        out: Counter = Counter()
        for (_, cls), n in self.kinds.items():
            out[cls] += n
        return dict(out)

    def clean(self) -> bool:
        """Canonical equals the selection exactly and the session record holds."""
        return (
            not self.kinds
            and not self.unmapped_canonical
            and not self.mixed_vendor_sessions
            and not self.session_choices_unrecorded
        )


def selected_rows(
    candidates: Sequence[Candidate],
    policy_rows: Sequence[PolicyRow],
    kind_order: Mapping[str, int],
    choices_out: list[ChoiceRecord] | None = None,
) -> tuple[dict[datetime, Row], dict[str, int]]:
    """The rows the live writer would write: winners with a volume (a NULL-volume winner is
    skipped and counted, as bar_selection does), one vendor per session. `choices_out` receives
    the session choices as the rows bar_session_choice must hold."""
    outcome = select_slots(candidates, policy_rows, kind_order)
    if choices_out is not None:
        choices_out.extend(choice_record(c) for c in outcome.choices)
    rows: dict[datetime, Row] = {}
    skipped = 0
    for w in outcome.winners:
        if w.volume is None:
            skipped += 1
            continue
        rows[w.timestamp] = ((w.vendor, w.kind), (w.open, w.high, w.low, w.close, w.volume))
    return rows, {
        "skipped_null_volume": skipped,
        "off_grid": outcome.n_off_grid,
        "unselected": outcome.n_unselected,
        "sessions_fallback": sum(c.vendor != c.ranking[0] for c in outcome.choices),
        "sessions_incomplete": sum(not c.complete for c in outcome.choices),
        "session_dropped_slots": len(outcome.dropped),
        "sessions_partial": sum(c.partial for c in outcome.choices),
    }


ChoiceRecord = (
    tuple  # (session_date, vendor, complete, n_slots, n_vendor_slots, n_grid, n_vg, n_pg)
)

_CHOICES_SQL = (
    "SELECT session_date, vendor, complete, n_slots, n_vendor_slots, n_grid_slots, "
    "n_vendor_grid_slots, n_primary_grid_slots FROM bar_session_choice "
    "WHERE symbol = %s AND timeframe = %s"
)


def choice_record(c: Any) -> ChoiceRecord:
    return (
        c.session,
        c.vendor,
        c.complete,
        c.n_slots,
        c.n_vendor_slots,
        c.n_grid_slots,
        c.n_vendor_grid_slots,
        c.n_primary_grid_slots,
    )


def unrecorded_choices(expected: Iterable[ChoiceRecord], recorded: Iterable[ChoiceRecord]) -> int:
    """Sessions whose recorded choice differs from the selection's, or is missing or stale."""
    want = {r[0]: tuple(r) for r in expected}
    have = {r[0]: tuple(r) for r in recorded}
    return sum(1 for day in want.keys() | have.keys() if want.get(day) != have.get(day))


def mixed_vendor_sessions(canonical: Mapping[datetime, Row]) -> int:
    """Sessions (NYSE session dates) whose canonical rows come from more than one vendor."""
    vendors: dict[date, set[str]] = defaultdict(set)
    for ts, (vk, _values) in canonical.items():
        vendors[session_date(ts)].add(vk[0])
    return sum(1 for held in vendors.values() if len(held) > 1)


def diff_rows(
    canonical: Mapping[datetime, Row],
    selected: Mapping[datetime, Row],
    *,
    months: set[str] | None = None,
) -> Iterable[tuple[datetime, tuple[str, str]]]:
    """Every differing slot as (timestamp, (kind, class)), in time order; `months` restricts."""
    stamps = [ts for ts, row in canonical.items() if selected.get(ts) != row]
    stamps += [ts for ts in selected if ts not in canonical]
    for ts in sorted(stamps):
        if months is not None and month_key(ts) not in months:
            continue
        found = classify(canonical.get(ts), selected.get(ts))
        if found is not None:
            yield ts, found


def compare_series(
    symbol: str,
    timeframe: str,
    canonical: Mapping[datetime, Row],
    selected: Mapping[datetime, Row],
    *,
    sample_limit: int = 20,
    counts: Mapping[str, int] | None = None,
) -> SeriesDiff:
    """Compare one series; month digests first, a row-level diff only for differing months."""
    diff = SeriesDiff(symbol, timeframe, n_canonical=len(canonical), n_selected=len(selected))
    for name in (
        "skipped_null_volume",
        "off_grid",
        "unselected",
        "sessions_fallback",
        "sessions_incomplete",
        "session_dropped_slots",
        "sessions_partial",
    ):
        setattr(diff, name, (counts or {}).get(name, 0))
    diff.mixed_vendor_sessions = mixed_vendor_sessions(canonical)
    canon_digest, sel_digest = month_digests(canonical), month_digests(selected)
    months = sorted(canon_digest.keys() | sel_digest.keys())
    diff.n_months = len(months)
    bad_months = {m for m in months if canon_digest.get(m) != sel_digest.get(m)}
    diff.n_months_digest_mismatch = len(bad_months)
    if bad_months:
        for ts, found in diff_rows(canonical, selected, months=bad_months):
            diff.kinds[found] += 1
            if found[1] == REAL:
                diff.unexplained_dates[session_date(ts)] += 1
            if len(diff.samples) < sample_limit:
                c, s = canonical.get(ts), selected.get(ts)
                diff.samples.append(
                    {
                        "timestamp": ts.astimezone(UTC).isoformat(),
                        "kind": found[0],
                        "class": found[1],
                        "canonical": (
                            None if c is None else {"vk": list(c[0]), "values": list(c[1])}
                        ),
                        "selected": None if s is None else {"vk": list(s[0]), "values": list(s[1])},
                    }
                )
    return diff


Ranking = tuple[str, ...]


def ranking_options(default: Ranking, vendors: Iterable[str]) -> list[Ranking]:
    """Rankings of at most two vendors to try for a span, in preference order.

    A policy row holds a primary and one fallback, so no ranking is longer than two. Order: a
    ranking that starts with the default primary first, then the one holding more vendors (the
    default primary with the other vendor as fallback beats the default alone, so a name whose
    history one vendor fills keeps being filled), then vendor name. The other vendor first, and
    alone, come last: the least surprising ranking that reproduces canonical wins.
    """
    pool = sorted((set(vendors) - {VENDOR_DERIVED}) | set(default))
    options: set[Ranking] = {tuple(default)}
    for a in pool:
        options.add((a,))
        for b in pool:
            if a != b:
                options.add((a, b))
    return sorted(options, key=lambda r: (r[0] != default[0], -len(r), r))


@dataclass(frozen=True)
class SpanRow:
    """A candidate bar_source_policy row."""

    timeframe: str
    symbol: str
    valid_from: date
    valid_to: date | None
    primary_source: str
    fallback_source: str | None
    n_canonical: int
    first_bar: str
    last_bar: str

    def key(self) -> tuple:
        return (
            self.timeframe,
            self.symbol,
            self.valid_from,
            self.valid_to,
            self.primary_source,
            self.fallback_source,
        )

    def to_json(self) -> dict[str, Any]:
        return {
            "timeframe": self.timeframe,
            "symbol": self.symbol,
            "valid_from": self.valid_from.isoformat(),
            "valid_to": self.valid_to.isoformat() if self.valid_to else None,
            "primary_source": self.primary_source,
            "fallback_source": self.fallback_source,
            "reason": SPAN_REASON,
            "evidence": {
                "plan": _PLAN,
                "rule": "reproduces_canonical",
                "canonical_rows": self.n_canonical,
                "first_bar": self.first_bar,
                "last_bar": self.last_bar,
            },
        }

    @staticmethod
    def from_json(row: Mapping[str, Any]) -> SpanRow:
        ev = row["evidence"]
        return SpanRow(
            row["timeframe"],
            row["symbol"],
            date.fromisoformat(row["valid_from"]),
            date.fromisoformat(row["valid_to"]) if row["valid_to"] else None,
            row["primary_source"],
            row["fallback_source"],
            ev["canonical_rows"],
            ev["first_bar"],
            ev["last_bar"],
        )


@dataclass
class SpanPlan:
    symbol: str
    timeframe: str
    spans: list[SpanRow]
    blocker_dates: list[date]
    ranking_by_date: dict[date, Ranking]


def derive_spans(
    symbol: str,
    timeframe: str,
    canonical: Mapping[datetime, Row],
    candidates: Sequence[Candidate],
    kind_order: Mapping[str, int],
    default: Ranking,
) -> SpanPlan:
    """The fewest date-contiguous ranking runs under which selection reproduces canonical.

    Every ranking option is tried as a constant policy over all history. A session date takes the
    options that reproduce canonical exactly there. A run keeps its
    ranking while it stays feasible and, when it must change, takes the option feasible longest
    (ties by preference order). A date no option reproduces is a blocker date. Runs equal to the
    default ranking need no row; the last non-default run is open-ended, the rule going forward.
    """
    vendors = {c.vendor for c in candidates} | {vk[0] for vk, _ in canonical.values()}
    options = ranking_options(default, vendors)
    dates = sorted(
        {session_date(ts) for ts in canonical} | {session_date(c.timestamp) for c in candidates}
    )
    real: dict[Ranking, set[date]] = {}
    for option in options:
        policy = [
            PolicyRow(
                timeframe,
                None,
                date(1, 1, 1),
                None,
                option[0],
                option[1] if len(option) > 1 else None,
            )
        ]
        selected, _ = selected_rows(candidates, policy, kind_order)
        real[option] = set()
        for ts, _found in diff_rows(canonical, selected):
            real[option].add(session_date(ts))
    # Feasible options of a date: those reproducing canonical exactly there.
    feasible_at: list[set[Ranking]] = [{o for o in options if day not in real[o]} for day in dates]
    # next_bad[option][i] = first index >= i of a date the option cannot take (len(dates) if none)
    next_bad: dict[Ranking, list[int]] = {}
    for option in options:
        marks = [len(dates)] * (len(dates) + 1)
        for i in range(len(dates) - 1, -1, -1):
            marks[i] = marks[i + 1] if option in feasible_at[i] else i
        next_bad[option] = marks
    ranking_by_date: dict[date, Ranking] = {}
    blockers: list[date] = []
    runs: list[tuple[int, Ranking]] = []  # (start index, ranking)
    current: Ranking | None = None
    i = 0
    while i < len(dates):
        if current is not None and current in feasible_at[i]:
            ranking_by_date[dates[i]] = current
            i += 1
            continue
        feasible = [o for o in options if o in feasible_at[i]]
        if not feasible:
            blockers.append(dates[i])
            if current is not None:
                ranking_by_date[dates[i]] = current
            i += 1
            continue
        best = max(feasible, key=lambda o: (next_bad[o][i], -options.index(o)))
        current = best
        runs.append((i, best))
        ranking_by_date[dates[i]] = best
        i += 1
    # Run starts as dates. The first run covers any leading dates before its first feasible date.
    starts = [
        (dates[0] if n == 0 else dates[start], ranking) for n, (start, ranking) in enumerate(runs)
    ]
    # Going forward the rule is the preferred ranking (the default primary, the other vendor as
    # fallback), never a ranking narrowed by what history needed: the day after the last date with
    # data starts a tail run when the last run is anything else.
    if starts and dates and starts[-1][1] != options[0]:
        starts.append((dates[-1] + timedelta(days=1), options[0]))
    spans: list[SpanRow] = []
    stamps = sorted(canonical)
    for n, (valid_from, ranking) in enumerate(starts):
        if ranking == tuple(default):
            continue
        end = starts[n + 1][0] if n + 1 < len(starts) else None
        # evidence of THIS span: the canonical rows whose session date it covers
        inside = [
            ts
            for ts in stamps
            if valid_from <= session_date(ts) and (end is None or session_date(ts) < end)
        ]
        spans.append(
            SpanRow(
                timeframe,
                symbol,
                valid_from,
                end,
                ranking[0],
                ranking[1] if len(ranking) > 1 else None,
                len(inside),
                inside[0].astimezone(UTC).isoformat() if inside else "",
                inside[-1].astimezone(UTC).isoformat() if inside else "",
            )
        )
    return SpanPlan(symbol, timeframe, spans, blockers, ranking_by_date)


_SUMMED_KEYS = (
    "series",
    "series_clean",
    "series_with_real_differences",
    "n_canonical",
    "n_selected",
    "n_months",
    "n_months_digest_mismatch",
    "real_differences",
    "skipped_null_volume",
    "off_grid_candidates",
    "unselected_slots",
    "unmapped_canonical_rows",
    "mixed_vendor_sessions",
    "sessions_fallback",
    "sessions_incomplete",
    "session_dropped_slots",
    "sessions_partial",
    "session_choices_unrecorded",
)


def check_shards(metas: Sequence[Mapping[str, Any]]) -> None:
    """SystemExit unless the reports are one unsharded run or every shard K/N of one N once,
    all over the same target and timeframes."""
    shards = [m.get("shard") for m in metas]
    if any(s is None for s in shards):
        if len(metas) != 1:
            raise SystemExit("merge: an unsharded report cannot be merged with others")
        return
    parsed = [tuple(int(x) for x in str(s).split("/")) for s in shards]
    counts = {n for _, n in parsed}
    if len(counts) != 1:
        raise SystemExit(f"merge: shards of different N: {sorted(shards)}")
    (n,) = counts
    indexes = sorted(k for k, _ in parsed)
    if indexes != list(range(n)):
        raise SystemExit(f"merge: need shards 0..{n - 1} once each, got {sorted(shards)}")
    for field_name in ("target", "timeframes", "with_spans"):
        if len({json.dumps(m.get(field_name), sort_keys=True) for m in metas}) != 1:
            raise SystemExit(f"merge: shards disagree on {field_name}")


def merge_reports(reports: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Total several shard compare reports (same keys as `build_report`). The shard set must be
    complete and disjoint (check_shards) and a series may appear in one shard only."""
    check_shards([rep.get("meta", {}) for rep in reports])
    total: dict[str, Any] = dict.fromkeys(_SUMMED_KEYS, 0)
    total["by_timeframe"] = {}
    series_list: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for rep in reports:
        for key in _SUMMED_KEYS:
            total[key] += rep["totals"].get(key, 0)
        for tf, sub in rep["totals"]["by_timeframe"].items():
            cur = total["by_timeframe"].setdefault(
                tf, {"series": 0, "n_canonical": 0, "n_selected": 0, "real_differences": 0}
            )
            for k in cur:
                cur[k] += sub[k]
        for entry in rep["series_not_clean"]:
            series = (entry["symbol"], entry["timeframe"])
            if series in seen:
                raise SystemExit(f"merge: series {series} appears in more than one report")
            seen.add(series)
            series_list.append(entry)
    # read over the whole table by every shard: the same count, never summed
    total["unreviewed_basis_flags"] = max(
        (rep["totals"].get("unreviewed_basis_flags", 0) for rep in reports), default=0
    )
    return {
        "meta": {"merged": [rep.get("meta", {}) for rep in reports]},
        "totals": total,
        "series_not_clean": series_list,
    }


def verdict(totals: Mapping[str, Any]) -> int:
    """EXIT_CLEAN only when canonical equals the selection exactly and no basis-change flag
    waits for review. Real differences or an unmapped canonical label are EXIT_REAL; a canonical
    session spliced from two vendors, a session choice the durable record does not hold or an
    unreviewed basis-change restatement flag is EXIT_RESIDUE."""
    if totals["real_differences"] or totals.get("unmapped_canonical_rows", 0):
        return EXIT_REAL
    if (
        totals.get("mixed_vendor_sessions", 0)
        or totals.get("session_choices_unrecorded", 0)
        or totals.get("unreviewed_basis_flags", 0)
    ):
        return EXIT_RESIDUE
    return EXIT_CLEAN


def count_unreviewed_basis(cur: Any) -> list[dict[str, Any]]:
    """Every unreviewed basis-change restatement flag (the whole table, not only the series this
    run compares), as report entries."""
    return [
        {
            "load_id": str(row[0]),
            "series": f"{row[1]} {row[2]} {row[3]}/{row[4]}",
            "signatures": list(row[8]),
            "detail": row[9],
        }
        for row in read_unreviewed_basis(cur)
    ]


# --------------------------------------------------------------------------------------
# Database edges
# --------------------------------------------------------------------------------------

_RAW_SQL = (
    'SELECT "timestamp", symbol, timeframe, vendor, kind, open, high, low, close, volume '
    "FROM ohlcv_raw WHERE symbol = %s AND timeframe = %s"
)
_POLICY_SQL = (
    "SELECT timeframe, symbol, valid_from, valid_to, primary_source, fallback_source "
    "FROM bar_source_policy"
)
_KIND_ORDER_SQL = "SELECT code, sort_order FROM controlled_vocabulary WHERE namespace = 'bar_kind'"
_UNMAPPED_SQL = (
    "SELECT count(*) FROM {target} WHERE symbol = %s AND timeframe = %s AND vendor = 'derived'"
)


def vendor_labels() -> dict[str, VK]:
    """Source labels that name a vendor row (derived labels are not vendor rows). The archive
    still carries its labels; canonical carries (vendor, kind) since plan 191-13."""
    return {
        label: pair for label, pair in LABEL_TO_VENDOR_KIND.items() if pair[0] != VENDOR_DERIVED
    }


def introspect_target(cur: Any, target: str) -> None:
    """The target must carry (vendor, kind) columns; anything else is refused before a read."""
    if not _SAFE_IDENT.match(target):
        raise SystemExit(f"refusing target {target!r}: not a plain table name")
    cur.execute(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_schema = 'public' AND table_name = %s",
        (target,),
    )
    columns = {r[0] for r in cur.fetchall()}
    if "vendor" not in columns or "kind" not in columns:
        raise SystemExit(f"target {target!r} has no (vendor, kind) columns")


def read_canonical(cur: Any, target: str, symbol: str, timeframe: str) -> dict[datetime, Row]:
    cur.execute(
        f'SELECT "timestamp", vendor, kind, open, high, low, close, volume FROM {target} '
        "WHERE symbol = %s AND timeframe = %s AND vendor <> %s",
        (symbol, timeframe, VENDOR_DERIVED),
    )
    return {r[0]: ((r[1], r[2]), tuple(r[3:8])) for r in cur.fetchall()}


def count_unmapped(cur: Any, target: str, symbol: str, timeframe: str) -> int:
    """Canonical rows the gate never compares, counted so they fail the verdict instead of
    vanishing: (vendor, kind) are NOT NULL columns, so the old NULL/unmapped-label residue is
    structurally gone and what remains is a derived vendor row in a direct timeframe (1m, 5m,
    4h: selection's, never the derivation's). A derived timeframe is the derivation's own
    ground and is not counted."""
    if timeframe not in DIRECT_TIMEFRAMES:
        return 0
    cur.execute(_UNMAPPED_SQL.format(target=target), (symbol, timeframe))
    return int(cur.fetchone()[0])


def read_candidates(cur: Any, symbol: str, timeframe: str) -> list[Candidate]:
    cur.execute(_RAW_SQL, (symbol, timeframe))
    return [Candidate(*row) for row in cur.fetchall()]


def read_policy(cur: Any) -> list[PolicyRow]:
    cur.execute(_POLICY_SQL)
    return [PolicyRow(*row) for row in cur.fetchall()]


def read_kind_order(cur: Any) -> dict[str, int]:
    cur.execute(_KIND_ORDER_SQL)
    return {code: order for code, order in cur.fetchall()}


def default_ranking(policy_rows: Sequence[PolicyRow], timeframe: str) -> Ranking:
    """The open timeframe default's ranking (the row with no symbol and no valid_to)."""
    rows = [
        p
        for p in policy_rows
        if p.timeframe == timeframe and p.symbol is None and p.valid_to is None
    ]
    if len(rows) != 1:
        raise SystemExit(f"{len(rows)} open default policy rows for {timeframe}; expected 1")
    row = rows[0]
    return (row.primary_source,) + ((row.fallback_source,) if row.fallback_source else ())


def series_symbols(cur: Any, requested: Sequence[str] | None) -> list[str]:
    cur.execute("SELECT symbol FROM instruments ORDER BY symbol")
    known = [r[0] for r in cur.fetchall()]
    if not requested:
        return known
    missing = sorted(set(requested) - set(known))
    if missing:
        raise SystemExit(f"unknown symbols: {missing}")
    return sorted(requested)


def shard_of(symbols: Sequence[str], shard: str | None) -> list[str]:
    if not shard:
        return list(symbols)
    index, count = (int(x) for x in shard.split("/"))
    if not 0 <= index < count:
        raise SystemExit(f"--shard {shard}: need 0 <= K < N")
    return [s for i, s in enumerate(sorted(symbols)) if i % count == index]


async def _read_apr() -> tuple[int, int, float]:
    """(batch rows, statement timeout s, request-to-load match tolerance s) from the APR."""
    cfg = ConfigService(get_settings().database_url)
    await cfg.initialize()
    try:
        batch_rows = int(await cfg.get(_BATCH_ROWS_KEY, 50_000))
        timeout_s = int(await cfg.get(_TIMEOUT_KEY, 7200))
        match_s = float(await cfg.get(_MATCH_KEY, 5))
    finally:
        await cfg.close()
    return batch_rows, timeout_s, match_s


def open_connection(timeout_s: int) -> psycopg.Connection:
    conn = psycopg.connect(get_settings().database_url)
    with conn.cursor() as cur:
        cur.execute(f"SET statement_timeout = {int(timeout_s) * 1000}")
    conn.commit()
    return conn


# --------------------------------------------------------------------------------------
# Modes
# --------------------------------------------------------------------------------------


def build_report(diffs: Sequence[SeriesDiff], meta: Mapping[str, Any]) -> dict[str, Any]:
    totals: dict[str, Any] = {
        "series": len(diffs),
        "series_clean": sum(1 for d in diffs if d.clean()),
        "series_with_real_differences": sum(1 for d in diffs if d.n_real),
        "n_canonical": sum(d.n_canonical for d in diffs),
        "n_selected": sum(d.n_selected for d in diffs),
        "n_months": sum(d.n_months for d in diffs),
        "n_months_digest_mismatch": sum(d.n_months_digest_mismatch for d in diffs),
        "real_differences": sum(d.n_real for d in diffs),
        "skipped_null_volume": sum(d.skipped_null_volume for d in diffs),
        "off_grid_candidates": sum(d.off_grid for d in diffs),
        "unselected_slots": sum(d.unselected for d in diffs),
        "unmapped_canonical_rows": sum(d.unmapped_canonical for d in diffs),
        "mixed_vendor_sessions": sum(d.mixed_vendor_sessions for d in diffs),
        "sessions_fallback": sum(d.sessions_fallback for d in diffs),
        "sessions_incomplete": sum(d.sessions_incomplete for d in diffs),
        "session_dropped_slots": sum(d.session_dropped_slots for d in diffs),
        "sessions_partial": sum(d.sessions_partial for d in diffs),
        "session_choices_unrecorded": sum(d.session_choices_unrecorded for d in diffs),
        "by_timeframe": {},
    }
    for d in diffs:
        sub = totals["by_timeframe"].setdefault(
            d.timeframe, {"series": 0, "n_canonical": 0, "n_selected": 0, "real_differences": 0}
        )
        sub["series"] += 1
        sub["n_canonical"] += d.n_canonical
        sub["n_selected"] += d.n_selected
        sub["real_differences"] += d.n_real
    not_clean = [
        {
            "symbol": d.symbol,
            "timeframe": d.timeframe,
            "n_canonical": d.n_canonical,
            "n_selected": d.n_selected,
            "counts": {f"{kind}/{cls}": n for (kind, cls), n in sorted(d.kinds.items())},
            "unmapped_canonical": d.unmapped_canonical,
            "mixed_vendor_sessions": d.mixed_vendor_sessions,
            "session_choices_unrecorded": d.session_choices_unrecorded,
            "unselected": d.unselected,
            "samples": d.samples,
        }
        for d in diffs
        if not d.clean()
    ]
    return {"meta": dict(meta), "totals": totals, "series_not_clean": not_clean}


def _stamp() -> str:
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")


def _out_path(args: argparse.Namespace, prefix: str) -> Path:
    if args.out:
        return Path(args.out)
    suffix = f"_shard{args.shard.replace('/', 'of')}" if args.shard else ""
    return _LOG_DIR / f"{prefix}_{_stamp()}{suffix}.json"


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str))


def candidate_policy(paths: Sequence[str]) -> list[PolicyRow]:
    """Policy rows of --emit-spans files, to test a plan before it is written."""
    rows: list[PolicyRow] = []
    for path in paths:
        for row in json.loads(Path(path).read_text())["spans"]:
            span = SpanRow.from_json(row)
            rows.append(
                PolicyRow(
                    span.timeframe,
                    span.symbol,
                    span.valid_from,
                    span.valid_to,
                    span.primary_source,
                    span.fallback_source,
                )
            )
    return rows


def run_compare(conn: psycopg.Connection, args: argparse.Namespace) -> tuple[dict[str, Any], int]:
    diffs: list[SeriesDiff] = []
    with conn.cursor() as cur:
        introspect_target(cur, args.target)
        policy = read_policy(cur) + candidate_policy(args.with_spans)
        kind_order = read_kind_order(cur)
        symbols = shard_of(series_symbols(cur, args.symbols), args.shard)
    conn.rollback()
    t0 = time.monotonic()
    out = _out_path(args, "selection_gate")
    meta = {
        "mode": "compare",
        "target": args.target,
        "timeframes": list(args.timeframes),
        "shard": args.shard,
        "with_spans": list(args.with_spans),
        "n_symbols": len(symbols),
        "started": _stamp(),
    }
    for n, symbol in enumerate(symbols, 1):
        for timeframe in args.timeframes:
            with conn.cursor() as cur:
                canonical = read_canonical(cur, args.target, symbol, timeframe)
                unmapped = count_unmapped(cur, args.target, symbol, timeframe)
                candidates = read_candidates(cur, symbol, timeframe)
                if not canonical and not candidates and not unmapped:
                    continue
                cur.execute(_CHOICES_SQL, (symbol, timeframe))
                recorded = [tuple(r) for r in cur.fetchall()]
            conn.rollback()
            expected: list[ChoiceRecord] = []
            selected, counts = selected_rows(candidates, policy, kind_order, choices_out=expected)
            diff = compare_series(
                symbol,
                timeframe,
                canonical,
                selected,
                sample_limit=args.sample_limit,
                counts=counts,
            )
            diff.unmapped_canonical = unmapped
            diff.session_choices_unrecorded = unrecorded_choices(expected, recorded)
            diffs.append(diff)
        if n % 25 == 0 or n == len(symbols):
            print(
                f"[{datetime.now(UTC):%H:%M:%S}] compare {n}/{len(symbols)} ({symbol}) "
                f"elapsed={time.monotonic() - t0:.0f}s real={sum(d.n_real for d in diffs)}",
                flush=True,
            )
    report = build_report(diffs, {**meta, "finished": _stamp()})
    with conn.cursor() as cur:
        flags = count_unreviewed_basis(cur)
    conn.rollback()
    report["totals"]["unreviewed_basis_flags"] = len(flags)
    report["unreviewed_basis_flags"] = flags
    _write_json(out, report)
    print(json.dumps(report["totals"], indent=2, sort_keys=True))
    print(f"report: {out}")
    return report, verdict(report["totals"])


def run_emit_spans(conn: psycopg.Connection, args: argparse.Namespace) -> int:
    with conn.cursor() as cur:
        introspect_target(cur, args.target)
        policy = read_policy(cur)
        kind_order = read_kind_order(cur)
        symbols = shard_of(series_symbols(cur, args.symbols), args.shard)
    conn.rollback()
    existing: dict[tuple[str, str], list[PolicyRow]] = defaultdict(list)
    for p in policy:
        if p.symbol is not None:
            existing[(p.timeframe, p.symbol)].append(p)
    rows: list[dict[str, Any]] = []
    blockers: list[dict[str, Any]] = []
    conflicts: list[dict[str, Any]] = []
    n_present = 0
    t0 = time.monotonic()
    for n, symbol in enumerate(symbols, 1):
        for timeframe in args.timeframes:
            with conn.cursor() as cur:
                canonical = read_canonical(cur, args.target, symbol, timeframe)
                candidates = read_candidates(cur, symbol, timeframe)
                if not canonical and not candidates:
                    continue
            conn.rollback()
            plan = derive_spans(
                symbol,
                timeframe,
                canonical,
                candidates,
                kind_order,
                default_ranking(policy, timeframe),
            )
            if plan.blocker_dates:
                blockers.append(
                    {
                        "symbol": symbol,
                        "timeframe": timeframe,
                        "dates": [d.isoformat() for d in plan.blocker_dates[:50]],
                        "n_dates": len(plan.blocker_dates),
                    }
                )
            have = {
                (p.valid_from, p.valid_to, p.primary_source, p.fallback_source)
                for p in existing.get((timeframe, symbol), ())
            }
            for span in plan.spans:
                if (
                    span.valid_from,
                    span.valid_to,
                    span.primary_source,
                    span.fallback_source,
                ) in have:
                    n_present += 1
                    continue
                if any(
                    _overlaps(span.valid_from, span.valid_to, p.valid_from, p.valid_to)
                    for p in existing.get((timeframe, symbol), ())
                ):
                    conflicts.append(span.to_json())
                    continue
                rows.append(span.to_json())
        if n % 25 == 0 or n == len(symbols):
            print(
                f"[{datetime.now(UTC):%H:%M:%S}] emit {n}/{len(symbols)} ({symbol}) "
                f"elapsed={time.monotonic() - t0:.0f}s spans={len(rows)} blockers={len(blockers)}",
                flush=True,
            )
    per_series = Counter((r["timeframe"], r["symbol"]) for r in rows)
    payload = {
        "meta": {
            "mode": "emit-spans",
            "target": args.target,
            "timeframes": list(args.timeframes),
            "shard": args.shard,
            "generated": _stamp(),
        },
        "spans": rows,
        "already_present": n_present,
        "conflicts_with_existing_rows": conflicts,
        "blockers": blockers,
        "summary": {
            "candidate_rows": len(rows),
            "series_with_candidates": len(per_series),
            "series_with_more_than_three": sorted(
                f"{tf}:{sym}" for (tf, sym), n in per_series.items() if n > 3
            ),
            "by_ranking": dict(
                Counter(f"{r['primary_source']}>{r['fallback_source']}" for r in rows)
            ),
        },
    }
    out = _out_path(args, "selection_gate_spans")
    _write_json(out, payload)
    print(json.dumps(payload["summary"], indent=2, sort_keys=True))
    print(f"already present {n_present}, conflicts {len(conflicts)}, blockers {len(blockers)}")
    print(f"spans: {out}")
    return 2 if blockers or conflicts else 0


def _overlaps(a_from: date, a_to: date | None, b_from: date, b_to: date | None) -> bool:
    far = date.max
    return a_from < (b_to or far) and b_from < (a_to or far)


def run_apply_spans(args: argparse.Namespace) -> int:
    from scripts.ops.bars import ops_source_policy as policy_writer

    rows: list[dict[str, Any]] = []
    for path in args.spans:
        payload = json.loads(Path(path).read_text())
        if payload.get("blockers"):
            print(f"{path}: carries blockers; refusing to apply a plan with an unresolved date")
            return 2
        rows.extend(payload["spans"])
    print(f"{len(rows)} candidate rows from {len(args.spans)} file(s)")
    if not args.apply:
        for row in rows[:10]:
            print(
                f"dry run: would insert {row['timeframe']} {row['symbol']} {row['valid_from']}..{row['valid_to']} "
                f"{row['primary_source']}>{row['fallback_source']}"
            )
        print("dry run: nothing written (use --apply)")
        return 0
    return asyncio.run(_apply_rows(rows, policy_writer))


async def _apply_rows(rows: Sequence[Mapping[str, Any]], policy_writer: Any) -> int:
    import asyncpg

    settings = get_settings()
    conn = await asyncpg.connect(
        settings.database_url.replace("postgresql+asyncpg://", "postgresql://")
    )
    written = refused = 0
    try:
        codes = await policy_writer.read_vendor_codes(conn)
        for row in rows:
            policy_writer.check_vendors(codes, row["primary_source"], row["fallback_source"])
        for row in rows:
            record = {
                "timeframe": row["timeframe"],
                "symbol": row["symbol"],
                "valid_from": date.fromisoformat(row["valid_from"]),
                "valid_to": date.fromisoformat(row["valid_to"]) if row["valid_to"] else None,
                "primary_source": row["primary_source"],
                "fallback_source": row["fallback_source"],
                "reason": row["reason"],
                "evidence": row["evidence"],
            }
            if await policy_writer.insert_row(conn, record):
                written += 1
            else:
                refused += 1
                print(
                    f"refused (overlaps an existing row): {row['timeframe']} {row['symbol']} {row['valid_from']}"
                )
    finally:
        await conn.close()
    print(f"written {written}; refused {refused}")
    return 2 if refused else 0


def spread_names(by_vendor: Mapping[str, Sequence[str]], n: int) -> list[str]:
    """`n` names spread over the vendor groups: an equal share of each (the first groups take
    the remainder), evenly spaced through the group's sorted names."""
    groups = [sorted(v) for _, v in sorted(by_vendor.items()) if v]
    if not groups:
        return []
    base, extra = divmod(n, len(groups))
    picked: list[str] = []
    for i, group in enumerate(groups):
        take = min(len(group), base + (1 if i < extra else 0))
        picked += [group[(j * len(group)) // take] for j in range(take)]
    return picked


def run_idempotence(conn: psycopg.Connection, args: argparse.Namespace, batch_rows: int) -> int:
    """Run the live writer over a spread of names in a transaction that is always rolled back."""
    with conn.cursor() as cur:
        policy = read_policy(cur)
        kind_order = read_kind_order(cur)
        timeframe = args.idempotence_timeframe
        if args.symbols:
            names = list(args.symbols)
        else:
            cur.execute(
                "SELECT symbol, vendor, count(*) FROM market_data_ohlcv "
                "WHERE timeframe = %s GROUP BY symbol, vendor",
                (timeframe,),
            )
            dominant: dict[str, tuple[str, int]] = {}
            for symbol, vendor, n in cur.fetchall():
                if symbol not in dominant or n > dominant[symbol][1]:
                    dominant[symbol] = (vendor, n)
            excluded = {
                entry["symbol"]
                for path in args.exclude_report
                for entry in json.loads(Path(path).read_text())["series_not_clean"]
            }
            by_vendor: dict[str, list[str]] = defaultdict(list)
            for symbol, (vendor, _) in dominant.items():
                if symbol not in excluded:
                    by_vendor[vendor].append(symbol)
            names = spread_names(by_vendor, args.idempotence_names)
    conn.rollback()
    print(f"idempotence over {len(names)} names ({timeframe}): {', '.join(names)}")
    far_past = datetime(1990, 1, 1, tzinfo=UTC)
    far_future = datetime(2100, 1, 1, tzinfo=UTC)
    inserted = replaced = unchanged = unselected = 0
    try:
        for symbol in names:
            result = select_and_write(
                conn,
                symbols=[symbol],
                timeframe=timeframe,
                start=far_past,
                end=far_future,
                policy_rows=policy,
                kind_order=kind_order,
                batch_rows=batch_rows,
            )
            inserted += result.new
            replaced += result.changed
            unchanged += result.unchanged
            unselected += result.unselected
            print(
                f"{symbol}: new {result.new} changed {result.changed} unchanged "
                f"{result.unchanged} unselected {result.unselected}",
                flush=True,
            )
    finally:
        conn.rollback()  # the writer ran inside this transaction; nothing is ever committed here
    report = {
        "mode": "idempotence",
        "names": names,
        "timeframe": timeframe,
        "inserted": inserted,
        "replaced": replaced,
        "unchanged": unchanged,
        "unselected": unselected,
    }
    out = _out_path(args, "selection_gate_idempotence")
    _write_json(out, report)
    print(
        f"inserted {inserted}, replaced {replaced}, unchanged {unchanged}, unselected {unselected}"
    )
    print(f"report: {out}")
    return 0 if inserted == 0 and replaced == 0 else 1


def locate_groups(cur: Any, symbol: str) -> list[tuple[str, str, str, int, int]]:
    """(timeframe, vendor, kind, raw rows, distinct store keys) for each group where raw has
    more rows than the stores have keys; the stores are those plan 04's balance check reads
    (archive and canonical vendor rows for the intraday timeframes, observation for 1d). The
    counting runs in the database; only group counts come back."""
    labels = {
        label: pair
        for label, pair in vendor_labels().items()
        if pair[1] not in ("fallback",)  # canonical-only kind, never raw
    }
    cur.execute(
        "SELECT timeframe, vendor, kind, count(*) FROM ohlcv_raw WHERE symbol = %s GROUP BY 1, 2, 3",
        (symbol,),
    )
    raw = {(tf, v, k): n for tf, v, k, n in cur.fetchall()}
    keys: Counter = Counter()
    # the UNION mixes the archive's label column with canonical 'vendor/kind' idents; the
    # canonical side excludes derived and fallback rows in the SQL itself
    cur.execute(
        "SELECT timeframe, source, count(*) FROM ("
        '  SELECT timeframe, source, "timestamp" FROM ohlcv_intraday_raw_archive WHERE symbol = %s '
        "  UNION "
        "  SELECT timeframe, vendor || '/' || kind, \"timestamp\" FROM market_data_ohlcv "
        "   WHERE symbol = %s AND timeframe <> '1d' AND vendor <> %s AND kind <> 'fallback'"
        ") u GROUP BY 1, 2",
        (symbol, symbol, VENDOR_DERIVED),
    )
    for tf, ident, n in cur.fetchall():
        pair = labels.get(ident)
        if pair is None:
            vendor, sep, kind = ident.partition("/")
            if not sep:
                continue  # an archive label outside the vendor map cannot be counted
            pair = (vendor, kind)
        keys[(tf, *pair)] += n
    cur.execute(
        "SELECT o.source, o.route, o.what_to_show, o.bar_date FROM ohlcv_observation o "
        "JOIN ohlcv_request r USING (request_id) "
        "WHERE o.symbol = %s AND r.caller NOT LIKE 'test-%%' GROUP BY 1, 2, 3, 4",
        (symbol,),
    )
    by_kind: dict[tuple[str, str], set[date]] = defaultdict(set)
    for source, route, wts, day in cur.fetchall():
        try:
            kind = observation_kind(source, route, wts)
        except ValueError:
            continue
        by_kind[(source, kind)].add(day)
    for (vendor, kind), days in by_kind.items():
        keys[("1d", vendor, kind)] += len(days)
    return [
        (tf, v, k, n, keys.get((tf, v, k), 0))
        for (tf, v, k), n in sorted(raw.items())
        if n > keys.get((tf, v, k), 0)
    ]


def run_locate_unsourced(conn: psycopg.Connection, args: argparse.Namespace) -> int:
    with conn.cursor() as cur:
        symbols = shard_of(series_symbols(cur, args.symbols), args.shard)
    conn.rollback()
    found: list[dict[str, Any]] = []
    t0 = time.monotonic()
    for n, symbol in enumerate(symbols, 1):
        with conn.cursor() as cur:
            groups = locate_groups(cur, symbol)
        conn.rollback()
        for tf, vendor, kind, n_raw, n_keys in groups:
            found.append(
                {
                    "symbol": symbol,
                    "timeframe": tf,
                    "vendor": vendor,
                    "kind": kind,
                    "raw_rows": n_raw,
                    "store_keys": n_keys,
                    "excess": n_raw - n_keys,
                }
            )
        if n % 50 == 0 or n == len(symbols):
            print(
                f"[{datetime.now(UTC):%H:%M:%S}] locate {n}/{len(symbols)} ({symbol}) "
                f"elapsed={time.monotonic() - t0:.0f}s groups={len(found)}",
                flush=True,
            )
    out = _out_path(args, "selection_gate_unsourced")
    _write_json(out, {"meta": {"mode": "locate-unsourced", "shard": args.shard}, "groups": found})
    print(json.dumps(found, indent=2, default=str))
    print(f"report: {out}")
    return 1 if found else 0


def run_merge(args: argparse.Namespace) -> int:
    reports = [json.loads(Path(p).read_text()) for p in args.files]
    merged = merge_reports(reports)
    out = _out_path(args, "selection_gate_merged")
    _write_json(out, merged)
    print(json.dumps(merged["totals"], indent=2, sort_keys=True))
    print(f"merged report: {out}")
    return verdict(merged["totals"])


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--compare", action="store_true")
    mode.add_argument("--emit-spans", action="store_true")
    mode.add_argument("--apply-spans", action="store_true")
    mode.add_argument("--idempotence", action="store_true")
    mode.add_argument("--locate-unsourced", action="store_true")
    mode.add_argument("--merge", nargs="+", dest="files", metavar="REPORT")
    parser.add_argument("--timeframes", nargs="+", default=list(DEFAULT_TIMEFRAMES))
    parser.add_argument("--target", default="market_data_ohlcv")
    parser.add_argument("--symbols", nargs="*", default=None)
    parser.add_argument(
        "--shard", default=None, help="K/N: symbol i of the sorted list when i %% N == K"
    )
    parser.add_argument("--out", default=None)
    parser.add_argument("--spans", nargs="*", default=[], help="--apply-spans: emit-spans files")
    parser.add_argument(
        "--with-spans",
        nargs="*",
        default=[],
        help="--compare: add the rows of these emit-spans files to the policy (a plan is tested before it is written)",
    )
    parser.add_argument(
        "--apply", action="store_true", help="--apply-spans: write (default dry run)"
    )
    parser.add_argument("--sample-limit", type=int, default=20)
    parser.add_argument("--idempotence-names", type=int, default=25)
    parser.add_argument(
        "--exclude-report",
        nargs="*",
        default=[],
        help="--idempotence: compare reports whose not-clean series are left out of the name spread "
        "(the claim is about names that already match)",
    )
    parser.add_argument("--idempotence-timeframe", default="5m", choices=sorted(DIRECT_TIMEFRAMES))
    args = parser.parse_args(argv)
    bad = sorted(set(args.timeframes) - DIRECT_TIMEFRAMES)
    if bad:
        parser.error(
            f"timeframes {bad}: the gate covers the direct timeframes {sorted(DIRECT_TIMEFRAMES)}"
        )
    if args.files:
        return run_merge(args)
    if args.apply_spans:
        if not args.spans:
            parser.error("--apply-spans needs --spans FILE...")
        return run_apply_spans(args)
    batch_rows, timeout_s, args.match_s = asyncio.run(_read_apr())
    conn = open_connection(timeout_s)
    try:
        if args.compare:
            return run_compare(conn, args)[1]
        if args.emit_spans:
            return run_emit_spans(conn, args)
        if args.locate_unsourced:
            return run_locate_unsourced(conn, args)
        return run_idempotence(conn, args, batch_rows)
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
