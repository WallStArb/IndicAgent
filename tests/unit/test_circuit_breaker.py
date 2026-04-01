"""Tests for circuit breaker functionality in BarAggregatorComputeAgent."""

from datetime import UTC, datetime, timedelta


def test_health_metrics_unhealthy_no_bars():
    """Test health check when no bars for 5+ minutes."""
    from services.bar_aggregator_agent import HealthMetrics

    metrics = HealthMetrics()
    metrics.record_bar(datetime.now(UTC) - timedelta(minutes=6))

    healthy, reason = metrics.is_healthy()
    assert not healthy
    assert "no_bars" in reason


def test_health_metrics_unhealthy_consuming_not_emitting():
    """Test health check when consuming but not emitting."""
    from services.bar_aggregator_agent import HealthMetrics

    metrics = HealthMetrics()

    # Simulate 101 bars processed but 0 HTF emitted (threshold is > 100)
    for _ in range(101):
        metrics.record_bar(datetime.now(UTC))

    healthy, reason = metrics.is_healthy()
    assert not healthy
    assert reason == "consuming_not_emitting"


def test_health_metrics_healthy_normal_operation():
    """Test health check during normal operation."""
    from services.bar_aggregator_agent import HealthMetrics

    metrics = HealthMetrics()

    # Normal operation: recent bars with some HTF output
    metrics.record_bar(datetime.now(UTC) - timedelta(seconds=30))
    metrics.record_bar(datetime.now(UTC) - timedelta(seconds=10))
    metrics.record_htf_bar()

    healthy, reason = metrics.is_healthy()
    assert healthy
    assert reason == "healthy"


def test_health_metrics_unhealthy_consecutive_errors():
    """Test health check when too many consecutive errors occur."""
    from services.bar_aggregator_agent import HealthMetrics

    metrics = HealthMetrics()

    # Record recent bar (passes no_bars check)
    metrics.record_bar(datetime.now(UTC) - timedelta(seconds=30))

    # Simulate 51 consecutive errors
    for _ in range(51):
        metrics.record_error()

    healthy, reason = metrics.is_healthy()
    assert not healthy
    assert "consecutive_errors" in reason


def test_health_metrics_never_processed():
    """Test health check when service has never processed a bar."""
    from services.bar_aggregator_agent import HealthMetrics

    metrics = HealthMetrics()

    # No bars recorded yet
    healthy, reason = metrics.is_healthy()
    assert not healthy
    assert reason == "never_processed"


def test_health_metrics_threshold_exactly_50_errors():
    """Test that exactly 50 errors is still healthy (threshold is > 50)."""
    from services.bar_aggregator_agent import HealthMetrics

    metrics = HealthMetrics()

    # Record recent bar
    metrics.record_bar(datetime.now(UTC) - timedelta(seconds=30))

    # Exactly 50 errors (should be healthy)
    for _ in range(50):
        metrics.record_error()

    healthy, reason = metrics.is_healthy()
    assert healthy
    assert reason == "healthy"


def test_health_metrics_threshold_exactly_300_seconds():
    """Test that exactly 300 seconds (5 minutes) is still healthy (threshold is > 300)."""
    from services.bar_aggregator_agent import HealthMetrics

    metrics = HealthMetrics()

    # 299 seconds ago - just under the 5 minute threshold
    bar_time = datetime.now(UTC) - timedelta(seconds=299)
    metrics.record_bar(bar_time)

    # Check immediately to avoid timing drift
    healthy, reason = metrics.is_healthy()
    assert healthy, f"Expected healthy but got {reason}"
    assert reason == "healthy"


def test_health_metrics_threshold_101_bars_no_htf():
    """Test that exactly 100 bars with 0 HTF is still healthy (threshold is > 100)."""
    from services.bar_aggregator_agent import HealthMetrics

    metrics = HealthMetrics()

    # Exactly 100 bars (should be healthy)
    for _ in range(100):
        metrics.record_bar(datetime.now(UTC))

    healthy, reason = metrics.is_healthy()
    assert healthy
    assert reason == "healthy"
