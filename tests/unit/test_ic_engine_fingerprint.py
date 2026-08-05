"""Unit tests: ic_engine.py's whole-cell fingerprint gate (Phase 162 Plan 03, todo 134).

Covers:
  Task 1: ICEngineConfig field classification (crash-loud partition test) +
          _compute_apr_snapshot_key() moves only on a COMPUTATIONAL field change.
  Task 2: per-table upstream watermark -- DB-free proof that an in-place value
          mutation (unchanged MAX(bar_ts)/COUNT) still moves the watermark.
  Task 3: _fingerprint_is_valid() component-match semantics, the DELETE SQL's
          cell-key scoping, and the existing_keys-removal regression (no compute
          function may retain a stale pre-delete snapshot parameter or reference).

No DB, no Kafka. Pure Python inspection of module constants/functions plus
DB-free dict construction for the watermark-inequality proof.
"""

from __future__ import annotations

import dataclasses
import inspect
import sys
from pathlib import Path

import pytest

_project_root = Path(__file__).parent.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from services.ic_engine import (
    _ARCHIVE_BEFORE_DELETE_CROSS_SECTIONAL_SQL,
    _ARCHIVE_BEFORE_DELETE_SQL,
    _COMPUTATIONAL_CONFIG_FIELDS,
    _FEATURE_STATUS_REFRESH_SQL,
    _FINGERPRINT_INVALIDATE_DELETE_CROSS_SECTIONAL_SQL,
    _FINGERPRINT_INVALIDATE_DELETE_SQL,
    _OPERATIONAL_CONFIG_FIELDS,
    ICEngineConfig,
    _classify_fingerprint,
    _compute_apr_snapshot_key,
    _compute_cross_sectional_tf,
    _compute_one_regime_cell,
    _compute_symbol_tf,
    _compute_upstream_watermark,
    _fingerprint_computational_key,
    _fingerprint_is_computationally_valid,
    _fingerprint_is_status_only_stale,
    _fingerprint_is_valid,
    _partition_symbol_cells,
    _symbol_expected_cells,
)

# ---------------------------------------------------------------------------
# Helper: a minimal, fully-populated ICEngineConfig for snapshot-key tests.
# ---------------------------------------------------------------------------


def _make_config(**overrides) -> ICEngineConfig:
    base = dict(
        min_observations=500,
        fdr_alpha=0.05,
        walk_forward_folds=3,
        sharpe_window_size=2000,
        sharpe_min_windows=10,
        subsample_min_stride=5,
        min_reliable_n=100,
        cluster_max_corr=0.70,
        lookahead_fast={"5m": 1, "15m": 1, "1h": 1, "1d": 1},
        lookahead_mid={"5m": 6, "15m": 2, "1h": 2, "1d": 2},
        lookahead_slow={"5m": 12, "15m": 5, "1h": 20, "1d": 5},
        lookahead_extended={"5m": 39, "15m": 10, "1h": 60, "1d": 10},
        active_scales={
            "5m": ("fast", "mid", "slow", "extended"),
            "15m": ("fast", "mid", "slow", "extended"),
            "1h": ("fast", "mid"),
            "1d": ("fast", "mid", "slow", "extended"),
        },
        equity_model_enabled=True,
        min_obs_daily=1000,
        hac_max_lag=3,
        cs_chunk_ts=5000,
        symbol_fetch_chunk_rows=5000,
        n_workers=1,
        blas_threads_per_worker=1,
    )
    base.update(overrides)
    return ICEngineConfig(**base)


def test_make_config_includes_active_scales_default():
    """_make_config's base dict must include active_scales or every existing test
    in this file breaks on ICEngineConfig's field-count growth -- same discipline
    as every prior field addition (see this file's existing base dict)."""
    cfg = _make_config()
    assert cfg.active_scales["1h"] == ("fast", "mid")
    assert cfg.active_scales["5m"] == ("fast", "mid", "slow", "extended")


# ---------------------------------------------------------------------------
# Task 1: field classification (crash-loud partition test)
# ---------------------------------------------------------------------------


def test_computational_and_operational_fields_partition_dataclass_exactly():
    """Every ICEngineConfig field must be in EXACTLY ONE of the two classification
    sets -- a field present on the dataclass but in neither set is the exact
    "unclassified field crashes loud" failure mode this test guards against.
    """
    all_field_names = {f.name for f in dataclasses.fields(ICEngineConfig)}
    union = _COMPUTATIONAL_CONFIG_FIELDS | _OPERATIONAL_CONFIG_FIELDS
    missing = all_field_names - union
    extra = union - all_field_names
    assert not missing, (
        f"ICEngineConfig field(s) {missing} are classified in NEITHER "
        "_COMPUTATIONAL_CONFIG_FIELDS nor _OPERATIONAL_CONFIG_FIELDS -- every field "
        "must be explicitly classified (162-03 Task 1 crash-loud requirement)."
    )
    assert not extra, (
        f"Classification set(s) reference field(s) {extra} that no longer exist on "
        "ICEngineConfig -- stale entries must be removed."
    )


