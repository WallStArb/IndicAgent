"""Unit tests for per-run weight epoch + DO UPDATE upsert + APR-backed stale cliff.

Covers Task 2 of Phase 141.1 Plan 04: EnsembleConfig.weight_stale_max_days binding,
_effective_weight_version CLI-override helper, and the DO UPDATE (not DO NOTHING)
upsert SQL at both ensemble_weights and ensemble_alpha write sites.

No live DB — pure unit tests against config-binding logic and module source text.
"""

from __future__ import annotations

import inspect
import sys
from pathlib import Path

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

import services.ensemble_trainer as ensemble_trainer_module
from services.ensemble_trainer import EnsembleConfig, _effective_weight_version


class TestWeightStaleMaxDaysBinding:
    """EnsembleConfig.from_apr must bind weight_stale_max_days from APR."""

    def test_binds_from_apr_key(self) -> None:
        cfg = {"alpha.ensemble.weight_stale_max_days": "45"}
        config = EnsembleConfig.from_apr(cfg)
        assert config.weight_stale_max_days == 45
        assert isinstance(config.weight_stale_max_days, int)

    def test_defaults_to_90_when_missing(self) -> None:
        cfg: dict = {}
        config = EnsembleConfig.from_apr(cfg)
        assert config.weight_stale_max_days == 90


class TestEffectiveWeightVersion:
    """_effective_weight_version(cli_arg, apr_default) resolves the per-run epoch."""

    def test_returns_cli_value_when_provided(self) -> None:
        assert _effective_weight_version("run_20260624", "v1") == "run_20260624"

    def test_returns_apr_default_when_cli_none(self) -> None:
        assert _effective_weight_version(None, "v1") == "v1"

    def test_returns_apr_default_when_cli_empty_string(self) -> None:
        assert _effective_weight_version("", "v1") == "v1"


class TestUpsertSQL:
    """ensemble_weights and ensemble_alpha INSERTs must use DO UPDATE, never DO NOTHING."""

    def _source(self) -> str:
        return inspect.getsource(ensemble_trainer_module)

    def test_no_do_nothing_remains(self) -> None:
        source = self._source()
        assert "DO NOTHING" not in source

    def test_ensemble_weights_insert_uses_do_update(self) -> None:
        source = self._source()
        assert "ON CONFLICT (symbol, tf, regime, weight_version, feature_name)" in source
        assert "DO UPDATE SET" in source

    def test_ensemble_alpha_insert_uses_do_update(self) -> None:
        source = self._source()
        assert "ON CONFLICT (symbol, tf, bar_ts, weight_version)" in source
        assert "DO UPDATE SET" in source


class TestStaleCliffUsesAPR:
    """The aging branch must reference config.weight_stale_max_days, not a literal 90."""

    def test_no_bare_literal_90_comparison(self) -> None:
        source = inspect.getsource(ensemble_trainer_module)
        assert "> 90" not in source

    def test_aging_logic_references_weight_stale_max_days(self) -> None:
        source = inspect.getsource(ensemble_trainer_module)
        assert "config.weight_stale_max_days" in source


class TestWeightVersionFullReplace:
    """A re-run under the same weight_version must fully replace that version's row-set,
    not incrementally upsert on top of it.

    Root cause this guards: _process_stratum silently early-returns (no write, no log
    above DEBUG) when a stratum's meta-eligible feature count drops below
    min_passing_features -- e.g. after the per-timeframe meta-FDR fix correctly tightens
    eligibility for a timeframe. Without a delete-scoped-to-weight_version at run start,
    a stratum that qualified under an older run's logic keeps its stale rows forever
    under a weight_version that's supposed to be a fully self-consistent snapshot of
    "this run's logic + this run's data." Found 2026-07-08: a re-run after the
    per-timeframe meta-FDR fix left 5 stale 1h/high_bear ensemble_weights rows
    (computed_at from the PRE-fix run) sitting under the same weight_version as the
    fixed run's genuinely-qualifying strata.
    """

    def _source(self) -> str:
        return inspect.getsource(ensemble_trainer_module)

    def test_deletes_ensemble_weights_scoped_to_weight_version(self) -> None:
        source = self._source()
        assert "DELETE FROM ensemble_weights" in source

    def test_deletes_ensemble_alpha_scoped_to_weight_version(self) -> None:
        source = self._source()
        assert "DELETE FROM ensemble_alpha" in source

    def test_deletes_do_not_use_returning(self) -> None:
        """RETURNING on a bulk DELETE forces Postgres to materialize the full deleted-row
        result set before a count can be taken. Against ensemble_alpha (30M+ rows for an
        active weight_version) this OOM-killed the Postgres backend and crashed the
        entire TimescaleDB instance (2026-07-08, required WAL recovery on restart) --
        confirmed via docker logs: 'client backend ... terminated by signal 9: Killed',
        'DETAIL: Failed process was running: WITH d AS (DELETE ... RETURNING 1) ...'.
        conn.execute()'s command-tag ("DELETE <n>") gives the row count without ever
        materializing result rows -- the same pattern already used correctly in
        alpha_publisher.py's delete.
        """
        source = self._source()
        # Exact-match the full DELETE statement strings (including the closing quote) --
        # this can only be present if the statement ends at weight_version = $1 with no
        # RETURNING clause appended. A blanket "RETURNING" not in source would false-positive
        # on this test's own docstring/comments explaining why RETURNING must be avoided here.
        assert 'DELETE FROM ensemble_weights WHERE weight_version = $1",\n' in source
        assert 'DELETE FROM ensemble_alpha WHERE weight_version = $1",\n' in source


class TestWeightVersionCLIOverride:
    """EnsembleTrainer accepts a CLI weight-version override threaded into config."""

    def test_init_accepts_weight_version_override(self) -> None:
        from services.ensemble_trainer import EnsembleTrainer

        trainer = EnsembleTrainer(
            db_dsn="postgresql://localhost/test", weight_version_override="run_20260624"
        )
        assert trainer._weight_version_override == "run_20260624"

    def test_init_defaults_weight_version_override_to_none(self) -> None:
        from services.ensemble_trainer import EnsembleTrainer

        trainer = EnsembleTrainer(db_dsn="postgresql://localhost/test")
        assert trainer._weight_version_override is None
