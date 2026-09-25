import numpy as np
import pytest

from src.intelligence.research.evaluate import EvaluatorMisuse
from src.intelligence.research.guards import (
    GuardFailure,
    causality_probe,
    integrity,
    memory_check,
    probe_rows,
    require_testable,
    run_guards,
)
from src.intelligence.research.panel import Panel, daily_panel, forward_returns, fwd_span
from src.intelligence.research.signals import SignalSource


def _panel(n: int = 400, m: int = 4, seed: int = 0) -> Panel:
    rng = np.random.default_rng(seed)
    close = 100 * np.exp(np.cumsum(rng.normal(0, 0.01, (n, m)), axis=0))
    opens = close * np.exp(rng.normal(0, 0.002, (n, m)))
    return daily_panel(
        close,
        opens=opens,
        volume=np.full((n, m), 1e6),
        dates=np.datetime64("2010-01-04", "D") + np.arange(n),
    )


def _log_diff(lead: int, lag: int):
    """alpha[t] = ln(close[t + lead] / close[t + lag]); causal only when lead <= 0."""

    def compute(panel: Panel) -> np.ndarray:
        log_close = np.log(panel.close)
        n = len(log_close)
        alpha = np.full(log_close.shape, np.nan)
        lo, hi = max(0, -min(lead, lag)), n - max(0, lead, lag)
        alpha[lo:hi] = log_close[lo + lead : hi + lead] - log_close[lo + lag : hi + lag]
        return alpha

    return compute


def _momentum(lookback: int):
    return _log_diff(0, -lookback)


def _ema(panel: Panel, span: int = 10) -> np.ndarray:
    r = np.diff(np.log(panel.close), axis=0, prepend=np.nan)
    out = np.full(r.shape, np.nan)
    k = 2.0 / (span + 1)
    acc = np.zeros(r.shape[1])
    for t in range(1, len(r)):
        acc = k * np.nan_to_num(r[t]) + (1 - k) * acc
        out[t] = acc
    return out


_leaky_next_close = _log_diff(1, 0)
# Reads only a ratio of two future prices: invisible to a uniform rescale of the future.
_leaky_future_ratio = _log_diff(3, 1)


def _centered_mean(panel: Panel) -> np.ndarray:
    r = np.diff(np.log(panel.close), axis=0, prepend=np.nan)
    out = np.full(r.shape, np.nan)
    for t in range(2, len(r) - 2):
        out[t] = r[t - 2 : t + 3].mean(axis=0)
    return out


ROWS = np.array([30, 150, 250, 380])


def test_causal_signal_passes_probe():
    causality_probe(_momentum(20), _panel(), ROWS, seed=1)


@pytest.mark.parametrize("leak", [_leaky_next_close, _leaky_future_ratio, _centered_mean])
def test_probe_catches_lookahead(leak):
    with pytest.raises(GuardFailure, match="lookahead"):
        causality_probe(leak, _panel(), ROWS, seed=1)


def test_target_probe_uses_forward_reach():
    target = lambda p: forward_returns(p.open, horizon=2)  # noqa: E731
    causality_probe(target, _panel(), ROWS, seed=1, reach=fwd_span(2))
    with pytest.raises(GuardFailure):
        causality_probe(target, _panel(), ROWS, seed=1, reach=fwd_span(2) - 1)


def test_memory_check_measures_finite_lookback():
    rows = np.array([10, 50, 100])
    assert memory_check(_momentum(20), _panel(), rows, declared=20) == 20
    with pytest.raises(GuardFailure, match="memory"):
        memory_check(_momentum(20), _panel(), rows, declared=19)


def test_memory_check_recursive_filter_against_declared_impulse_cut():
    # EMA span 10: k = 2/11; (1 - k)^L < 1e-4 of the peak at L = 47.
    rows = np.array([20, 100])
    reach = memory_check(_ema, _panel(), rows, declared=47)
    assert 30 <= reach <= 47
    with pytest.raises(GuardFailure, match="memory"):
        memory_check(_ema, _panel(), rows, declared=10)


def test_memory_check_flags_lookahead():
    with pytest.raises(GuardFailure, match="lookahead"):
        memory_check(_leaky_next_close, _panel(), np.array([100]), declared=5)


def test_integrity_passes_and_reports_coverage():
    panel = _panel()
    alpha = _momentum(20)(panel)
    report = integrity(panel, alpha)
    assert report.volume_checked
    assert (report.coverage[:20] == 0).all()
    assert (report.coverage[20:] == 1).all()


