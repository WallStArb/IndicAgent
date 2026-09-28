"""Bar content digest tests (D-07).

The digest is content identity over rows and quarantine state: stable under row
order, changed by any value or flag change, deterministic across processes, and
independent of the rule version. month_ranges covers the input's UTC calendar
months for the (symbol, tf, range) keys phase 186 consumes.
"""

from __future__ import annotations

import hashlib
import os
import re
import subprocess
import sys
import textwrap
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pytest

from src.intelligence.bars.digest import (
    DIGEST_ALGORITHM,
    bar_content_digest,
    month_ranges,
)

_REPO_ROOT = Path(__file__).parent.parent.parent.parent
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_EMPTY_SHA256 = hashlib.sha256(b"").hexdigest()


def _rows(n: int = 12, seed: int = 42) -> dict:
    """Deterministic synthetic rows: a seeded walk plus one flagged bar."""
    rng = np.random.default_rng(seed)
    closes = np.round(100.0 * np.exp(np.cumsum(rng.normal(0.0, 0.01, n))), 2)
    open_ = np.empty_like(closes)
    open_[0] = closes[0]
    open_[1:] = closes[:-1]
    ts = 1_700_000_000 + np.arange(n, dtype=np.int64) * 300
    rules: list[tuple[str, ...]] = [() for _ in range(n)]
    rules[3] = ("price_sanity",)
    rules[7] = ("ohlc_invariant", "non_positive_price")
    return {
        "ts_seconds": ts,
        "open_": open_,
        "high": np.maximum(open_, closes) * 1.002,
        "low": np.minimum(open_, closes) * 0.998,
        "close": closes,
        "volume": np.arange(1, n + 1, dtype=np.int64) * 1_000.0,
        "quarantine_rules": rules,
    }


def _digest(rows: dict, **overrides: object) -> str:
    merged = {**rows, **overrides}
    return bar_content_digest(
        merged["ts_seconds"],
        merged["open_"],
        merged["high"],
        merged["low"],
        merged["close"],
        merged["volume"],
        merged["quarantine_rules"],
    )


_CHILD_SCRIPT = textwrap.dedent("""
    import numpy as np
    from src.intelligence.bars.digest import bar_content_digest

    print(
        bar_content_digest(
            np.array({ts}, dtype=np.int64),
            np.array({open_}, dtype=np.float64),
            np.array({high}, dtype=np.float64),
            np.array({low}, dtype=np.float64),
            np.array({close}, dtype=np.float64),
            {volume},
            {rules},
        )
    )
    """)


def test_shuffle_gives_same_digest() -> None:
    rows = _rows()
    baseline = _digest(rows)
    rng = np.random.default_rng(7)
    order = rng.permutation(rows["ts_seconds"].size)
    shuffled = {
        "ts_seconds": rows["ts_seconds"][order],
        "open_": rows["open_"][order],
        "high": rows["high"][order],
        "low": rows["low"][order],
        "close": rows["close"][order],
        "volume": rows["volume"][order],
        "quarantine_rules": [rows["quarantine_rules"][i] for i in order],
    }
    assert _digest(shuffled) == baseline
    assert _HEX64.fullmatch(baseline)


def test_value_changes_change_the_digest() -> None:
    rows = _rows()
    baseline = _digest(rows)

    close_bumped = rows["close"].copy()
    close_bumped[5] += 0.01
    assert _digest(rows, close=close_bumped) != baseline

    volume_bumped = rows["volume"].copy()
    volume_bumped[5] += 1.0
    assert _digest(rows, volume=volume_bumped) != baseline

    open_bumped = rows["open_"].copy()
    open_bumped[2] += 0.01
    assert _digest(rows, open_=open_bumped) != baseline

    high_bumped = rows["high"].copy()
    high_bumped[9] += 0.01
    assert _digest(rows, high=high_bumped) != baseline

    low_bumped = rows["low"].copy()
    low_bumped[9] -= 0.01
    assert _digest(rows, low=low_bumped) != baseline

    ts_shifted = rows["ts_seconds"].copy()
    ts_shifted[0] += 300
    assert _digest(rows, ts_seconds=ts_shifted) != baseline


def test_quarantine_rule_change_changes_the_digest() -> None:
    rows = _rows()
    baseline = _digest(rows)
    with_rule = list(rows["quarantine_rules"])
    with_rule[2] = ("price_sanity",)
    assert _digest(rows, quarantine_rules=with_rule) != baseline

    # Rule order within a row does not matter: the row's set is sorted.
    reordered = [
        ("non_positive_price", "ohlc_invariant") if i == 7 else rules
        for i, rules in enumerate(rows["quarantine_rules"])
    ]
    assert _digest(rows, quarantine_rules=reordered) == baseline


