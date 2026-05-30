# Incremental Computation

**Version:** 1.0
**Status:** current
**Last Updated:** 2026-05-30
**Tags:** stateful-plugins, incremental-updates, computational-efficiency, streaming

> Plugins maintain bounded internal state and update it O(1) per bar — no history reprocessed after warmup.

## The Problem It Solves

132 plugins × full recomputation per bar = O(N×bars) work per tick. With 27 indicators, 55+ contracts, and 4 timeframes, that is ~5,940 full recomputations per bar. Each one reprocesses data that has not changed. A naive implementation recomputes RSI from the last 14 bars, ATR from the last 14 bars, MACD from the last 26 bars — redundant work that scales with history length and creates a processing backlog under live market conditions.

## The Principle

Each plugin maintains bounded internal state (e.g., a fixed-length deque, or a few running floats). On each new bar, the plugin calls `compute_next(bar)` which updates state O(1) — add the new value, drop the oldest, update the running sum. The full history is never reprocessed after warmup.

Examples:
- **EMA:** state is one float (previous EMA). New EMA = α × new_close + (1 - α) × prev_ema.
- **RSI:** state is two floats (smoothed gain, smoothed loss). Wilder's smoothing is a single division per bar.
- **Bollinger:** state is three floats (count, mean, M2). Welford's online variance — no accumulated floating point error.
- **Stochastic:** state is a fixed-length deque of closes. O(1) append, O(N) max over a small window (N=14-20).

The warmup period (~50 bars for GARCH/Kalman/HMM to converge) is the only legitimate O(N) operation. After warmup, every bar is O(1) regardless of history length.

## How IndicAgent Applies It

`supports_incremental` flag per plugin distinguishes two execution paths:

- **Incremental plugins** (`supports_incremental = True`) — called with only the new bar. State is managed by the pipeline service, not the plugin. A state key `(plugin_name, symbol, timeframe)` isolates state across instruments.
- **Window plugins** (`supports_incremental = False`) — receive a rolling window of bars on each call. Used for I3 (structure), I4 (regime), I5 (pattern): SwingDetector, GARCHVolatility, HMMRegime, pattern plugins. These require multi-bar windows for correctness. Window size is small enough that full recompute is acceptable, but they do not get the O(1) benefit.

Fallback: if state is empty (first bar after restart or state evicted), `compute_next()` calls `compute_full()` to seed state. After seeding, subsequent bars use the incremental path.

**State checkpointing:** Plugin state is serialized to `cache/plugin_states.json` on a timer. On restart, state is restored so warmup periods do not replay from scratch. If the checkpoint is corrupt or missing, the plugin reinitializes (warmup replays).

**Measured speedup: 141x faster than full recomputation across the I1 tier.**

## Invariants

- `compute_next()` may only read from internal state and the current bar — never from a full history lookup.
- Warmup is the only legitimate O(N) operation. All post-warmup computation must be O(1) or O(small-constant).
- State must be serializable to JSON for checkpointing.
- The state write-back after `compute_next()` is load-bearing for plugins (like GARCH, HMM) that fully reassign `_state` internally rather than mutating it in place.

## Recipe

When designing an incremental computation system:

1. **Identify which computations are truly incremental vs. window-based.** EMA, RSI, OBV are incremental. Chart patterns, regime detection, and swing points need a window.
2. **For incremental: define the minimal state representation.** Two floats for RSI, one float for EMA, a fixed deque for Stochastic. Resist storing more than you need.
3. **Set warmup length to the convergence window of the slowest state variable.** GARCH needs ~50 bars; EMA needs ~3N bars. The warmup is the maximum across all state variables in the plugin.
4. **Checkpoint state to local disk — not to a database.** Database round-trips on every bar negate the latency savings. Local file checkpoint on a timer is the right pattern.
5. **Implement fallback.** `compute_next()` should detect empty state and call `compute_full()` automatically. Callers should not need to know which path executes.
6. **Test incremental parity.** Verify that `compute_next()` over N bars produces the same result as `compute_full()` over those N bars. Divergence is a silent bug.

## See Also

- Implementation: `docs/intelligence/intelligence-plugins.md` — plugin protocol, `compute_full`/`compute_next` signatures, state management
- Related concept: `docs/concepts/dag-execution.md` — how incremental plugins are ordered across tiers
- Related concept: `docs/concepts/hot-path-isolation.md` — why hot-path state must be local, not DB-backed
