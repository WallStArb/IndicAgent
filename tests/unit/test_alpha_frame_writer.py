"""Unit tests: AlphaFrameWriter — FrameConfig binding, expected-R snapshot, idempotency,
and grep-style source guards (no sr_resist_dist branch, no feature_vectors read).

No DB, no Kafka.
"""

from __future__ import annotations

import sys
from pathlib import Path

_project_root = Path(__file__).parent.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from services.alpha_frame_writer import FrameConfig, compute_expected_r_snapshot
from src.core.agent.base_batch import BaseBatch

_SOURCE_PATH = _project_root / "services" / "alpha_frame_writer.py"


def _read_source() -> str:
    return _SOURCE_PATH.read_text()


# ---------------------------------------------------------------------------
# FrameConfig.from_apr
# ---------------------------------------------------------------------------


def test_frame_config_from_apr_binds_all_keys():
    cfg = FrameConfig.from_apr(
        {
            "alpha.frame.stop_atr_mult": "1.5",
            "alpha.frame.target_r_multiple": "2.0",
            "alpha.frame.atr_period": "14",
        }
    )
    assert cfg.stop_atr_mult == 1.5
    assert cfg.target_r_multiple == 2.0
    assert cfg.atr_period == 14


def test_frame_config_from_apr_applies_defaults_when_keys_missing():
    cfg = FrameConfig.from_apr({})
    assert cfg.stop_atr_mult == 1.5
    assert cfg.target_r_multiple == 2.0
    assert cfg.atr_period == 14


def test_frame_config_is_frozen():
    cfg = FrameConfig.from_apr({})
    try:
        cfg.stop_atr_mult = 9.9  # type: ignore[misc]
        raised = False
    except Exception:
        raised = True
    assert raised, "FrameConfig must reject attribute mutation (frozen=True)"


# ---------------------------------------------------------------------------
# compute_expected_r_snapshot (D-03)
# ---------------------------------------------------------------------------


def test_expected_r_snapshot_long_signal():
    gross, net = compute_expected_r_snapshot(0.4, 2.0, 0.05)
    assert gross == 0.8
    assert net == 0.75


def test_expected_r_snapshot_direction_agnostic():
    """Negative alpha_score (short signal) yields the same magnitude — abs() applied."""
    gross, net = compute_expected_r_snapshot(-0.4, 2.0, 0.05)
    assert gross == 0.8
    assert net == 0.75


def test_expected_r_snapshot_non_none_non_nan():
    gross, net = compute_expected_r_snapshot(0.0, 2.0, 0.0)
    assert gross is not None
    assert net is not None
    assert gross == gross  # not NaN
    assert net == net  # not NaN


# ---------------------------------------------------------------------------
# frame_id idempotency (content_key-derived)
# ---------------------------------------------------------------------------


def test_content_key_stable_across_invocations():
    event_id = "abc123"
    bar_ts = "2026-07-09 12:00:00+00:00"
    key1 = BaseBatch.content_key(event_id, bar_ts, "primary")
    key2 = BaseBatch.content_key(event_id, bar_ts, "primary")
    assert key1 == key2


def test_content_key_differs_across_frame_variants():
    event_id = "abc123"
    bar_ts = "2026-07-09 12:00:00+00:00"
    key_primary = BaseBatch.content_key(event_id, bar_ts, "primary")
    key_grid = BaseBatch.content_key(event_id, bar_ts, "grid_0.8")
    assert key_primary != key_grid


# ---------------------------------------------------------------------------
# Source guards (grep-style, mirrors test_ic_engine_compute_split.py's style)
# ---------------------------------------------------------------------------


def test_no_sr_resist_dist_branch():
    """ATR-only path (review Pitfall 1) — no dead conditional branch."""
    assert "sr_resist_dist" not in _read_source()


def test_no_feature_vectors_read():
    """ATR is caller-supplied, never read from feature_vectors (review H2)."""
    assert "feature_vectors" not in _read_source()


def test_no_kafka_or_topic_alpha_frames():
    """No live consumer for alpha_frames — matches EnsembleICEngine precedent (Pitfall 5)."""
    src = _read_source()
    assert "topic_alpha_frames" not in src
    assert "KafkaProducer" not in src


def test_exception_handler_uses_error_not_exc():
    src = _read_source()
    assert "except Exception as error" in src
    assert "as exc" not in src


def test_insert_sql_includes_expected_r_columns():
    src = _read_source()
    assert "gross_expected_r" in src
    assert "cost_r" in src
    assert "net_expected_r" in src


def test_pending_sql_is_parameterized_and_scoped_per_partition():
    """No f-string/%-format SQL interpolation of data values; scoped per (symbol, tf)."""
    src = _read_source()
    assert "ae.symbol = $1 AND ae.tf = $2" in src
