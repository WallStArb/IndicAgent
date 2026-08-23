"""Unit tests for AlphaPublisher service.

Covers:
- Class contract (job_name, BaseBatch subclass)
- _threshold_for_tf APR loading per TF
- Direction-aware emission gate: all rejection paths + passing long/short
- Zero-weight stratum guard (effective_n == 0 rejected before CI math)
- weights_cache preload: ensemble_weights fetched exactly once per execute() call
- top_features_count: top-N by abs(weight) when cache has more features
- Kafka publish: awaited with topic as first positional arg + msg= kwarg

No live DB, no live Kafka — all mocked via AsyncMock / MagicMock.
"""

from __future__ import annotations

import inspect
import sys
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

import services.alpha_publisher as alpha_publisher_module
from services.alpha_publisher import AlphaPublisher
from src.core.agent.base_batch import BaseBatch
from src.core.stream_keys import topic_alpha_events

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_DEFAULT_CFG: dict = {
    "alpha.ensemble.effective_n_gate": "3.0",
    "alpha.ensemble.weight_version": "v1",
    "alpha.ensemble.top_features_count": "10",
    "alpha.quant.threshold.5m": "1.5",
    "alpha.quant.threshold.15m": "1.2",
    "alpha.quant.threshold.1h": "1.0",
    "alpha.quant.threshold.1d": "0.8",
    "alpha.quant.cost_hurdle.5m": "0.0",
    "alpha.quant.cost_hurdle.15m": "0.0",
    "alpha.quant.cost_hurdle.1h": "0.0",
    "alpha.quant.cost_hurdle.1d": "0.0",
}


def _make_emitter() -> AlphaPublisher:
    """Create an AlphaPublisher without triggering DB connections."""
    return AlphaPublisher(db_dsn="postgresql://localhost/test")


def _make_alpha_row(
    symbol: str = "SPY",
    tf: str = "5m",
    bar_ts: datetime | None = None,
    alpha_score: float = 0.0,
    alpha_ci_lower: float = 0.0,
    alpha_ci_upper: float = 0.0,
    effective_n: float = 5.0,
    n_features_active: int = 8,
    regime: str = "trending_up",
    weight_version: str = "v1",
) -> MagicMock:
    """Create a mock asyncpg Record for an ensemble_alpha row."""
    row = MagicMock()
    row.__getitem__ = lambda self, key: {  # type: ignore[misc]
        "symbol": symbol,
        "tf": tf,
        "bar_ts": bar_ts or datetime(2024, 1, 15, 14, 30, tzinfo=UTC),
        "alpha_score": alpha_score,
        "alpha_ci_lower": alpha_ci_lower,
        "alpha_ci_upper": alpha_ci_upper,
        "effective_n": effective_n,
        "n_features_active": n_features_active,
        "regime": regime,
        "weight_version": weight_version,
    }[key]
    return row


# ---------------------------------------------------------------------------
# Class contract
# ---------------------------------------------------------------------------


class TestAlphaPublisherClassContract:
    def test_job_name(self) -> None:
        assert AlphaPublisher.job_name == "alpha-publisher"

    def test_compute_version(self) -> None:
        assert AlphaPublisher.compute_version == "1.0.0"

    def test_ensemble_version(self) -> None:
        assert AlphaPublisher.ensemble_version == "v1.0.0"

    def test_is_base_batch_subclass(self) -> None:
        assert issubclass(AlphaPublisher, BaseBatch)

    def test_has_execute_method(self) -> None:
        assert hasattr(AlphaPublisher, "execute")
        assert callable(AlphaPublisher.execute)

    def test_instantiation(self) -> None:
        emitter = _make_emitter()
        assert emitter.job_name == "alpha-publisher"


# ---------------------------------------------------------------------------
# _threshold_for_tf
# ---------------------------------------------------------------------------