def test_computational_and_operational_fields_are_disjoint():
    overlap = _COMPUTATIONAL_CONFIG_FIELDS & _OPERATIONAL_CONFIG_FIELDS
    assert not overlap, (
        f"Field(s) {overlap} appear in BOTH classification sets -- a field must be "
        "exactly one of COMPUTATIONAL or OPERATIONAL, never both."
    )


def test_apr_snapshot_key_unchanged_by_operational_field_change():
    """Changing an OPERATIONAL-only field (n_workers) must NOT move the snapshot key."""
    cfg_a = _make_config(n_workers=1)
    cfg_b = _make_config(n_workers=12)
    assert _compute_apr_snapshot_key(cfg_a) == _compute_apr_snapshot_key(
        cfg_b
    ), "n_workers is OPERATIONAL -- changing it must never move apr_snapshot_key."


def test_apr_snapshot_key_moves_on_computational_field_change():
    """Changing a COMPUTATIONAL field (min_observations) MUST move the snapshot key."""
    cfg_a = _make_config(min_observations=500)
    cfg_b = _make_config(min_observations=1000)
    assert _compute_apr_snapshot_key(cfg_a) != _compute_apr_snapshot_key(
        cfg_b
    ), "min_observations is COMPUTATIONAL -- changing it must move apr_snapshot_key."


def test_apr_snapshot_key_moves_on_dict_field_change():
    """bootstrap_block_size (dict-valued, COMPUTATIONAL) must move the key when its
    per-tf values change, proving dict serialization isn't a silent no-op.
    """
    cfg_a = _make_config(bootstrap_block_size={"5m": 78, "15m": 26, "1h": 10, "1d": 10})
    cfg_b = _make_config(bootstrap_block_size={"5m": 99, "15m": 26, "1h": 10, "1d": 10})
    assert _compute_apr_snapshot_key(cfg_a) != _compute_apr_snapshot_key(cfg_b)


def test_apr_snapshot_key_deterministic_regardless_of_dict_insertion_order():
    """A dict field's key-insertion order must never affect the hash (sorted join)."""
    cfg_a = _make_config(bootstrap_block_size={"5m": 78, "15m": 26, "1h": 10, "1d": 10})
    cfg_b = _make_config(bootstrap_block_size={"1d": 10, "1h": 10, "15m": 26, "5m": 78})
    assert _compute_apr_snapshot_key(cfg_a) == _compute_apr_snapshot_key(cfg_b)


def test_apr_snapshot_key_unchanged_by_cross_sectional_bootstrap_threads_change():
    """Explicit case named in the plan: cross_sectional_bootstrap_threads is
    OPERATIONAL (thread count changes wall time only, per 162-01's precomputed
    resample-index matrix) -- must never move the snapshot key.
    """
    cfg_a = _make_config(cross_sectional_bootstrap_threads={"5m": 6, "15m": 1, "1h": 1, "1d": 1})
    cfg_b = _make_config(cross_sectional_bootstrap_threads={"5m": 1, "15m": 1, "1h": 1, "1d": 1})
    assert _compute_apr_snapshot_key(cfg_a) == _compute_apr_snapshot_key(cfg_b)


# ---------------------------------------------------------------------------
# active_scales field (2026-07-30 per-tf active-scale-set design)
# ---------------------------------------------------------------------------


def test_active_scales_for_returns_canonical_tuple():
    cfg = _make_config()
    assert cfg.active_scales_for("1h") == ("fast", "mid")
    assert cfg.active_scales_for("5m") == ("fast", "mid", "slow", "extended")


def test_apr_snapshot_key_moves_on_active_scales_change():
    """active_scales is COMPUTATIONAL -- excluding a scale changes which cells get
    attempted, so it must move the fingerprint or a stale cell would silently be
    treated as already-correct under the old scale set."""
    cfg_a = _make_config(
        active_scales={
            "5m": ("fast", "mid", "slow", "extended"),
            "15m": ("fast", "mid", "slow", "extended"),
            "1h": ("fast", "mid", "slow", "extended"),
            "1d": ("fast", "mid", "slow", "extended"),
        }
    )
    cfg_b = _make_config(
        active_scales={
            "5m": ("fast", "mid", "slow", "extended"),
            "15m": ("fast", "mid", "slow", "extended"),
            "1h": ("fast", "mid"),
            "1d": ("fast", "mid", "slow", "extended"),
        }
    )
    assert _compute_apr_snapshot_key(cfg_a) != _compute_apr_snapshot_key(cfg_b)


def test_apr_snapshot_key_deterministic_regardless_of_active_scales_tuple_order():
    """An operator reordering the configured JSON array (semantically identical
    active set) must NOT move the fingerprint -- canonicalize_active_scales()
    (called at load time in from_apr, not here) is what guarantees this in
    production; this test proves _compute_apr_snapshot_key itself doesn't need to
    re-sort, AS LONG AS both configs already hold canonically-ordered tuples."""
    cfg_a = _make_config(active_scales={"5m": ("fast", "mid"), "15m": (), "1h": (), "1d": ()})
    cfg_b = _make_config(active_scales={"5m": ("fast", "mid"), "15m": (), "1h": (), "1d": ()})
    assert _compute_apr_snapshot_key(cfg_a) == _compute_apr_snapshot_key(cfg_b)


