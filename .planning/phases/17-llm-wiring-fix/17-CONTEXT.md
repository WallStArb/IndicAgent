# Phase 17: LLM Wiring Fix - Context

**Gathered:** 2026-03-06
**Status:** Ready for planning

<domain>
## Phase Boundary

Fix two broken production flows identified by the v1.4 audit:
1. `signal_id` UUID never reaches `llm_calls` — outcome back-fill always no-ops
2. `SessionExtremesSetup` emits session labels into `regime_context` — corrupts score grouping

Scope also includes: regime vocabulary consistency (stored value = lookup key, no translation),
and `SessionExtremesSetup` fix to emit proper regime buckets with session label preserved in
`supporting_factors`.

Out of scope: 3 plugins with no `regime_context` field (LiquidityHunt, LiquiditySweepReclaim,
SupplyDemandSetup) — their empty string falls to `__all__` bucket, acceptable for now.

</domain>

<decisions>
## Implementation Decisions

### signal_id threading — stream-first, DB-second

- **Source**: `signal_id` is already assigned in `LedgerEntry` inside `build_ledger_entries()`.
  Read it back from the `was_selected=True` entry — no new UUID generation.
- **Order flip** (Renaissance hot/warm/cold principle): publish to `signals:aggregated` stream
  FIRST, then run `insert_signals()` DB write. Stream is hot tier (sub-ms); DB is cold tier.
  `signal_lifecycle_service` exits signals minutes-to-hours later — `signal_ledger` row will
  exist long before any outcome back-fill is attempted.
- **Safe**: Phase 16 deliberately used soft FK (no FK constraint on `llm_calls.signal_id`).
  If DB insert fails after stream publish, outcome back-fill no-ops — same as today.
- **Code change**: in `signal_generator_service._process_bar()`, after `build_ledger_entries`:
  ```python
  selected_entry = next((e for e in entries if e.was_selected), None)
  message["signal_id"] = selected_entry.signal_id if selected_entry else ""
  await redis.xadd(stream_name, message, ...)   # stream first
  await insert_signals(db_manager, entries)      # DB after
  ```

### ai_narrative_service — extract and pass signal_id

- `parse_aggregated_signal()`: add `signal_id` field extraction from stream message
- `_build_llm_call_payload()`: use `str(sd.get("signal_id", ""))` instead of hardcoded `""`
- No other changes to the payload builder

### Regime vocabulary — keep raw values, no translation (Renaissance: segment relentlessly)

- Do NOT translate plugin `regime_context` values to a 3-bucket canonical vocabulary.
  Raw plugin strings ARE the regime vocabulary — they represent distinct market conditions
  with potentially different model performance profiles.
- Complete vocabulary (18 distinct values across all 17 I7 plugins):
  `"bullish"`, `"bearish"`, `"ranging"`, `"neutral"`, `"breakout_bullish"`,
  `"breakout_bearish"`, `"expansion_bullish"`, `"expansion_bearish"`,
  `"vwap_extended_low"`, `"vwap_extended_high"`, `"transitioning"`,
  `"bullish_transition"`, `"bearish_transition"`, `"gap_open"`,
  `"session_extreme_london"`, `"session_extreme_ny"`, `"session_extreme_both"`,
  `""` (3 plugins with no regime_context — falls to `__all__` aggregate)
- `llm_calls.regime` stores the raw value as-is
- `_apply_score_routing` already looks up by the same raw string — no change needed
- `__all__` aggregate row handles cross-regime routing until per-bucket n>=30

### SessionExtremesSetup — emit session-specific regime buckets

- Replace session label in `regime_context` with three distinct regime strings:
  - `"session_extreme_london"` — signal fires during London session
  - `"session_extreme_ny"` — signal fires during NY session
  - `"session_extreme_both"` — signal fires during London/NY overlap
- Move session label to `supporting_factors` where it belongs as metadata:
  `supporting_factors.append(f"session:{session_ctx}")` alongside existing factors
- Rationale: London open fades, NY open fades, and overlap fades have distinct statistical
  profiles (different liquidity, follow-through, volatility). Renaissance segments at this
  granularity. `__all__` bucket covers routing until n>=30 accumulates per bucket.
- Note: No Asian session bucket — plugin only fires during London/NY (Asian range is the
  setup reference, not a trigger window).

### Score cache key alignment — resolved by consistency

- No dedicated fix needed. Once `regime_context` flows through consistently (raw values
  stored = raw values looked up), the cache key mismatch resolves automatically.
- `_apply_score_routing` uses `signal_data.get("regime_context", "")` — already correct.

### Claude's Discretion

- Whether `parse_aggregated_signal` returns empty string or None for missing `signal_id`
  (either works — llm_writer_service handles both via `_dec()` helper)
- Test structure for signal_id threading (unit vs integration)
- Whether to add `signal_id` to `parse_aggregated_signal` return dict or handle in caller

</decisions>

<code_context>
## Existing Code Insights

### Reusable Assets
- `build_ledger_entries()` in `signal_ledger.py`: already assigns `signal_id=str(uuid4())`
  per entry; `was_selected` flag identifies the winner — no changes to this function needed
- `_build_llm_call_payload()` in `ai_narrative_service.py`: single location for all signal
  field extraction — minimal change to add `signal_id` passthrough
- `parse_aggregated_signal()` in `ai_narrative_service.py`: pure function, easy to extend
  with `signal_id` field using existing `_get()` helper

### Established Patterns
- Stream-first ordering already used by `feature_writer_service` (hot/warm/cold separation)
- `supporting_factors` is a list of strings — append pattern used by all I7 plugins
- `_dec()` helper in `llm_writer_service._parse_llm_call_fields` handles empty string
  gracefully (returns None for empty, which asyncpg casts to NULL for UUID column)

### Integration Points
- `signal_generator_service._process_bar()`: stream publish order flip + signal_id injection
- `ai_narrative_service.parse_aggregated_signal()`: add signal_id extraction
- `ai_narrative_service._build_llm_call_payload()`: use signal_id from signal_data
- `session_extremes_setup.py`: replace session label logic in regime_context assignment

</code_context>

<specifics>
## Specific Ideas

- The `signals:aggregated` stream message already serialises all scalar fields from
  `result.selected_signal` via `{k: str(v) for k, v in sig.items() if isinstance(v, ...)}`.
  `signal_id` is a string — it will pass through the existing serialisation check naturally
  once added to the message dict.

- `_build_llm_call_payload` comment "not in aggregated stream" on `signal_id` should be
  removed/updated — it will be in the stream after this fix.

- `llm_writer_service._parse_llm_call_fields` already has `"signal_id": _dec(b"signal_id")`
  — it's already wired to read signal_id from the stream. No changes needed there.

- The `_UPDATE_OUTCOME_SQL WHERE signal_id = $1::uuid` in `llm_writer_service` is already
  correct — it just needs non-null signal_ids to match against.

</specifics>

<deferred>
## Deferred Ideas

- Add `regime_context` to `LiquidityHunt`, `LiquiditySweepReclaim`, `SupplyDemandSetup` —
  these 3 plugins have no `regime_context` in their outputs frozenset; their signals fall to
  `__all__` aggregate bucket. Acceptable for now; add as separate todo.
- Regime-specific model promotion gate (must hold across 2+ regimes) — v2 per Phase 16 deferred
- Latency-adjusted model routing — backlog

</deferred>

---

*Phase: 17-llm-wiring-fix*
*Context gathered: 2026-03-06*
