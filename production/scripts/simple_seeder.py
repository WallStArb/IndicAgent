#!/usr/bin/env python3
"""
Simple synchronous historical data seeder - no asyncio conflicts.

Adds CLI flags for symbols and days, and reads IB host/port from Settings by default.
"""
# DEPRECATED: This script is superseded by historical_backfill.py which:
#   - Uses Settings.contracts (all 14 current instruments, auto-updated expiries)
#   - Runs the full I1→I7 intelligence pipeline to populate signal_ledger
#   - Supports multi-timeframe (1m/5m/15m/1h) bar generation
# Use: python production/scripts/historical_backfill.py --days 90

import argparse
import sys
import time
from pathlib import Path
from typing import Any

import psycopg2

# Add project root to path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from ib_insync import IB, Future

from src.config.settings import Settings


class SimpleSeeder:
    """Simple synchronous seeder."""

    def __init__(
        self,
        host: str | None = None,
        port: int | None = None,
        client_id: int = 55,
        symbols_csv: str | None = None,
        days: str = "10 D",
    ):
        settings = Settings()
        self.host = host or settings.ib_host
        self.port = port or settings.ib_port
        self.client_id = client_id  # Different ID
        self.days = days

        all_contracts = [
            # Equity Index Futures (CME)
            {"symbol": "ESU5", "base": "ES", "exchange": "CME", "expiry": "20250919"},
            {"symbol": "NQU5", "base": "NQ", "exchange": "CME", "expiry": "20250919"},
            {"symbol": "RTYU5", "base": "RTY", "exchange": "CME", "expiry": "20250919"},
            # Energy Futures (NYMEX)
            {"symbol": "CLU5", "base": "CL", "exchange": "NYMEX"},
            {"symbol": "NGU25", "base": "NG", "exchange": "NYMEX"},
            # Metals Futures (COMEX/NYMEX)
            {"symbol": "GCV5", "base": "GC", "exchange": "COMEX"},
            {"symbol": "SILU5", "base": "SI", "exchange": "COMEX"},
            {"symbol": "HGU5", "base": "HG", "exchange": "COMEX"},
        ]

        if symbols_csv:
            wanted = {s.strip() for s in symbols_csv.split(",") if s.strip()}
            self.contracts = [c for c in all_contracts if c["symbol"] in wanted]
        else:
            self.contracts = all_contracts

        print("📊 Simple Seeder initialized")

    def connect_tws(self) -> IB | None:
        """Connect to TWS synchronously."""
        try:
            print(f"🔌 Connecting to TWS ({self.host}:{self.port}, Client ID: {self.client_id})")

            ib = IB()
            ib.connect(host=self.host, port=self.port, clientId=self.client_id, timeout=30)

            if ib.isConnected():
                print("✅ TWS connected successfully")
                return ib
            else:
                print("❌ TWS connection failed")
                return None

        except Exception as e:
            print(f"❌ TWS connection error: {e}")
            return None

    def connect_db(self):
        """Connect to PostgreSQL."""
        try:
            conn = psycopg2.connect(
                host="localhost",
                port=5432,
                database="indicagent",
                user="postgres",
                password="postgres",
            )
            print("✅ Database connected")
            return conn
        except Exception as e:
            print(f"❌ Database connection error: {e}")
            return None

    def get_historical_data(self, ib: IB, contract_config: dict[str, str]) -> list[dict[str, Any]]:
        """Get historical 1m bars."""
        try:
            # Create contract
            expiry = contract_config.get("expiry", "")
            contract = Future(
                symbol=contract_config["base"],
                lastTradeDateOrContractMonth=expiry,
                exchange=contract_config["exchange"],
            )

            # Qualify contract
            details = ib.reqContractDetails(contract)
            if not details:
                print(f"❌ No contract details for {contract_config['symbol']}")
                return []

            qualified_contract = details[0].contract
            print(
                f"📋 Qualified {contract_config['symbol']}: "
                f"{qualified_contract.lastTradeDateOrContractMonth}"
            )

            # Request N days of 1m bars
            print(f"📈 Requesting {self.days} of 1m bars for {contract_config['symbol']}...")

            bars = ib.reqHistoricalData(
                contract=qualified_contract,
                endDateTime="",
                durationStr=self.days,
                barSizeSetting="1 min",
                whatToShow="TRADES",
                useRTH=True,
            )

            if not bars:
                print(f"❌ No historical data for {contract_config['symbol']}")
                return []

            # Convert to our format
            historical_data = []
            for bar in bars:
                historical_data.append(
                    {
                        "timestamp": bar.date,
                        "symbol": contract_config["symbol"],
                        "open": float(bar.open),
                        "high": float(bar.high),
                        "low": float(bar.low),
                        "close": float(bar.close),
                        "volume": int(bar.volume),
                    }
                )

            print(f"✅ Retrieved {len(historical_data)} bars for {contract_config['symbol']}")
            return historical_data

        except Exception as e:
            print(f"❌ Historical data error for {contract_config['symbol']}: {e}")
            return []

    def store_data(self, db_conn, data: list[dict[str, Any]]):
        """Store data in database."""
        if not data:
            return

        try:
            cursor = db_conn.cursor()

            insert_query = """
                INSERT INTO market_data_ohlcv
                (timestamp, symbol, timeframe, open, high, low, close, volume, source)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (symbol, timeframe, source, timestamp) DO NOTHING
            """

            # Prepare data
            insert_data = []
            for bar in data:
                insert_data.append(
                    (
                        bar["timestamp"],
                        bar["symbol"],
                        "1m",
                        bar["open"],
                        bar["high"],
                        bar["low"],
                        bar["close"],
                        bar["volume"],
                        "ibkr_simple_seeder",
                    )
                )

            cursor.executemany(insert_query, insert_data)
            db_conn.commit()

            print(f"✅ Stored {len(insert_data)} bars in database")

        except Exception as e:
            print(f"❌ Database storage error: {e}")
            if db_conn:
                db_conn.rollback()

    def run(self):
        """Main seeding process."""
        print("🚀 Starting Simple Historical Data Seeding")
        print("=" * 50)

        # Connect to TWS
        ib = self.connect_tws()
        if not ib:
            print("❌ Cannot proceed without TWS connection")
            return

        # Connect to database
        db_conn = self.connect_db()
        if not db_conn:
            print("❌ Cannot proceed without database connection")
            if ib:
                ib.disconnect()
            return

        try:
            # Seed each contract
            total_bars = 0
            for contract_config in self.contracts:
                print(f"\n📊 Processing {contract_config['symbol']}...")

                # Get historical data
                historical_data = self.get_historical_data(ib, contract_config)

                if historical_data:
                    # Store in database
                    self.store_data(db_conn, historical_data)
                    total_bars += len(historical_data)

                # Rate limiting
                print("⏳ Pausing 2 seconds...")
                time.sleep(2.0)

            # Final summary
            print("\n🎉 SEEDING COMPLETE!")
            print(f"📊 Total bars seeded: {total_bars:,}")

            # Check database
            cursor = db_conn.cursor()
            cursor.execute(
                """
                SELECT symbol, COUNT(*) as bar_count,
                       MIN(timestamp) as first_bar, MAX(timestamp) as last_bar
                FROM market_data_ohlcv
                WHERE source = 'ibkr_simple_seeder'
                GROUP BY symbol
                ORDER BY symbol
            """
            )

            results = cursor.fetchall()
            print("\n📋 Database Summary:")
            print("=" * 30)
            for row in results:
                symbol, count, first, last = row
                print(f"{symbol}: {count:,} bars ({first} to {last})")

        except Exception as e:
            print(f"❌ Seeding error: {e}")
        finally:
            # Cleanup
            if ib and ib.isConnected():
                ib.disconnect()
                print("🔌 Disconnected from TWS")

            if db_conn:
                db_conn.close()
                print("🔌 Disconnected from database")


def main():
    parser = argparse.ArgumentParser(description="Seed historical bars from IBKR into TimescaleDB")
    parser.add_argument("--symbols", help="Comma-separated symbols (e.g., ESU5,NQU5)", default=None)
    parser.add_argument(
        "--days", help='Duration string (e.g., "2 D", "5 D", "10 D")', default="10 D"
    )
    parser.add_argument("--host", help="IBKR host (defaults to Settings)", default=None)
    parser.add_argument("--port", help="IBKR port (defaults to Settings)", type=int, default=None)
    parser.add_argument("--client-id", help="IBKR client ID", type=int, default=55)
    args = parser.parse_args()

    seeder = SimpleSeeder(
        host=args.host,
        port=args.port,
        client_id=args.client_id,
        symbols_csv=args.symbols,
        days=args.days,
    )
    seeder.run()


if __name__ == "__main__":
    main()
