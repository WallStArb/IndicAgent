"""D6 listing venue writer (phase 185 plan 24, D-25): point-in-time listing venue per symbol.

IBKR serves SMART-routed history only from a stock's last listing-venue move; the same
contract routed to the former venue serves the years before it (D1 venue observations, the
ohlcv_venue_head view, plans 13/14/19). This writer turns that inventory into
listing_venue (migration 408): for each 1d-eligible symbol,

- before the SMART head, the former venue of each date range is the venue whose close is
  most often the nearest to the official (Tradier) close: the listing venue runs the closing
  auction, which is the official close, and the D3 venue study found only the listing
  venue's close matches SMART's. Each venue's closes are compared after dividing out its
  median ratio to the official close over the range, so a series stored on another split
  scale still compares. Where no official close overlaps, the venue with the most
  venue-only volume wins (the plan's original rule; measured on the 45 moved names, volume
  alone hands most post-2008 ranges to BATS, which listed none of them). Adjacent ranges won
  by the same venue merge, and the first range extends back to the symbol's first D1 bar;
- from the SMART head on, the venue is SMART's latest primary_exchange (open span).

The inference cannot name a venue the D1 inventory has no route for (a NASDAQ-listed name
whose ISLAND route never answered gets its best available route), so every span carries its
evidence: the per-route nearest-close win share and volume behind it.

Venue codes are the IBKR primary-exchange vocabulary (route ISLAND is NASDAQ). A former
venue equal to the current primary is not a move the data shows, so no closed span is
invented; D7's listing_venue_coverage check reports the moved name instead.

Writes are append-only: identical spans are skipped; a new move closes the open span and
inserts the next one; any other difference from the stored history is a conflict, logged and
left for a human (the table refuses rewrites). One bar_derivation_batch row (stage
listing_venue) per applied run; one transaction per symbol under bar_derivation_writer.
Default is a dry run.

    .venv/bin/python -m services.listing_venue_writer            # dry run, all 1d-eligible
    .venv/bin/python -m services.listing_venue_writer --apply    # write
"""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
from collections import defaultdict
from collections.abc import Mapping, Sequence
from datetime import date, timedelta
from typing import Any, NamedTuple

import asyncpg

from services._batch_utils import cfg as _cfg
from services._batch_utils import load_apr_dict_async
from services.bar_derivation_batch import close_batch, open_batch
from src.config.settings import Settings, dimension_where_clause
from src.core.agent.base_batch import BaseBatch
from src.intelligence.bars.sources import SOURCE_TRADIER
from src.observability.otel import OTelInitError, init_otel_providers
from src.providers.base import VENUE_ROUTE_ALIASES

_JOB = "listing-venue-writer"
_STAGE = "listing_venue"
RULE_VERSION = "1"
# Fallback is migration 437's seed (the former-venue routes venue fallback asks).
_DEFAULT_VENUES = ["NYSE", "ARCA", "ISLAND", "AMEX", "BATS"]
_ONE_DAY = timedelta(days=1)

Span = tuple[str, date, date | None]


# ---------------------------------------------------------------------------
# Pure inference and reconciliation
# ---------------------------------------------------------------------------


def _venue(route: str) -> str:
    return VENUE_ROUTE_ALIASES.get(route, route)


class RangeScore(NamedTuple):
    """One route's evidence over one date range."""

    # Days its close was the nearest to the official close (ties split). A route answering
    # alone wins its day: the name traded there and nowhere else the inventory asked.
    wins: float
    n_compared: int  # days with an official close and at least one route
    volume: float


