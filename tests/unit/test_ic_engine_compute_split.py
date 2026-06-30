"""Unit test: ic_engine _compute_symbol_tf returns rows, not writes.

Verifies the compute/write split following regime_writer pattern:
- _compute_symbol_tf returns pooled_rows, regime_rows (no DB writes)
- Return contract is dict with keys: pooled_rows, regime_rows, all_results, n_skipped

This test validates the function signature and return structure without a live DB.
No actual compute is performed -- we're checking the contract only.

Related to Task 001: ic_engine compute/write split.
"""

from __future__ import annotations

import inspect
import sys
from pathlib import Path

_project_root = Path(__file__).parent.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from services.ic_engine import _compute_symbol_tf


def test_compute_symbol_tf_return_keys():
    """_compute_symbol_tf must return dict with specific keys (compute/write split)."""
    # Check function signature
    sig = inspect.signature(_compute_symbol_tf)
    params = list(sig.parameters.keys())
    expected_params = [
        "conn",
        "symbol",
        "tf",
        "training_window_end",
        "existing_keys",
        "config",
        "tracer",
        "run_ts",
        "feature_status_map",
        "mr_dict",
    ]
    assert params == expected_params, f"Expected params {expected_params}, got {params}"

    # Check docstring mentions no DB writes
    docstring = _compute_symbol_tf.__doc__
    assert docstring is not None, "_compute_symbol_tf must have docstring"
    assert (
        "No DB writes" in docstring or "pure compute" in docstring
    ), "Docstring must mention no DB writes / pure compute"
    assert "pooled_rows" in docstring, "Docstring must mention pooled_rows in return"
    assert "regime_rows" in docstring, "Docstring must mention regime_rows in return"


def test_compute_symbol_tf_has_no_db_write_code():
    """_compute_symbol_tf should not contain execute_batch calls.

    This is a simple grep check for the pattern. After the compute/write split,
    execute_batch should only be in _write_ic_results.
    """

    source = inspect.getsource(_compute_symbol_tf)

    # execute_batch should NOT be in _compute_symbol_tf
    assert "execute_batch" not in source, (
        "_compute_symbol_tf should not contain execute_batch "
        "(DB writes moved to _write_ic_results)"
    )

    # commit() should NOT be in _compute_symbol_tf
    assert "conn.commit()" not in source, (
        "_compute_symbol_tf should not call conn.commit() " "(DB writes moved to _write_ic_results)"
    )


def test_write_ic_results_exists():
    """_write_ic_results function must exist for serial writes."""
    import services.ic_engine as ic_module

    assert hasattr(ic_module, "_write_ic_results"), (
        "_write_ic_results function must exist " "(serial write function for main process)"
    )

    # Check signature -- focused write helper: conn + split row lists only.
    sig = inspect.signature(ic_module._write_ic_results)
    params = list(sig.parameters.keys())
    expected_params = [
        "conn",
        "pooled_rows",
        "regime_rows",
    ]
    assert params == expected_params, f"Expected params {expected_params}, got {params}"

    # Check docstring mentions serial write
    docstring = ic_module._write_ic_results.__doc__
    assert docstring is not None, "_write_ic_results must have docstring"
    assert "serial" in docstring.lower(), "Docstring must mention serial write"
    assert "main process" in docstring.lower(), "Docstring must mention main process"


def test_write_ic_results_has_db_write_code():
    """_write_ic_results should contain execute_batch for DB writes."""
    import services.ic_engine as ic_module

    source = inspect.getsource(ic_module._write_ic_results)

    # execute_batch SHOULD be in _write_ic_results
    assert "execute_batch" in source, "_write_ic_results must contain execute_batch for DB writes"

    # commit() SHOULD be in _write_ic_results
    assert "conn.commit()" in source, "_write_ic_results must call conn.commit() for DB writes"


def test_run_ic_worker_return_keys():
    """_run_ic_worker must return rows for corpus-level BH-FDR and serial write."""
    import services.ic_engine as ic_module

    sig = inspect.signature(ic_module._run_ic_worker)
    # Worker accepts single args tuple
    params = list(sig.parameters.keys())
    assert params == ["args"], f"Expected single 'args' param, got {params}"

    # Check docstring mentions returning rows and corpus-level BH-FDR fields
    docstring = ic_module._run_ic_worker.__doc__
    assert docstring is not None, "_run_ic_worker must have docstring"
    assert "pooled_rows" in docstring, "Docstring must mention pooled_rows in return"
    assert "regime_rows" in docstring, "Docstring must mention regime_rows in return"
    assert "pvals_flat" in docstring, "Docstring must mention pvals_flat for corpus BH-FDR"