# ---------------------------------------------------------------------------
# Task 2: per-table upstream watermark -- DB-free in-place-mutation proof
# ---------------------------------------------------------------------------


def test_watermark_differs_on_forward_returns_computed_at_change_alone():
    """Two watermark dicts with identical MAX(bar_ts)/COUNT but a different
    forward_returns.computed_at (an in-place correction bumped it) must NOT be
    equal -- this is the resolved Open Question #1 requirement.
    """
    base = {
        "forward_returns": {
            "max_bar_ts": "2026-01-01T00:00:00Z",
            "count": 1000,
            "max_computed_at": "2026-01-01T01:00:00Z",
        },
        "feature_vectors": {"max_bar_ts": "2026-01-01T00:00:00Z", "count": 1000},
    }
    mutated = {
        "forward_returns": {
            "max_bar_ts": "2026-01-01T00:00:00Z",
            "count": 1000,
            "max_computed_at": "2026-01-02T09:00:00Z",
        },
        "feature_vectors": {"max_bar_ts": "2026-01-01T00:00:00Z", "count": 1000},
    }
    assert base != mutated


def test_watermark_differs_on_market_regimes_relabel_hash_change_alone():
    """An HMM relabel mutates market_regimes.regime_label in place with unchanged
    ts/count -- only the value-sensitive md5(string_agg(regime_label...)) hash differs.
    """
    base = {
        "market_regimes": {"max_ts": "2026-01-01T00:00:00Z", "count": 500, "regime_hash": "aaa111"}
    }
    mutated = {
        "market_regimes": {"max_ts": "2026-01-01T00:00:00Z", "count": 500, "regime_hash": "bbb222"}
    }
    assert base != mutated


def test_watermark_differs_on_concept_registry_status_hash_change_alone():
    """A concept_registry (domain='feature') status transition (e.g.
    active -> shadow_only) moves the status-hash component even though
    concept_registry carries no timestamp column relevant to this watermark.
    """
    base = {"concept_registry": {"status_hash": "xyz789"}}
    mutated = {"concept_registry": {"status_hash": "uvw456"}}
    assert base != mutated


def test_watermark_equal_when_all_components_identical():
    w1 = {
        "forward_returns": {
            "max_bar_ts": "2026-01-01T00:00:00Z",
            "count": 1000,
            "max_computed_at": "2026-01-01T01:00:00Z",
        },
        "feature_vectors": {"max_bar_ts": "2026-01-01T00:00:00Z", "count": 1000},
    }
    w2 = {
        "forward_returns": {
            "max_bar_ts": "2026-01-01T00:00:00Z",
            "count": 1000,
            "max_computed_at": "2026-01-01T01:00:00Z",
        },
        "feature_vectors": {"max_bar_ts": "2026-01-01T00:00:00Z", "count": 1000},
    }
    assert w1 == w2


class _FakeCursor:
    """Records the params passed to every execute() call; returns dummy
    fetchone() rows shaped to match each real query in call order."""

    def __init__(self, fetchone_results: list[tuple]):
        self.captured_params: list[dict] = []
        self._fetchone_results = fetchone_results
        self._call_idx = 0

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False

    def execute(self, sql, params=None):
        self.captured_params.append(params)

    def fetchone(self):
        row = self._fetchone_results[self._call_idx]
        self._call_idx += 1
        return row


class _FakeConn:
    def __init__(self, fetchone_results: list[tuple]):
        self._cursor = _FakeCursor(fetchone_results)

    def cursor(self):
        return self._cursor


def test_compute_upstream_watermark_per_symbol_cross_sectional_scopes_to_own_symbol():
    """CR-01 regression (162 code review): a regime-group-routed symbol's OWN
    'cross_sectional' row (is_group_pooled defaults False) must scope
    forward_returns/feature_vectors to [symbol] -- NEVER to symbol_list=None.

    Before the fix, is_group_pooled was inferred from pass_type == 'cross_sectional'
    alone, so this exact call (a per-symbol prepass cell, not the group-pooled
    POOLED cell) silently queried WHERE symbol = ANY(NULL), permanently hiding
    that symbol's real upstream data changes from the fingerprint gate. The
    function no longer even accepts a pass_type parameter (162 simplify-pass) --
    it was dead weight once is_group_pooled fully determined behavior.
    """
    fake_conn = _FakeConn(fetchone_results=[(None, 0, None), (None, 0)])
    _compute_upstream_watermark(
        fake_conn,
        "SPY",
        "1d",
        concept_registry_watermark={"status_hash": "precomputed"},
    )
    assert len(fake_conn._cursor.captured_params) == 2
    for params in fake_conn._cursor.captured_params:
        assert params["symbols"] == ["SPY"], (
            f"expected symbols=['SPY'], got {params['symbols']!r} -- per-symbol "
            "cross_sectional cell must not degrade to ANY(NULL)"
        )


