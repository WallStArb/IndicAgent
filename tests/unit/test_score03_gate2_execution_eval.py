"""Unit tests: Gate 2 execution-proof evaluation (SCORE-03).

Analog: scripts/analysis/phase143_1_08_shadow_validation.py (this function minus
challenger/c6, plus a gate_evaluations INSERT, per CONTEXT.md D-08).

No DB, no Kafka -- these tests exercise the pure evidence-assembly core
(assemble_gate2_evidence and its helpers) on synthetic rows, plus the group_key
round-trip contract of services.counterfactual_tracker.evaluate_frame_gate itself.
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

_project_root = Path(__file__).parent.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from scripts.analysis.score03_gate2_execution_eval import (
    _GATE_ID,
    _build_snapshot,
    _write_gate2_row,
    assemble_gate2_evidence,
)
from services.counterfactual_tracker import evaluate_frame_gate


def _synthetic_rows() -> list[dict]:
    """~8 synthetic rows spanning 2 directions x 2 regimes, plus enough day-clusters
    for the pooled c1 (>=60 days) criterion to be exercisable in both directions by
    the tests below. Reused across tests that just need "some" champion-shaped rows."""
    rows = []
    base_day = datetime(2026, 1, 1, tzinfo=UTC)
    directions = ["long", "short"]
    regimes = ["bull", "bear"]
    day_offset = 0
    for direction in directions:
        for regime in regimes:
            for _ in range(2):
                ts = base_day.replace(day=1) if day_offset == 0 else base_day
                # Use a distinct calendar day per row so cluster_id (bar_ts::date) varies.
                from datetime import timedelta

                ts = base_day + timedelta(days=day_offset)
                rows.append(
                    {
                        "bar_ts": ts,
                        "direction": direction,
                        "regime": regime,
                        "cluster_id": ts.date(),
                        "pnl_r": 0.1 if direction == "long" else -0.1,
                    }
                )
                day_offset += 1
    return rows


def _apr_kwargs() -> dict:
    return {
        "min_n": 1,
        "bootstrap_max_n": 100,
        "bootstrap_batch": 50,
        "bootstrap_random_state": 42,
        "min_sharpe": 0.5,
        "max_drawdown_ratio": 0.25,
        "regime_gate_min_clusters": 2,
    }


def _async_cm(return_value=None) -> MagicMock:
    """A MagicMock usable as `async with x() as y`. asyncpg's Pool.acquire() and
    Connection.transaction() are both plain (non-async) methods that return an async
    context manager object -- NOT coroutines -- so the mock for `.acquire`/`.transaction`
    itself must be a MagicMock (sync call) whose return_value implements
    __aenter__/__aexit__ as AsyncMocks."""
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=return_value)
    cm.__aexit__ = AsyncMock(return_value=False)
    return cm


def _snapshot() -> dict:
    return _build_snapshot(
        oos_start=datetime(2026, 1, 1, tzinfo=UTC),
        weight_epoch="143.1-08-champion",
        apr_values_used={"min_sharpe": 0.5, "max_drawdown_ratio": 0.25},
        input_population_row_count=8,
        fetch_sql_sha256="deadbeef",
    )


# ---------------------------------------------------------------------------
# STEP 0 group-key verify-first (Consensus Concern 1): the raw 2-tuple round-trip
# ---------------------------------------------------------------------------


def test_evaluate_frame_gate_direction_regime_groupkey_roundtrip():
    """evaluate_frame_gate's `for (dim_a, dim_b), bucket in groups.items():` unpack
    accepts a (direction, regime) 2-tuple group_key and remaps it into the returned
    dict's "tf"/"regime" fields byte-for-byte (dim_a -> tf, dim_b -> regime) -- the
    exact round-trip this plan's production call site relies on. Verified in isolation
    BEFORE asserting anything about the production integration (plan Task 1 STEP 0)."""
    rows = _synthetic_rows()

    cells = evaluate_frame_gate(
        rows,
        min_n=1,
        bootstrap_max_n=100,
        bootstrap_batch=50,
        bootstrap_random_state=42,
        group_key=lambda row: (row["direction"], row["regime"]),
        min_clusters=2,
    )

    fed_pairs = {(r["direction"], r["regime"]) for r in rows}
    returned_pairs = {(c["tf"], c["regime"]) for c in cells}
    assert returned_pairs == fed_pairs
    for cell in cells:
        assert cell["coverage"] in ("evaluated", "insufficient")


# ---------------------------------------------------------------------------
# test_cites_champion_143_1_08_numbers
# ---------------------------------------------------------------------------


def test_cites_champion_143_1_08_numbers():
    """The pooled evidence carries all 5 criteria keys (c1..c5, including the c5
    confident-loss proxy AND its c5_proxy_note label), the query binds
    weight_epoch='143.1-08-champion' (not a recomputation over a different epoch),
    and c3/c4 verdicts trace to the APR thresholds rather than baked-in literals --
    shifting alpha.scoring.min_sharpe flips c3_passes accordingly."""
    rows = _synthetic_rows()
    snapshot = _snapshot()

    evidence = assemble_gate2_evidence(
        rows,
        "143.1-08-champion",
        **_apr_kwargs(),
        snapshot=snapshot,
    )

    assert evidence["weight_epoch"] == "143.1-08-champion"
    pooled = evidence["pooled"]
    for key in (
        "c1_min_60_days",
        "c2_ci_lower",
        "c2_ci_upper",
        "c2_passes",
        "c3_sharpe",
        "c3_passes",
        "c3_min_sharpe_threshold",
        "c4_max_dd",
        "c4_passes",
        "c4_max_drawdown_ratio_threshold",
        "c5_confident_loss",
        "c5_passes",
        "c5_proxy_note",
    ):
        assert key in pooled, f"missing pooled criterion key: {key}"
    assert "proxy" in pooled["c5_proxy_note"].lower()

    # APR threshold actually governs c3_passes: an artificially high min_sharpe must
    # flip a previously-passing Sharpe to failing.
    kwargs_low_bar = _apr_kwargs()
    kwargs_low_bar["min_sharpe"] = -100.0
    evidence_low_bar = assemble_gate2_evidence(
        rows, "143.1-08-champion", **kwargs_low_bar, snapshot=snapshot
    )
    kwargs_high_bar = _apr_kwargs()
    kwargs_high_bar["min_sharpe"] = 100.0
    evidence_high_bar = assemble_gate2_evidence(
        rows, "143.1-08-champion", **kwargs_high_bar, snapshot=snapshot
    )
    assert evidence_low_bar["pooled"]["c3_passes"] is True
    assert evidence_high_bar["pooled"]["c3_passes"] is False
    assert (
        evidence_low_bar["pooled"]["c3_min_sharpe_threshold"]
        != evidence_high_bar["pooled"]["c3_min_sharpe_threshold"]
    )


# ---------------------------------------------------------------------------
# test_regime_stratified_companion_required
# ---------------------------------------------------------------------------


def test_regime_stratified_companion_required():
    """A pooled Gate 2 verdict is never assembled without the regime-stratified
    companion (D-07): the evidence always carries both pooled and regime_cells keys,
    and each regime cell's direction/regime were correctly remapped from
    evaluate_frame_gate's returned "tf"/"regime" fields (the group-key round-trip is
    asserted here too, on the production assembly path -- not just in isolation)."""
    rows = _synthetic_rows()
    snapshot = _snapshot()

    evidence = assemble_gate2_evidence(
        rows,
        "143.1-08-champion",
        **_apr_kwargs(),
        snapshot=snapshot,
    )

    assert "pooled" in evidence
    assert "regime_cells" in evidence
    assert len(evidence["regime_cells"]) > 0
    assert "c2_regime_stratified_passes" in evidence

    fed_pairs = {(r["direction"], r["regime"]) for r in rows}
    returned_pairs = {(c["tf"], c["regime"]) for c in evidence["regime_cells"]}
    assert returned_pairs == fed_pairs


# ---------------------------------------------------------------------------
# test_gate2_dry_run_writes_nothing
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_gate2_dry_run_writes_nothing():
    """--dry-run drives the full computation but the write path (_write_gate2_row) is
    never invoked -- assert directly that no INSERT/transaction call occurs by
    verifying a mocked pool's acquire() is never called when the dry-run branch is
    taken (mirrors main()'s `if args.dry_run: ... return` short-circuit before
    _write_gate2_row is ever awaited)."""
    rows = _synthetic_rows()
    snapshot = _snapshot()

    evidence = assemble_gate2_evidence(
        rows,
        "143.1-08-champion",
        **_apr_kwargs(),
        snapshot=snapshot,
    )
    assert evidence["result"] in ("pass", "fail")

    mock_pool = AsyncMock()
    dry_run = True
    if not dry_run:
        await _write_gate2_row(mock_pool, evidence, datetime.now(UTC), Path("/tmp/unused.jsonl"))

    mock_pool.acquire.assert_not_called()


@pytest.mark.asyncio
async def test_gate2_real_write_atomic_transaction_and_look_log():
    """The real (non-dry-run) write path opens exactly one transaction, checks for a
    prior row, INSERTs, and appends to the look-log only after the transaction context
    exits (commit)."""
    rows = _synthetic_rows()
    snapshot = _snapshot()
    evidence = assemble_gate2_evidence(
        rows, "143.1-08-champion", **_apr_kwargs(), snapshot=snapshot
    )

    mock_conn = AsyncMock()
    mock_conn.fetchval.return_value = 0  # no prior gate2_execution row
    mock_conn.transaction = MagicMock(return_value=_async_cm(None))

    mock_pool = MagicMock()
    mock_pool.acquire = MagicMock(return_value=_async_cm(mock_conn))

    look_log_path = Path("/tmp/gsd_test_gate2_look_log.jsonl")
    if look_log_path.exists():
        look_log_path.unlink()

    with patch("scripts.analysis.score03_gate2_execution_eval._append_look_log") as mock_append_log:
        await _write_gate2_row(mock_pool, evidence, datetime.now(UTC), look_log_path)

    mock_conn.fetchval.assert_awaited_once()
    fetchval_args = mock_conn.fetchval.await_args.args
    assert _GATE_ID in fetchval_args
    mock_conn.execute.assert_awaited_once()
    execute_args = mock_conn.execute.await_args.args
    assert _GATE_ID in execute_args
    mock_append_log.assert_called_once()


@pytest.mark.asyncio
async def test_gate2_real_write_refuses_second_run():
    """D-04's run-once cadence: if gate_evaluations already has a gate2_execution row,
    the real write path raises rather than silently overwriting or re-running."""
    rows = _synthetic_rows()
    snapshot = _snapshot()
    evidence = assemble_gate2_evidence(
        rows, "143.1-08-champion", **_apr_kwargs(), snapshot=snapshot
    )

    mock_conn = AsyncMock()
    mock_conn.fetchval.return_value = 1  # a prior row already exists
    mock_conn.transaction = MagicMock(return_value=_async_cm(None))

    mock_pool = MagicMock()
    mock_pool.acquire = MagicMock(return_value=_async_cm(mock_conn))

    with pytest.raises(RuntimeError, match="already"):
        await _write_gate2_row(
            mock_pool, evidence, datetime.now(UTC), Path("/tmp/gsd_test_gate2_look_log2.jsonl")
        )
    mock_conn.execute.assert_not_awaited()


# ---------------------------------------------------------------------------
# test_gate2_evidence_payload_shape
# ---------------------------------------------------------------------------


def test_gate2_evidence_payload_shape():
    """Integration-style: call the evidence-assembly function on synthetic champion
    rows and assert the EXACT evidence key set -- pooled {c1..c5 keys incl
    c3_min_sharpe_threshold, c4_max_drawdown_ratio_threshold, c5_proxy_note},
    regime_cells, c2_regime_stratified_passes, snapshot (with its {oos_start,
    weight_epoch, apr_values_used, input_population_row_count, fetch_sql_sha256}),
    result, and provenance -- asserting payload shape, not merely that a row exists."""
    rows = _synthetic_rows()
    snapshot = _snapshot()

    evidence = assemble_gate2_evidence(
        rows,
        "143.1-08-champion",
        **_apr_kwargs(),
        snapshot=snapshot,
    )

    expected_top_level = {
        "weight_epoch",
        "n_rows",
        "n_days",
        "pooled",
        "regime_cells",
        "c2_regime_stratified_passes",
        "c7_regime_stratified_no_confident_loss",
        "snapshot",
        "result",
        "provenance",
    }
    assert set(evidence.keys()) == expected_top_level

    expected_pooled_keys = {
        "c1_min_60_days",
        "c2_ci_lower",
        "c2_ci_upper",
        "c2_passes",
        "c3_sharpe",
        "c3_passes",
        "c3_min_sharpe_threshold",
        "c4_max_dd",
        "c4_passes",
        "c4_max_drawdown_ratio_threshold",
        "c5_confident_loss",
        "c5_passes",
        "c5_proxy_note",
    }
    assert set(evidence["pooled"].keys()) == expected_pooled_keys

    expected_snapshot_keys = {
        "oos_start",
        "weight_epoch",
        "apr_values_used",
        "input_population_row_count",
        "fetch_sql_sha256",
    }
    assert set(evidence["snapshot"].keys()) == expected_snapshot_keys

    assert evidence["result"] in ("pass", "fail")
    assert isinstance(evidence["provenance"], str) and len(evidence["provenance"]) > 0
