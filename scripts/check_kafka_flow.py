#!/usr/bin/env python3
"""
Check Kafka data flow: Market bars (1m) and Intelligence records.

Verifies:
- Deterministic 1m bar emission (TwsDaemon heartbeat)
- Reconciliation metadata (is_reconciled, drift_detected)
- Intelligence record flow (SignalGenerator output)
"""

import asyncio
import json
import sys
from datetime import datetime, UTC
from pathlib import Path

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

from src.config.settings import Settings
from src.core.kafka_utils import KafkaConsumerClient
from src.core.stream_keys import topic_market_bars, topic_intelligence

async def check_flow():
    settings = Settings()
    env = settings.env_name
    
    topics = [
        topic_market_bars(env),
        topic_intelligence(env)
    ]
    
    print(f"Connecting to Kafka at {settings.kafka_bootstrap_servers}...")
    print(f"Monitoring topics: {topics}")
    
    consumer = KafkaConsumerClient(
        *topics,
        bootstrap_servers=settings.kafka_bootstrap_servers,
        group_id=f"check_flow_{datetime.now().timestamp()}",
        auto_offset_reset="latest"
    )
    
    await consumer.start()
    print("Listening for messages (Ctrl+C to stop)...\n")
    
    try:
        async for topic, key, payload in consumer.messages():
            now = datetime.now(UTC).strftime("%H:%M:%S")
            
            if "market.bars" in topic:
                symbol = payload.get("symbol")
                ts = payload.get("timestamp")
                vol = payload.get("volume")
                reconciled = payload.get("is_reconciled", False)
                drift = payload.get("drift_detected", False)
                
                status = "HEARTBEAT" if float(vol or 0) == 0 else "TRADE"
                rec_status = "✅" if reconciled else "⏳"
                drift_status = "⚠️ DRIFT" if drift else "OK"
                
                print(f"[{now}] BAR  | {symbol:8} | {ts} | {status:9} | Vol: {vol:10} | {rec_status} | {drift_status}")
            
            elif "intelligence" in topic:
                event = payload.get("event")
                if isinstance(event, str):
                    event = json.loads(event)
                
                symbol = event.get("symbol")
                tf = event.get("tf")
                ts = event.get("ts")
                print(f"[{now}] INTEL| {symbol:8} | {tf:3} | {ts}")

    except KeyboardInterrupt:
        pass
    finally:
        await consumer.stop()

if __name__ == "__main__":
    try:
        asyncio.run(check_flow())
    except KeyboardInterrupt:
        print("\nVerification stopped.")
