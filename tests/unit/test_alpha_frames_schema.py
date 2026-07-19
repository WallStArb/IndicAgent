"""Unit tests: migration 205 (alpha_frames schema) DDL assertions.

No DB. Reads the migration SQL text and asserts structural properties, mirroring
test_ensemble_ic_config.py's schema-assertion style applied to raw SQL text.
"""

from __future__ import annotations

from pathlib import Path

_MIGRATION_PATH = (
    Path(__file__).parent.parent.parent
    / "production"
    / "migrations"
    / "205_alpha_frames_schema.sql"
)


def _read_migration() -> str:
    return _MIGRATION_PATH.read_text()


def test_migration_file_exists():
    assert _MIGRATION_PATH.is_file()


def test_status_check_has_closed_ic_decay_and_closed_max_hold():
    sql = _read_migration()
    assert "closed_ic_decay" in sql
    assert "closed_max_hold" in sql


def test_status_check_does_not_contain_closed_reversal():
    """D-04: closed_reversal is dropped entirely, not reserved or half-supported."""
    sql = _read_migration()
    assert "closed_reversal" not in sql


def test_contains_provenance_columns():
    """Pitfall 6: corpus_run_id and weight_epoch provenance columns."""
    sql = _read_migration()
    assert "corpus_run_id" in sql
    assert "weight_epoch" in sql


def test_pk_is_composite_frame_id_bar_ts():
    """Review H1: PK must contain bar_ts (the hypertable partition column)."""
    sql = _read_migration()
    assert "PRIMARY KEY (frame_id, bar_ts)" in sql


def test_frame_id_is_not_uuid():
    """Review H1: frame_id is a deterministic content_key TEXT, not a uuid."""
    sql = _read_migration()
    assert "frame_id uuid" not in sql


def test_no_standalone_frame_id_primary_key():
    """The schema doc's sole-column `frame_id uuid PRIMARY KEY` shape must not survive."""
    sql = _read_migration()
    for line in sql.splitlines():
        stripped = line.strip()
        if (
            stripped.startswith("frame_id")
            and "PRIMARY KEY" in stripped
            and "bar_ts" not in stripped
        ):
            raise AssertionError(f"Found a standalone frame_id PRIMARY KEY line: {stripped!r}")


def test_no_foreign_key_to_alpha_events():
    """Review M1: no FK -- alpha_events is truncated on every corpus rebuild."""
    sql = _read_migration()
    assert "REFERENCES alpha_events" not in sql


def test_create_hypertable_and_uq_constraint_present():
    sql = _read_migration()
    assert "create_hypertable" in sql
    assert "uq_alpha_frames_variant" in sql


def test_seeds_correct_apr_key_names():
    sql = _read_migration()
    for key in (
        "alpha.frame.target_r_multiple",
        "alpha.frame.stop_atr_mult",
        "alpha.frame.atr_period",
        "alpha.scoring.min_strategy_n",
        "alpha.scoring.bootstrap_max_n",
        "alpha.scoring.bootstrap_batch",
        "infra.alpha_frame_writer.chunk_size",
        "infra.counterfactual_tracker.itersize",
        "infra.counterfactual_tracker.workers",
    ):
        assert key in sql, f"missing APR key seed: {key}"


def test_does_not_seed_target_r_fallback():
    """Pitfall 3: seed exactly one name (target_r_multiple), never target_r_fallback."""
    sql = _read_migration()
    assert "target_r_fallback" not in sql


def test_does_not_reseed_hold_max_bars_keys():
    """The 36 alpha.frame.hold_max_bars.<regime>.<tf> keys already exist (migration 195);
    this migration may reference the key name in comments (max_hold_bars column) but must
    not INSERT it as a literal config_key value."""
    sql = _read_migration()
    assert "'alpha.frame.hold_max_bars" not in sql


def test_does_not_seed_grid_stop_atr_mults():
    """The 4-variant calibration grid is out of scope for this phase; the key name may be
    mentioned in a comment explaining the omission but must not be INSERTed."""
    sql = _read_migration()
    assert "'alpha.frame.grid_stop_atr_mults'" not in sql
