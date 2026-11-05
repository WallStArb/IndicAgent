"""Source-level guard: feature_vectors' columns equal the kernel registry's column set (186-24).

The table's columns are migration 425's CREATE TABLE (as feature_vectors_v2) plus every later
migration's `ALTER TABLE ... ADD COLUMN` under the table's name at that migration:
feature_vectors_v2 before migration 570 renamed it, feature_vectors from then on (526, todo 553,
is one such addition). Before 570, `ALTER TABLE feature_vectors` is the dropped v1 table and never
counts. The expectation is
derived from `default_registry()` and `UNOWNED_COLUMNS`, never from a hardcoded list, so a later
registry change fails here instead of silently skewing the rebuilt table against what the
kernels compute (train-serve skew for 186-25 and 186-27).
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from src.intelligence.features.contract.registry import UNOWNED_COLUMNS, default_registry

_ROOT = Path(__file__).resolve().parents[3]
_MIGRATIONS = _ROOT / "production" / "migrations"
_EVIDENCE = (
    _ROOT
    / ".planning/phases/186-old-ensemble-chain-retirement-and-ic-engine-re-scope/evidence"
    / "186-24-feature-vectors-v2-schema.json"
)

KEYS = ("symbol", "tf", "bar_ts")
REGIME_TEXT = ("regime", "regime_volatility")

# Dropped feature columns and why (mirrors the evidence JSON).
DROPPED_COLUMNS: dict[str, str] = {
    "momentum_rank_z": "todo 421: never computed, cross-sectional rank is not a kernel",
    "volume_rank_z": "todo 421",
    "volatility_rank_z": "todo 421",
    "regime_rolling": "text column never computed, not a FeatureVector field",
    "days_to_month_end": "todo 115: exact duplicate of 1 - month_position",
}
# Columns the registry retired after migration 425 created the table (todo 584 item 6, D5): the
# kernels are gone and the writers stop populating them, but the physical columns stay until the
# rebuild's summary card is written (derived cache, no same-day DROP).
RETIRED_COLUMNS: dict[str, str] = {
    name: "todo 584 item 6: retired (D5 universe-dead, or the saturated sweep_detected flag, 6c)"
    for name in (
        "in_london_kz",
        "amd_phase",
        "amd_manipulation_detected",
        "amd_distribution_direction",
        "manip_strength",
        "overnight_high_dist_atr",
        "overnight_low_dist_atr",
        "overnight_range_pct",
        "asian_session_high_dist_atr",
        "asian_session_low_dist_atr",
        "ret_div_1m_5m",
        "sweep_detected",
        "hmm_vol_prob_elevated",
    )
}
NEVER_COMPUTED = ("momentum_rank_z", "volume_rank_z", "volatility_rank_z")
METADATA_DROPPED: dict[str, str] = {
    "feature_vector_id": "superseded by the PK plus provenance_batch (D-34)",
    "pipeline_version": "per-row provenance superseded by provenance_batch",
    "feature_factory_version": "per-row provenance superseded by provenance_batch",
    "regime_label_source": "constant per-row provenance",
    "bar_close_ts": "derived: bar_ts plus the tf length",
}


def expected_columns() -> set[str]:
    """Registry-derived column set of feature_vectors."""
    feature = set(default_registry().feature_columns()) | set(UNOWNED_COLUMNS)
    return (feature - set(DROPPED_COLUMNS)) | set(KEYS) | set(REGIME_TEXT)


def migration_path() -> Path:
    paths = sorted(_MIGRATIONS.glob("*_feature_vectors_v2.sql"))
    assert len(paths) == 1, paths
    return paths[0]


def _migration_number(path: Path) -> int:
    return int(path.name.split("_", 1)[0])


def rename_number() -> int:
    """The migration that gave the table the name feature_vectors (570)."""
    paths = sorted(_MIGRATIONS.glob("*_feature_vectors_one_name.sql"))
    assert len(paths) == 1, paths
    return _migration_number(paths[0])


def _migration_lines() -> list[str]:
    return [line.split("--", 1)[0].rstrip() for line in migration_path().read_text().splitlines()]


def created_columns() -> list[str]:
    """Migration 425's CREATE TABLE columns, in DDL order."""
    pattern = re.compile(r"^    ([a-z_][a-z0-9_]*) (real|text|timestamptz|varchar|uuid)")
    columns = [m.group(1) for line in _migration_lines() if (m := pattern.match(line))]
    assert columns, "no columns parsed: keep 4-space-indented `name type` lines, one per line"
    return columns