def score_range(
    routes: Sequence[str],
    lo: date,
    hi: date,
    venue_bars: Mapping[str, Mapping[date, tuple[float, float]]],
    official_close: Mapping[date, float],
) -> dict[str, RangeScore]:
    """Nearest-close wins and volume per route over [lo, hi).

    venue_bars: route -> {bar_date: (close, venue-only volume)}. A route's closes are
    divided by its median close/official ratio over the range before comparing, so a
    constant scale difference (a split applied to one series only) does not decide it.
    """
    bars = {r: {d: cv for d, cv in venue_bars.get(r, {}).items() if lo <= d < hi} for r in routes}
    median_ratio: dict[str, float] = {}
    for r, days in bars.items():
        ratios = [
            c / official_close[d]
            for d, (c, _) in days.items()
            if c > 0 and official_close.get(d, 0.0) > 0
        ]
        if ratios:
            median_ratio[r] = statistics.median(ratios)
    wins: dict[str, float] = dict.fromkeys(routes, 0.0)
    n_compared = 0
    for d in sorted({d for days in bars.values() for d in days}):
        official = official_close.get(d, 0.0)
        if official <= 0:
            continue
        distance = {
            r: abs(bars[r][d][0] / (median_ratio[r] * official) - 1.0)
            for r in routes
            if d in bars[r] and r in median_ratio
        }
        if not distance:
            continue
        n_compared += 1
        best = min(distance.values())
        nearest = [r for r, x in distance.items() if x == best]
        for r in nearest:
            wins[r] += 1.0 / len(nearest)
    return {
        r: RangeScore(wins[r], n_compared, float(sum(v for _, v in bars[r].values())))
        for r in routes
    }


def infer_listing_spans(
    first_bar_date: date,
    smart_head: date | None,
    venue_spans: Sequence[tuple[str, date, date]],
    current_primary: str | None,
    *,
    venue_bars: Mapping[str, Mapping[date, tuple[float, float]]],
    official_close: Mapping[date, float],
) -> list[Span]:
    """Listing spans [valid_from, valid_to) for one symbol; the last is open when the current
    primary is known.

    venue_spans: (route, first venue bar, last venue bar) per former-venue route; spans that
    end on or after `smart_head` answered alongside SMART and say nothing about a former
    listing, so they are ignored. Ranges split only where a route stops answering (a venue
    that ceased to list the name); a route that starts answering later is a venue that came
    into existence (BATS became an exchange on 2008-10-17), not a move, so it opens no
    range. Each range goes to the route with the most nearest-close wins over it, then the
    most volume, then the alphabetically first venue (deterministic).
    """
    former: list[Span] = []
    if smart_head is not None:
        pre = [(r, s, e) for r, s, e in venue_spans if e < smart_head and s <= e]
        edges = sorted(
            {min((s for _, s, _ in pre), default=smart_head)} | {e + _ONE_DAY for _, _, e in pre}
        )
        for lo, hi in zip(edges, edges[1:], strict=False):
            active = [r for r, s, e in pre if s < hi and e >= lo]
            scores = score_range(active, lo, hi, venue_bars, official_close)
            # max keeps the first of equal keys: sorting by venue first breaks ties.
            winner = max(
                sorted(active, key=_venue), key=lambda r: (scores[r].wins, scores[r].volume)
            )
            venue = _venue(winner)
            if former and former[-1][0] == venue:
                former[-1] = (venue, former[-1][1], hi)
            else:
                former.append((venue, lo, hi))
        # Contiguous from the first bar to the head: the first range reaches back to the
        # first bar and the last runs to the head (the gap between the last venue bar and the
        # head is unobserved; the move date is the head).
        former = [
            (
                venue,
                min(start, first_bar_date) if i == 0 else start,
                former[i + 1][1] if i + 1 < len(former) else smart_head,
            )
            for i, (venue, start, _) in enumerate(former)
        ]

    if current_primary is None:
        return former
    if not former:
        return [(current_primary, first_bar_date, None)]
    if former[-1][0] == current_primary:
        venue, start, _ = former[-1]
        return [*former[:-1], (venue, start, None)]
    return [*former, (current_primary, smart_head, None)]


class SpanPlan(NamedTuple):
    """What to write for one symbol: close the open span (its valid_from, the new valid_to),
    then insert these spans; or a conflict, which writes nothing."""

    close: tuple[date, date] | None
    insert: tuple[Span, ...]
    conflict: str | None

    @property
    def is_noop(self) -> bool:
        return self.close is None and not self.insert and self.conflict is None