def test_integrity_rejects_filled_alpha_on_missing_close():
    panel = _panel()
    panel.close[50, 1] = np.nan
    alpha = np.zeros(panel.close.shape)
    with pytest.raises(GuardFailure, match="no close"):
        integrity(panel, alpha)


def test_integrity_rejects_zero_volume_and_inf():
    panel = _panel()
    alpha = _momentum(5)(panel)
    alpha_inf = alpha.copy()
    alpha_inf[40, 0] = np.inf
    with pytest.raises(GuardFailure, match="infinite"):
        integrity(panel, alpha_inf)
    panel.volume[60, 2] = 0
    with pytest.raises(GuardFailure, match="volume"):
        integrity(panel, alpha)


def test_integrity_shape_mismatch_is_misuse_not_a_verdict():
    with pytest.raises(EvaluatorMisuse):
        integrity(_panel(), np.zeros((3, 3)))


def test_run_guards_reads_declared_memory_from_source():
    source = SignalSource(_momentum(20), memory=20, direction=1.0, n_tested=0)
    report = run_guards(source, _panel(), seed=1, n_random=5, max_rows=20)
    assert report.memory_reach == 20
    short = SignalSource(_momentum(20), memory=19, direction=1.0, n_tested=0)
    with pytest.raises(GuardFailure, match="memory"):
        run_guards(short, _panel(), seed=1, n_random=5, max_rows=20)


def test_infinite_alpha_fails_as_integrity_not_lookahead():
    def with_inf(panel: Panel) -> np.ndarray:
        alpha = _momentum(1)(panel)
        alpha[10, 0] = np.inf
        return alpha

    source = SignalSource(with_inf, memory=1, direction=1.0, n_tested=0)
    with pytest.raises(GuardFailure, match="infinite"):
        run_guards(source, _panel(), seed=1, n_random=5, max_rows=20)
    causality_probe(with_inf, _panel(), ROWS, seed=1)  # an unchanged inf is not a leak


def test_probe_rows_rejects_random_budget_over_cap():
    with pytest.raises(EvaluatorMisuse):
        probe_rows(_panel(), n_random=30, seed=0, max_rows=10)


def test_integrity_skips_volume_on_synthetic_panel():
    panel = daily_panel(np.full((10, 2), 100.0))
    assert not integrity(panel, np.zeros((10, 2))).volume_checked


def test_require_testable_resolution_and_power():
    require_testable(n_shifts=600, alpha_level=0.05, budget_m=30, power=0.5)
    with pytest.raises(GuardFailure, match="resolve"):
        require_testable(n_shifts=599, alpha_level=0.05, budget_m=30, power=0.9)
    with pytest.raises(GuardFailure, match="underpowered"):
        require_testable(n_shifts=5000, alpha_level=0.05, budget_m=30, power=0.49)
    with pytest.raises(GuardFailure, match="underpowered"):
        require_testable(n_shifts=5000, alpha_level=0.05, budget_m=30, power=float("nan"))


def test_probe_rows_cover_month_ends_listing_edges_and_half_days():
    n, m, bps = 8 * 4, 2, 4  # 8 sessions of 4 slots
    days = np.array(
        [
            "2020-01-29",
            "2020-01-30",
            "2020-01-31",
            "2020-02-03",
            "2020-02-04",
            "2020-02-05",
            "2020-02-06",
            "2020-02-07",
        ],
        dtype="datetime64[D]",
    )
    ts = (
        days.repeat(bps).astype("datetime64[m]")
        + np.timedelta64(14 * 60 + 30, "m")
        + np.tile(np.arange(bps) * 60, len(days)).astype("timedelta64[m]")
    )
    close = np.full((n, m), 100.0)
    close[:6, 1] = np.nan  # second name lists at row 6
    close[18:20] = np.nan  # session 4 is a half day: slots 2 and 3 untraded
    valid = np.isfinite(close).any(axis=1)
    panel = Panel(
        tf="1h",
        symbols=("a", "b"),
        timestamps=ts.astype("datetime64[ns]"),
        bars_per_session=bps,
        valid=valid,
        open=close.copy(),
        close=close,
        volume=np.full((n, m), 1.0),
    )
    rows = set(probe_rows(panel, n_random=0, seed=0, max_rows=100).tolist())
    assert 11 in rows  # 2020-01-31, last bar: a month end
    assert 17 in rows  # half day's last traded bar
    assert {0, 6, n - 1} <= rows  # listing edges
