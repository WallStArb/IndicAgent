"""Tests for shadow signal promotion gate."""

from __future__ import annotations

import pytest

from production.scripts.promote_shadow import run_promotion_test, MIN_SAMPLES, WIN_OUTCOMES


def _make_signals(n: int, win_rate: float) -> list[dict]:
    """Build n signals with approximate win_rate."""
    n_wins = int(n * win_rate)
    signals = []
    for i in range(n):
        outcome = "target_1" if i < n_wins else "stopped_in_trade"
        signals.append({"outcome": outcome})
    return signals


def test_rejects_insufficient_samples_shadow(capsys):
    prod = _make_signals(300, 0.40)
    shadow = _make_signals(50, 0.60)  # Too few
    code = run_promotion_test(prod, shadow)
    assert code == 1
    assert "insufficient samples" in capsys.readouterr().out


def test_rejects_insufficient_samples_prod(capsys):
    prod = _make_signals(100, 0.40)  # Too few
    shadow = _make_signals(300, 0.60)
    code = run_promotion_test(prod, shadow)
    assert code == 1
    assert "insufficient samples" in capsys.readouterr().out


def test_rejects_high_p_value(capsys):
    # Same win rate — no significant difference
    prod = _make_signals(300, 0.45)
    shadow = _make_signals(300, 0.45)
    code = run_promotion_test(prod, shadow)
    assert code == 1
    captured = capsys.readouterr().out
    assert "REJECTED" in captured
    assert "p=" in captured


def test_promotes_significant_improvement(capsys):
    # Shadow much better — should be significant with large N
    prod = _make_signals(500, 0.35)
    shadow = _make_signals(500, 0.55)
    code = run_promotion_test(prod, shadow)
    assert code == 0
    captured = capsys.readouterr().out
    assert "PROMOTED" in captured
    assert "p=" in captured


def test_rejects_when_shadow_worse(capsys):
    # Shadow worse than prod — one-sided test should reject
    prod = _make_signals(500, 0.55)
    shadow = _make_signals(500, 0.35)
    code = run_promotion_test(prod, shadow)
    assert code == 1
    assert "REJECTED" in capsys.readouterr().out


def test_prints_win_rates_in_rejection(capsys):
    prod = _make_signals(300, 0.40)
    shadow = _make_signals(300, 0.42)
    code = run_promotion_test(prod, shadow)
    captured = capsys.readouterr().out
    assert "shadow_wr=" in captured
    assert "prod_wr=" in captured
