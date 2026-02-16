#!/usr/bin/env python3
"""
Redis Stream Health Check

Version: 1.0.0
Last Updated: 2025-08-09
Status: Current ✅

Prints lengths and XINFO for key streams and pending sizes for consumer groups.
"""

import argparse
import json
import sys
from pathlib import Path

import redis

# Add project root to path for settings import
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.config.settings import Settings
from src.core.stream_keys import indicators as sk_indicators
from src.core.stream_keys import live_tick as sk_live_tick
from src.core.stream_keys import market as sk_market


def main():
    # Use Settings class for configuration with CLI overrides
    settings = Settings()

    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default=settings.redis_host)
    parser.add_argument("--port", type=int, default=settings.redis_port)
    parser.add_argument("--db", type=int, default=settings.redis_db)
    parser.add_argument("--env", default=settings.env_name or "dev")
    parser.add_argument("--symbol", default="ESU5")
    args = parser.parse_args()

    r = redis.Redis(host=args.host, port=args.port, db=args.db)

    env_prefix = f"{args.env}:" if args.env else ""
    streams = [
        sk_live_tick(env_prefix, args.symbol),
        sk_market(env_prefix, args.symbol, "1m"),
        sk_indicators(env_prefix, args.symbol, "1m"),
    ]

    for s in streams:
        try:
            xlen = r.xlen(s)
            info = r.execute_command("XINFO", "STREAM", s)
            print(json.dumps({"stream": s, "length": xlen, "info": info}, default=str))
        except Exception as e:
            print(json.dumps({"stream": s, "error": str(e)}))

    # Example consumer group pending checks
    groups = [
        (sk_market(env_prefix, args.symbol, "1m"), "indicator_processor"),
        (sk_live_tick(env_prefix, args.symbol), "websocket_clients"),
    ]
    for stream, group in groups:
        try:
            pend = r.xpending(stream, group)
            print(json.dumps({"stream": stream, "group": group, "pending": pend}, default=str))
        except Exception as e:
            print(json.dumps({"stream": stream, "group": group, "error": str(e)}))


if __name__ == "__main__":
    main()
