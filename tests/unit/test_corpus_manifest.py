"""Unit tests: CorpusManifest.ensure_success_for().

2026-07-08: a downstream table having nonzero rows for some key (e.g. a
weight_version) is not sufficient evidence the run that wrote them finished --
a step whose write pattern is delete-then-repopulate (not one transaction
spanning the whole run) can be interrupted mid-run, leaving nonzero-but-
incomplete rows with no exception ever raised on the read side.
ensure_success_for() is the shared primitive every prerequisite-gate call site
should use instead of hand-rolling its own manifest read + status check.

No DB, no Kafka. Pure filesystem (tmp_path) + JSON.
"""

from __future__ import annotations

import pytest

from src.observability.corpus_manifest import CorpusManifest


class TestAssertSuccessFor:
    def test_raises_when_no_manifest_exists(self, tmp_path):
        with pytest.raises(RuntimeError, match="No manifest found for prerequisite step"):
            CorpusManifest.ensure_success_for(tmp_path, "ensemble_trainer")

    def test_raises_when_expected_input_does_not_match(self, tmp_path):
        manifest = CorpusManifest("ensemble_trainer", tmp_path)
        manifest.set_inputs(weight_version="v1")
        manifest.mark_success()
        manifest.write()

        with pytest.raises(RuntimeError, match="does not match this run's inputs"):
            CorpusManifest.ensure_success_for(
                tmp_path, "ensemble_trainer", weight_version="v1_shrunk"
            )

    def test_raises_when_status_is_not_success(self, tmp_path):
        manifest = CorpusManifest("ensemble_trainer", tmp_path)
        manifest.set_inputs(weight_version="v1")
        manifest.add_error("crashed mid-run")
        manifest.write()

        with pytest.raises(RuntimeError, match="status='failed'"):
            CorpusManifest.ensure_success_for(tmp_path, "ensemble_trainer", weight_version="v1")

    def test_raises_when_status_is_partial_not_success(self, tmp_path):
        """Unlike verify_prerequisites (which accepts any non-'failed' status),
        ensure_success_for requires 'success' exactly -- a 'partial' status (e.g. a
        step that ran but recorded a warning) must not silently pass."""
        manifest = CorpusManifest("ensemble_trainer", tmp_path)
        manifest.set_inputs(weight_version="v1")
        manifest.add_warning("something looked off")
        manifest.write()

        with pytest.raises(RuntimeError, match="status='partial'"):
            CorpusManifest.ensure_success_for(tmp_path, "ensemble_trainer", weight_version="v1")

    def test_returns_manifest_when_inputs_match_and_status_success(self, tmp_path):
        manifest = CorpusManifest("ensemble_trainer", tmp_path)
        manifest.set_inputs(weight_version="v1", tfs=["5m", "15m"])
        manifest.mark_success()
        manifest.write()

        result = CorpusManifest.ensure_success_for(
            tmp_path, "ensemble_trainer", weight_version="v1"
        )

        assert result["status"] == "success"
        assert result["inputs"]["weight_version"] == "v1"

    def test_passes_with_no_expected_inputs_given(self, tmp_path):
        """Callers that only care about status, not specific input values, can omit
        expected_inputs entirely -- no mismatch is possible against an empty set."""
        manifest = CorpusManifest("ensemble_trainer", tmp_path)
        manifest.mark_success()
        manifest.write()

        result = CorpusManifest.ensure_success_for(tmp_path, "ensemble_trainer")

        assert result["status"] == "success"

    def test_checks_multiple_expected_inputs(self, tmp_path):
        manifest = CorpusManifest("ensemble_trainer", tmp_path)
        manifest.set_inputs(weight_version="v1", run_ts="2026-07-08T00:00:00Z")
        manifest.mark_success()
        manifest.write()

        with pytest.raises(RuntimeError, match="run_ts"):
            CorpusManifest.ensure_success_for(
                tmp_path,
                "ensemble_trainer",
                weight_version="v1",
                run_ts="2026-07-09T00:00:00Z",
            )


class TestScopeSuffix:
    """Regression guard (high-effort code review, 2026-07-08): without scope_suffix,
    two runs of the same step_name for different inputs (e.g. ensemble_trainer.py
    running once per weight_version -- champion + challenger variants coexist by
    design) share ONE manifest file and stomp each other. A crashed run for one
    weight_version would overwrite the record a completely unrelated, still-healthy
    weight_version's readers depend on."""

    def test_write_and_read_round_trip_with_matching_scope_suffix(self, tmp_path):
        manifest = CorpusManifest("ensemble_trainer", tmp_path)
        manifest.set_inputs(weight_version="v1_shrunk")
        manifest.scope_suffix = "v1_shrunk"
        manifest.mark_success()
        manifest.write()

        result = CorpusManifest.read(tmp_path, "ensemble_trainer", scope_suffix="v1_shrunk")

        assert result["status"] == "success"

    def test_scoped_and_unscoped_writes_land_in_different_files(self, tmp_path):
        """A step with no scoping axis (scope_suffix=None, the default) must never
        collide with a scoped write for the same step_name."""
        unscoped = CorpusManifest("ensemble_trainer", tmp_path)
        unscoped.mark_success()
        unscoped.write()

        scoped = CorpusManifest("ensemble_trainer", tmp_path)
        scoped.scope_suffix = "v1_shrunk"
        scoped.add_error("crashed")
        scoped.write()

        # The unscoped file is untouched by the scoped write's failure.
        assert CorpusManifest.read(tmp_path, "ensemble_trainer")["status"] == "success"
        assert (
            CorpusManifest.read(tmp_path, "ensemble_trainer", scope_suffix="v1_shrunk")["status"]
            == "failed"
        )

    def test_two_different_scope_suffixes_do_not_clobber_each_other(self, tmp_path):
        v1 = CorpusManifest("ensemble_trainer", tmp_path)
        v1.set_inputs(weight_version="v1")
        v1.scope_suffix = "v1"
        v1.mark_success()
        v1.write()

        v1_shrunk = CorpusManifest("ensemble_trainer", tmp_path)
        v1_shrunk.set_inputs(weight_version="v1_shrunk")
        v1_shrunk.scope_suffix = "v1_shrunk"
        v1_shrunk.add_error("crashed mid-run")
        v1_shrunk.write()

        # v1's healthy manifest passes, completely unaffected by v1_shrunk's crash.
        result = CorpusManifest.ensure_success_for(
            tmp_path, "ensemble_trainer", scope_suffix="v1", weight_version="v1"
        )
        assert result["status"] == "success"

        with pytest.raises(RuntimeError, match="status='failed'"):
            CorpusManifest.ensure_success_for(
                tmp_path, "ensemble_trainer", scope_suffix="v1_shrunk", weight_version="v1_shrunk"
            )

    def test_raises_not_found_when_scope_suffix_requested_but_only_unscoped_exists(self, tmp_path):
        unscoped = CorpusManifest("ensemble_trainer", tmp_path)
        unscoped.mark_success()
        unscoped.write()

        with pytest.raises(RuntimeError, match="No manifest found for prerequisite step"):
            CorpusManifest.ensure_success_for(
                tmp_path, "ensemble_trainer", scope_suffix="v1_shrunk"
            )