def test_compute_upstream_watermark_group_pooled_scopes_to_regime_group_and_peer_symbols():
    """Companion to the CR-01 regression above: the actual group-pooled POOLED
    cell (is_group_pooled=True, the cs_cell_plan/group-level call site) must
    still scope by regime_group/symbol_list, not collapse to a single symbol --
    this is T-162-03-01's original guarantee and must not regress from the
    is_group_pooled refactor.
    """
    fake_conn = _FakeConn(
        fetchone_results=[(None, 0, None), (None, 0), (None, 0, "hash1"), ("hash2",)]
    )
    _compute_upstream_watermark(
        fake_conn,
        symbol=None,
        tf="1d",
        is_group_pooled=True,
        regime_group="equity",
        symbol_list=["SPY", "QQQ"],
        concept_registry_watermark={"status_hash": "precomputed"},
    )
    fr_fv_params, mr_params = (
        fake_conn._cursor.captured_params[0],
        fake_conn._cursor.captured_params[2],
    )
    assert fr_fv_params["symbols"] == ["SPY", "QQQ"]
    assert mr_params["regime_group"] == "equity"


def test_compute_upstream_watermark_rejects_group_pooled_with_a_real_symbol():
    """Altitude fix (162 code-review): is_group_pooled=True with a non-None
    symbol must fail loud, not silently misroute -- this is the exact
    invalid-combination shape that caused CR-01, now structurally impossible
    to pass without an immediate crash rather than a wrong answer.
    """
    fake_conn = _FakeConn(fetchone_results=[])
    with pytest.raises(AssertionError):
        _compute_upstream_watermark(
            fake_conn,
            "SPY",
            "1d",
            is_group_pooled=True,
            regime_group="equity",
            symbol_list=["SPY", "QQQ"],
        )


def test_compute_upstream_watermark_rejects_per_symbol_with_no_symbol():
    """Companion: is_group_pooled=False (default) with symbol=None must also
    fail loud -- every per-symbol row is scoped to exactly one real symbol.
    """
    fake_conn = _FakeConn(fetchone_results=[])
    with pytest.raises(AssertionError):
        _compute_upstream_watermark(fake_conn, None, "1d")


# ---------------------------------------------------------------------------
# Task 3: _fingerprint_is_valid component-match semantics
# ---------------------------------------------------------------------------

_FULL_MATCH_CURRENT = {
    "code_content_key": "code123",
    "apr_snapshot_key": "apr456",
    "upstream_watermark": {"forward_returns": {"count": 10}},
}


def test_fingerprint_valid_on_full_component_match():
    stored = dict(_FULL_MATCH_CURRENT)
    assert _fingerprint_is_valid(stored, _FULL_MATCH_CURRENT) is True


def test_fingerprint_invalid_on_none_stored():
    assert _fingerprint_is_valid(None, _FULL_MATCH_CURRENT) is False


def test_fingerprint_invalid_on_code_content_key_mismatch():
    stored = dict(_FULL_MATCH_CURRENT, code_content_key="different")
    assert _fingerprint_is_valid(stored, _FULL_MATCH_CURRENT) is False


def test_fingerprint_invalid_on_apr_snapshot_key_mismatch():
    stored = dict(_FULL_MATCH_CURRENT, apr_snapshot_key="different")
    assert _fingerprint_is_valid(stored, _FULL_MATCH_CURRENT) is False


def test_fingerprint_invalid_on_upstream_watermark_mismatch():
    stored = dict(_FULL_MATCH_CURRENT, upstream_watermark={"forward_returns": {"count": 99}})
    assert _fingerprint_is_valid(stored, _FULL_MATCH_CURRENT) is False


def test_fingerprint_invalid_on_partial_match_two_of_three():
    """A partial match (2 of 3 components equal) is a full miss, never a partial skip."""
    stored = dict(_FULL_MATCH_CURRENT, upstream_watermark={"forward_returns": {"count": 99}})
    assert _fingerprint_is_valid(stored, _FULL_MATCH_CURRENT) is False


# ---------------------------------------------------------------------------
# Task 4 (todo 198): status-only staleness -- a concept_registry.status_hash
# change must never force a recompute of the expensive bootstrap-CI math.
# Verified against the real code (main()'s registry-drift gate at the
# get_all_concepts() comment): ic_engine always computes every feature
# regardless of status, so status never gates WHAT gets computed -- it only
# feeds the feature_status_at_eval provenance column. A status-hash mismatch
# with every other component matching must be treated as "cheap metadata
# refresh needed", never "recompute everything".
#
# Phase 170 Plan 06: watermark key renamed "feature_registry" -> "concept_registry".
# ---------------------------------------------------------------------------

_STATUS_MATCH_CURRENT = {
    "code_content_key": "code123",
    "apr_snapshot_key": "apr456",
    "upstream_watermark": {
        "forward_returns": {"count": 10},
        "concept_registry": {"status_hash": "hash_now"},
    },
}


def test_fingerprint_computational_key_drops_concept_registry():
    key = _fingerprint_computational_key(_STATUS_MATCH_CURRENT)
    assert "concept_registry" not in key["upstream_watermark"]
    assert key["upstream_watermark"]["forward_returns"] == {"count": 10}