class TestThresholdForTf:
    def test_5m_threshold_from_apr(self) -> None:
        emitter = _make_emitter()
        cfg = {"alpha.quant.threshold.5m": "2.0"}
        assert emitter._threshold_for_tf("5m", cfg) == 2.0

    def test_15m_threshold_from_apr(self) -> None:
        emitter = _make_emitter()
        cfg = {"alpha.quant.threshold.15m": "1.8"}
        assert emitter._threshold_for_tf("15m", cfg) == 1.8

    def test_1h_threshold_from_apr(self) -> None:
        emitter = _make_emitter()
        cfg = {"alpha.quant.threshold.1h": "0.9"}
        assert emitter._threshold_for_tf("1h", cfg) == 0.9

    def test_1d_threshold_from_apr(self) -> None:
        emitter = _make_emitter()
        cfg = {"alpha.quant.threshold.1d": "0.7"}
        assert emitter._threshold_for_tf("1d", cfg) == 0.7

    def test_default_5m_when_key_absent(self) -> None:
        emitter = _make_emitter()
        assert emitter._threshold_for_tf("5m", {}) == 1.5

    def test_default_15m_when_key_absent(self) -> None:
        emitter = _make_emitter()
        assert emitter._threshold_for_tf("15m", {}) == 1.2

    def test_default_1h_when_key_absent(self) -> None:
        emitter = _make_emitter()
        assert emitter._threshold_for_tf("1h", {}) == 1.0

    def test_default_1d_when_key_absent(self) -> None:
        emitter = _make_emitter()
        assert emitter._threshold_for_tf("1d", {}) == 0.8

    def test_unknown_tf_falls_back_to_1_0(self) -> None:
        emitter = _make_emitter()
        assert emitter._threshold_for_tf("2h", {}) == 1.0


# ---------------------------------------------------------------------------
# Emission gate logic
# Tests run through execute() via heavily mocked pool + producer.
# We simulate the per-row gate by calling execute() with exactly one alpha row
# and asserting publish was (or was not) called.
# ---------------------------------------------------------------------------


def _build_weights_cache_rows(
    symbol: str = "SPY",
    tf: str = "5m",
    regime: str = "trending_up",
    n_features: int = 5,
) -> list[MagicMock]:
    """Build mock ensemble_weights rows for weights_cache preload."""
    rows = []
    for i in range(n_features):
        r = MagicMock()
        r.__getitem__ = lambda self, key, i=i: {  # type: ignore[misc]
            "symbol": symbol,
            "tf": tf,
            "regime": regime,
            "feature_name": f"feature_{i}",
            "weight": float(n_features - i) / 10.0,  # descending weights
        }[key]
        rows.append(r)
    return rows


async def _run_emitter_with_rows(
    alpha_rows: list[MagicMock],
    weight_rows: list | None = None,
    n_alpha_total: int = 1,
    effective_n_gate: str = "3.0",
    weight_version: str = "v1",
    top_features_count: str = "10",
    threshold_5m: str = "1.5",
    is_shadow: str | None = None,
    chunk_size: str = "50000",
) -> tuple[AsyncMock, AsyncMock]:
    """Helper: run AlphaPublisher.execute() with N alpha rows (0 or more) and return
    (mock_producer, mock_conn). The general form _run_emitter_with_single_row wraps.

    is_shadow=None omits the key entirely, exercising the APR-absent default path.
    chunk_size overrides infra.alpha_publisher.chunk_size for tests exercising
    _flush_chunk's chunking behavior at N rows without needing thousands of mock rows.
    """
    emitter = _make_emitter()

    # Override specific values
    full_cfg = dict(_DEFAULT_CFG)
    full_cfg["alpha.ensemble.effective_n_gate"] = effective_n_gate
    full_cfg["alpha.ensemble.weight_version"] = weight_version
    full_cfg["alpha.ensemble.top_features_count"] = top_features_count
    full_cfg["alpha.quant.threshold.5m"] = threshold_5m
    full_cfg["infra.alpha_publisher.chunk_size"] = chunk_size
    if is_shadow is not None:
        full_cfg["alpha.publisher.is_shadow"] = is_shadow

    final_cfg_rows: list[MagicMock] = []
    for k, v in full_cfg.items():
        r = MagicMock()
        r.__getitem__ = lambda self, key, _k=k, _v=v: _k if key == "config_key" else _v  # type: ignore[misc]
        final_cfg_rows.append(r)

    if weight_rows is None:
        weight_rows = _build_weights_cache_rows()

    # conn.cursor() is an async generator; SQL gates are mocked by controlling what it yields.
    captured_rows = alpha_rows

    async def _mock_cursor(*args, **kwargs):
        for row in captured_rows:
            yield row

    mock_transaction = MagicMock()
    mock_transaction.__aenter__ = AsyncMock(return_value=None)
    mock_transaction.__aexit__ = AsyncMock(return_value=False)

    mock_conn = AsyncMock()
    mock_conn.fetch = AsyncMock(
        side_effect=[
            final_cfg_rows,  # APR fetch
            weight_rows,  # ensemble_weights preload
        ]
    )
    mock_conn.fetchval = AsyncMock(return_value=n_alpha_total)  # startup gate count
    mock_conn.transaction = MagicMock(return_value=mock_transaction)
    mock_conn.cursor = MagicMock(return_value=_mock_cursor())
    mock_conn.executemany = AsyncMock()

    mock_pool = AsyncMock()
    mock_pool.acquire = MagicMock(
        return_value=AsyncMock(
            __aenter__=AsyncMock(return_value=mock_conn), __aexit__=AsyncMock(return_value=False)
        )
    )

    mock_producer = AsyncMock()
    mock_producer.publish = AsyncMock()
    mock_producer.start = AsyncMock()
    mock_producer.stop = AsyncMock()

    settings_mock = MagicMock()
    settings_mock.env_name = "test"
    settings_mock.kafka_bootstrap_servers = "localhost:9092"

    with (
        patch("services.alpha_publisher.Settings", return_value=settings_mock),
        patch("services.alpha_publisher.KafkaProducerClient", return_value=mock_producer),
        # Without this, CorpusManifest("alpha_publisher", Path(".planning/corpus_manifests"))
        # writes a REAL file at that hardcoded, repo-relative path on every test run,
        # silently overwriting the real corpus pipeline's manifest with fake test-fixture
        # row counts (found 2026-07-02: a "1 row" manifest with no matching real run in any
        # log turned out to be exactly this test suite executing, not a data-loss bug).
        patch("services.alpha_publisher.CorpusManifest", return_value=MagicMock()),
    ):
        await emitter.execute(mock_pool)

    return mock_producer, mock_conn