_ADD = re.compile(r"^\s+ADD COLUMN (?:IF NOT EXISTS )?([a-z_][a-z0-9_]*) real[,;]$")
_DROP = re.compile(r"^\s+DROP COLUMN (?:IF EXISTS )?([a-z_][a-z0-9_]*)[,;]$")


def _altered_columns(pattern: re.Pattern[str]) -> list[str]:
    """Columns later migrations add or drop, in migration order: indented one-per-line
    `ADD COLUMN [IF NOT EXISTS] name real` or `DROP COLUMN [IF EXISTS] name` lines under
    `ALTER TABLE <the table's name then>`. The rename migration itself alters no column."""
    created = _migration_number(migration_path())
    renamed = rename_number()
    columns: list[str] = []
    for path in sorted(_MIGRATIONS.glob("*.sql")):
        number = path.name.split("_", 1)[0]
        if not number.isdigit() or int(number) <= created or int(number) == renamed:
            continue
        name = "feature_vectors_v2" if int(number) < renamed else "feature_vectors"
        text = path.read_text()
        if not re.search(rf"ALTER TABLE {name}\b", text):
            continue
        lines = [line.split("--", 1)[0].rstrip() for line in text.splitlines()]
        parsed = [line for line in lines if _ADD.match(line) or _DROP.match(line)]
        assert parsed, f"{path.name} alters {name} but no ADD or DROP COLUMN line parsed"
        columns.extend(match.group(1) for match in map(pattern.match, lines) if match)
    return columns


def added_columns() -> list[str]:
    return _altered_columns(_ADD)


def dropped_columns() -> list[str]:
    """Columns later migrations drop (577: the retired columns, from the empty table)."""
    return _altered_columns(_DROP)


def parsed_columns() -> list[str]:
    """The table's columns in physical order: 425's, then the later additions, minus drops."""
    dropped = set(dropped_columns())
    return [c for c in (*created_columns(), *added_columns()) if c not in dropped]


def test_migration_source_strings() -> None:
    text = "\n".join(_migration_lines())
    for needle in (
        "CREATE TABLE feature_vectors_v2",
        "PRIMARY KEY (symbol, tf, bar_ts)",
        "INTERVAL '1 year'",
        "compress_segmentby = 'symbol,tf'",
        "compress_orderby = 'bar_ts'",
    ):
        assert needle in text, needle
    assert "add_compression_policy" not in text
    assert "add_retention_policy" not in text


def test_migration_columns_equal_registry_derivation() -> None:
    columns = parsed_columns()
    assert len(columns) == len(set(columns)), "duplicate column in migration"
    assert set(columns) == expected_columns()  # migration 577 dropped the retired columns
    # The 186-24 evidence counts migration 425's table; later additions are counted on top.
    evidence = json.loads(_EVIDENCE.read_text())
    assert len(created_columns()) == evidence["expected_column_count"]
    assert len(columns) == (
        evidence["expected_column_count"] + len(added_columns()) - len(dropped_columns())
    )


def test_dropped_columns_absent_and_unowned_contract_intact() -> None:
    columns = set(parsed_columns())
    for name in {**DROPPED_COLUMNS, **METADATA_DROPPED}:
        assert name not in columns, name
    for name in NEVER_COMPUTED:
        assert name in UNOWNED_COLUMNS, name
    assert not set(RETIRED_COLUMNS) & columns  # migration 577 dropped them from the empty table
    assert set(RETIRED_COLUMNS) <= set(dropped_columns())
    assert not set(RETIRED_COLUMNS) & expected_columns()