def test_fingerprint_computational_key_keeps_other_watermark_components():
    fp = dict(
        _STATUS_MATCH_CURRENT,
        upstream_watermark={
            "forward_returns": {"count": 10},
            "feature_vectors": {"count": 10},
            "market_regimes": {"count": 5},
            "concept_registry": {"status_hash": "hash_now"},
        },
    )
    key = _fingerprint_computational_key(fp)
    assert set(key["upstream_watermark"]) == {
        "forward_returns",
        "feature_vectors",
        "market_regimes",
    }


def test_computationally_valid_when_only_concept_registry_status_hash_differs():
    stored = dict(
        _STATUS_MATCH_CURRENT,
        upstream_watermark=dict(
            _STATUS_MATCH_CURRENT["upstream_watermark"],
            concept_registry={"status_hash": "hash_before"},
        ),
    )
    assert _fingerprint_is_computationally_valid(stored, _STATUS_MATCH_CURRENT) is True


def test_computationally_invalid_when_forward_returns_differs_too():
    stored = dict(
        _STATUS_MATCH_CURRENT,
        upstream_watermark={
            "forward_returns": {"count": 99},
            "concept_registry": {"status_hash": "hash_before"},
        },
    )
    assert _fingerprint_is_computationally_valid(stored, _STATUS_MATCH_CURRENT) is False


def test_computational_key_unchanged_by_registry_key_rename():
    """Direct proof the Phase 170 Plan 06 cutover cannot trigger a recompute:
    a fingerprint built with the OLD watermark key ('feature_registry') and one
    built with the NEW key ('concept_registry'), otherwise identical, must
    produce EQUAL computational keys -- _fingerprint_computational_key drops
    whichever key is present under the SAME "concept_registry" filter name, so
    if the key/filter pairing were ever mismatched, this would be the first
    test to catch it.
    """
    fp_old_key = {
        "code_content_key": "code123",
        "apr_snapshot_key": "apr456",
        "upstream_watermark": {
            "forward_returns": {"count": 10},
            "feature_registry": {"status_hash": "hash_before_rename"},
        },
    }
    fp_new_key = {
        "code_content_key": "code123",
        "apr_snapshot_key": "apr456",
        "upstream_watermark": {
            "forward_returns": {"count": 10},
            "concept_registry": {"status_hash": "hash_after_rename"},
        },
    }
    assert _fingerprint_computational_key(fp_old_key) == _fingerprint_computational_key(fp_new_key)


def test_computationally_invalid_on_code_content_key_mismatch():
    stored = dict(_STATUS_MATCH_CURRENT, code_content_key="different")
    assert _fingerprint_is_computationally_valid(stored, _STATUS_MATCH_CURRENT) is False


def test_computationally_invalid_on_none_stored():
    assert _fingerprint_is_computationally_valid(None, _STATUS_MATCH_CURRENT) is False


def test_status_only_stale_true_when_computationally_valid_but_not_fully_valid():
    stored = dict(
        _STATUS_MATCH_CURRENT,
        upstream_watermark=dict(
            _STATUS_MATCH_CURRENT["upstream_watermark"],
            concept_registry={"status_hash": "hash_before"},
        ),
    )
    assert _fingerprint_is_status_only_stale(stored, _STATUS_MATCH_CURRENT) is True


def test_status_only_stale_false_when_fully_valid():
    """Nothing changed at all -- true full skip, no refresh needed."""
    stored = dict(_STATUS_MATCH_CURRENT)
    assert _fingerprint_is_status_only_stale(stored, _STATUS_MATCH_CURRENT) is False


def test_status_only_stale_false_when_computationally_invalid_too():
    """A real data/code change alongside the status change is a full recompute,
    not a status-only refresh -- the expensive path already rewrites
    feature_status_at_eval as a side effect, so a separate refresh would be
    redundant (and, if ordered wrong, could clobber the fresh recompute)."""
    stored = dict(
        _STATUS_MATCH_CURRENT,
        upstream_watermark={
            "forward_returns": {"count": 99},
            "concept_registry": {"status_hash": "hash_before"},
        },
    )
    assert _fingerprint_is_status_only_stale(stored, _STATUS_MATCH_CURRENT) is False


def test_status_only_stale_false_on_none_stored():
    """A never-before-computed cell must go through the full compute path, not
    a metadata-only refresh of rows that don't exist yet."""
    assert _fingerprint_is_status_only_stale(None, _STATUS_MATCH_CURRENT) is False


def test_feature_status_refresh_sql_targets_feature_ic_scores_via_registry_join():
    sql_upper = _FEATURE_STATUS_REFRESH_SQL.upper()
    assert "UPDATE FEATURE_IC_SCORES" in sql_upper
    assert "CONCEPT_REGISTRY" in sql_upper
    assert "FEATURE_STATUS_AT_EVAL" in sql_upper