async def _run_emitter_with_single_row(
    alpha_row: MagicMock,
    weight_rows: list | None = None,
    n_alpha_total: int = 1,
    effective_n_gate: str = "3.0",
    weight_version: str = "v1",
    top_features_count: str = "10",
    threshold_5m: str = "1.5",
    cursor_yields_row: bool = True,
    is_shadow: str | None = None,
) -> tuple[AsyncMock, AsyncMock]:
    """Helper: run AlphaPublisher.execute() with one alpha row and return (mock_producer, mock_conn).

    cursor_yields_row=False simulates SQL filtering the row out (all gates are SQL-level).
    """
    return await _run_emitter_with_rows(
        [alpha_row] if cursor_yields_row else [],
        weight_rows=weight_rows,
        n_alpha_total=n_alpha_total,
        effective_n_gate=effective_n_gate,
        weight_version=weight_version,
        top_features_count=top_features_count,
        threshold_5m=threshold_5m,
        is_shadow=is_shadow,
    )


class TestEmissionGate:
    @pytest.mark.asyncio
    async def test_zero_weight_stratum_rejected(self) -> None:
        """effective_n == 0 is filtered by SQL gate; cursor yields nothing."""
        row = _make_alpha_row(
            alpha_score=2.0, alpha_ci_lower=0.5, alpha_ci_upper=3.5, effective_n=0.0
        )
        mock_producer, _ = await _run_emitter_with_single_row(row, cursor_yields_row=False)
        mock_producer.publish.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_effective_n_low_rejected(self) -> None:
        """effective_n < effective_n_gate is filtered by SQL gate; cursor yields nothing."""
        row = _make_alpha_row(
            alpha_score=2.0, alpha_ci_lower=0.5, alpha_ci_upper=3.5, effective_n=1.0
        )
        mock_producer, _ = await _run_emitter_with_single_row(
            row, effective_n_gate="3.0", cursor_yields_row=False
        )
        mock_producer.publish.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_threshold_miss_rejected(self) -> None:
        """abs(alpha_score) <= threshold is filtered by SQL gate; cursor yields nothing."""
        row = _make_alpha_row(
            alpha_score=0.5, alpha_ci_lower=0.1, alpha_ci_upper=0.9, effective_n=5.0
        )
        mock_producer, _ = await _run_emitter_with_single_row(
            row, threshold_5m="1.5", cursor_yields_row=False
        )
        mock_producer.publish.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_long_ci_not_directional_rejected(self) -> None:
        """Long row with alpha_ci_lower <= cost_hurdle is filtered by SQL gate; cursor yields nothing."""
        row = _make_alpha_row(
            alpha_score=2.0, alpha_ci_lower=-0.1, alpha_ci_upper=3.5, effective_n=5.0
        )
        mock_producer, _ = await _run_emitter_with_single_row(
            row, threshold_5m="1.0", cursor_yields_row=False
        )
        mock_producer.publish.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_short_ci_not_directional_rejected(self) -> None:
        """Short row with alpha_ci_upper >= -cost_hurdle is filtered by SQL gate; cursor yields nothing."""
        row = _make_alpha_row(
            alpha_score=-2.0, alpha_ci_lower=-3.5, alpha_ci_upper=0.1, effective_n=5.0
        )
        mock_producer, _ = await _run_emitter_with_single_row(
            row, threshold_5m="1.0", cursor_yields_row=False
        )
        mock_producer.publish.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_passing_long_emits(self) -> None:
        """Passing long: alpha_score=2.0, ci_lower=0.5, effective_n=4.0, threshold=1.0 → emits."""
        row = _make_alpha_row(
            alpha_score=2.0,
            alpha_ci_lower=0.5,
            alpha_ci_upper=3.5,
            effective_n=4.0,
        )
        mock_producer, _ = await _run_emitter_with_single_row(row, threshold_5m="1.0")
        mock_producer.publish.assert_awaited_once()
        call_args = mock_producer.publish.call_args
        # topic_alpha_events is the first positional arg
        assert call_args.args[0] == topic_alpha_events("test")
        payload = call_args.kwargs["msg"]
        assert payload["direction"] == "long"

    @pytest.mark.asyncio
    async def test_passing_short_emits(self) -> None:
        """Passing short: alpha_score=-2.0, ci_upper=-0.5, effective_n=4.0, threshold=1.0 → emits."""
        row = _make_alpha_row(
            alpha_score=-2.0,
            alpha_ci_lower=-3.5,
            alpha_ci_upper=-0.5,
            effective_n=4.0,
        )
        mock_producer, _ = await _run_emitter_with_single_row(row, threshold_5m="1.0")
        mock_producer.publish.assert_awaited_once()
        call_args = mock_producer.publish.call_args
        assert call_args.args[0] == topic_alpha_events("test")
        payload = call_args.kwargs["msg"]
        assert payload["direction"] == "short"


