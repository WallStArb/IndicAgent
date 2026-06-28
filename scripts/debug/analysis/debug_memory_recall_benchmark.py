#!/usr/bin/env python3
"""
debug_memory_recall_benchmark.py — MemoryClient.recall() latency measurement and MEM-04 gate

Measures end-to-end recall latency (embed + HNSW + rerank) over >=1000 calls against
a seeded cohort in memory_episodes_labeled; produces p95 latency evidence for 50ms budget.
Run when validating memory subsystem performance or after pgvector tuning.
Requires seeded memory_episodes_labeled data; optionally Ollama for live embed tests.
"""

from __future__ import annotations

import argparse
import asyncio
import random
import resource
import sys
import time
from pathlib import Path
from uuid import uuid4

# Project root on sys.path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import asyncpg
import structlog

from src.config.settings import Settings
from src.core.database_manager import create_pool as create_db_pool
from src.core.memory.backends.calibration import PgvectorCalibrationBackend
from src.core.memory.backends.episodic import PgvectorEpisodicBackend
from src.core.memory.backends.mem0 import Mem0BackendImpl
from src.core.memory.backends.regime import PgvectorRegimeBackend
from src.core.memory.client import MemoryClient
from src.core.memory.embedding import EmbeddingService

log = structlog.get_logger("memory_recall_benchmark")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_BENCH_SYMBOL = "BENCH"
_BENCH_AGENT_ID = "benchmark_agent"
_BENCH_REGIME = "trending_up"
_BENCH_ENTRY_TYPE = "at_close"
_BENCH_REGIME_EPOCH = 1
_BENCH_TIMEFRAME = "5m"
_SEED_ROWS = 100  # episodic cohort size
_EMBED_DIM = 768
_VALID_OUTCOMES = [
    "never_activated",
    "stopped_at_entry",
    "stopped_in_trade",
    "target_1",
    "target_1_2",
    "target_full",
    "ttl_expired_ahead",
    "ttl_expired_behind",
    "condition_expired",
]

# ---------------------------------------------------------------------------
# Fake embedding service (zero-latency stub for HNSW-only measurement)
# ---------------------------------------------------------------------------


class _FakeEmbeddingService:
    """Zero-latency embedding stub for HNSW+rerank isolation benchmarks.

    Returns deterministic 768-dim vectors by cycling through a pre-generated
    pool. Warm-up cost amortized across the pool; per-call cost is a list copy.
    """

    def __init__(self, pool_size: int = 20, seed: int = 42) -> None:
        rng = random.Random(seed)
        self._pool = [[rng.gauss(0, 1) for _ in range(_EMBED_DIM)] for _ in range(pool_size)]
        self._idx = 0

    async def embed_context(self, context: object) -> tuple[list[float] | None, str]:
        vector = self._pool[self._idx % len(self._pool)]
        self._idx += 1
        return list(vector), "BENCH 5m at_close regime:trending_up"


# ---------------------------------------------------------------------------
# Context stub
# ---------------------------------------------------------------------------


class _BenchContext:
    """Minimal duck-typed context matching EmbeddingService.serialize() expectations."""

    symbol = _BENCH_SYMBOL
    timeframe = _BENCH_TIMEFRAME
    entry_type = _BENCH_ENTRY_TYPE
    hmm_regime = _BENCH_REGIME
    vol_regime = "normal"
    regime_epoch = _BENCH_REGIME_EPOCH
    hmm_prob = 0.75
    trend_score = 0.60
    ctf_score = 0.55
    rsi_pct = 0.65
    atr_pct = 0.50
    swing_structure = "HL"
    vol_pct = 0.45
    momentum_pct = 0.52


# ---------------------------------------------------------------------------
# Seeding
# ---------------------------------------------------------------------------


def _make_deterministic_vector(idx: int, seed: int = 99) -> str:
    """Generate a deterministic 768-dim unit vector for row idx as pgvector literal.

    asyncpg sends this as a text parameter; the ::vector cast in the SQL
    instructs pgvector to parse it (same pattern as PgvectorEpisodicBackend).
    """
    rng = random.Random(seed + idx)
    vec = [rng.gauss(0, 1) for _ in range(_EMBED_DIM)]
    norm = sum(x**2 for x in vec) ** 0.5 or 1.0
    vec = [x / norm for x in vec]
    return "[" + ",".join(str(v) for v in vec) + "]"