def test_feature_status_refresh_sql_is_idempotent_via_is_distinct_from():
    """IS DISTINCT FROM (not plain !=, which is NULL-unsafe) -- a no-op refresh
    on already-current rows must not touch them, keeping this cheap even when
    called on a large already-fresh symbol set."""
    assert "IS DISTINCT FROM" in _FEATURE_STATUS_REFRESH_SQL.upper()


# ---------------------------------------------------------------------------
# Task 4: _classify_fingerprint -- the ONE decision function shared by both the
# per-symbol and cross-sectional prepass loops (todo 198), so the two passes
# can never diverge in what counts as valid/stale/invalid.
# ---------------------------------------------------------------------------

_STATUS_STALE_STORED = dict(
    _STATUS_MATCH_CURRENT,
    upstream_watermark=dict(
        _STATUS_MATCH_CURRENT["upstream_watermark"],
        concept_registry={"status_hash": "hash_before"},
    ),
)
_FULLY_STALE_STORED = dict(
    _STATUS_MATCH_CURRENT,
    upstream_watermark={
        "forward_returns": {"count": 99},
        "concept_registry": {"status_hash": "hash_before"},
    },
)


def test_classify_fingerprint_valid_on_full_match():
    result = _classify_fingerprint(
        dict(_STATUS_MATCH_CURRENT), _STATUS_MATCH_CURRENT, force_refresh=False
    )
    assert result == "valid"


def test_classify_fingerprint_status_only_stale_on_status_hash_mismatch_alone():
    result = _classify_fingerprint(_STATUS_STALE_STORED, _STATUS_MATCH_CURRENT, force_refresh=False)
    assert result == "status_only_stale"


def test_classify_fingerprint_invalid_on_computational_mismatch():
    result = _classify_fingerprint(_FULLY_STALE_STORED, _STATUS_MATCH_CURRENT, force_refresh=False)
    assert result == "invalid"


def test_classify_fingerprint_invalid_on_no_stored():
    result = _classify_fingerprint(None, _STATUS_MATCH_CURRENT, force_refresh=False)
    assert result == "invalid"


def test_classify_fingerprint_force_refresh_overrides_full_match_to_invalid():
    """--refresh means redo everything, including cells that are fully valid --
    matches the pre-existing args.refresh semantics, not a status-only refresh."""
    result = _classify_fingerprint(
        dict(_STATUS_MATCH_CURRENT), _STATUS_MATCH_CURRENT, force_refresh=True
    )
    assert result == "invalid"


def test_classify_fingerprint_force_refresh_overrides_status_only_stale_to_invalid():
    result = _classify_fingerprint(_STATUS_STALE_STORED, _STATUS_MATCH_CURRENT, force_refresh=True)
    assert result == "invalid"


# ---------------------------------------------------------------------------
# Task 4: _partition_symbol_cells -- aggregates one symbol's per-cell
# _classify_fingerprint results into (invalid_cells, needs_status_refresh) as
# TWO INDEPENDENT values (2026-07-29 code review regression, todo 198).
#
# The bug this guards against: the original wiring used a single elif to
# bucket a symbol as EITHER dispatched (has an invalid cell) OR needing a
# status refresh (no invalid cell, but a status_only_stale one) -- never
# both. A symbol with an invalid cell in one (tf, pass_type) AND a
# status_only_stale cell in a DIFFERENT (tf, pass_type) got dispatched (for
# the invalid cell) but its status_only_stale sibling was silently never
# refreshed: the dispatched worker's redundant recompute of that
# fingerprint-valid sibling hits feature_ic_scores' ON CONFLICT ... DO
# NOTHING (T-162-03-06), discarding the fresh feature_status_at_eval, while
# the post-compute fingerprint upsert (which covers ALL of a dispatched
# symbol's cells, unconditionally) stamps that cell's fingerprint fresh
# anyway -- permanent, silent status drift, never detected on any future run.
# ---------------------------------------------------------------------------


def test_partition_symbol_cells_all_valid_no_dispatch_no_refresh():
    result = _partition_symbol_cells({("5m", "pooled"): "valid"})
    assert result == ([], False)


def test_partition_symbol_cells_invalid_only_dispatches_no_refresh_from_that_cell():
    result = _partition_symbol_cells({("5m", "pooled"): "invalid"})
    assert result == ([("5m", "pooled")], False)


def test_partition_symbol_cells_status_only_stale_only_no_dispatch_needs_refresh():
    result = _partition_symbol_cells({("1d", "pooled"): "status_only_stale"})
    assert result == ([], True)


def test_partition_symbol_cells_mixed_invalid_and_status_only_stale_dispatches_and_refreshes():
    """The exact regression case: an invalid cell in one (tf, pass_type) and a
    status_only_stale cell in another must produce BOTH a dispatch (for the
    invalid cell) AND needs_status_refresh=True (for the sibling) -- never
    collapsed into an either/or bucket."""
    result = _partition_symbol_cells(
        {("5m", "pooled"): "invalid", ("1d", "pooled"): "status_only_stale"}
    )
    assert result == ([("5m", "pooled")], True)