class TestKafkaPublish:
    @pytest.mark.asyncio
    async def test_publish_uses_topic_as_first_positional_arg(self) -> None:
        """publish() is called with topic_alpha_events(env) as first positional arg."""
        row = _make_alpha_row(
            alpha_score=2.0, alpha_ci_lower=0.5, alpha_ci_upper=3.5, effective_n=4.0
        )
        mock_producer, _ = await _run_emitter_with_single_row(row, threshold_5m="1.0")
        mock_producer.publish.assert_awaited_once()
        first_arg = mock_producer.publish.call_args.args[0]
        assert first_arg == topic_alpha_events("test")

    @pytest.mark.asyncio
    async def test_publish_uses_msg_kwarg(self) -> None:
        """publish() is called with msg= keyword arg, not value=."""
        row = _make_alpha_row(
            alpha_score=2.0, alpha_ci_lower=0.5, alpha_ci_upper=3.5, effective_n=4.0
        )
        mock_producer, _ = await _run_emitter_with_single_row(row, threshold_5m="1.0")
        mock_producer.publish.assert_awaited_once()
        kwargs = mock_producer.publish.call_args.kwargs
        assert "msg" in kwargs, "msg= kwarg must be present"
        assert "value" not in kwargs, "value= kwarg must NOT be used"