def reconcile_spans(existing: Sequence[Span], desired: Sequence[Span]) -> SpanPlan:
    """Plan the append-only writes that turn `existing` into `desired` (both ordered by
    valid_from), or a conflict when that would rewrite history.

    Stored closed spans must reappear unchanged as a prefix of `desired`; a stored open span
    must match the next desired span's venue and valid_from (it is closed when the desired
    one is closed); everything after is inserted.
    """
    existing = list(existing)
    desired = list(desired)
    if existing == desired:
        return SpanPlan(None, (), None)
    if existing and not desired:
        return SpanPlan(None, (), "stored spans but nothing inferred")
    if len(existing) > len(desired):
        return SpanPlan(None, (), f"{len(existing)} stored spans, {len(desired)} inferred")
    close: tuple[date, date] | None = None
    for i, stored in enumerate(existing):
        want = desired[i]
        if stored[2] is not None or i < len(existing) - 1:
            if stored != want:
                return SpanPlan(None, (), f"stored span {stored} differs from inferred {want}")
            continue
        if (stored[0], stored[1]) != (want[0], want[1]):
            return SpanPlan(None, (), f"open span {stored} differs from inferred {want}")
        if want[2] is not None:
            close = (stored[1], want[2])
    return SpanPlan(close, tuple(desired[len(existing) :]), None)


# ---------------------------------------------------------------------------
# IO
# ---------------------------------------------------------------------------

_UNIVERSE_SQL = "SELECT i.symbol FROM instruments i WHERE {clause} ORDER BY i.symbol"
# D1 rows a test wrote (caller 'test-...') are provenance-excluded, as in bar_derivation.
_FIRST_BAR_SQL = """
SELECT o.symbol, min(o.bar_date) AS first_bar
FROM ohlcv_observation o JOIN ohlcv_request q ON q.request_id = o.request_id
WHERE o.symbol = ANY($1::text[]) AND q.caller NOT LIKE 'test-%'
GROUP BY o.symbol
"""
_SMART_HEAD_SQL = """
SELECT o.symbol, min(o.bar_date) AS head
FROM ohlcv_observation o JOIN ohlcv_request q ON q.request_id = o.request_id
WHERE o.symbol = ANY($1::text[]) AND o.source = 'ibkr' AND o.route = 'SMART'
  AND o.what_to_show = 'TRADES' AND q.caller NOT LIKE 'test-%'
GROUP BY o.symbol
"""
_PRIMARY_SQL = """
SELECT DISTINCT ON (symbol) symbol, primary_exchange, request_id::text, answered_at
FROM ohlcv_request
WHERE symbol = ANY($1::text[]) AND timeframe = '1d' AND source = 'ibkr' AND route = 'SMART'
  AND what_to_show = 'TRADES' AND primary_exchange IS NOT NULL AND caller NOT LIKE 'test-%'
ORDER BY symbol, answered_at DESC
"""
# The inventory (plans 14/19): former-venue spans that end before the SMART head.
_VENUE_HEAD_SQL = """
SELECT symbol, route, first_bar_date, last_bar_date FROM ohlcv_venue_head
WHERE symbol = ANY($1::text[]) AND route = ANY($2::text[])
  AND pre_move AND smart_head_date IS NOT NULL
ORDER BY symbol, route
"""
_VENUE_BARS_SQL = """
SELECT DISTINCT ON (route, bar_date) route, bar_date, close, volume FROM ohlcv_observation
WHERE symbol = $1 AND route = ANY($2::text[]) AND what_to_show = 'TRADES' AND bar_date < $3
ORDER BY route, bar_date, fetched_at DESC
"""
_OFFICIAL_CLOSE_SQL = """
SELECT DISTINCT ON (bar_date) bar_date, close FROM ohlcv_observation
WHERE symbol = $1 AND source = $2 AND bar_date < $3
ORDER BY bar_date, fetched_at DESC
"""
_VENUE_REQUESTS_SQL = """
SELECT route, array_agg(request_id::text ORDER BY answered_at) AS ids FROM ohlcv_request
WHERE symbol = $1 AND timeframe = '1d' AND route = ANY($2::text[]) AND what_to_show = 'TRADES'
  AND outcome = 'bars'
GROUP BY route
"""
_EXISTING_SQL = """
SELECT venue, valid_from, valid_to FROM listing_venue WHERE symbol = $1 ORDER BY valid_from
"""
_CLOSE_SQL = """
UPDATE listing_venue SET valid_to = $3
WHERE symbol = $1 AND valid_from = $2 AND valid_to IS NULL
"""
_INSERT_SQL = """
INSERT INTO listing_venue (symbol, venue, valid_from, valid_to, evidence, batch_id)
VALUES ($1, $2, $3, $4, $5::text::jsonb, $6::uuid)
"""


