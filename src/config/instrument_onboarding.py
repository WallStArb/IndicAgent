"""onboard_instrument() -- the single sanctioned "add an instrument" code path.

Phase 174 (Universe Expansion) is about to add hundreds of symbols (a Russell 3000
sample, Plan 08/12) plus a handful of gap-fill ETFs (Plan 07/10). The 111->231
universe expansion (2026-08-05/06) wrote `instruments` rows and nothing else --
0% `instrument_metadata` coverage for 151 symbols (todo 282), and CLAUDE.md's
Corpus Pipeline Gotcha records the same omission failure class one table over
(`--compute-only` silently skips every symbol with no `backfill_status` row).
Both are omission bugs that produce a plausible-looking but incomplete corpus.

This module exists so the complete write -- instruments + instrument_tags +
instrument_metadata (or an explicit, logged skip) + backfill_status -- is the
only easy path, not a checklist a caller can partially follow. D-08 (todo 282)
is the metadata mandate; T-174-02 is the qualification-gate / injection
mitigation; T-174-42 is the caller-transaction-boundary guarantee. Every write
this phase makes to `instruments` should route through `onboard_instrument()`.

Caller contract: `conn` must be a pooled `asyncpg.Connection` (from
`src.core.database_manager.create_pool()`), which registers the JSONB codec
needed for `contract_details` to round-trip as a `dict`. A bare
`asyncpg.connect()` connection has no codec registered -- call
`src.core.database_manager._setup_codecs(conn)` on it first, or this helper's
`contract_details` write will fail to serialize correctly.
"""

from __future__ import annotations

import json as _json
from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol

import asyncpg
import structlog

if TYPE_CHECKING:
    from src.core.models import Instrument

logger = structlog.get_logger(__name__)

# Migration 296's fixed ten-key contract_details JSONB shape -- reuse exactly,
# do not invent a new key set per caller.
_CONTRACT_DETAILS_KEYS = (
    "symbol",
    "base",
    "name",
    "asset_class",
    "exchange",
    "sector",
    "tick_size",
    "session_id",
    "point_value",
    "provider_meta",
)

_INSERT_INSTRUMENT_SQL = """
INSERT INTO instruments (symbol, base, contract_details, is_active, compute_eligible, live_tradeable)
VALUES ($1, $2, $3::jsonb, true, $4, $5)
ON CONFLICT (symbol) DO NOTHING
"""

_SELECT_KNOWN_TAGS_SQL = """
SELECT tag FROM tag_vocabulary WHERE tag = ANY($1::text[])
"""

_INSERT_TAG_SQL = """
INSERT INTO instrument_tags (symbol, tag, weight, source, evidence)
VALUES ($1, $2, $3, 'human', $4::jsonb)
ON CONFLICT (symbol, tag) DO NOTHING
"""

_INSERT_METADATA_SQL = """
INSERT INTO instrument_metadata (symbol, listing_date, underlying_index, issuer, description)
VALUES ($1, $2, $3, $4, $5)
ON CONFLICT (symbol) DO UPDATE SET
    listing_date = EXCLUDED.listing_date,
    underlying_index = EXCLUDED.underlying_index,
    issuer = EXCLUDED.issuer,
    description = EXCLUDED.description,
    updated_at = NOW()
"""

# Asyncpg-form rewrite of services/backfill_feature_factory.py's _UPSERT_STATUS_SQL
# (psycopg %s form) -- semantics unchanged, only the placeholder syntax differs.
_UPSERT_BACKFILL_STATUS_SQL = """
INSERT INTO backfill_status (symbol, tf, status, fetch_complete, started_at)
VALUES ($1, $2, $3, $4, NOW())
ON CONFLICT (symbol, tf) DO UPDATE SET
    status = EXCLUDED.status,
    fetch_complete = GREATEST(backfill_status.fetch_complete, EXCLUDED.fetch_complete),
    started_at = COALESCE(backfill_status.started_at, EXCLUDED.started_at)
"""