async def seed_bench_rows(pool: asyncpg.Pool) -> int:
    """Insert _SEED_ROWS synthetic labeled episodes for the BENCH cohort.

    Idempotent: deletes prior BENCH rows first.
    Returns number of rows inserted.
    """
    now_utc = __import__("datetime").datetime.now(__import__("datetime").timezone.utc)
    async with pool.acquire() as conn:
        deleted = await conn.execute(
            "DELETE FROM memory_episodes_labeled WHERE symbol = $1", _BENCH_SYMBOL
        )
        print(f"  Cleanup: removed prior BENCH rows ({deleted})")

        rows_inserted = 0
        for i in range(_SEED_ROWS):
            vec = _make_deterministic_vector(i)
            outcome = _VALID_OUTCOMES[i % len(_VALID_OUTCOMES)]
            pnl_r = round(random.uniform(-2.0, 3.0), 3)  # noqa: S311

            # asyncpg requires pgvector passed as a text literal with ::vector cast
            # (same pattern as PgvectorEpisodicBackend and MemoryEpisodeWriter)
            await conn.execute(
                """
                INSERT INTO memory_episodes_labeled (
                    id, ts, written_at, labeled_at, kind, signal_id, symbol, timeframe,
                    agent_id, embedding, embedding_text, hmm_regime, vol_regime,
                    entry_type, regime_epoch, n_eligible, memory_assisted,
                    outcome, pnl_r, mae, mfe, bars_in_trade, payload
                ) VALUES (
                    $1, $2, $2, $2, 'episodic'::memory_episode_kind, $3, $4, $5,
                    $6, $7::vector, $8, $9, 'normal', $10, $11, 50, FALSE,
                    $12, $13, $14, $15, $16, '{}'::jsonb
                )
                """,
                str(uuid4()),  # id
                now_utc,  # ts / written_at / labeled_at
                uuid4(),  # signal_id
                _BENCH_SYMBOL,  # symbol
                _BENCH_TIMEFRAME,  # timeframe
                _BENCH_AGENT_ID,  # agent_id
                vec,  # embedding (pgvector literal string "[f1,f2,...]")
                f"BENCH 5m at_close regime:trending_up sample_{i}",  # embedding_text
                _BENCH_REGIME,  # hmm_regime
                _BENCH_ENTRY_TYPE,  # entry_type
                _BENCH_REGIME_EPOCH,  # regime_epoch
                outcome,  # outcome
                pnl_r,  # pnl_r
                abs(pnl_r) * 0.3,  # mae
                abs(pnl_r) * 1.5,  # mfe
                random.randint(1, 20),  # bars_in_trade  # noqa: S311
            )
            rows_inserted += 1

    return rows_inserted


async def cleanup_bench_rows(pool: asyncpg.Pool) -> None:
    """Remove BENCH rows inserted by seed_bench_rows."""
    async with pool.acquire() as conn:
        result = await conn.execute(
            "DELETE FROM memory_episodes_labeled WHERE symbol = $1", _BENCH_SYMBOL
        )
    print(f"  Cleanup: removed BENCH rows ({result})")


# ---------------------------------------------------------------------------
# Benchmark runner
# ---------------------------------------------------------------------------


