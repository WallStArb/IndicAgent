#!/usr/bin/env python3
import asyncio
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pandas as pd

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.config.settings import Settings
from src.core.database_manager import DatabaseManager


class AlphaPromotionWorker:
    """
    Automated worker for auditing shadow-mode contributor performance.
    Computes Pearson correlation between contributor output and realized PnL.
    Generates promotion candidates for human/CI-pipeline review.
    """

    def __init__(self):
        self.settings = Settings()
        self.db = DatabaseManager(self.settings.database_url)
        self.lookback_days = 14
        self.correlation_threshold = 0.4

    async def run(self):
        await self.db.initialize()
        try:
            print(f"[{datetime.now(UTC)}] Starting Alpha Promotion Audit...")

            query = """
            SELECT
                s.signal_id,
                s.pnl_r as realized_pnl,
                sh.agent_id,
                sh.multiplier as agent_multiplier
            FROM alpha_multiplier_shadow sh
            JOIN signal_ledger s ON sh.signal_id = s.signal_id
            WHERE sh.ts > $1
            """
            data = await self.db.execute_query(
                query, datetime.now(UTC) - timedelta(days=self.lookback_days)
            )

            if not data:
                print("No data found for lookback period.")
                return

            df = pd.DataFrame(data)

            candidates = []
            for agent_id, group in df.groupby("agent_id"):
                corr = group["agent_multiplier"].corr(group["realized_pnl"])
                if pd.isna(corr):
                    print(f"Warning: Agent {agent_id} has insufficient data for correlation (n={len(group)})")  # noqa: E501
                    continue
                if corr >= self.correlation_threshold:
                    candidates.append((agent_id, corr))

            self._generate_report(candidates)
        finally:
            await self.db.close()

    def _generate_report(self, candidates):
        report_path = project_root / "docs/reports/promotion_candidates.md"
        report_path.parent.mkdir(parents=True, exist_ok=True)

        with open(report_path, "w") as f:
            f.write(f"# Promotion Audit Report - {datetime.now(UTC).date()}\n\n")
            if not candidates:
                f.write(
                    f"No agents met the performance criteria "
                    f"(ρ ≥ {self.correlation_threshold}) for promotion.\n"
                )
            else:
                f.write("| Agent ID | Pearson Correlation (ρ) |\n")
                f.write("| --- | --- |\n")
                for agent, corr in candidates:
                    f.write(f"| {agent} | {corr:.4f} |\n")

        print(f"Report generated: {report_path}")


if __name__ == "__main__":
    worker = AlphaPromotionWorker()
    asyncio.run(worker.run())
