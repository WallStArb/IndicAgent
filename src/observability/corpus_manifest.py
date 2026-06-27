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


class CorpusManifest:
    """Manifest emitter for corpus pipeline steps."""

    def __init__(self, step_name: str, manifest_dir: Path):
        self.step_name = step_name
        self.manifest_dir = Path(manifest_dir)
        self.manifest_dir.mkdir(parents=True, exist_ok=True)

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

        manifest_path = self.manifest_dir / f"{self.step_name}.json"
        with open(manifest_path, "w") as f:
            json.dump(self.data, f, indent=2, default=str)

        return manifest_path

    @staticmethod
    def read(manifest_dir: Path, step_name: str) -> dict[str, Any]:
        """Read a manifest file."""
        manifest_path = Path(manifest_dir) / f"{step_name}.json"
        if not manifest_path.exists():
            raise FileNotFoundError(f"Manifest not found: {manifest_path}")

        with open(manifest_path) as f:
            return json.load(f)

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