async def run_benchmark(
    pool: asyncpg.Pool,
    settings: Settings,
    n_calls: int = 1000,
    live_embed: bool = False,
) -> dict:
    """Run n_calls of MemoryClient.recall() and return latency statistics.

    Args:
        pool: asyncpg connection pool.
        settings: Application settings.
        n_calls: Number of timed recall calls to execute.
        live_embed: If True, use real EmbeddingService (requires Ollama).
                    If False (default), use _FakeEmbeddingService.

    Returns:
        dict with p50, p95, p99 (ms), embed_mode, n_calls, and component breakdown.
    """
    # Build backends
    episodic = PgvectorEpisodicBackend(pool=pool, timeout_ms=40, ef_search=100)
    calibration = PgvectorCalibrationBackend(pool=pool)
    regime = PgvectorRegimeBackend(pool=pool)
    mem0 = Mem0BackendImpl(settings=settings)

    if live_embed:
        embedding: EmbeddingService | _FakeEmbeddingService = EmbeddingService(
            model=settings.embedding_model,
            api_base=settings.ollama_base_url,
        )
        embed_mode = f"live ({settings.embedding_model})"
    else:
        embedding = _FakeEmbeddingService()
        embed_mode = "fake (zero-latency stub)"

    client = MemoryClient(
        episodic=episodic,
        calibration=calibration,
        regime=regime,
        mem0=mem0,
        embedding=embedding,
        recall_limit=10,
        embed_timeout_ms=30,
    )

    ctx = _BenchContext()
    latencies: list[float] = []

    # WR-04: measure embed as part of recall(), not as a separate external call.
    # The prior code called embed_context() twice per iteration — once externally
    # for timing, then again internally via client.recall(). In --live-embed mode
    # this doubled Ollama HTTP requests. The total recall latency is the authoritative
    # end-to-end measurement; in fake-embed mode, embed contribution is negligible
    # by design so hnsw_p95 ~ total_p95.
    print(f"\n  Running {n_calls} recall() calls (embed_mode={embed_mode})...")
    for i in range(n_calls):
        t0 = time.monotonic()
        await client.recall(ctx, agent_id=_BENCH_AGENT_ID)
        latencies.append((time.monotonic() - t0) * 1000.0)

        if (i + 1) % 200 == 0:
            print(f"    {i + 1}/{n_calls} calls done")

    latencies.sort()

    def pct(values: list[float], p: float) -> float:
        idx = int(len(values) * p / 100)
        return round(values[min(idx, len(values) - 1)], 3)

    total_p50 = pct(latencies, 50)
    total_p95 = pct(latencies, 95)
    total_p99 = pct(latencies, 99)

    # In fake-embed mode embed latency is ~0 so hnsw_p95 ~ total_p95.
    # In live-embed mode total_p95 includes real Ollama latency.
    # Report embed contribution as 0 in fake mode; live mode shows full path.
    embed_p50 = 0.0 if not live_embed else float("nan")
    embed_p95 = 0.0 if not live_embed else float("nan")
    hnsw_p50 = total_p50 if not live_embed else float("nan")
    hnsw_p95 = total_p95 if not live_embed else float("nan")

    return {
        "total_p50_ms": total_p50,
        "total_p95_ms": total_p95,
        "total_p99_ms": total_p99,
        "embed_p50_ms": embed_p50,
        "embed_p95_ms": embed_p95,
        "hnsw_rerank_p50_ms": hnsw_p50,
        "hnsw_rerank_p95_ms": hnsw_p95,
        "n_calls": n_calls,
        "embed_mode": embed_mode,
    }


# ---------------------------------------------------------------------------
# RAM footprint estimation
# ---------------------------------------------------------------------------


