---
phase: 126-signal-universe-hardening
plan: "07"
status: complete
completed_at: "2026-06-15"
---

# 126-07 Summary: REQUIREMENTS.md Gap Closure

## What Was Done

Closed all 3 staleness gaps identified in Phase 126 VERIFICATION.md. No code changes — documentation fixes only.

**SIGNAL-QUALITY-01** — Corrected gate location, APR key names, threshold values, and deferral note:
- Gate: `frame_trade()` using `_reject_frame("zone_too_narrow:{zone_source}", ...)` (not `_resolve_zone_bounds()` / `no_signal()`)
- APR keys: `.equity`/`.fx`/`.futures` = 1.5/1.0/1.5 (not equity_etf/forex with 0.5/0.25/0.35)
- stopped_at_entry rate measurement deferred to Phase 127 (REPLAY-01)
- Marked `[x]`

**SIGNAL-QUALITY-02** — Corrected frozenset name, annotation architecture, schema version:
- Frozenset: `_I7_I6_EXEMPT` (not `_CONFLUENCE_EXEMPT_PLUGINS`)
- Annotation: `signal_processor._annotate_signal()` pipeline layer (not per-plugin `requires_i6_confluence=True` / `capture_signal_features()`)
- `capture_signal_features()` deprecated (deletion Phase 128)
- `SIGNAL_SCHEMA_VERSION` v4 noted
- Marked `[x]`

**Traceability table** — both rows updated Pending → Complete.

## Artifacts Modified

- `.planning/REQUIREMENTS.md` — SIGNAL-QUALITY-01/02 text corrected, both marked Complete, last-updated 2026-06-15
