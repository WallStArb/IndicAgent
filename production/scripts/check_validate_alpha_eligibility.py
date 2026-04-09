#!/usr/bin/env python3
"""Check whether DerivOsc and ACOsc bootstrap-promoted plugins have enough
resolved signal_ledger outcomes to run validate_alpha.py.

Usage:
    .venv/bin/python production/scripts/check_validate_alpha_eligibility.py
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

import asyncpg

from src.config.settings import Settings

BOOTSTRAP_PLUGINS = ["trad_DerivativeOscillator", "trad_ACOscillator"]
MIN_N = 30


async def _amain() -> None:
    settings = Settings()
    conn = await asyncpg.connect(settings.database_url)

    rows = await conn.fetch(
        """
        SELECT setup_plugin, count(*) AS resolved_n
        FROM signal_ledger
        WHERE setup_plugin = ANY($1)
          AND outcome IS NOT NULL
          AND outcome != 'never_activated'
        GROUP BY setup_plugin
        ORDER BY setup_plugin
        """,
        BOOTSTRAP_PLUGINS,
    )
    await conn.close()

    counts = {r["setup_plugin"]: r["resolved_n"] for r in rows}

    print(f"\nValidate-alpha eligibility gate (requires N >= {MIN_N} resolved outcomes)\n")
    for plugin in BOOTSTRAP_PLUGINS:
        n = counts.get(plugin, 0)
        status = (
            "ELIGIBLE — run validate_alpha.py now"
            if n >= MIN_N
            else f"NOT YET — {MIN_N - n} more needed"
        )
        print(f"  {plugin}: {n} resolved outcomes -> {status}")

    print()
    for plugin in BOOTSTRAP_PLUGINS:
        if counts.get(plugin, 0) >= MIN_N:
            print(f"Run: .venv/bin/python production/scripts/validate_alpha.py --plugin {plugin}")
            print("     If gate fails (r<=0 or p>=0.05): add IS_SHADOW=True in the plugin file.\n")


if __name__ == "__main__":
    asyncio.run(_amain())
