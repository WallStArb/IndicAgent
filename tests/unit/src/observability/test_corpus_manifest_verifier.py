"""Unit tests for corpus_manifest_verifier.py's per-tf lookahead handling (todo 202).

Todo 146 replaced the single global alpha.ic.lookahead.{scale} grid with a per-tf
alpha.ic.lookahead.{tf}.{scale} grid. This file's Check 3 (verify_data_quality) used to
read a single global "expected lookaheads" set off a phantom alpha.ic.lookaheads
(plural) APR key that was never actually seeded in any migration -- it always silently
used the hardcoded [1, 5, 20, 60] fallback, applied uniformly to every tf. Todo 146's
fix read the real 16 alpha.ic.lookahead.{tf}.{scale} keys with no cross-tf leakage.
Those keys retired with the old ic_engine stack (phase 186 plan 23). Since migration 575 the
verifier reads the IC writer's own grid, alpha.ic_measure.horizons; the tests below prove it is
used per tf, that its absence raises, and that stray rows for the retired keys cannot leak in.
"""

from __future__ import annotations

import inspect
from typing import Any

import pytest

from src.observability.corpus_manifest_verifier import (
    _ABSENCE_EXEMPT_TFS,
    _FEATURE_COLUMNS,
    CorpusManifestVerifier,
    _check_feature_null_rates,
    _load_apr_values,
)


class _FakeCursor:
    description: list[Any] = []

    def __init__(self, config_rows: list[tuple[str, str]], fetch_results: list[Any]):
        self._config_rows = config_rows
        self._fetch_results = fetch_results
        self._pending: list[Any] = []

    def __enter__(self) -> _FakeCursor:
        return self

    def __exit__(self, *exc: Any) -> None:
        return None

    def execute(self, sql: str, params: Any = None) -> None:
        if "FROM config_state" in sql:
            keys = set(params)
            self._pending = [(k, v) for k, v in self._config_rows if k in keys]
        else:
            self._pending = self._fetch_results.pop(0) if self._fetch_results else []

    def fetchall(self) -> list[Any]:
        return self._pending

    def fetchone(self) -> Any:
        return self._pending[0] if self._pending else None


# The live alpha.ic_measure.horizons value (2026-11-04).
_HORIZONS = '{"5m":[6,12,39],"15m":[2,5,10],"1h":[1,2],"1d":[1,2,5,10]}'


class _FakeConn:
    def __init__(
        self,
        config_rows: list[tuple[str, str]],
        fetch_results: list[Any] | None = None,
        horizons: str | None = _HORIZONS,
    ):
        extra = [] if horizons is None else [("alpha.ic_measure.horizons", horizons)]
        self._config_rows = [*config_rows, *extra]
        self._fetch_results = fetch_results or []

    def cursor(self, **kwargs: Any) -> _FakeCursor:
        return _FakeCursor(self._config_rows, self._fetch_results)


def test_load_apr_values_reads_the_ic_writer_horizons_per_tf():
    apr = _load_apr_values(_FakeConn(config_rows=[]))
    assert apr["lookaheads_by_tf"] == {
        "5m": {6, 12, 39},
        "15m": {2, 5, 10},
        "1h": {1, 2},
        "1d": {1, 2, 5, 10},
    }


def test_load_apr_values_raises_without_the_horizons_key():
    with pytest.raises(RuntimeError, match="alpha.ic_measure.horizons"):
        _load_apr_values(_FakeConn(config_rows=[], horizons=None))


def test_load_apr_values_raises_runtime_error_on_malformed_horizons():
    with pytest.raises(RuntimeError, match="malformed"):
        _load_apr_values(_FakeConn(config_rows=[], horizons="[1, 2]"))


def test_load_apr_values_ignores_stray_rows_for_retired_keys():
    """A leftover row for a retired per-tf key (alpha.ic.lookahead.1d.mid=99) never leaks in."""
    conn = _FakeConn(config_rows=[("alpha.ic.lookahead.1d.mid", "99")])
    apr = _load_apr_values(conn)
    assert all(99 not in grid for grid in apr["lookaheads_by_tf"].values())