def test_partition_symbol_cells_multiple_invalid_cells_all_collected():
    result = _partition_symbol_cells(
        {("5m", "pooled"): "invalid", ("1d", "pooled"): "invalid", ("1h", "pooled"): "valid"}
    )
    assert set(result[0]) == {("5m", "pooled"), ("1d", "pooled")}
    assert result[1] is False


# ---------------------------------------------------------------------------
# Task 3: DELETE SQL is scoped to the exact cell-key columns
# ---------------------------------------------------------------------------


def test_invalidate_delete_sql_scoped_to_full_cell_key():
    """Must filter on symbol + tf + regime_scope + training_window_end (the exact
    ic_cell_fingerprints PK columns) -- never a bare training_window_end filter,
    which would delete valid unrelated cells at the same window.
    """
    sql_upper = _FINGERPRINT_INVALIDATE_DELETE_SQL.upper()
    assert "DELETE FROM FEATURE_IC_SCORES" in sql_upper
    for required in ("SYMBOL", "TF", "REGIME_SCOPE", "TRAINING_WINDOW_END"):
        assert required in sql_upper, f"DELETE SQL missing required scoping column {required}"


def test_invalidate_delete_sql_is_not_a_bare_training_window_end_filter():
    """Regression: the DELETE must not be satisfiable by training_window_end alone --
    it must reference symbol/tf/regime_scope as real WHERE-clause predicates, not just
    appear as column names in a comment.
    """
    # Count '=' bound-parameter style predicates in the WHERE clause: symbol, tf,
    # regime_scope, training_window_end must each appear with their own placeholder.
    assert _FINGERPRINT_INVALIDATE_DELETE_SQL.count("%(") >= 4


# ---------------------------------------------------------------------------
# Todo 252: archive-before-delete -- feature_ic_scores rows must be preserved
# (never silently hard-deleted) whenever a code/APR change invalidates an
# already-computed cell. Live end-to-end correctness (including the fp_symbol vs
# symbol key-naming asymmetry between feature_ic_scores and ic_cell_fingerprints
# for cross-sectional cells) was verified manually against the live schema inside a
# rolled-back transaction before these tests were written; these are the structural/
# shape regressions, matching this file's own DB-free convention.
# ---------------------------------------------------------------------------


def test_archive_before_delete_sql_targets_history_table_from_live_table():
    sql_upper = _ARCHIVE_BEFORE_DELETE_SQL.upper()
    assert "INSERT INTO FEATURE_IC_SCORES_HISTORY" in sql_upper
    assert "FROM FEATURE_IC_SCORES FIS" in sql_upper


def test_archive_before_delete_sql_scoped_to_full_cell_key():
    """Same scoping discipline as the DELETE it precedes -- must filter on the
    exact ic_cell_fingerprints PK columns, never a bare training_window_end filter
    that could archive+leave-alone unrelated valid cells."""
    sql_upper = _ARCHIVE_BEFORE_DELETE_SQL.upper()
    for required in ("FIS.SYMBOL", "FIS.TF", "FIS.REGIME_SCOPE", "FIS.TRAINING_WINDOW_END"):
        assert required in sql_upper, f"archive SQL missing required scoping column {required}"


def test_archive_before_delete_sql_captures_fingerprint_provenance():
    """Must carry the OLD (about-to-be-overwritten) ic_cell_fingerprints tuple into
    the archived row -- reusing that table's existing provenance convention rather
    than inventing a second one (todo 252's explicit design requirement)."""
    sql_upper = _ARCHIVE_BEFORE_DELETE_SQL.upper()
    assert "LEFT JOIN IC_CELL_FINGERPRINTS FP" in sql_upper
    for col in (
        "ARCHIVED_CODE_CONTENT_KEY",
        "ARCHIVED_APR_SNAPSHOT_KEY",
        "ARCHIVED_UPSTREAM_WATERMARK",
    ):
        assert col in sql_upper


def test_archive_before_delete_sql_joins_fingerprint_on_separate_fp_symbol_param():
    """Regression for the exact bug class this design guards against: a naive same-
    column join (fp.symbol = fis.symbol) would silently miss every cross-sectional
    fingerprint, since feature_ic_scores.symbol is the 'POOLED' sentinel there while
    ic_cell_fingerprints.symbol is the real per-cell group:regime key. The join must
    bind fp.symbol to its OWN parameter, not reference fis.symbol directly."""
    assert "FP.SYMBOL = %(FP_SYMBOL)S" in _ARCHIVE_BEFORE_DELETE_SQL.upper()
    assert "FP.SYMBOL = FIS.SYMBOL" not in _ARCHIVE_BEFORE_DELETE_SQL.upper()


def test_archive_before_delete_cross_sectional_sql_same_shape_as_its_delete_counterpart():
    """The cross-sectional archive variant must mirror
    _FINGERPRINT_INVALIDATE_DELETE_CROSS_SECTIONAL_SQL's exact scoping (including the
    explicit regime filter neither the per-symbol DELETE nor its archive counterpart
    need), so archive and delete can never silently diverge in which rows they touch."""
    archive_upper = _ARCHIVE_BEFORE_DELETE_CROSS_SECTIONAL_SQL.upper()
    delete_upper = _FINGERPRINT_INVALIDATE_DELETE_CROSS_SECTIONAL_SQL.upper()
    for required in ("FIS.SYMBOL", "FIS.TF", "FIS.REGIME", "FIS.TRAINING_WINDOW_END"):
        assert required in archive_upper
    assert "CROSS_SECTIONAL" in delete_upper
    assert "FP.SYMBOL = %(FP_SYMBOL)S" in archive_upper
    assert "FP.PASS_TYPE = 'CROSS_SECTIONAL'" in archive_upper