def test_identical_rows_identical_digest() -> None:
    assert _digest(_rows()) == _digest(_rows())
    assert _digest(_rows(seed=1)) == _digest(_rows(seed=1))
    assert _digest(_rows(seed=1)) != _digest(_rows(seed=2))


def test_digest_deterministic_across_processes() -> None:
    """No Python hash randomization or platform ordering leaks into the digest."""
    rows = _rows()
    expected = _digest(rows)
    script = _CHILD_SCRIPT.format(
        ts=rows["ts_seconds"].tolist(),
        open_=rows["open_"].tolist(),
        high=rows["high"].tolist(),
        low=rows["low"].tolist(),
        close=rows["close"].tolist(),
        volume=f"np.array({rows['volume'].tolist()}, dtype=np.float64)",
        rules=[list(rule) for rule in rows["quarantine_rules"]],
    )
    for hashseed in ("0", "1", "12345"):
        env = {**os.environ, "PYTHONPATH": str(_REPO_ROOT), "PYTHONHASHSEED": hashseed}
        result = subprocess.run(
            [sys.executable, "-c", script],
            capture_output=True,
            text=True,
            env=env,
            cwd=str(_REPO_ROOT),
            check=True,
        )
        assert result.stdout.strip() == expected


def test_nan_and_none_volume_serialize_as_null() -> None:
    ts = np.array([1_700_000_000, 1_700_000_300], dtype=np.int64)
    zeros = np.array([5.0, 5.0])

    nan_volume = np.array([100.0, np.nan])
    none_volume = np.array([100.0, None], dtype=object)
    zero_volume = np.array([100.0, 0.0])

    kwargs = {"ts_seconds": ts, "open_": zeros, "high": zeros, "low": zeros, "close": zeros}
    nan_digest = bar_content_digest(volume=nan_volume, quarantine_rules=[(), ()], **kwargs)
    none_digest = bar_content_digest(volume=none_volume, quarantine_rules=[(), ()], **kwargs)
    zero_digest = bar_content_digest(volume=zero_volume, quarantine_rules=[(), ()], **kwargs)
    assert nan_digest == none_digest
    assert nan_digest != zero_digest


def test_empty_input_returns_empty_serialization_digest() -> None:
    empty = {
        "ts_seconds": np.empty(0, dtype=np.int64),
        "open_": np.empty(0, dtype=np.float64),
        "high": np.empty(0, dtype=np.float64),
        "low": np.empty(0, dtype=np.float64),
        "close": np.empty(0, dtype=np.float64),
        "volume": np.empty(0, dtype=np.float64),
        "quarantine_rules": [],
    }
    assert _digest(empty) == _EMPTY_SHA256


def test_mismatched_rule_count_raises() -> None:
    rows = _rows()
    with_rules = {**rows, "quarantine_rules": rows["quarantine_rules"][:-1]}
    with pytest.raises(ValueError, match="quarantine_rules"):
        _digest(with_rules)


def test_month_ranges_covers_input_months() -> None:
    ts = np.array(
        [
            int(datetime(2024, 1, 15, 15, 0, tzinfo=UTC).timestamp()),
            int(datetime(2024, 3, 2, 15, 0, tzinfo=UTC).timestamp()),
        ],
        dtype=np.int64,
    )
    assert month_ranges(ts) == [
        (datetime(2024, 1, 1, tzinfo=UTC), datetime(2024, 2, 1, tzinfo=UTC)),
        (datetime(2024, 2, 1, tzinfo=UTC), datetime(2024, 3, 1, tzinfo=UTC)),
        (datetime(2024, 3, 1, tzinfo=UTC), datetime(2024, 4, 1, tzinfo=UTC)),
    ]


def test_month_ranges_year_boundary_and_empty() -> None:
    ts = np.array(
        [
            int(datetime(2024, 11, 30, tzinfo=UTC).timestamp()),
            int(datetime(2025, 2, 1, tzinfo=UTC).timestamp()),
        ],
        dtype=np.int64,
    )
    assert month_ranges(ts) == [
        (datetime(2024, 11, 1, tzinfo=UTC), datetime(2024, 12, 1, tzinfo=UTC)),
        (datetime(2024, 12, 1, tzinfo=UTC), datetime(2025, 1, 1, tzinfo=UTC)),
        (datetime(2025, 1, 1, tzinfo=UTC), datetime(2025, 2, 1, tzinfo=UTC)),
        (datetime(2025, 2, 1, tzinfo=UTC), datetime(2025, 3, 1, tzinfo=UTC)),
    ]
    assert month_ranges(np.empty(0, dtype=np.int64)) == []


def test_algorithm_identifier() -> None:
    assert DIGEST_ALGORITHM == "sha256-bars-v1"
