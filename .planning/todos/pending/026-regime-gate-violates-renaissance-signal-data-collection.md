# Todo: Regime Gate Violates Renaissance Signal Data Collection

**Priority:** High
**Phase:** v2.1 (can slot into Phase 49 or as Phase 49.1)
**Discovered:** 2026-03-23

## Problem

The current signal pipeline has a hard regime gate that blocks signals from reaching `signal_ledger` when the market is in a ranging/non-trend regime. Investigation showed `signals_after_regime: 0` in logs — **all signals suppressed**.

This violates core Renaissance principles from CLAUDE.md:
- **"Never drop data that could contain signal."** — Signals are discarded before outcomes can be measured.
- **"Earn the right through proof."** — We can't calculate p-values by regime if we never write the data.
- **"Segment relentlessly."** — How do we know trend-following fails in ranging regimes if we never test it?
- **"Let the system run. Don't override data with intuition."** — The gate is an a priori assumption, not data-driven suppression.

## Root Cause

The regime gate acts as a hard filter **before** writing to `signal_ledger`. This means:
- No signal records = no outcome tracking = no statistical validation
- Can never compute `win_rate by (plugin, regime_type)` — the segmentation data doesn't exist
- Permanently blind to whether some I7 setups actually work in ranging regimes

Confirmed via Redpanda consumption:
```bash
docker exec redpanda rpk topic consume development.intelligence.record --num 10 --offset 28548 2>/dev/null | jq -r '.value' |
  python3 -c "
import sys, json
for line in sys.stdin:
    d = json.loads(json.loads(line))  # Double-parse
    if d.get('winner_plugin'):
        print(f\"WINNER: {d['intelligence']['ts']} - {d['intelligence']['symbol']} - {d['winner_plugin']}\")
    else:
        print(f\"NO WINNER: {d['intelligence']['ts']} - {d['intelligence']['symbol']} - regime_gated\")
"
```
All lines returned `NO WINNER: ... - regime_gated`.

## Renaissance-Correct Architecture

```
Current (broken):
  I7 → Regime gate (hard block) → Signals lost forever

Correct (Renaissance):
  I7 → Write ALL signals to signal_ledger (with regime_type_at_fire metadata)
     → Track outcomes per signal
     → Calculate win_rate / p-value by (plugin, regime_type, tf) segment
     → Only THEN gate/promote/demote based on statistical proof (p < 0.05, N ≥ 30)
```

The regime is a **feature dimension for segmentation**, not a gate. Suppression (if ever justified) must be earned through proof, not assumed.

## Required Changes

1. **Remove hard regime gate** from signal publish path in `signal_generator_service.py`
2. **Verify `regime_type_at_fire` column** is present in `signal_ledger` and populated at insert time (check `signal_ledger.py` LedgerEntry)
3. **Add `regime_eligible` flag** to signal dict (keep as metadata, don't gate on it) — allows future analysis without blocking writes
4. **Dashboard/UI**: Display regime context alongside signals so operator has visibility — but operator cannot override the data collection
5. **Future (Phase 53+)**: Build `setup_performance` segmentation by `(plugin, regime_type, tf)` → drives `perf_multiplier` per regime segment

## Investigation Starting Points

- `services/signal_generator_service.py` — find the regime gate logic, likely in `_apply_regime_filter()` or similar
- `src/intelligence/composites/signal_aggregator.py` or equivalent — check where `regime_eligible` suppression happens
- `src/core/plugin_state_manager.py` was deleted — check if any regime gate moved into service layer
- `signal_ledger.py` — verify `regime_type_at_fire` is in `LedgerEntry.to_insert_params()` (currently at $58 params per CLAUDE.md)

## Notes

- The system IS computing regime correctly (HMM state is flowing) — the error is applying it as a gate rather than a label
- Ranging markets may still produce valid mean-reversion signals — we literally cannot know without data
- This fix unblocks ML scoring (Phase 53+) which requires sufficient labeled signal outcomes per regime segment
