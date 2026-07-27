"""Integration tests: CrossSectionalSpreadTracker watermark scoping, run-boundary turnover,
idempotency, and crash recovery (Phase 167 Plan 03).

Proves the two genuine engineering problems RESEARCH.md identifies (Pattern 1: incremental
watermark scoping; Pattern 2 / Pitfall 4: turnover across run boundaries) and Codex's HIGH
crash-recovery review concern ("if a backfill or incremental run dies after partially writing a
bar cluster, the next run must not double-count, skip, or mis-seed turnover from an incomplete
last row") against a live test database, not merely by design inspection.

Seeds a small synthetic 12-symbol, 4-bar panel into `feature_vectors`/`forward_returns` --
12 symbols so `alpha.construction.decile_fraction=0.10` (migration 260's seeded default)
yields `n_leg = max(1, round(12 * 0.10)) = 1`, making leg membership fully controlled by
exactly which symbol carries the extreme low/high `ctf_momentum` value at each bar.

ISOLATION: this file's fixtures TRUNCATE `construction_spreads` and DELETE `feature_vectors`/
`forward_returns` rows scoped to its own 12-symbol synthetic universe + tf='15m' at the start
of every test, so tests are order-independent. This is safe under this file's own verification
command (`pytest tests/integration/ -k cross_sectional_spread -m integration -x -q` --
selects only this file's tests, so no other test's panel data ever coexists with these tests'
runs in the same session) but would NOT be safe run unscoped alongside another suite that
writes 15m equity feature_vectors/forward_returns rows for the same symbols -- ` +
CrossSectionalSpreadTracker`'s panel query has no time-window bound in `--backfill` mode, so
any stray same-symbol/tf row left by a concurrent test would be picked up too.

IMPORTANT: asserts against indicagent_test (the conftest-rebuilt database), never against
production `indicagent`.

Run: pytest tests/integration/ -k cross_sectional_spread -m integration -x -q
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import asyncpg
import pytest

from services.cross_sectional_spread_tracker import CrossSectionalSpreadTracker

pytestmark = [pytest.mark.integration, pytest.mark.requires_db]

_TEST_DB_URL = "postgresql://postgres:postgres@localhost:5432/indicagent_test"
_TF = "15m"
_CONSTRUCTION_NAME = "ctf_momentum_decile_ls"
_MANIFEST_PATH = Path(".planning/corpus_manifests/cross_sectional_spread_tracker.json")

_N_SYMBOLS = 12
_BASE_BAR_TS = datetime(2020, 1, 1, tzinfo=UTC)

# Per-bar (short_symbol_index, long_symbol_index) into the 12-symbol universe -- controls
# which symbol carries the extreme low (short leg) / extreme high (long leg) ctf_momentum
# value at that bar. Chosen so bar 2 -> bar 3's turnover changes exactly ONE leg: with
# n_leg=1, one_way_turnover = (long_changed_frac + short_changed_frac) / 2, so a single
# changed leg gives exactly 0.5 -- neither 0.0 (no predecessor / no change) nor 1.0 (both legs
# changed), which is what RESEARCH.md Pattern 2's cross-run-turnover proof needs.
_LEG_INDEX_PER_BAR: list[tuple[int, int]] = [
    (0, 11),  # bar 1: short=idx0, long=idx11 (first bar -- no predecessor, turnover None)
    (1, 10),  # bar 2: short=idx1, long=idx10 (both legs differ from bar 1)
    (1, 9),  # bar 3: short=idx1 (SAME as bar 2), long=idx9 (changed) -> turnover 0.5
    (2, 9),  # bar 4: short=idx2 (changed), long=idx9 (SAME as bar 3) -> turnover 0.5
]


async def _active_equity_symbols(conn: asyncpg.Connection) -> list[str]:
    rows = await conn.fetch(
        "SELECT symbol FROM instruments WHERE is_active = true "
        "AND contract_details->>'asset_class' = 'equity' ORDER BY symbol LIMIT $1",
        _N_SYMBOLS,
    )
    return [r["symbol"] for r in rows]


def _bar_timestamps(n: int) -> list[datetime]:
    return [_BASE_BAR_TS + timedelta(minutes=15 * i) for i in range(n)]


async def _reset_panel_tables(conn: asyncpg.Connection, symbols: list[str]) -> None:
    """Clears any rows this file's own synthetic symbols may have left from a previous test
    in this session, so every test starts from a clean, order-independent panel. Scoped to
    `symbols` (this file's 12-symbol synthetic universe) and tf='15m' -- never touches any
    other symbol or timeframe's data."""
    await conn.execute("TRUNCATE construction_spreads")
    await conn.execute(
        "DELETE FROM feature_vectors WHERE symbol = ANY($1::text[]) AND tf = $2", symbols, _TF
    )
    await conn.execute(
        "DELETE FROM forward_returns WHERE symbol = ANY($1::text[]) AND tf = $2", symbols, _TF
    )


async def _seed_bars(
    conn: asyncpg.Connection,
    symbols: list[str],
    bar_timestamps: list[datetime],
    leg_index_per_bar: list[tuple[int, int]],
) -> None:
    """Insert one feature_vectors + forward_returns row per (symbol, bar_ts). Exactly one
    symbol per bar gets an extreme-low ctf_momentum (the short-leg candidate) and one gets an
    extreme-high value (the long-leg candidate); every other symbol gets a fixed, distinct-but-
    irrelevant baseline value -- with 12 symbols and decile_fraction=0.10, n_leg=1, so only the
    two extremes determine leg membership. return_fast/return_slow are distinct per (symbol,
    bar) so the gross-spread math never accidentally exercises a degenerate all-equal case."""
    for bar_idx, (bar_ts, (short_idx, long_idx)) in enumerate(
        zip(bar_timestamps, leg_index_per_bar, strict=True)
    ):
        for sym_idx, symbol in enumerate(symbols):
            if sym_idx == short_idx:
                ctf_momentum = -1000.0
            elif sym_idx == long_idx:
                ctf_momentum = 1000.0
            else:
                ctf_momentum = float(sym_idx)
            return_fast = 0.0001 * (bar_idx * 100 + sym_idx)
            return_slow = 0.0002 * (bar_idx * 100 + sym_idx)
            await conn.execute(
                "INSERT INTO feature_vectors (symbol, tf, bar_ts, pipeline_version, "
                "ctf_momentum) VALUES ($1, $2, $3, $4, $5)",
                symbol,
                _TF,
                bar_ts,
                "test",
                ctf_momentum,
            )
            await conn.execute(
                "INSERT INTO forward_returns (symbol, tf, bar_ts, pipeline_version, "
                "return_type, complete_fast, complete_slow, return_fast, return_slow) "
                "VALUES ($1, $2, $3, $4, 'executable_open_to_open', true, true, $5, $6)",
                symbol,
                _TF,
                bar_ts,
                "test",
                return_fast,
                return_slow,
            )


async def _fetch_rows(conn: asyncpg.Connection) -> list[asyncpg.Record]:
    return await conn.fetch(
        "SELECT * FROM construction_spreads WHERE construction_name = $1 AND tf = $2 "
        "ORDER BY bar_ts ASC",
        _CONSTRUCTION_NAME,
        _TF,
    )


def _decode_jsonb(value: object) -> object:
    """Plain asyncpg.connect() (unlike BaseBatch's pooled connections) has no JSONB codec
    registered, so jsonb columns come back as raw JSON text -- decode for comparison."""
    return json.loads(value) if isinstance(value, str) else value


async def _seed_and_get_symbols() -> list[str]:
    conn = await asyncpg.connect(_TEST_DB_URL)
    try:
        symbols = await _active_equity_symbols(conn)
        if len(symbols) < _N_SYMBOLS:
            pytest.skip(
                f"Need at least {_N_SYMBOLS} active equity symbols in indicagent_test's "
                f"instruments table, found {len(symbols)}"
            )
        await _reset_panel_tables(conn, symbols)
    finally:
        await conn.close()
    return symbols


@pytest.mark.asyncio
async def test_cross_sectional_spread_backfill_writes_one_row_per_bar() -> None:
    symbols = await _seed_and_get_symbols()
    bar_timestamps = _bar_timestamps(4)

    conn = await asyncpg.connect(_TEST_DB_URL)
    try:
        await _seed_bars(conn, symbols, bar_timestamps, _LEG_INDEX_PER_BAR)
    finally:
        await conn.close()

    await CrossSectionalSpreadTracker(_TEST_DB_URL, backfill=True).run()

    conn = await asyncpg.connect(_TEST_DB_URL)
    try:
        rows = await _fetch_rows(conn)
    finally:
        await conn.close()

    assert len(rows) == 4, f"expected 4 construction_spreads rows (one per bar), got {len(rows)}"

    for row in rows:
        assert row["construction_name"] == _CONSTRUCTION_NAME
        assert row["tf"] == _TF
        assert row["n_universe"] == 12
        assert row["n_leg"] == 1
        assert len(row["long_leg_symbols"]) == 1
        assert len(row["short_leg_symbols"]) == 1
        assert set(row["long_leg_symbols"]).isdisjoint(set(row["short_leg_symbols"]))
        assert row["compute_version"] is not None

    null_turnover_rows = [r for r in rows if r["one_way_turnover"] is None]
    assert len(null_turnover_rows) == 1, (
        "exactly one row must have one_way_turnover IS NULL -- the genuinely-first bar "
        f"(Pitfall 4 / Plan 01 design decision 2), got {len(null_turnover_rows)}"
    )
    assert (
        null_turnover_rows[0]["bar_ts"] == rows[0]["bar_ts"]
    ), "the single NULL-turnover row must be the earliest bar_ts"

    for row in rows:
        if row["one_way_turnover"] is None:
            continue
        assert row["net_spread_fast_by_cost_bps"] is not None
        assert row["net_spread_slow_by_cost_bps"] is not None
        fast_keys = set(_decode_jsonb(row["net_spread_fast_by_cost_bps"]))
        slow_keys = set(_decode_jsonb(row["net_spread_slow_by_cost_bps"]))
        assert fast_keys == {"1", "3", "5", "10"}
        assert slow_keys == {"1", "3", "5", "10"}


@pytest.mark.asyncio
async def test_cross_sectional_spread_incremental_watermark_scoping() -> None:
    """167-VALIDATION.md row 167-03-01."""
    symbols = await _seed_and_get_symbols()
    bar_timestamps = _bar_timestamps(4)

    conn = await asyncpg.connect(_TEST_DB_URL)
    try:
        # Seed only the first 2 bars.
        await _seed_bars(conn, symbols, bar_timestamps[:2], _LEG_INDEX_PER_BAR[:2])
    finally:
        await conn.close()

    await CrossSectionalSpreadTracker(_TEST_DB_URL, backfill=True).run()

    conn = await asyncpg.connect(_TEST_DB_URL)
    try:
        first_run_rows = await _fetch_rows(conn)
    finally:
        await conn.close()
    assert len(first_run_rows) == 2
    first_run_created_at = {r["bar_ts"]: r["created_at"] for r in first_run_rows}

    conn = await asyncpg.connect(_TEST_DB_URL)
    try:
        # Insert the remaining 2 bars' panel rows.
        await _seed_bars(conn, symbols, bar_timestamps[2:], _LEG_INDEX_PER_BAR[2:])
    finally:
        await conn.close()

    await CrossSectionalSpreadTracker(_TEST_DB_URL, backfill=False).run()

    conn = await asyncpg.connect(_TEST_DB_URL)
    try:
        rows = await _fetch_rows(conn)
    finally:
        await conn.close()

    assert len(rows) == 4, f"expected 4 total rows after the incremental run, got {len(rows)}"

    for bar_ts, created_at in first_run_created_at.items():
        matching = [r for r in rows if r["bar_ts"] == bar_ts]
        assert len(matching) == 1
        assert matching[0]["created_at"] == created_at, (
            "the second (incremental) run must not rewrite the first run's already-persisted "
            "rows -- ON CONFLICT ... DO NOTHING (design decision 3)"
        )

    assert _MANIFEST_PATH.exists(), f"manifest not written to {_MANIFEST_PATH}"
    manifest_data = json.loads(_MANIFEST_PATH.read_text())
    assert manifest_data["inputs"]["n_bars_processed"] == 2, (
        "the second run's own manifest must report exactly 2 bars processed, not 4 -- proof "
        "the incremental scan is scoped by the watermark, not a full-corpus rescan "
        f"(RESEARCH.md Pattern 1). Got manifest inputs={manifest_data['inputs']}"
    )

    new_rows = [r for r in rows if r["bar_ts"] not in first_run_created_at]
    assert len(new_rows) == 2
    first_new_row = min(new_rows, key=lambda r: r["bar_ts"])
    assert first_new_row["one_way_turnover"] is not None
    assert first_new_row["one_way_turnover"] not in (0.0, 1.0), (
        "the second run's FIRST new bar's turnover must be computed against bar 2's "
        "PERSISTED leg membership (RESEARCH.md Pattern 2 / Pitfall 4), which was not present "
        "in the second run's own query window -- a turnover of exactly 0.0 or 1.0 here is "
        "Pitfall 4's stated symptom of treating 'first bar this run' as having no predecessor. "
        f"Got {first_new_row['one_way_turnover']!r}"
    )


@pytest.mark.asyncio
async def test_cross_sectional_spread_rerun_is_idempotent() -> None:
    symbols = await _seed_and_get_symbols()
    bar_timestamps = _bar_timestamps(4)

    conn = await asyncpg.connect(_TEST_DB_URL)
    try:
        await _seed_bars(conn, symbols, bar_timestamps, _LEG_INDEX_PER_BAR)
    finally:
        await conn.close()

    await CrossSectionalSpreadTracker(_TEST_DB_URL, backfill=True).run()

    conn = await asyncpg.connect(_TEST_DB_URL)
    try:
        first_rows = await _fetch_rows(conn)
    finally:
        await conn.close()
    assert len(first_rows) == 4
    first_created_at = {r["bar_ts"]: r["created_at"] for r in first_rows}

    # Re-run backfill over the exact same range.
    await CrossSectionalSpreadTracker(_TEST_DB_URL, backfill=True).run()

    conn = await asyncpg.connect(_TEST_DB_URL)
    try:
        second_rows = await _fetch_rows(conn)
    finally:
        await conn.close()

    assert (
        len(second_rows) == 4
    ), "re-running backfill over an already-processed range must write no duplicate rows"
    for row in second_rows:
        assert row["created_at"] == first_created_at[row["bar_ts"]], (
            "ON CONFLICT ... DO NOTHING must make a re-run a no-op -- no created_at churn "
            "(design decision 3)"
        )


@pytest.mark.asyncio
async def test_cross_sectional_spread_recovers_from_interrupted_run() -> None:
    """167-VALIDATION.md row 167-03-02. Direct answer to Codex's HIGH crash-recovery review
    concern: "if a backfill or incremental run dies after partially writing a bar cluster, the
    next run must not double-count, skip, or mis-seed turnover from an incomplete last row.\" """
    symbols = await _seed_and_get_symbols()
    bar_timestamps = _bar_timestamps(4)

    conn = await asyncpg.connect(_TEST_DB_URL)
    try:
        await _seed_bars(conn, symbols, bar_timestamps, _LEG_INDEX_PER_BAR)
    finally:
        await conn.close()

    await CrossSectionalSpreadTracker(_TEST_DB_URL, backfill=True).run()

    conn = await asyncpg.connect(_TEST_DB_URL)
    try:
        reference_rows = await _fetch_rows(conn)
    finally:
        await conn.close()
    assert len(reference_rows) == 4
    reference_by_bar_ts = {r["bar_ts"]: dict(r) for r in reference_rows}

    # Simulate a crash that lost the last write chunk: delete a contiguous TAIL of rows --
    # design decision 5 explains this is the only shape an ordered chunked writer can produce.
    third_bar_ts = bar_timestamps[2]
    conn = await asyncpg.connect(_TEST_DB_URL)
    try:
        await conn.execute(
            "DELETE FROM construction_spreads WHERE construction_name = $1 AND tf = $2 "
            "AND bar_ts >= $3",
            _CONSTRUCTION_NAME,
            _TF,
            third_bar_ts,
        )
        remaining = await _fetch_rows(conn)
    finally:
        await conn.close()
    assert len(remaining) == 2, (
        "the simulated crash must leave exactly the first 2 rows committed -- a contiguous "
        "tail truncation (design decision 5), got "
        f"{len(remaining)} remaining row(s)"
    )

    # Recover: run again in INCREMENTAL mode with NO special recovery flag -- exactly what an
    # operator would do after a crash.
    await CrossSectionalSpreadTracker(_TEST_DB_URL, backfill=False).run()

    conn = await asyncpg.connect(_TEST_DB_URL)
    try:
        recovered_rows = await _fetch_rows(conn)
    finally:
        await conn.close()

    assert len(recovered_rows) == 4, (
        "the recovery run must bring the table back to exactly 4 rows with no duplicates, got "
        f"{len(recovered_rows)}"
    )
    recovered_by_bar_ts = {r["bar_ts"]: dict(r) for r in recovered_rows}

    third_bar_recovered = recovered_by_bar_ts[third_bar_ts]
    assert third_bar_recovered["one_way_turnover"] is not None
    assert third_bar_recovered["one_way_turnover"] not in (0.0, 1.0), (
        "the recomputed row for the first lost bar must have a turnover seeded from bar 2's "
        "SURVIVING persisted leg membership (design decision 5), not a fresh empty state -- "
        "the specific failure Codex's HIGH crash-recovery review concern named. Got "
        f"{third_bar_recovered['one_way_turnover']!r}"
    )

    compare_cols = (
        "long_leg_symbols",
        "short_leg_symbols",
        "gross_spread_fast",
        "gross_spread_slow",
        "one_way_turnover",
        "net_spread_fast_by_cost_bps",
        "net_spread_slow_by_cost_bps",
    )
    for bar_ts in bar_timestamps[2:]:
        expected = reference_by_bar_ts[bar_ts]
        actual = recovered_by_bar_ts[bar_ts]
        for col in compare_cols:
            expected_val = expected[col]
            actual_val = actual[col]
            if col in ("net_spread_fast_by_cost_bps", "net_spread_slow_by_cost_bps"):
                expected_val = _decode_jsonb(expected_val)
                actual_val = _decode_jsonb(actual_val)
            assert actual_val == expected_val, (
                "design decision 5 / Codex's HIGH crash-recovery concern: the recovered row "
                f"for bar_ts={bar_ts} column {col!r} must equal the uninterrupted reference "
                f"run's value exactly (byte-identical measurement record) -- a gate verdict "
                f"computed after a crash-and-resume must be the same verdict that would have "
                f"been computed without the crash. Expected {expected_val!r}, got "
                f"{actual_val!r}"
            )
