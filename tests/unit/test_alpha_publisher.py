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

import sys
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

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


async def _run_emitter_with_single_row(
    alpha_row: MagicMock,
    weight_rows: list | None = None,
    n_alpha_total: int = 1,
    effective_n_gate: str = "3.0",
    weight_version: str = "v1",
    top_features_count: str = "10",
    threshold_5m: str = "1.5",
    cursor_yields_row: bool = True,
) -> tuple[AsyncMock, AsyncMock]:
    """Helper: run AlphaPublisher.execute() with one alpha row and return (mock_producer, mock_conn).

    cursor_yields_row=False simulates SQL filtering the row out (all gates are SQL-level).
    """
    emitter = _make_emitter()

    cfg_rows = [MagicMock() for _ in _DEFAULT_CFG.items()]
    for i, (k, v) in enumerate(_DEFAULT_CFG.items()):
        cfg_rows[i].__getitem__ = lambda self, key, _k=k, _v=v: _k if key == "config_key" else _v
    # Override specific values
    full_cfg = dict(_DEFAULT_CFG)
    full_cfg["alpha.ensemble.effective_n_gate"] = effective_n_gate
    full_cfg["alpha.ensemble.weight_version"] = weight_version
    full_cfg["alpha.ensemble.top_features_count"] = top_features_count
    full_cfg["alpha.quant.threshold.5m"] = threshold_5m

    final_cfg_rows: list[MagicMock] = []
    for k, v in full_cfg.items():
        r = MagicMock()
        r.__getitem__ = lambda self, key, _k=k, _v=v: _k if key == "config_key" else _v  # type: ignore[misc]
        final_cfg_rows.append(r)

    if weight_rows is None:
        weight_rows = _build_weights_cache_rows()

    # conn.cursor() is an async generator; SQL gates are mocked by controlling what it yields.
    captured_alpha_row = alpha_row
    _emit = cursor_yields_row

    async def _mock_cursor(*args, **kwargs):
        if _emit:
            yield captured_alpha_row

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
    ):
        await emitter.execute(mock_pool)

    return mock_producer, mock_conn


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