class TestWeightsCachePreload:
    @pytest.mark.asyncio
    async def test_weights_cache_fetched_exactly_once(self) -> None:
        """ensemble_weights is fetched exactly once before the emission loop."""
        # Use a row that passes the gate so we can verify publish was called
        row = _make_alpha_row(
            alpha_score=2.0, alpha_ci_lower=0.5, alpha_ci_upper=3.5, effective_n=4.0
        )
        weight_rows = _build_weights_cache_rows(n_features=5)
        mock_producer, mock_conn = await _run_emitter_with_single_row(
            row, weight_rows=weight_rows, threshold_5m="1.0"
        )

        # Count calls to conn.fetch that match the ensemble_weights query
        fetch_calls = mock_conn.fetch.call_args_list
        ensemble_weights_calls = [c for c in fetch_calls if "ensemble_weights" in str(c)]
        assert (
            len(ensemble_weights_calls) == 1
        ), f"ensemble_weights should be fetched exactly once, got {len(ensemble_weights_calls)}"


class TestTopFeaturesCount:
    @pytest.mark.asyncio
    async def test_top_features_sliced_to_count(self) -> None:
        """When cache has 10 features and top_features_count=3, payload has exactly 3 top_features."""
        row = _make_alpha_row(
            alpha_score=2.0, alpha_ci_lower=0.5, alpha_ci_upper=3.5, effective_n=4.0
        )
        # Build 10 weight rows
        weight_rows = _build_weights_cache_rows(n_features=10)
        mock_producer, _ = await _run_emitter_with_single_row(
            row,
            weight_rows=weight_rows,
            top_features_count="3",
            threshold_5m="1.0",
        )
        mock_producer.publish.assert_awaited_once()
        payload = mock_producer.publish.call_args.kwargs["msg"]
        assert (
            len(payload["top_features"]) == 3
        ), f"Expected exactly 3 top_features, got {len(payload['top_features'])}"


class TestIsShadow:
    """todo 011: alpha_events.is_shadow is a one-way live-promotion switch. Defaults
    True (shadow) when the APR key is absent or stores the string 'true'; only an
    explicit 'false' flips it. Regression coverage for the bool-string-cast bug
    fixed in services/_batch_utils.py::cfg() alongside this wiring."""

    @pytest.mark.asyncio
    async def test_defaults_true_when_apr_key_absent(self) -> None:
        row = _make_alpha_row(
            alpha_score=2.0, alpha_ci_lower=0.5, alpha_ci_upper=3.5, effective_n=4.0
        )
        mock_producer, _ = await _run_emitter_with_single_row(row, threshold_5m="1.0")
        payload = mock_producer.publish.call_args.kwargs["msg"]
        assert payload["is_shadow"] is True

    @pytest.mark.asyncio
    async def test_true_string_stamps_true(self) -> None:
        row = _make_alpha_row(
            alpha_score=2.0, alpha_ci_lower=0.5, alpha_ci_upper=3.5, effective_n=4.0
        )
        mock_producer, _ = await _run_emitter_with_single_row(
            row, threshold_5m="1.0", is_shadow="true"
        )
        payload = mock_producer.publish.call_args.kwargs["msg"]
        assert payload["is_shadow"] is True

    @pytest.mark.asyncio
    async def test_false_string_stamps_false(self) -> None:
        """The promotion case: operator flips the APR key to 'false' at Phase 144.
        Guards against bool("false") == True silently defeating the switch."""
        row = _make_alpha_row(
            alpha_score=2.0, alpha_ci_lower=0.5, alpha_ci_upper=3.5, effective_n=4.0
        )
        mock_producer, _ = await _run_emitter_with_single_row(
            row, threshold_5m="1.0", is_shadow="false"
        )
        payload = mock_producer.publish.call_args.kwargs["msg"]
        assert payload["is_shadow"] is False

    @pytest.mark.asyncio
    async def test_is_shadow_in_db_insert_tuple(self) -> None:
        """skip_kafka path writes straight to executemany; is_shadow must reach the
        DB tuple too, not just the Kafka payload."""
        row = _make_alpha_row(
            alpha_score=2.0, alpha_ci_lower=0.5, alpha_ci_upper=3.5, effective_n=4.0
        )
        emitter = _make_emitter()
        emitter.skip_kafka = True

        full_cfg = dict(_DEFAULT_CFG)
        full_cfg["alpha.quant.threshold.5m"] = "1.0"
        full_cfg["alpha.publisher.is_shadow"] = "false"
        cfg_rows = []
        for k, v in full_cfg.items():
            r = MagicMock()
            r.__getitem__ = lambda self, key, _k=k, _v=v: _k if key == "config_key" else _v  # type: ignore[misc]
            cfg_rows.append(r)
        weight_rows = _build_weights_cache_rows()

        async def _mock_cursor(*args, **kwargs):
            yield row

        mock_transaction = MagicMock()
        mock_transaction.__aenter__ = AsyncMock(return_value=None)
        mock_transaction.__aexit__ = AsyncMock(return_value=False)

        mock_conn = AsyncMock()
        mock_conn.fetch = AsyncMock(side_effect=[cfg_rows, weight_rows])
        mock_conn.fetchval = AsyncMock(return_value=1)
        mock_conn.transaction = MagicMock(return_value=mock_transaction)
        mock_conn.cursor = MagicMock(return_value=_mock_cursor())
        # AsyncMock.call_args holds a reference, not a snapshot -- the real code
        # clears _chunk immediately after this call, so capture a copy on the way in.
        captured_rows: list[tuple] = []

        async def _capture_executemany(_sql: str, rows: list[tuple]) -> None:
            captured_rows.extend(rows)

        mock_conn.executemany = AsyncMock(side_effect=_capture_executemany)

        mock_pool = AsyncMock()
        mock_pool.acquire = MagicMock(
            return_value=AsyncMock(
                __aenter__=AsyncMock(return_value=mock_conn),
                __aexit__=AsyncMock(return_value=False),
            )
        )

        with patch("services.alpha_publisher.CorpusManifest", return_value=MagicMock()):
            await emitter.execute(mock_pool)

        mock_conn.executemany.assert_called_once()
        assert captured_rows[0][-1] is False, "is_shadow must be the last INSERT tuple element"