class _SymbolInputs(NamedTuple):
    symbol: str
    first_bar: date
    smart_head: date | None
    primary: tuple[str, str, Any] | None  # (primary_exchange, request_id, answered_at)
    venue_spans: list[tuple[str, date, date]]
    venue_bars: dict[str, dict[date, tuple[float, float]]]
    official_close: dict[date, float]
    venue_requests: dict[str, list[str]]

    def infer(self) -> list[Span]:
        return infer_listing_spans(
            self.first_bar,
            self.smart_head,
            self.venue_spans,
            self.primary[0] if self.primary else None,
            venue_bars=self.venue_bars,
            official_close=self.official_close,
        )


def _evidence(span: Span, inputs: _SymbolInputs) -> dict[str, Any]:
    """Why a span holds: the requests behind it and the scores the rule read (T-185-24-02)."""
    venue, start, end = span
    evidence: dict[str, Any] = {
        "rule_version": RULE_VERSION,
        "first_bar_date": inputs.first_bar.isoformat(),
        "smart_head": inputs.smart_head.isoformat() if inputs.smart_head else None,
    }
    request_ids: list[str] = []
    if end is None and inputs.primary is not None and inputs.primary[0] == venue:
        evidence["basis"] = "smart_primary_exchange"
        evidence["primary_answered_at"] = inputs.primary[2].isoformat()
        request_ids.append(inputs.primary[1])
    else:
        evidence["basis"] = "former_venue_nearest_close"
    head = inputs.smart_head
    if inputs.venue_spans and head is not None and start < head:
        stop = min(end or head, head)
        routes = [r for r, s, e in inputs.venue_spans if s < stop and e >= start]
        scores = score_range(routes, start, stop, inputs.venue_bars, inputs.official_close)
        evidence["venue_evidence"] = {
            r: [s.isoformat(), e.isoformat()] for r, s, e in inputs.venue_spans
        }
        evidence["route_scores_in_span"] = {r: sc._asdict() for r, sc in scores.items()}
        if scores:
            # The two signals disagreeing marks a span a human should read before trusting.
            by_volume = max(sorted(scores, key=_venue), key=lambda r: scores[r].volume)
            evidence["max_volume_venue"] = _venue(by_volume)
            evidence["contested"] = _venue(by_volume) != venue
        request_ids += [
            i for r in routes if _venue(r) == venue for i in inputs.venue_requests.get(r, [])
        ]
        if end is None:
            evidence["note"] = "former venue equals current primary; no move recorded"
    evidence["request_ids"] = request_ids
    return evidence