_DEFAULT_TIMEFRAMES: tuple[str, ...] = ("5m", "15m", "1h", "1d")


class OnboardingRejected(Exception):
    """Raised when a symbol fails to clear a mandatory onboarding gate.

    Covers both the IBKR qualification gate (T-174-02/T-174-03 -- the ticker
    does not resolve to a real, tradeable contract) and the tag-vocabulary
    gate (ITR rule -- a tag must be registered vocabulary, not invented at
    insert time). In both cases no DB write happens; the caller's transaction
    is left exactly as it was before the call.
    """


class InstrumentQualifier(Protocol):
    """Minimal provider surface this module depends on.

    Deliberately NOT importing src/providers/ibkr.py here: ibkr.py already
    imports settings, and a reverse import would create a cycle; the Ring
    rule also keeps provider specifics inside src/providers/. Callers inject
    a real IBKRProvider (or any qualifier satisfying this Protocol) instead,
    which also makes this module's unit tests provider-free and DB-free.
    """

    async def qualify_instrument(
        self,
        instrument: Any,
        *,
        ibkr_symbol: str = "",
        trading_class: str = "",
    ) -> bool: ...


@dataclass
class OnboardResult:
    """Outcome of a single onboard_instrument() call.

    Callers aggregate these into one end-of-run summary log rather than
    logging per symbol (CLAUDE.md's no-per-row-logging-in-a-corpus-loop rule
    -- Plan 12 calls this helper hundreds of times in one run).
    """

    symbol: str
    qualified: bool
    instrument_inserted: bool
    tags_inserted: int
    metadata_written: bool
    backfill_rows_seeded: int