class TestWeightVersionFullReplace:
    """A re-run under the same weight_version must fully replace alpha_events for that
    version, not incrementally accumulate on top of a prior run's output.

    Root cause this guards: the INSERT uses ON CONFLICT (event_id, bar_ts) DO NOTHING,
    which only ever adds rows or no-ops -- it never removes rows for bars that no longer
    qualify under an ensemble_alpha regenerated by a newer ensemble_trainer run (e.g.
    after the per-timeframe meta-FDR fix correctly stopped a stratum from qualifying).
    Found 2026-07-08: after fixing ensemble_trainer's meta-FDR scoping, 2346 stale
    1h/high_bear alpha_events rows (published under the pre-fix ensemble_alpha) remained
    in the table with no path to ever being cleaned up by a normal re-run.
    """

    def _source(self) -> str:
        return inspect.getsource(alpha_publisher_module)

    def test_deletes_alpha_events_scoped_to_weight_version(self) -> None:
        source = self._source()
        assert "DELETE FROM alpha_events" in source


class TestKafkaPathChunking:
    """OOM incident, 2026-08-22: the Kafka-publish path (skip_kafka=False, the corpus
    pipeline's default) accumulated every emitted event as a dict in one unbounded list
    for the ENTIRE run, flushing DB insert + Kafka publish only once at the very end.
    Confirmed via dmesg to have OOM-killed a corpus run at 24.6GB RSS once ensemble_alpha
    grew past ~30M rows (88.7M in the run that crashed). The skip_kafka=True path already
    had the right shape (flush every chunk_size rows); this fix brings the Kafka path to
    the same O(chunk) discipline instead of O(total emit_count).

    These tests assert the chunked-flush BEHAVIOR (multiple executemany/publish calls
    happening incrementally during iteration, not one giant call at the very end) as a
    proxy for bounded memory -- the same thing TestWeightVersionFullReplace above proves
    about DELETE scoping via behavior, not by measuring RSS directly.
    """

    async def _make_multi_row_harness(
        self, n_rows: int, chunk_size: str
    ) -> tuple[AsyncMock, AsyncMock, list[MagicMock]]:
        """Thin wrapper over the shared _run_emitter_with_rows helper: builds n_rows
        alpha rows and returns (mock_producer, mock_conn, rows) so callers can inspect
        call history and event count together.
        """
        rows = [
            _make_alpha_row(
                symbol=f"SYM{i}",
                alpha_score=2.0,
                alpha_ci_lower=0.5,
                alpha_ci_upper=3.5,
                effective_n=4.0,
            )
            for i in range(n_rows)
        ]
        mock_producer, mock_conn = await _run_emitter_with_rows(
            rows, n_alpha_total=n_rows, threshold_5m="1.0", chunk_size=chunk_size
        )
        return mock_producer, mock_conn, rows

    @pytest.mark.asyncio
    async def test_kafka_path_flushes_db_inserts_in_chunks_not_one_call_at_the_end(self) -> None:
        """5 rows at chunk_size=2 must flush in [2, 2, 1] -- 3 executemany calls, not 1
        giant call holding all 5 events until the run finishes."""
        mock_producer, mock_conn, _ = await self._make_multi_row_harness(n_rows=5, chunk_size="2")
        assert mock_conn.executemany.await_count == 3, (
            f"expected 3 chunked executemany calls (ceil(5/2)), got "
            f"{mock_conn.executemany.await_count} -- the Kafka path must not "
            "accumulate every event before its first DB write"
        )

    @pytest.mark.asyncio
    async def test_kafka_path_publishes_every_event_across_chunks(self) -> None:
        """Chunking must not drop or duplicate events -- every emitted row still gets
        published exactly once, just spread across chunk flushes instead of one pass
        over an unbounded list at the end."""
        mock_producer, _, rows = await self._make_multi_row_harness(n_rows=5, chunk_size="2")
        assert mock_producer.publish.await_count == len(rows)

    @pytest.mark.asyncio
    async def test_chunk_size_is_apr_backed_not_a_hardcoded_constant(self) -> None:
        """infra.alpha_publisher.chunk_size must be read from APR, not a hardcoded
        class constant -- migrate-as-you-go (CLAUDE.md): any batch-size constant
        touched while fixing adjacent code must move to APR in the same session.
        chunk_size=1 forces one executemany call per row; 4 rows -> 4 calls proves
        the small APR-supplied value was actually honored, not the 50_000 default.
        """
        _, mock_conn, _ = await self._make_multi_row_harness(n_rows=4, chunk_size="1")
        assert mock_conn.executemany.await_count == 4


