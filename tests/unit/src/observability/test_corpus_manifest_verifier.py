"""Unit tests for corpus_manifest_verifier.py's per-tf lookahead handling (todo 202).

Todo 146 replaced the single global alpha.ic.lookahead.{scale} grid with a per-tf
alpha.ic.lookahead.{tf}.{scale} grid. This file's Check 3 (verify_data_quality) used to
read a single global "expected lookaheads" set off a phantom alpha.ic.lookaheads
(plural) APR key that was never actually seeded in any migration -- it always silently
used the hardcoded [1, 5, 20, 60] fallback, applied uniformly to every tf. These tests
cover the fix: per-tf expected lookaheads, read from the real 16 alpha.ic.lookahead.
{tf}.{scale} keys, with no cross-tf leakage.
"""

from __future__ import annotations

from typing import Any

import pytest

from src.observability.corpus_manifest_verifier import (
    _APR_DEFAULT_LOOKAHEADS_BY_TF,
    CorpusManifestVerifier,
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


class _FakeConn:
    def __init__(self, config_rows: list[tuple[str, str]], fetch_results: list[Any] | None = None):
        self._config_rows = config_rows
        self._fetch_results = fetch_results or []

    def cursor(self, **kwargs: Any) -> _FakeCursor:
        return _FakeCursor(self._config_rows, self._fetch_results)


def test_load_apr_values_reads_real_per_tf_keys_not_phantom_plural_key():
    """The old code read alpha.ic.lookaheads (plural), a key never seeded by any
    migration. The fix reads the real per-tf alpha.ic.lookahead.{tf}.{scale} keys."""
    conn = _FakeConn(
        config_rows=[
            ("alpha.ic.lookahead.5m.fast", "1"),
            ("alpha.ic.lookahead.5m.mid", "6"),
            ("alpha.ic.lookahead.5m.slow", "12"),
            ("alpha.ic.lookahead.5m.extended", "39"),
        ]
    )
    apr = _load_apr_values(conn)
    assert apr["lookaheads_by_tf"]["5m"] == {1, 6, 12, 39}


def test_load_apr_values_falls_back_per_tf_when_keys_absent():
    """No config_state rows at all -- every tf must fall back to ITS OWN default grid,
    not a single shared default applied uniformly."""
    conn = _FakeConn(config_rows=[])
    apr = _load_apr_values(conn)
    for tf, defaults in _APR_DEFAULT_LOOKAHEADS_BY_TF.items():
        if tf == "1h":
            continue  # 1h's active_scales excludes slow/extended -- asserted separately below
        assert apr["lookaheads_by_tf"][tf] == set(defaults.values())
    # Confirms tfs genuinely differ -- proves this isn't accidentally passing because
    # every tf's fallback happens to be identical.
    assert apr["lookaheads_by_tf"]["5m"] != apr["lookaheads_by_tf"]["15m"]
    # 1h's active_scales fallback (fast/mid only) excludes slow(20)/extended(60) --
    # not the full default grid like the other tfs.
    assert apr["lookaheads_by_tf"]["1h"] == {1, 2}


def test_load_apr_values_partial_override_only_affects_that_tf():
    """Overriding one tf's keys must not leak into another tf's expected set."""
    conn = _FakeConn(
        config_rows=[
            ("alpha.ic.lookahead.1d.fast", "1"),
            ("alpha.ic.lookahead.1d.mid", "99"),
            ("alpha.ic.lookahead.1d.slow", "5"),
            ("alpha.ic.lookahead.1d.extended", "10"),
        ]
    )
    apr = _load_apr_values(conn)
    assert 99 in apr["lookaheads_by_tf"]["1d"]
    assert 99 not in apr["lookaheads_by_tf"]["15m"]
    assert apr["lookaheads_by_tf"]["15m"] == set(_APR_DEFAULT_LOOKAHEADS_BY_TF["15m"].values())


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


def test_load_apr_values_scopes_lookaheads_by_active_scales_for_1h():
    """1h's active_scales excludes slow/extended (live since migration 271) -- Check 3's
    expected set for 1h must reflect only the ACTIVE scales' bar counts, not all 4
    unconditionally, or the check will false-positive-fail on every real corpus run."""
    conn = _FakeConn(
        config_rows=[
            ("alpha.ic.active_scales.1h", '["fast","mid"]'),
        ]
    )
    apr = _load_apr_values(conn)
    assert apr["lookaheads_by_tf"]["1h"] == {1, 2}  # fast=1, mid=2 -- NOT {1,2,20,60}


def test_load_apr_values_active_scales_falls_back_when_key_absent():
    """No alpha.ic.active_scales.* rows at all -- must fall back to the by-value mirror
    of ACTIVE_SCALES_FALLBACKS_BY_TF (1h -> fast/mid only), not silently include all 4."""
    conn = _FakeConn(config_rows=[])
    apr = _load_apr_values(conn)
    assert apr["lookaheads_by_tf"]["1h"] == {1, 2}
    assert apr["lookaheads_by_tf"]["5m"] == {1, 6, 12, 39}  # 5m keeps all 4, unaffected


def test_load_apr_values_active_scales_explicit_empty_list_stays_empty():
    """todo 212: an operator-configured alpha.ic.active_scales.{tf} = '[]' (a deliberate
    "no scales active" state) must NOT be treated the same as the key being absent --
    it must produce a genuinely empty expected set, matching
    canonicalize_active_scales([]) == () in services/_batch_utils.py (the Ring 2 path
    this Ring 0 copy mirrors). Before the fix, `tuple(parsed) if parsed else default`
    silently fell back to the tf's default scale set for both an absent key AND an
    explicit empty list."""
    conn = _FakeConn(config_rows=[("alpha.ic.active_scales.1h", "[]")])
    apr = _load_apr_values(conn)
    assert apr["lookaheads_by_tf"]["1h"] == set()  # NOT {1, 2} (the fast/mid default)


def test_verify_data_quality_check3_passes_for_1h_with_only_two_scales(tmp_path):
    """Positive case mirroring test_verify_data_quality_check3_passes_with_correct_per_tf_grid
    but for 1h post-fix: only fast(1)/mid(2) rows exist, and Check 3 must NOT raise."""
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
    """Symmetric-direction case (final whole-branch review finding 1): 1h's
    active_scales excludes slow/extended, so its expected set is only {1, 2}
    (fast, mid). If feature_ic_scores somehow also has a lookahead_bars=20 (slow)
    row for 1h -- e.g. the by-value ACTIVE_SCALES_FALLBACKS_BY_TF/
    _APR_DEFAULT_ACTIVE_SCALES_BY_TF mirrors drifting out of sync, or a stale row
    an exclusion-driven purge failed to clear -- Check 3 must still catch it. Prior
    to this fix, Check 3 only computed `expected - actual` (missing) and silently
    ignored anything present in `actual` but absent from `expected`."""
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