async def onboard_instrument(
    conn: asyncpg.Connection,
    instrument: Instrument,
    *,
    qualifier: InstrumentQualifier,
    tags: Sequence[tuple[str, float, dict]] = (),
    timeframes: Sequence[str] = _DEFAULT_TIMEFRAMES,
    metadata: dict | None = None,
    metadata_skip_reason: str = "",
    compute_eligible: bool = False,
    live_tradeable: bool = False,
) -> OnboardResult:
    """Onboard one instrument: qualify, then write instruments + instrument_tags
    + instrument_metadata (or an explicit logged skip) + backfill_status, all
    inside one transaction.

    This is the single sanctioned "add an instrument" path (D-08, todo 282,
    todo 274, Phase 174). Never bypass the qualification gate with a
    force=True escape hatch -- IBKR's contract universe is the de facto
    allowlist standing between an externally-downloaded ticker string and the
    `instruments` table.

    Transaction contract: this function opens exactly one transaction-context
    block (see the implementation below) and never explicitly finalizes,
    undoes, or manually opens a transaction of its own outside that block --
    every outcome (success or failure) is decided solely by that context
    manager. asyncpg's `Connection.transaction()` opens a top-level
    transaction when `conn` is idle and a SAVEPOINT when `conn` is already
    inside one -- so a single-symbol caller gets all-or-nothing atomicity
    across the four tables, while a bulk caller (Plan 08's batched-writes
    loop, Plan 12's run) may hold its own outer transaction-context block
    across hundreds of onboardings: one rejected symbol unwinds only that
    symbol's savepoint, and the outer batch stays open under the caller's
    control. This helper must never close the caller's transaction out from
    under it.

    Args:
        conn: an open, pooled asyncpg.Connection owned by the caller.
        instrument: the Instrument to onboard (src.core.models.Instrument).
        qualifier: an InstrumentQualifier (e.g. a live IBKRProvider) used to
            confirm the ticker resolves to a real, tradeable contract before
            any write happens.
        tags: (tag, weight, evidence_dict) tuples. Every tag must already
            exist in tag_vocabulary -- this is checked with one query before
            any write. Written with source='human' (a definitional seed
            prior -- measured-provenance rows are TagCalibrator's exclusive
            domain, never impersonated here).
        timeframes: backfill_status is seeded once per timeframe here.
        metadata: dict with keys listing_date, underlying_index, issuer,
            description. If None, metadata_skip_reason must be a non-empty
            string (D-08's metadata mandate -- a silent omission must be
            unrepresentable in this API).
        metadata_skip_reason: required non-empty string when metadata is
            omitted; logged as a WARNING-level structlog event so the skip is
            visible, not silent.
        compute_eligible: defaults to False -- a newly onboarded symbol has
            no history yet, so it is backfill-eligible but not
            compute-eligible until a later promotion step (Plan 12).
        live_tradeable: defaults to False; this function provides no path to
            set it True.

    Raises:
        OnboardingRejected: qualification failed, or one or more tags are not
            registered in tag_vocabulary. No DB write happens in either case.
        ValueError: metadata is None and metadata_skip_reason is empty.

    Returns:
        OnboardResult summarizing what was written.
    """
    if metadata is None and not metadata_skip_reason:
        raise ValueError(
            "onboard_instrument: metadata is None and metadata_skip_reason is empty -- "
            "a silent instrument_metadata omission is not permitted (D-08, todo 282). "
            "Pass metadata=... or a non-empty metadata_skip_reason=... explaining why "
            f"this instrument (symbol={instrument.symbol!r}) has no metadata row."
        )

    # Qualification gate (V5 / T-174-02) -- runs before the transaction opens
    # and before any tag/vocabulary check, so a bad ticker never reaches SQL.
    qualified = await qualifier.qualify_instrument(instrument)
    if not qualified:
        raise OnboardingRejected(
            f"onboard_instrument: {instrument.symbol!r} did not resolve to a real "
            "IBKR contract -- rejected before any DB write."
        )

    tag_names = [tag_name for tag_name, _weight, _evidence in tags]

    async with conn.transaction():
        if tag_names:
            known_rows = await conn.fetch(_SELECT_KNOWN_TAGS_SQL, tag_names)
            known_tags = {row["tag"] for row in known_rows}
            missing_tags = [name for name in tag_names if name not in known_tags]
            if missing_tags:
                raise OnboardingRejected(
                    f"onboard_instrument: {instrument.symbol!r} references unregistered "
                    f"tag_vocabulary tags {missing_tags!r} -- a tag must be registered "
                    "vocabulary, not invented at insert time (ITR rule)."
                )

        contract_details = {key: getattr(instrument, key) for key in _CONTRACT_DETAILS_KEYS}

        await conn.execute(
            _INSERT_INSTRUMENT_SQL,
            instrument.symbol,
            instrument.base,
            _json.dumps(contract_details),
            compute_eligible,
            live_tradeable,
        )
        instrument_inserted = True

        tags_inserted = 0
        for tag_name, weight, evidence in tags:
            await conn.execute(
                _INSERT_TAG_SQL,
                instrument.symbol,
                tag_name,
                weight,
                _json.dumps(evidence),
            )
            tags_inserted += 1

        metadata_written = False
        if metadata is not None:
            await conn.execute(
                _INSERT_METADATA_SQL,
                instrument.symbol,
                metadata.get("listing_date"),
                metadata.get("underlying_index"),
                metadata.get("issuer"),
                metadata.get("description"),
            )
            metadata_written = True
        else:
            logger.warning(
                "instrument_onboarding.metadata_skipped",
                symbol=instrument.symbol,
                reason=metadata_skip_reason,
            )

        backfill_rows_seeded = 0
        for tf in timeframes:
            await conn.execute(
                _UPSERT_BACKFILL_STATUS_SQL,
                instrument.symbol,
                tf,
                "pending",
                False,
            )
            backfill_rows_seeded += 1

    return OnboardResult(
        symbol=instrument.symbol,
        qualified=qualified,
        instrument_inserted=instrument_inserted,
        tags_inserted=tags_inserted,
        metadata_written=metadata_written,
        backfill_rows_seeded=backfill_rows_seeded,
    )