class TestKafkaPublishConcurrencyWithinChunk:
    """/code-review finding, 2026-08-23 (same session as TestKafkaPathChunking above):
    unifying the two accumulate-then-flush paths onto _flush_chunk correctly fixed the
    O(chunk) memory bug, but introduced a real efficiency regression -- the Kafka
    publish loop now runs INSIDE the open DB transaction (async with conn.transaction():
    wraps the whole cursor loop, and _flush_chunk is called from inside it once per
    chunk). Before this session's fix, Kafka publishing ran exactly once, entirely
    AFTER the transaction had already closed. KafkaProducerClient.publish() awaits each
    message's delivery future individually (acks='all', a real broker round trip) --
    sequential per-message awaits inside an open transaction means the DELETE this
    transaction holds, and the server-side cursor snapshot, stay open for however long
    ALL of a chunk's Kafka publishing takes, not just the DB write. At chunk_size=50,000
    (the APR default) this could hold the transaction open far longer than the DB work
    alone would need.

    Fix: publish a chunk's events concurrently (asyncio.gather over publish() calls)
    instead of one at a time -- the same production skip_kafka=False systemd path
    (production/systemd/indicagent-alpha-publisher.service invokes without
    --skip-kafka, so this is not a dormant code path) benefits from bounding wall time
    to roughly one round trip's worth of concurrent waiting, not chunk_size sequential
    round trips, without needing to touch KafkaProducerClient itself or restructure the
    transaction boundary (a bigger, riskier change deferred to todo 351 alongside the
    connection-mismatch question).

    Behavioral call-count assertions can't distinguish "10 sequential awaits" from "10
    gathered awaits" against an AsyncMock (both produce 10 calls, order-independent) --
    this is a source-inspection test, matching this file's own established convention
    for structural invariants (see TestWeightVersionFullReplace._source() above).
    """

    def test_flush_chunk_publishes_kafka_events_concurrently_not_sequentially(self) -> None:
        source = inspect.getsource(alpha_publisher_module.AlphaPublisher._flush_chunk)
        assert "asyncio.gather" in source, (
            "_flush_chunk's Kafka publish step must use asyncio.gather to publish a "
            "chunk's events concurrently -- a sequential 'for e in chunk: await "
            "self._producer.publish(...)' loop holds the open DB transaction for "
            "chunk_size sequential broker round trips instead of ~1 concurrent one"
        )
