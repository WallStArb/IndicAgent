#!/usr/bin/env python3
"""Shadow signal promotion gate — statistical validation before production promotion.

SHAD-02: Two-sample proportion z-test. Requires:
  - p < 0.05 (shadow variant statistically better than production)
  - N >= 200 per variant (minimum sample for reliable inference)

Usage:
    .venv/bin/python production/scripts/promote_shadow.py [--db-url DATABASE_URL]

Exit codes:
    0 = PROMOTED (shadow variant is statistically better)
    1 = REJECTED (insufficient data or not statistically significant)
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from typing import Any

WIN_OUTCOMES = frozenset({"target_1", "target_1_2", "target_full"})
MIN_SAMPLES = 200


def run_promotion_test(
    prod_signals: list[dict[str, Any]],
    shadow_signals: list[dict[str, Any]],
) -> int:
    """Run two-sample proportion z-test on production vs shadow signals.

    Returns exit code: 0 = PROMOTED, 1 = REJECTED.
    Prints human-readable result to stdout.
    """
    from statsmodels.stats.proportion import proportions_ztest

    n_prod = len(prod_signals)
    n_shadow = len(shadow_signals)

    if n_prod < MIN_SAMPLES or n_shadow < MIN_SAMPLES:
        print(
            f"REJECTED: insufficient samples "
            f"(prod={n_prod}, shadow={n_shadow}, required={MIN_SAMPLES})"
        )
        return 1

    prod_wins = sum(1 for r in prod_signals if r.get("outcome") in WIN_OUTCOMES)
    shadow_wins = sum(1 for r in shadow_signals if r.get("outcome") in WIN_OUTCOMES)

    prod_wr = prod_wins / n_prod
    shadow_wr = shadow_wins / n_shadow

    # One-sided test: is shadow win rate GREATER than production?
    stat, p_value = proportions_ztest(
        [shadow_wins, prod_wins],
        [n_shadow, n_prod],
        alternative="larger",
    )

    if p_value >= 0.05:
        print(
            f"REJECTED: p={p_value:.4f} >= 0.05 "
            f"(shadow_wr={shadow_wr:.3f}, prod_wr={prod_wr:.3f}, "
            f"shadow_n={n_shadow}, prod_n={n_prod})"
        )
        return 1

    print(
        f"PROMOTED: p={p_value:.4f} < 0.05 "
        f"(shadow_wr={shadow_wr:.3f}, prod_wr={prod_wr:.3f}, "
        f"shadow_n={n_shadow}, prod_n={n_prod})"
    )
    return 0


async def main() -> None:
    parser = argparse.ArgumentParser(description="Shadow signal promotion gate")
    parser.add_argument(
        "--db-url",
        default=None,
        help="Database URL (defaults to INDICAGENT_DATABASE_URL or DATABASE_URL env var)",
    )
    args = parser.parse_args()

    db_url = args.db_url
    if db_url is None:
        import os
        db_url = os.environ.get("INDICAGENT_DATABASE_URL") or os.environ.get("DATABASE_URL")
    if db_url is None:
        print("ERROR: No database URL. Set DATABASE_URL or pass --db-url.")
        sys.exit(2)

    import asyncpg

    conn = await asyncpg.connect(db_url)
    try:
        rows = await conn.fetch("""
            SELECT outcome, is_shadow
            FROM signal_ledger
            WHERE outcome IS NOT NULL
            ORDER BY timestamp DESC
            LIMIT 50000
        """)
        prod = [dict(r) for r in rows if not r["is_shadow"]]
        shadow = [dict(r) for r in rows if r["is_shadow"]]
        exit_code = run_promotion_test(prod, shadow)
    finally:
        await conn.close()

    sys.exit(exit_code)


if __name__ == "__main__":
    asyncio.run(main())