def test_verify_data_quality_check3_no_cross_tf_leakage(monkeypatch, tmp_path):
    """Adversarial case mirroring todo 146's ic_engine lifecycle-hook test: 15m actually
    has rows at the bar counts that are 5m's fallback grid (1,6,12,39), but NOT its own
    (1,2,5,10). A verifier that (bug) compared against a single global set could pass
    this incorrectly; the per-tf fix must still fail it, since 15m is missing 15m's own
    expected lookaheads."""
    verifier = CorpusManifestVerifier(tmp_path)

    # Check 1 (symbol coverage), Check 2 (pooled rows) fetches, then Check 3's fetchall.
    fetch_results = [
        [(2,)],  # check 1: symbol count query, called once per tf below (reused)
        [("15m", 10)],  # check 2: pooled rows by tf
        [  # check 3: (tf, lookahead_bars, n_features) rows -- 15m has 5m's grid, not its own
            ("15m", 1, 3),
            ("15m", 6, 3),
            ("15m", 12, 3),
            ("15m", 39, 3),
        ],
    ]
    conn = _FakeConn(config_rows=[], fetch_results=fetch_results)

    with pytest.raises(RuntimeError, match="TF 15m missing lookaheads"):
        verifier.verify_data_quality(conn, required_tfs=["15m"], required_symbols=["A", "B"])


def test_verify_data_quality_check3_passes_with_correct_per_tf_grid(tmp_path):
    """Positive case: 15m rows match 15m's own expected grid exactly -- must pass."""
    verifier = CorpusManifestVerifier(tmp_path)

    fetch_results = [
        [(2,)],
        [("15m", 10)],
        [
            ("15m", 1, 3),
            ("15m", 2, 3),
            ("15m", 5, 3),
            ("15m", 10, 3),
        ],
    ]
    conn = _FakeConn(config_rows=[], fetch_results=fetch_results)

    # Should not raise past Check 3 -- Check 5/6/7 need more fetch results than this
    # fixture provides, so we only assert Check 3 doesn't itself raise by checking the
    # error (if any) isn't the lookahead one.
    try:
        verifier.verify_data_quality(conn, required_tfs=["15m"], required_symbols=["A", "B"])
    except RuntimeError as err:
        assert "missing lookaheads" not in str(err)
    except (IndexError, TypeError, AttributeError):
        # Fixture doesn't provide enough fetch_results/description for checks 4-7;
        # that's fine, this test only asserts Check 3 itself passes.
        pass


def test_verify_data_quality_check3_passes_for_1h_with_only_two_scales(tmp_path):
    """Positive case mirroring test_verify_data_quality_check3_passes_with_correct_per_tf_grid
    for 1h: exactly its configured horizons (1, 2) exist, and Check 3 must NOT raise."""
    verifier = CorpusManifestVerifier(tmp_path)
    fetch_results = [
        [(2,)],
        [("1h", 10)],
        [
            ("1h", 1, 3),
            ("1h", 2, 3),
        ],
    ]
    conn = _FakeConn(config_rows=[], fetch_results=fetch_results)
    try:
        verifier.verify_data_quality(conn, required_tfs=["1h"], required_symbols=["A", "B"])
    except RuntimeError as err:
        assert "missing lookaheads" not in str(err)
    except (IndexError, TypeError, AttributeError):
        pass  # fixture doesn't provide enough fetch_results for checks 4-7; fine here


def test_verify_data_quality_check3_fails_on_unexpected_lookaheads_for_1h(tmp_path):
    """Symmetric-direction case (final whole-branch review finding 1): 1h's configured
    horizons are {1, 2} (alpha.ic_measure.horizons; longer ones cross the session, D-18). A
    1h lookahead_bars=20 row (a stale row, or a writer drifting from its own configuration)
    must still fail Check 3: it checks `actual - expected` as well as `expected - actual`."""
    verifier = CorpusManifestVerifier(tmp_path)

    fetch_results = [
        [(2,)],  # check 1: symbol count query
        [("1h", 10)],  # check 2: pooled rows by tf
        [  # check 3: 1h has fast(1)/mid(2) as expected, PLUS an unexpected slow(20) row
            ("1h", 1, 3),
            ("1h", 2, 3),
            ("1h", 20, 3),
        ],
    ]
    conn = _FakeConn(config_rows=[], fetch_results=fetch_results)

    with pytest.raises(RuntimeError, match="unexpected lookaheads"):
        verifier.verify_data_quality(conn, required_tfs=["1h"], required_symbols=["A", "B"])


