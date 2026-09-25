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

import json
from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol

import asyncpg
import structlog

from src.config.classification_service import (
    DEFAULT_SCHEME,
    SECTOR_LEVEL,
    ClassificationAssignment,
)

if TYPE_CHECKING:
    from src.core.models import Instrument

logger = structlog.get_logger(__name__)

# Migration 296's fixed ten-key contract_details JSONB shape minus the flat sector
# label, which stopped being written in Phase 182 (D-10, todo 384) -- the
# classification tables are the source of truth for sector now; existing rows keep
# their sector value as historical data, this module just never writes it again.
_CONTRACT_DETAILS_KEYS = (
    "symbol",
    "base",
    "name",
    "asset_class",
    "exchange",
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

_SELECT_CLASSIFICATION_NODE_SQL = """
SELECT level FROM classification_node WHERE scheme = $1 AND code = $2 AND valid_to IS NULL
"""

# valid_from is the database's UTC date: the same date migration 368's trigger requires, so a
# Python clock and the transaction start can never disagree across UTC midnight.
_INSERT_CLASSIFICATION_SQL = """
INSERT INTO instrument_classification (symbol, scheme, code, valid_from, source_ref)
VALUES ($1, $2, $3, (now() AT TIME ZONE 'UTC')::date, $4)
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
# Seed-only: an existing checkpoint is never touched. The earlier upsert reset `status` to
# 'pending' while GREATEST kept fetch_complete=true, leaving an inconsistent row that made
# backfill_feature_factory recompute an already-complete symbol (174 review WR-03).
_SEED_BACKFILL_STATUS_SQL = """
INSERT INTO backfill_status (symbol, tf, status, fetch_complete, started_at)
VALUES ($1, $2, 'pending', false, NOW())
ON CONFLICT (symbol, tf) DO NOTHING
"""

# The compute timeframe stack: the timeframes the feature factory computes, and therefore
# the timeframes a symbol must be backfilled at before it is compute-ready. One APR key
# (migration 278) drives the factory, onboarding's seed, and the promotion predicate.
COMPUTE_TIMEFRAMES_APR_KEY = "feature.factory.target_timeframes"

_SELECT_APR_VALUE_SQL = "SELECT config_value FROM config_state WHERE config_key = $1"


def parse_compute_timeframes(raw: str | None) -> list[str]:
    """Parse and validate the compute-timeframes APR value; raise if absent or malformed.

    No fallback literal: a missing key must fail loudly rather than seed a timeframe set
    nobody configured.
    """
    if raw is None:
        raise RuntimeError(f"APR key {COMPUTE_TIMEFRAMES_APR_KEY!r} is not set in config_state")
    value = json.loads(raw)
    if not (isinstance(value, list) and value and all(isinstance(tf, str) and tf for tf in value)):
        raise RuntimeError(
            f"APR key {COMPUTE_TIMEFRAMES_APR_KEY!r} must be a non-empty JSON array of "
            f"timeframe strings, got {raw!r}"
        )
    if len(set(value)) != len(value):
        # A duplicate makes COMPUTE_READY_PREDICATE_SQL's count(*) = cardinality(...) unsatisfiable,
        # so promotion would silently report zero candidates forever.
        raise RuntimeError(
            f"APR key {COMPUTE_TIMEFRAMES_APR_KEY!r} lists a timeframe twice: {raw!r}"
        )
    return value


async def load_compute_timeframes(conn: asyncpg.Connection) -> list[str]:
    """Read and validate the APR compute timeframe stack on an asyncpg connection.

    Bulk callers resolve it once per run and pass `timeframes=` explicitly, so every
    symbol in a run is seeded with the same stack and the key is read once.
    """
    return parse_compute_timeframes(
        await conn.fetchval(_SELECT_APR_VALUE_SQL, COMPUTE_TIMEFRAMES_APR_KEY)
    )


def _inserted(status: str) -> bool:
    """True if an asyncpg INSERT command tag reports one row written ("INSERT 0 1")."""
    return status.split()[-1] == "1"


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
    timeframes: Sequence[str] | None = None,
    metadata: dict | None = None,
    metadata_skip_reason: str = "",
    classification: ClassificationAssignment | None = None,
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
        timeframes: backfill_status is seeded once per timeframe here. None (the
            default) reads the compute timeframe stack from APR
            (`feature.factory.target_timeframes`); pass an explicit subset only for a
            deliberately partial-stack cohort such as the D-09 1d-only pilot.
        metadata: dict with keys listing_date, underlying_index, issuer,
            description. If None, metadata_skip_reason must be a non-empty
            string (D-08's metadata mandate -- a silent omission must be
            unrepresentable in this API).
        metadata_skip_reason: required non-empty string when metadata is
            omitted; logged as a WARNING-level structlog event so the skip is
            visible, not silent.
        classification: a ClassificationAssignment (code, source_ref) naming the
            indicagent_v1 node this instrument belongs to. Required -- there is
            no skip escape hatch (D-09, todo 384): an instrument that cannot be
            classified is not onboarded. The code must already exist as a
            current classification_node; the row is written to
            instrument_classification inside this call's own transaction.
        compute_eligible: defaults to False -- a newly onboarded symbol has
            no history yet, so it is backfill-eligible but not
            compute-eligible until a later promotion step (Plan 12).
        live_tradeable: defaults to False; this function provides no path to
            set it True.

    Raises:
        OnboardingRejected: qualification failed, one or more tags are not
            registered in tag_vocabulary, the classification code is not a
            current classification_node, or the symbol already exists in
            `instruments`. No DB write happens in any of these cases -- re-onboarding
            an existing symbol is refused rather than silently reported as done.
        ValueError: metadata is None and metadata_skip_reason is empty, or
            classification is None (D-09 -- no skip escape hatch).

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

    if classification is None:
        raise ValueError(
            "onboard_instrument: classification is None -- a new instrument must carry "
            "an indicagent_v1 classification at onboarding (D-09, todo 384); there is no "
            "skip escape hatch, an instrument that cannot be classified is not onboarded "
            f"(symbol={instrument.symbol!r})."
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

        node_level = await conn.fetchval(
            _SELECT_CLASSIFICATION_NODE_SQL, DEFAULT_SCHEME, classification.code
        )
        if node_level is None:
            raise OnboardingRejected(
                f"onboard_instrument: {instrument.symbol!r} classification code "
                f"{classification.code!r} is not a current {DEFAULT_SCHEME} node -- "
                "rejected before any DB write."
            )
        if node_level < SECTOR_LEVEL:
            # An asset-class-only assignment would land in the unclassified sector stratum
            # while the coverage audit counts it as covered: a silent gap.
            raise OnboardingRejected(
                f"onboard_instrument: {instrument.symbol!r} classification code "
                f"{classification.code!r} is level {node_level}; an instrument must be "
                f"classified to at least the sector level ({SECTOR_LEVEL})."
            )

        contract_details = {key: getattr(instrument, key) for key in _CONTRACT_DETAILS_KEYS}

        status = await conn.execute(
            _INSERT_INSTRUMENT_SQL,
            instrument.symbol,
            instrument.base,
            contract_details,
            compute_eligible,
            live_tradeable,
        )
        if not _inserted(status):
            # Raising inside the transaction block unwinds it (or this call's savepoint),
            # so nothing below is written for an existing symbol.
            raise OnboardingRejected(
                f"onboard_instrument: {instrument.symbol!r} already exists in instruments -- "
                "refusing to re-onboard. Change an existing row's flags deliberately, not "
                "through this path."
            )
        instrument_inserted = True

        # No ON CONFLICT: a brand-new symbol cannot already have a row here, and if one
        # somehow exists the unique violation (uq_instrument_classification_current) must
        # surface rather than be silently absorbed.
        await conn.execute(
            _INSERT_CLASSIFICATION_SQL,
            instrument.symbol,
            DEFAULT_SCHEME,
            classification.code,
            classification.source_ref,
        )

        tags_inserted = 0
        for tag_name, weight, evidence in tags:
            tag_status = await conn.execute(
                _INSERT_TAG_SQL,
                instrument.symbol,
                tag_name,
                weight,
                evidence,
            )
            tags_inserted += _inserted(tag_status)

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

        if timeframes is None:
            timeframes = await load_compute_timeframes(conn)
        backfill_rows_seeded = 0
        for tf in timeframes:
            seed_status = await conn.execute(_SEED_BACKFILL_STATUS_SQL, instrument.symbol, tf)
            backfill_rows_seeded += _inserted(seed_status)

    return OnboardResult(
        symbol=instrument.symbol,
        qualified=qualified,
        instrument_inserted=instrument_inserted,
        tags_inserted=tags_inserted,
        metadata_written=metadata_written,
        backfill_rows_seeded=backfill_rows_seeded,
    )
