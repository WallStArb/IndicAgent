# Signal Banner Redesign

**Date:** 2026-03-12
**Status:** Approved

## Problem

1. `OutcomeBadge` renders at `text-xs px-2 py-1` — full-size relative to the banner's `text-[0.45rem]` micro-typography. Badge is visually oversized in resolved state.
2. Signal banner layout is a single dense row of tokens with no clear reading hierarchy. Key trade info (entry, SL, T1, R-multiple) is buried among timing metadata.

## Changes

### 1. OutcomeBadge — `small` prop

Add `small?: boolean` to `OutcomeBadgeProps`. When true, apply `text-[0.45rem] px-1 py-0.5 rounded-sm` instead of `text-xs px-2 py-1 rounded`.

`signal-banner.tsx` passes `small`. `drill-panel.tsx` and any other consumer keep default (large) size.

### 2. SignalBanner — two-line layout

Replace the current single-row layout with a two-line structure inside the existing `<button>`:

**Line 1** (primary, `text-[0.55rem]`):
```
[OutcomeBadge small?] [Icon] SHORT @ 6707.75 (85% FVG Fill) | SL: 6718.30 | T1: 6681.63 (2.5R)  [ChevronRight]
```
- Direction icon (size=10) in direction color
- "SHORT" / "LONG" label in direction color, bold uppercase, tracking-widest
- `@ {entry_price}` in direction color
- `({confidence}% {signalType})` in muted color — `signalType` = title-case of `signal_type` e.g. `fvg_fill` → `FVG Fill`
- `| SL: {stop_loss}` in muted color
- `| T1: {profit_target} ({rr_t1}R)` in muted color — omitted if `profit_target` is null. If `profit_target` is present but `rr_t1` is absent, render `| T1: {profit_target}` without the R-multiple parenthetical.
- ChevronRight (size=8, ml-auto)

**Line 2** (secondary, `text-[0.45rem]`, fully muted, `opacity-70`):
```
Zone: 6775.25–6776.00 | Sig: 11:50:05 (+5.3s)
```
- `Zone: {low}–{high}` if `entry_zone_low` and `entry_zone_high` present
- `| Sig: {signalTimeStr} ({ttsStr})` — time from `signal_computed_at`, lag from existing `ttsStr` logic. If `signal_computed_at` is present but `ttsS` resolves to null (e.g. `barCloseIso` unavailable), render `Sig: {signalTimeStr}` without the parenthetical.
- Row omitted entirely if neither zone nor signal time is available

**Resolved state**: `OutcomeBadge small` renders left of the direction icon. `opacity-50` wrapper unchanged.

### Signal type formatting

```ts
function fmtSignalType(raw: string): string {
  return raw.replace(/_/g, " ").replace(/\b\w/g, c => c.toUpperCase());
}
```

Defined locally in `signal-banner.tsx`.

## Files Changed

- `dashboard/src/components/signal-panel.tsx` — add `small` prop to `OutcomeBadge`. Note: `SignalPanel` was orphaned in a prior phase; this file is now effectively an `OutcomeBadge` module.
- `dashboard/src/components/signal-banner.tsx` — two-line layout + `fmtSignalType` + `small` badge

## Out of Scope

- NarrativeElevated quality improvements (separate concern — LLM prompt tuning)
- Adding symbol to banner (omitted, implied by card context)
- T2/T3 targets (T1 + R-multiple is sufficient for the primary banner)