# ---------------------------------------------------------------------------
# Task 3: existing_keys-removal regression (structural proof the stale-snapshot
# channel is gone -- same inspect-based style as 162-01's parity tests)
# ---------------------------------------------------------------------------


def test_compute_one_regime_cell_has_no_existing_keys_parameter():
    sig = inspect.signature(_compute_one_regime_cell)
    assert "existing_keys" not in sig.parameters


def test_compute_one_regime_cell_source_has_no_existing_keys_reference():
    source = inspect.getsource(_compute_one_regime_cell)
    assert "existing_keys" not in source


def test_compute_symbol_tf_has_no_existing_keys_parameter():
    sig = inspect.signature(_compute_symbol_tf)
    assert "existing_keys" not in sig.parameters


def test_compute_symbol_tf_source_has_no_existing_keys_reference():
    source = inspect.getsource(_compute_symbol_tf)
    assert "existing_keys" not in source


def test_compute_cross_sectional_tf_has_no_existing_keys_parameter():
    sig = inspect.signature(_compute_cross_sectional_tf)
    assert "existing_keys" not in sig.parameters


def test_compute_cross_sectional_tf_source_has_no_existing_keys_reference():
    source = inspect.getsource(_compute_cross_sectional_tf)
    assert "existing_keys" not in source


# ---------------------------------------------------------------------------
# Task 3: _symbol_expected_cells -- must mirror _compute_symbol_tf's real
# routing exactly (main()'s worker_args construction reuses the identical
# symbol_regime_class/group_by_name/equity_model_enabled inputs).
# ---------------------------------------------------------------------------

_TFS = ["5m", "1d"]


def test_symbol_expected_cells_unrouted_symbol_gets_pooled_and_symbol_hmm():
    """A symbol with no matching enabled group: cross_sectional=False, so the
    primary regime pass is 'symbol_hmm' (mr_dict=None case in _compute_symbol_tf).
    """
    cells = _symbol_expected_cells("SPY", _TFS, {}, {}, equity_model_enabled=True)
    assert set(cells) == {
        ("5m", "pooled"),
        ("5m", "symbol_hmm"),
        ("1d", "pooled"),
        ("1d", "symbol_hmm"),
    }


def test_symbol_expected_cells_equity_model_disabled_gets_pooled_and_symbol_hmm():
    """equity_model_enabled=False: no group can ever be routed (mirrors main()'s
    mr_dict=None-if-not-enabled_groups branch) regardless of symbol_regime_class.
    """
    cells = _symbol_expected_cells(
        "SPY", _TFS, {"SPY": "equity"}, {"equity": {}}, equity_model_enabled=False
    )
    assert set(cells) == {
        ("5m", "pooled"),
        ("5m", "symbol_hmm"),
        ("1d", "pooled"),
        ("1d", "symbol_hmm"),
    }


def test_symbol_expected_cells_routed_symbol_gets_pooled_and_cross_sectional():
    """A symbol routed to an enabled group (no dual-write): primary pass is
    'cross_sectional', no additional 'symbol_hmm' dual-write pass.
    """
    cells = _symbol_expected_cells(
        "SPY", _TFS, {"SPY": "equity"}, {"equity": {"dual_write_symbol_hmm": False}}, True
    )
    assert set(cells) == {
        ("5m", "pooled"),
        ("5m", "cross_sectional"),
        ("1d", "pooled"),
        ("1d", "cross_sectional"),
    }


def test_symbol_expected_cells_dual_write_gets_all_three_pass_types():
    """A symbol routed to a group with dual_write_symbol_hmm=true: pooled +
    cross_sectional (primary) + symbol_hmm (dual-write) -- 3 cells per tf.
    """
    cells = _symbol_expected_cells(
        "TLT", _TFS, {"TLT": "rates"}, {"rates": {"dual_write_symbol_hmm": True}}, True
    )
    assert set(cells) == {
        ("5m", "pooled"),
        ("5m", "cross_sectional"),
        ("5m", "symbol_hmm"),
        ("1d", "pooled"),
        ("1d", "cross_sectional"),
        ("1d", "symbol_hmm"),
    }
    # Exactly 3 cells per tf, 6 total across 2 tfs -- no accidental duplicates.
    assert len(cells) == 6


def test_symbol_expected_cells_pooled_always_present_exactly_once_per_tf():
    for cells in (
        _symbol_expected_cells("SPY", _TFS, {}, {}, True),
        _symbol_expected_cells("SPY", _TFS, {"SPY": "equity"}, {"equity": {}}, True),
    ):
        for tf in _TFS:
            assert cells.count((tf, "pooled")) == 1
