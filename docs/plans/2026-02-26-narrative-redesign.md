# AI Narrative Service Redesign

Date: 2026-02-26
Status: Approved — ready for implementation

## Problem

`ai_narrative_service` was saturating the server by calling `qwen3:8b` (~90s/call) for every signal on 23 contracts × 4 timeframes. With 92 streams and no filtering, Ollama ran at 550%+ CPU continuously, making the server laggy. The service also had a SIGTERM bug (120s Ollama timeout > 90s systemd stop timeout) causing a SIGKILL → Restart=always loop.

## Design

### Two narrative modes in one service

**Mode 1: Per-signal narrative** (`qwen3:8b`, rare/high quality)
- Trigger: signal arrives with `confidence > 0.7` AND `timeframe ∈ {5m, 15m, 1h}`
- Skip: 1m entirely, low-confidence signals
- Output: existing `narratives:SYMBOL:TF` stream + `narrative:SYMBOL:TF:latest` hash
- Volume: occasional — only exceptional setups

**Mode 2: Group synthesis** (`phi4-mini:3.8b`, change-driven)
- 6 asset groups:
  - `equity`: ES, NQ, RTY, YM
  - `energy`: CL, BZ, NG
  - `metals`: GC, SI, HG, PL
  - `rates`: ZN, ZF, ZB, ZT, SR1
  - `fx_crypto`: 6E, 6J, BTC
  - `ag`: ZS, ZC, ZW
- Trigger: any group member's signal changes direction OR regime vs last synthesis (state stored in Redis hash `narrative:group:GROUP_NAME:state`)
- Prompt: all current signals for all group members across all TFs in one call — gives LLM cross-asset context
- Output: new `narratives:group:GROUP_NAME` stream + `narrative:group:GROUP_NAME:latest` hash
- Volume: ~low — only fires on material market changes

### Dashboard
- Existing narrative panel: shows group synthesis for the selected symbol's group by default
- Override: shows per-signal narrative when one exists for selected symbol+TF
- No new panel needed

### SIGTERM fix
- Reduce Ollama timeout from 120s → 60s (phi4-mini needs ~15s, qwen3:8b ~60s on CPU)
- Add `TimeoutStopSec=75` to systemd unit
- Fix signal handler to cancel asyncio tasks via `loop.call_soon_threadsafe`

## Implementation Scope

### Backend: `services/ai_narrative_service.py`
1. Add `ASSET_GROUPS` dict and `SYMBOL_TO_GROUP` lookup
2. Per-signal loop: add confidence + TF filter before calling Ollama
3. Group synthesis loop: maintain state hash in Redis, detect changes, build multi-symbol prompt, call phi4-mini
4. Config: add `group_model: "phi4-mini:3.8b"`, reduce `timeout_sec: 60`
5. Fix SIGTERM: cancel tasks in signal handler

### Backend: systemd unit
- Add `TimeoutStopSec=75`

### Backend: stream keys
- Add `narratives_group(env_prefix, group_name)` to `src/core/stream_keys.py`

### Frontend: `dashboard/src/`
- `use-market-stream.ts`: consume `narratives:group:GROUP_NAME:latest` hash, add `groupNarrative` to state
- `narrative-panel.tsx`: show `groupNarrative` as default, override with `narrative` when present for active symbol+TF

## Success Criteria
- Ollama CPU idle except when synthesis/signal fires
- Server load average < 2 at rest
- Group narrative updates within 30s of a material signal change
- Per-signal narrative only fires on confidence > 0.7, TF ≥ 5m
- Service stops cleanly in < 70s (no SIGKILL)
