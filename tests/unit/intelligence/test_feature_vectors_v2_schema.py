"""Source-level guard: feature_vectors_v2's columns equal the kernel registry's column set (186-24).

The table's columns are migration 425's CREATE TABLE plus every later migration's
`ALTER TABLE feature_vectors_v2 ... ADD COLUMN` (migration 526, todo 553). The expectation is
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

# Dropped feature columns and why (mirrors the evidence JSON). The Asian session pair is NOT
# here: the vp_sr kernel computes it, so it stays in the table.
DROPPED_COLUMNS: dict[str, str] = {
    "momentum_rank_z": "todo 421: never computed, cross-sectional rank is not a kernel",
    "volume_rank_z": "todo 421",
    "volatility_rank_z": "todo 421",
    "regime_rolling": "text column never computed, not a FeatureVector field",
    "days_to_month_end": "todo 115: exact duplicate of 1 - month_position",
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
    """Registry-derived column set of feature_vectors_v2."""
    feature = set(default_registry().feature_columns()) | set(UNOWNED_COLUMNS)
    return (feature - set(DROPPED_COLUMNS)) | set(KEYS) | set(REGIME_TEXT)


def migration_path() -> Path:
    paths = sorted(_MIGRATIONS.glob("*_feature_vectors_v2.sql"))
    assert len(paths) == 1, paths
    return paths[0]


def _migration_lines() -> list[str]:
    return [line.split("--", 1)[0].rstrip() for line in migration_path().read_text().splitlines()]


def created_columns() -> list[str]:
    """Migration 425's CREATE TABLE columns, in DDL order."""
    pattern = re.compile(r"^    ([a-z_][a-z0-9_]*) (real|text|timestamptz|varchar|uuid)")
    columns = [m.group(1) for line in _migration_lines() if (m := pattern.match(line))]
    assert columns, "no columns parsed: keep 4-space-indented `name type` lines, one per line"
    return columns


def added_columns() -> list[str]:
    """Columns later migrations add, in migration order: indented
    `ADD COLUMN [IF NOT EXISTS] name real` lines under `ALTER TABLE feature_vectors_v2`, one per line.
    """
    created = int(migration_path().name.split("_", 1)[0])
    pattern = re.compile(r"^\s+ADD COLUMN (?:IF NOT EXISTS )?([a-z_][a-z0-9_]*) real[,;]$")
    columns: list[str] = []
    for path in sorted(_MIGRATIONS.glob("*.sql")):
        number = path.name.split("_", 1)[0]
        if not number.isdigit() or int(number) <= created:
            continue
        text = path.read_text()
        if "ALTER TABLE feature_vectors_v2" not in text:
            continue
        lines = [line.split("--", 1)[0].rstrip() for line in text.splitlines()]
        found = [m.group(1) for line in lines if (m := pattern.match(line))]
        assert found, f"{path.name} alters feature_vectors_v2 but no ADD COLUMN line parsed"
        columns.extend(found)
    return columns


def parsed_columns() -> list[str]:
    """The table's columns in physical order: 425's, then the later additions."""
    return [*created_columns(), *added_columns()]


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
    assert set(columns) == expected_columns()
    # The 186-24 evidence counts migration 425's table; later additions are counted on top.
    evidence = json.loads(_EVIDENCE.read_text())
    assert len(created_columns()) == evidence["expected_column_count"]
    assert len(columns) == evidence["expected_column_count"] + len(added_columns())


def test_dropped_columns_absent_and_unowned_contract_intact() -> None:
    columns = set(parsed_columns())
    for name in {**DROPPED_COLUMNS, **METADATA_DROPPED}:
        assert name not in columns, name
    for name in NEVER_COMPUTED:
        assert name in UNOWNED_COLUMNS, name
    assert {"asian_session_high_dist_atr", "asian_session_low_dist_atr"} <= columns
