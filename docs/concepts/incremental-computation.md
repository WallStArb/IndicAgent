# Incremental Computation

**Version:** 2.0
**Status:** current
**Last Updated:** 2026-09-04
**Tags:** bounded-state, incremental-updates, computational-efficiency, streaming

> Per-bar compute must be bounded work, not O(full history) — either by capping the window that gets reprocessed, or by carrying genuinely incremental state across calls.

## The Problem It Solves

298 features × full-history recomputation per bar, across dozens of contracts and multiple timeframes, is unbounded work per tick that grows with how much history has accumulated. A naive implementation reloads and reprocesses the entire bar history for every feature on every bar — redundant work that scales with corpus age and creates a processing backlog under live market conditions. The system needs per-bar cost to stay flat regardless of how many months of history exist upstream.

## The Principle

There are two legitimate ways to keep per-bar cost bounded, and a real system uses both:

1. **Bounded-window recompute.** Cap the input to a fixed-size window (not the full history) and recompute over just that window each bar. Cost is O(window size), which is small and constant — it does not grow as history accumulates, even though it is not O(1) in the strict sense.
2. **True incremental state.** Maintain a running summary (a few floats, a counter) and update it O(1) per bar without ever touching the window at all — e.g. an EMA's running value, or a duration counter that increments or resets.

Both satisfy the same invariant: per-bar cost must not scale with total history length. Which one applies depends on whether the calculation is genuinely re-derivable from a small window (most technical features) or requires carrying forward a value that a window recompute would have to reconstruct expensively (regime state, session counters).

## How IndicAgent Applies It

`FeatureFactory.compute()` (`src/intelligence/feature_factory.py`) is a stateless pure function — no `__init__`, no stored config, zero I/O, deterministic given its inputs (D-08 contract). It is called once per bar per (symbol, timeframe) with:

- `bars` — the bounded window for that (symbol, tf) from `BarHistory` (`src/core/bar_history.py`), a per-key deque capped at `maxlen` (default 200). Appending a new bar evicts the oldest automatically — the window never grows past its cap, so recompute cost is flat regardless of how much history exists in the database.
- `cache: FeatureCache` — the small set of fields that genuinely need to persist across calls rather than being re-derived from the window each time: HMM regime (refreshed every `regime_cache_refresh_bars`, not every bar — cheaper than even O(1)-per-bar), cross-asset state (`vix_z`, `flight_quality`, `yield_slope_z`, populated by `update_cross_asset()`), and simple counters (`hmm_duration`, `above_wk_vwap`) incremented or reset by the caller each bar.
- `config: FeatureFactoryConfig` — a frozen dataclass built once by the caller and passed explicitly on every call; never stored on the class.

So most of the 298 features are bounded-window recompute (the window is the state boundary), and a handful of genuinely stateful fields live in `FeatureCache` as true incremental state. This is architecturally the old doc's "window plugin" strategy generalized to the whole feature set, with the old doc's "incremental plugin" pattern surviving only for the few fields where re-deriving from a window would be wasteful or impossible (e.g. a duration counter has no window-based reconstruction).

**Checkpointing:** `FeatureVectorPipeline` checkpoints `last_bar_offset` (the Kafka replay position) via `PluginStateManager`, not the window contents or `FeatureCache` fields themselves — on restart, `BarHistory` is repopulated from DB warmup/Kafka replay rather than deserialized from a state file. This differs from the old plugin-tier model, which serialized full per-plugin state to `cache/plugin_states.json`.

## Invariants

- `FeatureFactory.compute()` must remain a pure function of `(bars, symbol, tf, cache, config)` — no I/O, no `ConfigService.get()` calls, no Kafka, no `async`/`await` inside it.
- `BarHistory`'s per-key deque is capped (`maxlen`); nothing appends without eviction. Per-bar cost must never scale with total corpus history length.
- Fields promoted into `FeatureCache` must be fields that cannot be cheaply re-derived from the bounded window alone — don't add a cache field for something a window recompute already gives you.
- All tunable window sizes come from `FeatureFactoryConfig`, itself sourced from APR (`feature.*` namespace) — zero inline magic numbers in primitive bodies (SC-9).

## Recipe

When designing a bounded per-bar computation system:

1. **Default to bounded-window recompute.** It's simpler, stateless, and easy to test — most technical features fit this.
2. **Reserve true incremental state for what a window genuinely can't reconstruct.** A duration counter or a regime label refreshed on its own cadence are legitimate; don't build incremental state machines for things a window recompute already handles correctly.
3. **Size the window to the slowest feature's requirement**, and make sure the window cap is large enough that no feature silently truncates.
4. **Checkpoint only what's expensive to rebuild** (stream offsets), and let bounded, cheap-to-rebuild state (bar windows) repopulate from source on restart rather than round-tripping it through a state file.
5. **Test window-boundary correctness**, not incremental/full-recompute parity — since there's no separate incremental code path to diverge from the window path in this design.

## See Also

- Implementation: `docs/intelligence/intelligence-alphaengine.md` — `FeatureFactory`/`FeatureVectorPipeline` architecture
- Related concept: `docs/concepts/dag-execution.md` — how feature computation is ordered
- Related concept: `docs/concepts/hot-path-isolation.md` — why hot-path state must be local, not DB-backed