class ListingVenueWriter(BaseBatch):
    """D6: infer listing_venue spans for the 1d-eligible universe and append them."""

    job_name = _JOB
    compute_version = RULE_VERSION

    def __init__(self, db_dsn: str, *, symbols: list[str] | None, apply: bool) -> None:
        super().__init__(db_dsn)
        self._symbols = symbols
        self._apply = apply

    async def execute(self, pool: asyncpg.Pool) -> dict[str, int]:
        async with pool.acquire() as conn:
            apr = await load_apr_dict_async(conn, ["infra.ibkr.venue_fallback.%"])
            venues = list(_cfg(apr, "infra.ibkr.venue_fallback.exchanges", _DEFAULT_VENUES))
            symbols = self._symbols or [
                r["symbol"]
                for r in await conn.fetch(
                    _UNIVERSE_SQL.format(clause=dimension_where_clause("compute_1d", "i"))
                )
            ]
            inputs = await self._load(conn, symbols, venues)

            batch_id: str | None = None
            if self._apply:
                batch_id = await open_batch(
                    conn,
                    stage=_STAGE,
                    rule_version=RULE_VERSION,
                    apr_snapshot={"infra.ibkr.venue_fallback.exchanges": venues},
                    n_symbols=len(inputs),
                )
            totals: dict[str, int] = defaultdict(int)
            conflicts: list[str] = []
            try:
                for item in inputs:
                    outcome = await self._write_symbol(conn, item, batch_id)
                    totals[outcome.split(":", 1)[0]] += 1
                    if outcome.startswith("conflict"):
                        conflicts.append(f"{item.symbol}: {outcome}")
            except Exception as error:
                if batch_id is not None:
                    await close_batch(
                        conn, batch_id, status="failed", detail={"error": str(error)[:500]}
                    )
                raise
            totals["no_observation"] = len(symbols) - len(inputs)
            detail = {**totals, "conflicts": conflicts[:50]}
            if batch_id is not None:
                await close_batch(conn, batch_id, status="completed", detail=detail)

        if conflicts:
            self.logger.error("listing_venue.conflicts", n=len(conflicts), conflicts=conflicts)
        self.logger.info(
            "listing_venue.done", apply=self._apply, batch_id=batch_id, totals=dict(totals)
        )
        print(json.dumps({"apply": self._apply, "batch_id": batch_id, **detail}, default=str))
        return dict(totals)

    @staticmethod
    async def _load(conn: Any, symbols: list[str], venues: list[str]) -> list[_SymbolInputs]:
        first = {r["symbol"]: r["first_bar"] for r in await conn.fetch(_FIRST_BAR_SQL, symbols)}
        heads = {r["symbol"]: r["head"] for r in await conn.fetch(_SMART_HEAD_SQL, symbols)}
        primary = {
            r["symbol"]: (r["primary_exchange"], r["request_id"], r["answered_at"])
            for r in await conn.fetch(_PRIMARY_SQL, symbols)
        }
        spans: dict[str, list[tuple[str, date, date]]] = defaultdict(list)
        for r in await conn.fetch(_VENUE_HEAD_SQL, symbols, venues):
            spans[r["symbol"]].append((r["route"], r["first_bar_date"], r["last_bar_date"]))
        out: list[_SymbolInputs] = []
        for symbol in symbols:
            if symbol not in first:
                continue
            bars: dict[str, dict[date, tuple[float, float]]] = defaultdict(dict)
            official: dict[date, float] = {}
            requests: dict[str, list[str]] = {}
            head = heads.get(symbol)
            if spans.get(symbol) and head:
                for r in await conn.fetch(_VENUE_BARS_SQL, symbol, venues, head):
                    bars[r["route"]][r["bar_date"]] = (r["close"], float(r["volume"] or 0))
                official = {
                    r["bar_date"]: r["close"]
                    for r in await conn.fetch(_OFFICIAL_CLOSE_SQL, symbol, SOURCE_TRADIER, head)
                }
                requests = {
                    r["route"]: list(r["ids"])
                    for r in await conn.fetch(_VENUE_REQUESTS_SQL, symbol, venues)
                }
            out.append(
                _SymbolInputs(
                    symbol,
                    first[symbol],
                    head,
                    primary.get(symbol),
                    spans.get(symbol, []),
                    dict(bars),
                    official,
                    requests,
                )
            )
        return out

    async def _write_symbol(self, conn: Any, item: _SymbolInputs, batch_id: str | None) -> str:
        desired = item.infer()
        if not desired:
            return "no_primary"
        moved = any(end is not None for _, _, end in desired)
        async with conn.transaction():
            if self._apply:
                await conn.execute("SET LOCAL ROLE bar_derivation_writer")
            existing = [
                (r["venue"], r["valid_from"], r["valid_to"])
                for r in await conn.fetch(_EXISTING_SQL, item.symbol)
            ]
            plan = reconcile_spans(existing, desired)
            if plan.conflict is not None:
                return f"conflict: {plan.conflict}"
            if plan.is_noop:
                return "unchanged"
            if not self._apply:
                return "would_write_moved" if moved else "would_write"
            if plan.close is not None:
                status = await conn.execute(_CLOSE_SQL, item.symbol, *plan.close)
                if status != "UPDATE 1":
                    raise RuntimeError(f"{item.symbol}: closing {plan.close} updated {status}")
            for span in plan.insert:
                await conn.execute(
                    _INSERT_SQL,
                    item.symbol,
                    span[0],
                    span[1],
                    span[2],
                    json.dumps(_evidence(span, item)),
                    batch_id,
                )
        return "written_moved" if moved else "written"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--symbols", default=None, help="comma-separated symbols (default: all 1d-eligible)"
    )
    parser.add_argument(
        "--apply", action="store_true", help="write (default: dry run, infer and report only)"
    )
    args = parser.parse_args()
    symbols = (
        sorted({s.strip().upper() for s in args.symbols.split(",") if s.strip()})
        if args.symbols
        else None
    )
    try:
        init_otel_providers(f"indicagent-{_JOB}")
    except OTelInitError:
        pass
    settings = Settings()
    db_dsn = settings.database_url.replace("postgresql+asyncpg://", "postgresql://")
    asyncio.run(ListingVenueWriter(db_dsn, symbols=symbols, apply=args.apply).run())


if __name__ == "__main__":
    main()