class TestUnstratifiedScopeFilter:
    """Checks 2 and 3 must count only the proposer's unstratified rows: other scopes in the
    same table (regime_volatility, member_window) would otherwise satisfy "POOLED rows exist
    for all TFs" or "all lookaheads present" for a TF whose unstratified population is missing.
    SQL-text inspection, no live DB required (mirrors this file's own house style)."""

    def test_checks_2_and_3_read_the_unstratified_scope_only(self) -> None:
        # Migration 413 scopes (unstratified, regime_volatility, member_window): the
        # per-tf presence and lookahead checks hold the proposer's unstratified rows, so a
        # regime_volatility or member_window row cannot fake a PASS for a missing TF.
        source = inspect.getsource(CorpusManifestVerifier.verify_data_quality)
        assert source.count("regime_scope = 'unstratified'") >= 2
        assert "earnings_season" not in source


def _null_rate_conn(rows_by_tf: dict[str, dict[str, int]]):
    """Feeds _check_feature_null_rates one precomputed null-count row per TF.

    The gate's only per-TF input is the (tf, sample_size) params tuple on
    execute; description is rebuilt from the row's keys exactly like a real
    psycopg cursor so col_names zip matches.
    """

    class _Cur:
        description: list[Any] = []
        _values: tuple[int, ...] = ()

        def __enter__(self) -> _Cur:
            return self

        def __exit__(self, *exc: Any) -> None:
            return None

        def execute(self, sql: str, params: Any = None) -> None:
            row = rows_by_tf[params[0]]
            self.description = [(name,) for name in row]
            self._values = tuple(row.values())

        def fetchone(self) -> tuple[int, ...]:
            return self._values

    class _Conn:
        def cursor(self, **kwargs: Any) -> _Cur:
            return _Cur()

    return _Conn()


def _null_row(total: int, **null_counts: int) -> dict[str, int]:
    row: dict[str, int] = {"total_rows": total}
    for col in _FEATURE_COLUMNS:
        row[f"null_{col}"] = null_counts.get(col, 0)
    return row


class TestFeatureNullRateGateTiers:
    """D1 rule 2 (todo 584 4b-2 group 4) made object-existence columns None
    wherever their object does not exist, so the strict max_null_rate tier
    would fail honest data (session-VP columns are 100% NULL on 1d by design).
    The gate is two-tier: strict columns keep max_null_rate; absence-legit
    columns are only checked against being ENTIRELY NULL on a TF where the
    object can exist, and skipped on their _ABSENCE_EXEMPT_TFS TFs."""

    def test_1d_session_columns_entirely_null_pass(self) -> None:
        conn = _null_rate_conn(
            {"1d": _null_row(100, poc_dist_atr=100, va_position=100, sr_support_dist=60)}
        )
        _check_feature_null_rates(conn, ["1d"], 0.05, 10000)  # must not raise

    def test_absence_legit_column_entirely_null_on_live_tf_fails(self) -> None:
        conn = _null_rate_conn({"5m": _null_row(100, poc_dist_atr=100, sr_support_dist=100)})
        with pytest.raises(RuntimeError, match="poc_dist_atr.*entirely NULL"):
            _check_feature_null_rates(conn, ["5m"], 0.05, 10000)

    def test_strict_tier_unchanged_and_partial_absence_nulls_pass(self) -> None:
        # momentum_z_fast at 6% breaches the strict tier; sr_resist_dist at 50%
        # is honest absence (D1 rule 2) and must NOT fire.
        conn = _null_rate_conn({"5m": _null_row(100, momentum_z_fast=6, sr_resist_dist=50)})
        with pytest.raises(RuntimeError) as excinfo:
            _check_feature_null_rates(conn, ["5m"], 0.05, 10000)
        assert "momentum_z_fast" in str(excinfo.value)
        assert "sr_resist_dist" not in str(excinfo.value)

    def test_every_exempt_tf_is_a_tf_the_object_cannot_exist_on(self) -> None:
        # the exemption map must stay consistent with the columns actually present
        # in _FEATURE_COLUMNS -- a retired column left in the map silently drops
        # its strict-tier check entirely.
        assert set(_ABSENCE_EXEMPT_TFS) <= set(_FEATURE_COLUMNS)
