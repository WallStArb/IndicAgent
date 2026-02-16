---
name: wire-pipeline
description: Use when connecting a new intelligence plugin to the processing pipeline, SSE stream, and dashboard UI. Triggers include adding a dashboard panel, wiring SSE, or integrating a new tier.
---

# Wire Pipeline — Dashboard & Service Integration

## Overview

Rigid 7-step checklist for wiring a new intelligence tier into the full pipeline: processor service → SSE → dashboard. Every step is required. Skipping a step breaks `next build`.

## Checklist

### 1. Processor Service
Add plugin name to the correct tier list in `services/intelligence_processor_service.py`:
```python
# Line ~68-78 — find the right list
I3_PLUGINS = [...]
SMC_PLUGINS = [...]
I6_PLUGINS = [...]
```

### 2. Dashboard Types
In `dashboard/src/lib/types.ts`:
- Add a new `<Tier>Data` interface with optional fields
- Add field to `SymbolData` interface: `myTier: MyTierData | null`

### 3. SSE Parsing
In `dashboard/src/hooks/use-market-stream.ts`:
- Import new type
- Add to `parseIntelligence()` return type signature
- Parse fields using `f("field_name")` helper (converts string → float)
- Add to return object and destructuring at call site (~line 283)

### 4. Demo Data — ALL 3 SITES
In `dashboard/src/hooks/use-demo-data.ts`, add `myTier: null` at:
- **Site 1** (~line 377): initial `SymbolData` construction
- **Site 2** (~line 430): tick simulation `next[sym]` construction
- **Site 3**: search for all `SymbolData` literal objects — there may be more

**GOTCHA:** Missing any site → `next build` fails with type error.

### 5. Panel Component
Create `dashboard/src/components/<tier>-panel.tsx`:
- Accept `data: MyTierData | null` prop
- Handle null state (collapsed/empty)
- Follow existing pattern from `smart-money-panel.tsx` or `confluence-panel.tsx`

### 6. Main Dashboard
In `dashboard/src/components/trading-dashboard.tsx`:
- Import panel component
- Add inside `SymbolCard` with border wrapper:
```tsx
<div className="border-t border-[var(--border-subtle)]">
  <MyTierPanel myTier={data.myTier} />
</div>
```

### 7. Verify
```bash
cd dashboard && npx next build    # Must pass — catches type mismatches
python -m pytest tests/unit/ -q   # Must pass — catches registration issues
```

## Common Gotchas
- `use-demo-data.ts` has **3 separate** `SymbolData` construction sites — all must match the interface
- `f("field_name")` in `parseIntelligence()` returns 0 for missing fields — use `|| undefined` for optional fields
- `SymbolData` interface must match ALL construction sites or `next build` fails
- SSE field names must match exactly what the processor service publishes to Redis
