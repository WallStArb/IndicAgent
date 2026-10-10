#!/usr/bin/env python3
"""Compatibility shim at the retired module path (phase 190 plan 05; deleted by 190-06).

The fetcher renamed to ohlcv_history_fetcher.py in phase 190 (code identifiers only;
external identity strings frozen). The live root-owned systemd unit
(indicagent-ibkr-history-fetcher.service) still names THIS path in its ExecStart until
the 190-06 cutover installs the updated unit, so without this shim the timer's next
fire fails with 203/EXEC and the drain stops. This shim imports the renamed module and
execs its main exactly as the module's own __main__ block does: same argv, same exit
code, same otel init. 190-06 deletes this file after the new unit is installed and
verified through it.
"""

from __future__ import annotations

import sys
from pathlib import Path

project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from scripts.infrastructure.backfill.ohlcv_history_fetcher import JOB, main  # noqa: E402

if __name__ == "__main__":
    from src.observability.otel import OTelInitError, init_otel_providers

    try:
        init_otel_providers(JOB)
    except OTelInitError as error:
        print(f"[warn] OTel init failed, metrics disabled: {error}")
    sys.exit(main())
