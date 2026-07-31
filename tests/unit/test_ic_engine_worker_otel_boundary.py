"""Boundary test: no OTel metric instrument may be called from inside a
ProcessPoolExecutor worker function in ic_engine.py (todo 009/2026-07-31 fix).

Same allow-list-boundary-test pattern as test_market_data_ohlcv_boundary.py --
this project's established way of turning a fixed bug into an enforced invariant
instead of trusting future contributors to remember why.

Concrete incident this guards against: _run_ic_worker's own docstring says "No
OTel tracer -- workers log only", but 3 metric instruments
(IC_ENGINE_CELLS_COMPLETED_TOTAL, IC_ENGINE_CELLS_SKIPPED_TOTAL,
FEATURE_IC_PASSING_WALKFORWARD_TOTAL) were being called with .add()/.set()
directly from _compute_symbol_tf and _compute_one_regime_cell -- both reachable
ONLY from inside a ProcessPoolExecutor worker. No OTel exporter is initialized in
that process, so every one of those calls silently no-op'd forever: the metric
objects existed, the calls executed without error, and zero data ever reached
Prometheus. A live corpus rebuild ran for over a day before this was caught by
manual Prometheus inspection, not by any automated check -- exactly the "silent
wrong answer" this project's principles call the worst class of bug.

The fix moved every metric-worthy count (cell_emissions, n_passing_wf_by_tf,
skip_reasons_by_tf) into the worker's plain-data return dict; only main() (the
process IC_ENGINE_SYMBOLS_COMPLETED_TOTAL was already correctly emitted from)
calls any OTel instrument now.
"""

from __future__ import annotations

import inspect
import re
import sys
from pathlib import Path

_project_root = Path(__file__).parent.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from services.ic_engine import (
    _compute_one_regime_cell,
    _compute_symbol_tf,
    _run_ic_worker,
)

# Any identifier ending in _TOTAL or _GAUGE (this project's OTel instrument naming
# convention, src/observability/metrics.py) followed by .add( or .set( is a metric
# emission call.
_OTEL_EMISSION_PATTERN = re.compile(r"\b\w*(?:_TOTAL|_GAUGE)\.(?:add|set)\(")

# Functions reachable ONLY from inside a ProcessPoolExecutor worker
# (_run_ic_worker itself, and everything it calls transitively) -- extend this
# list if another worker-only function is added to ic_engine.py.
_WORKER_ONLY_FUNCTIONS = [
    _run_ic_worker,
    _compute_symbol_tf,
    _compute_one_regime_cell,
]


def test_no_otel_metric_emission_inside_worker_only_functions() -> None:
    violations: list[str] = []
    for func in _WORKER_ONLY_FUNCTIONS:
        source = inspect.getsource(func)
        for match in _OTEL_EMISSION_PATTERN.finditer(source):
            violations.append(f"{func.__name__}: {match.group(0)}")

    assert not violations, (
        "OTel metric instrument called from inside a ProcessPoolExecutor "
        "worker-only function -- these processes have no metrics exporter "
        "initialized, so the call would silently no-op forever (the exact bug "
        "fixed 2026-07-31). Return the count as plain data instead and emit it "
        "from main() after the worker's result is aggregated, matching "
        f"IC_ENGINE_SYMBOLS_COMPLETED_TOTAL's existing pattern. Violations: {violations}"
    )