def estimate_ram_footprint(queue_maxsize: int = 500) -> dict:
    """Estimate the memory subsystem RAM footprint.

    Three components:
    1. asyncio.Queue buffer: queue_maxsize * avg episode dict size (~800 bytes)
    2. EmbeddingService: litellm manages transport — no persistent HTTP client held
    3. asyncpg pool: 2 connections * ~50KB per connection
    """
    # Queue: each Episode dict has ~15 fields; conservatively 800 bytes per slot
    avg_episode_bytes = 800
    queue_bytes = queue_maxsize * avg_episode_bytes

    # EmbeddingService: litellm is stateless (no httpx client held); negligible
    embedding_service_bytes = 4 * 1024  # 4KB for model string + api_base

    # asyncpg pool (2 min connections for benchmark, 5 in production)
    asyncpg_bytes_per_conn = 50 * 1024
    prod_pool_conns = 5
    pool_bytes = prod_pool_conns * asyncpg_bytes_per_conn

    # Process RSS delta (actual Python interpreter overhead)
    try:
        rss_kb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    except Exception:
        rss_kb = -1

    return {
        "queue_kb": round(queue_bytes / 1024, 1),
        "embedding_service_kb": round(embedding_service_bytes / 1024, 1),
        "asyncpg_pool_kb": round(pool_bytes / 1024, 1),
        "total_estimated_kb": round((queue_bytes + embedding_service_bytes + pool_bytes) / 1024, 1),
        "process_rss_kb": rss_kb,
        "queue_maxsize": queue_maxsize,
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


async def main(args: argparse.Namespace) -> None:
    settings = Settings()

    print("=== MemoryClient.recall() Latency Benchmark (MEM-04) ===")
    print(f"  n_calls:     {args.n}")
    print(f"  embed_mode:  {'live' if args.live_embed else 'fake'}")
    print(f"  seed_rows:   {_SEED_ROWS}")
    print(f"  DB:          {settings.database_url}")

    pool = await create_db_pool(settings.database_url, min_size=1, max_size=3)

    # Seed
    print("\n[1/4] Seeding BENCH cohort...")
    n_seeded = await seed_bench_rows(pool)
    print(f"  Inserted {n_seeded} rows into memory_episodes_labeled")

    # --seed-only: rows are retained in DB; exit before the try/finally cleanup block.
    if args.seed_only:
        print("\nSeed-only mode - rows retained. Run cleanup manually when done.")
        await pool.close()
        return

    try:
        # Benchmark
        print("\n[2/4] Running benchmark...")
        stats = await run_benchmark(
            pool=pool,
            settings=settings,
            n_calls=args.n,
            live_embed=args.live_embed,
        )

        # RAM
        print("\n[3/4] Estimating RAM footprint...")
        ram = estimate_ram_footprint()

        # Report
        print("\n" + "=" * 60)
        print("LATENCY RESULTS")
        print("=" * 60)
        print(f"  Embed mode:              {stats['embed_mode']}")
        print(f"  Calls:                   {stats['n_calls']}")
        print(f"  Total recall p50:        {stats['total_p50_ms']:.3f} ms")
        print(f"  Total recall p95:        {stats['total_p95_ms']:.3f} ms")
        print(f"  Total recall p99:        {stats['total_p99_ms']:.3f} ms")
        print(f"  Embed contribution p50:  {stats['embed_p50_ms']:.3f} ms")
        print(f"  Embed contribution p95:  {stats['embed_p95_ms']:.3f} ms")
        print(f"  HNSW+rerank p50:         {stats['hnsw_rerank_p50_ms']:.3f} ms")
        print(f"  HNSW+rerank p95:         {stats['hnsw_rerank_p95_ms']:.3f} ms")

        budget_gate = stats["hnsw_rerank_p95_ms"] <= 20.0  # embed gets the other 30ms
        gate_str = "PASS" if budget_gate else "NEEDS REVIEW"
        print(f"\n  50ms gate verdict:       {gate_str}")
        print(
            f"    HNSW+rerank p95 {stats['hnsw_rerank_p95_ms']:.1f}ms + embed_timeout 30ms <= 50ms budget"
        )
        if not budget_gate:
            print("    WARNING: HNSW+rerank p95 > 20ms — review index or pool config")

        print("\nRAM FOOTPRINT")
        print("=" * 60)
        print(f"  asyncio.Queue ({ram['queue_maxsize']} slots x ~800B):  {ram['queue_kb']:.1f} KB")
        print(f"  EmbeddingService (litellm stateless):    {ram['embedding_service_kb']:.1f} KB")
        print(f"  asyncpg pool (5 conns x 50KB):           {ram['asyncpg_pool_kb']:.1f} KB")
        print(f"  Total estimated:                         {ram['total_estimated_kb']:.1f} KB")
        print(f"  Process RSS (max):                       {ram['process_rss_kb']} KB")
        print("=" * 60)

    finally:
        # Cleanup
        print("\n[4/4] Cleaning up BENCH rows...")
        await cleanup_bench_rows(pool)
        await pool.close()
        print("  Done.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="MemoryClient.recall() latency benchmark")
    parser.add_argument("--n", type=int, default=1000, help="Number of recall calls (default 1000)")
    parser.add_argument(
        "--live-embed",
        action="store_true",
        help="Use live EmbeddingService (requires Ollama running)",
    )
    parser.add_argument(
        "--seed-only",
        action="store_true",
        help="Seed rows and exit without running benchmark",
    )
    args = parser.parse_args()
    asyncio.run(main(args))
