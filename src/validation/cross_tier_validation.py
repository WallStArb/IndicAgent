"""
Cross-tier consistency validation.

Validates that transformations between intelligence tiers are consistent:
- I1 features feed I4 context correctly
- I6 features are present for I7 signals
- I4 regime matches I7 regime_type
"""

import asyncpg
import numpy as np
from typing import Dict


class CrossTierValidator:
    """Validate cross-tier consistency in the intelligence pipeline."""

    def __init__(self, db: asyncpg.Connection):
        """Initialize validator with database connection.

        Args:
            db: asyncpg connection or connection pool
        """
        self.db = db

    async def validate_i1_to_i4_consistency(
        self, symbol: str, tf: str
    ) -> Dict:
        """Validate I1 features correlate with I4 context.

        I1 ATR should correlate with I4 volatility (both measure volatility).
        Correlation threshold: ≥0.5

        Args:
            symbol: Trading symbol
            tf: Timeframe

        Returns:
            Dict with correlation and pass/fail status
        """
        query = """
            SELECT
                i1->>'atr_14' as i1_atr,
                i4->>'volatility' as i4_volatility
            FROM intelligence_features
            WHERE symbol = $1 AND tf = $2
              AND ts > NOW() - INTERVAL '24 hours'
        """

        rows = await self.db.fetch(query, symbol, tf)

        # Extract arrays (skip nulls)
        i1_atr = np.array(
            [float(r["i1_atr"]) for r in rows if r["i1_atr"] is not None]
        )
        i4_vol = np.array(
            [float(r["i4_volatility"]) for r in rows if r["i4_volatility"] is not None]
        )

        # Compute correlation
        if len(i1_atr) > 0 and len(i4_vol) > 0:
            min_len = min(len(i1_atr), len(i4_vol))
            if min_len > 1:
                corr_matrix = np.corrcoef(i1_atr[:min_len], i4_vol[:min_len])
                corr = corr_matrix[0, 1]
            else:
                corr = np.nan
        else:
            corr = np.nan
            min_len = 0

        result = {
            "i1_atr_i4_volatility_correlation": float(corr) if not np.isnan(corr) else 0.0,
            "expected_min": 0.5,
            "passed": bool(corr >= 0.5) if not np.isnan(corr) else False,
            "samples": min_len,
        }

        # Persist
        await self.db.execute(
            """
            INSERT INTO intelligence_metrics (symbol, timeframe, i1_i4_correlation)
            VALUES ($1, $2, $3)
        """,
            symbol,
            tf,
            result["i1_atr_i4_volatility_correlation"],
        )

        return result

    async def validate_i6_to_i7_completeness(
        self, symbol: str, tf: str
    ) -> Dict:
        """Validate I6 confluence fields are present for I7 signals.

        Required I6 fields: ctf_score, ctf_trend_alignment, ctf_fvg_alignment, ctf_ob_alignment
        Completeness threshold: ≥95%

        Args:
            symbol: Trading symbol
            tf: Timeframe

        Returns:
            Dict with completeness rate and pass/fail status
        """
        query = """
            SELECT i6, i7
            FROM intelligence_features
            WHERE symbol = $1 AND tf = $2
              AND ts > NOW() - INTERVAL '24 hours'
        """

        rows = await self.db.fetch(query, symbol, tf)

        total_rows = 0
        complete_rows = 0
        missing_field_counts = {}

        # Required I6 confluence fields
        required_fields = [
            "ctf_score",
            "ctf_trend_alignment",
            "ctf_fvg_alignment",
            "ctf_ob_alignment",
        ]

        for row in rows:
            i6 = row.get("i6", {})
            if not isinstance(i6, dict):
                continue

            total_rows += 1

            # Check if all required I6 fields are present and non-null
            missing = [f for f in required_fields if i6.get(f) is None]

            if not missing:
                complete_rows += 1
            else:
                for f in missing:
                    missing_field_counts[f] = missing_field_counts.get(f, 0) + 1

        completeness_rate = (
            complete_rows / total_rows if total_rows > 0 else 0.0
        )

        result = {
            "total_rows": total_rows,
            "complete_rows": complete_rows,
            "completeness_rate": completeness_rate,
            "expected_min": 0.95,
            "passed": completeness_rate >= 0.95,
            "missing_field_counts": missing_field_counts,
        }

        # Persist
        await self.db.execute(
            """
            INSERT INTO intelligence_metrics (symbol, timeframe, i6_i7_completeness)
            VALUES ($1, $2, $3)
        """,
            symbol,
            tf,
            completeness_rate,
        )

        return result

    async def validate_regime_agreement(
        self, symbol: str, tf: str
    ) -> Dict:
        """Validate I4 regime matches I7 signal regime_type.

        Signals with regime_type='any' match any I4 regime.
        Agreement threshold: ≥90%

        Args:
            symbol: Trading symbol
            tf: Timeframe

        Returns:
            Dict with agreement rate and pass/fail status
        """
        query = """
            SELECT
                i4->>'regime' as i4_regime,
                i7
            FROM intelligence_features
            WHERE symbol = $1 AND tf = $2
              AND i4->>'regime' IS NOT NULL
              AND i7 IS NOT NULL
              AND ts > NOW() - INTERVAL '24 hours'
        """

        rows = await self.db.fetch(query, symbol, tf)

        total_signals = 0
        matching_signals = 0

        for row in rows:
            i4_regime = row["i4_regime"]
            i7_signals = row.get("i7", [])

            if not isinstance(i7_signals, list):
                continue

            for signal in i7_signals:
                if not isinstance(signal, dict):
                    continue

                total_signals += 1
                i7_regime = signal.get("regime_type")

                # Signals with regime_type='any' match any I4 regime
                if i7_regime == "any" or i7_regime == i4_regime:
                    matching_signals += 1

        agreement_rate = (
            matching_signals / total_signals if total_signals > 0 else 0.0
        )

        result = {
            "total_signals": total_signals,
            "matching_signals": matching_signals,
            "agreement_rate": agreement_rate,
            "expected_min": 0.90,
            "passed": agreement_rate >= 0.90,
        }

        # Persist
        await self.db.execute(
            """
            INSERT INTO intelligence_metrics (symbol, timeframe, i4_i7_regime_agreement)
            VALUES ($1, $2, $3)
        """,
            symbol,
            tf,
            agreement_rate,
        )

        return result
