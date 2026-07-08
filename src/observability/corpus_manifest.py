"""
Corpus pipeline manifest system.

Each pipeline step emits a manifest describing what it wrote.
Downstream steps read prior manifests and crash if prerequisites aren't met.

Manifest schema:
{
    "step_name": "ic_engine_cross_sectional",
    "step_version": "1.0",
    "timestamp": "2026-06-27T12:00:00Z",
    "status": "success",  # success | partial | failed
    "inputs": {
        "training_window_end": "2026-06-24T05:15:00Z",
        "tfs": ["5m", "15m", "1h", "1d"],
        "symbols": ["SPY", "TLT", ...]
    },
    "outputs": {
        "feature_ic_scores": {
            "table": "feature_ic_scores",
            "rows_total": 50000,
            "rows_by_tf": {
                "5m": 13456,
                "15m": 13456,
                "1h": 10034,
                "1d": 12405
            },
            "rows_by_regime": {
                "high_bull": 5000,
                ...
            },
            "columns_written": ["feature_name", "symbol", "tf", "regime", ...]
        }
    },
    "errors": [],
    "warnings": []
}
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def _manifest_filename(step_name: str, scope_suffix: str | None) -> str:
    """Single source of truth for the manifest filename convention, shared by the
    write side (CorpusManifest.write) and read side (CorpusManifest.read,
    ensure_success_for) so they can never drift apart."""
    if scope_suffix is None:
        return f"{step_name}.json"
    return f"{step_name}__{scope_suffix}.json"


class CorpusManifest:
    """Manifest emitter for corpus pipeline steps."""

    # Single source of truth for the manifest directory -- every corpus pipeline step
    # (ic_engine, ensemble_trainer, ensemble_ic_engine, alpha_publisher, ...) reads
    # and writes manifests from the same directory; hardcoding the literal
    # separately at each call site let them drift.
    DEFAULT_MANIFEST_DIR: Path = Path(".planning/corpus_manifests")

    def __init__(self, step_name: str, manifest_dir: Path):
        self.step_name = step_name
        self.manifest_dir = Path(manifest_dir)
        self.manifest_dir.mkdir(parents=True, exist_ok=True)
        # Set (e.g. `manifest.scope_suffix = weight_version`) for steps that can
        # legitimately run for multiple concurrent inputs under the same step_name --
        # ensemble_trainer.py runs once per weight_version (champion + challenger
        # variants coexist by design, migration 196 Section 3). Without this, two
        # weight_version runs share one manifest file and stomp each other: a crashed
        # run for a challenger variant would overwrite the manifest a completely
        # unrelated, still-healthy champion weight_version's readers rely on,
        # producing a false "run failed" rejection for data that was never touched.
        # None preserves the original single-file-per-step behavior for steps with no
        # such scoping axis (ic_engine, regime_writer, feature_factory, etc).
        self.scope_suffix: str | None = None

        self.data: dict[str, Any] = {
            "step_name": step_name,
            "step_version": "1.0",
            "timestamp": datetime.now(UTC).isoformat(),
            "status": "in_progress",
            "inputs": {},
            "outputs": {},
            "errors": [],
            "warnings": [],
        }

    def set_inputs(self, **kwargs: Any) -> None:
        """Record step inputs (training_window_end, tfs, symbols, etc)."""
        self.data["inputs"].update(kwargs)

    def add_output(
        self,
        table_name: str,
        rows_total: int,
        rows_by_tf: dict[str, int] | None = None,
        rows_by_regime: dict[str, int] | None = None,
        columns_written: list[str] | None = None,
    ) -> None:
        """Record an output table's statistics."""
        if "outputs" not in self.data:
            self.data["outputs"] = {}

        self.data["outputs"][table_name] = {
            "table": table_name,
            "rows_total": rows_total,
        }

        if rows_by_tf:
            self.data["outputs"][table_name]["rows_by_tf"] = rows_by_tf
        if rows_by_regime:
            self.data["outputs"][table_name]["rows_by_regime"] = rows_by_regime
        if columns_written:
            self.data["outputs"][table_name]["columns_written"] = columns_written

    def add_error(self, error: str) -> None:
        """Record an error."""
        self.data["errors"].append(error)
        self.data["status"] = "failed"

    def add_warning(self, warning: str) -> None:
        """Record a warning."""
        self.data["warnings"].append(warning)
        if self.data["status"] == "in_progress":
            self.data["status"] = "partial"

    def mark_success(self) -> None:
        """Mark step as successful."""
        if self.data["status"] == "in_progress":
            self.data["status"] = "success"

    def write(self) -> Path:
        """Write manifest to file."""
        if not self.data["outputs"]:
            self.add_warning("No outputs recorded")

        manifest_path = self.manifest_dir / _manifest_filename(self.step_name, self.scope_suffix)
        with open(manifest_path, "w") as f:
            json.dump(self.data, f, indent=2, default=str)

        return manifest_path

    @staticmethod
    def read(manifest_dir: Path, step_name: str, scope_suffix: str | None = None) -> dict[str, Any]:
        """Read a manifest file.

        scope_suffix must match whatever the writer set on `manifest.scope_suffix`
        (see CorpusManifest.__init__) -- steps with no scoping axis pass None (the
        default) and read the single per-step file as before.
        """
        manifest_path = Path(manifest_dir) / _manifest_filename(step_name, scope_suffix)
        if not manifest_path.exists():
            raise FileNotFoundError(f"Manifest not found: {manifest_path}")

        with open(manifest_path) as f:
            return json.load(f)

    @staticmethod
    def ensure_success_for(
        manifest_dir: Path,
        step_name: str,
        scope_suffix: str | None = None,
        **expected_inputs: Any,
    ) -> dict[str, Any]:
        """Assert a prerequisite step's manifest shows a clean success FOR THESE EXACT
        inputs, and return it. Raises RuntimeError (crash loud) otherwise.

        Row/table data existing downstream of `step_name` is not sufficient evidence
        that the run which wrote it finished -- a step whose write pattern is a
        delete-then-repopulate (not wrapped in one transaction spanning the whole
        run) can be interrupted mid-run, leaving nonzero-but-incomplete rows behind
        with no exception ever raised on the READ side. Unlike verify_prerequisites()
        (which treats any non-"failed" status, including "partial", as acceptable, and
        has no concept of matching specific input values), this requires status ==
        "success" exactly and that every kwarg in expected_inputs matches the
        manifest's recorded `inputs` -- so a manifest left over from a different run
        (e.g. a different weight_version) is never mistaken for evidence about the
        run a caller actually cares about.

        Pass scope_suffix for prerequisite steps that can run for multiple
        legitimately-coexisting inputs under one step_name (e.g. ensemble_trainer.py
        runs once per weight_version, champion + challenger variants coexist by
        design). Without it, two such runs would share one manifest file: a crashed
        run for one weight_version would overwrite the manifest a completely
        unrelated, still-healthy weight_version's readers rely on, either falsely
        rejecting healthy data (status mismatch) or -- worse -- being masked by the
        input-matching check below into a "wrong weight_version" error that looks
        like a caller bug rather than the real cross-run clobbering it is.

        KNOWN GAP: a hard process kill (OOM-killer, SIGKILL) never reaches the
        except-handler that marks a manifest "failed", so the manifest on disk can
        still show a PRIOR run's success after an unclean interruption. This closes
        the loud-crash gap, not the hard-kill gap.
        """
        try:
            manifest = CorpusManifest.read(manifest_dir, step_name, scope_suffix=scope_suffix)
        except FileNotFoundError as error:
            raise RuntimeError(
                f"No manifest found for prerequisite step {step_name!r}. Row/table data "
                f"existing is not sufficient evidence the run that wrote it finished -- "
                f"run {step_name}.py first."
            ) from error

        manifest_inputs = manifest.get("inputs", {})
        mismatched = {
            key: (manifest_inputs.get(key), expected)
            for key, expected in expected_inputs.items()
            if manifest_inputs.get(key) != expected
        }
        if mismatched:
            detail = ", ".join(
                f"{key}: manifest has {got!r}, expected {want!r}"
                for key, (got, want) in mismatched.items()
            )
            raise RuntimeError(
                f"Prerequisite step {step_name!r}'s last manifest does not match this "
                f"run's inputs ({detail}). Data existing under a matching-looking key may "
                f"be a stale leftover from a different run -- re-run {step_name}.py."
            )

        if manifest.get("status") != "success":
            raise RuntimeError(
                f"Prerequisite step {step_name!r}'s manifest shows status="
                f"{manifest.get('status')!r}, not 'success' -- its run did not finish "
                f"cleanly. Re-run {step_name}.py before trusting its output."
            )

        return manifest

    @staticmethod
    def verify_prerequisites(
        manifest_dir: Path,
        required_steps: list[str],
        required_tfs: list[str],
        required_symbols: list[str] | None = None,
    ) -> None:
        """
        Verify that all prerequisite steps wrote expected data.

        Raises RuntimeError if any prerequisite is missing or incomplete.
        """
        for step_name in required_steps:
            try:
                manifest = CorpusManifest.read(manifest_dir, step_name)
            except FileNotFoundError as err:
                raise RuntimeError(
                    f"Prerequisite step '{step_name}' did not emit a manifest. "
                    f"Cannot proceed without verification."
                ) from err

            # Check status
            if manifest.get("status") == "failed":
                raise RuntimeError(
                    f"Prerequisite step '{step_name}' failed. Errors: {manifest.get('errors', [])}"
                )

            # Check TF coverage
            outputs = manifest.get("outputs", {})
            for table_name, table_stats in outputs.items():
                rows_by_tf = table_stats.get("rows_by_tf", {})
                missing_tfs = set(required_tfs) - set(rows_by_tf.keys())
                if missing_tfs:
                    raise RuntimeError(
                        f"Table '{table_name}' from step '{step_name}' is missing TFs: {missing_tfs}. "
                        f"Has rows for TFs: {list(rows_by_tf.keys())}"
                    )

                # Check row counts (should be > 0 for each TF)
                zero_tfs = [tf for tf, count in rows_by_tf.items() if count == 0]
                if zero_tfs:
                    raise RuntimeError(
                        f"Table '{table_name}' from step '{step_name}' has zero rows for TFs: {zero_tfs}"
                    )

            # Check symbol coverage if specified
            if required_symbols is not None:
                for table_name, table_stats in outputs.items():
                    # Can't easily verify symbols without querying, so we check total row count
                    # as a proxy (expecting at least N × M rows where N=symbols, M=regimes)
                    expected_min_rows = len(required_symbols) * 9  # 9 regimes
                    actual_rows = table_stats.get("rows_total", 0)
                    if actual_rows < expected_min_rows:
                        raise RuntimeError(
                            f"Table '{table_name}' from step '{step_name}' has only {actual_rows} rows, "
                            f"expected at least {expected_min_rows} rows for {len(required_symbols)} symbols × 9 regimes"
                        )
