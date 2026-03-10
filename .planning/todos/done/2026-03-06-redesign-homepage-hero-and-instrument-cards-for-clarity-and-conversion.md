---
created: 2026-03-06T22:10:00.000Z
title: Redesign homepage hero and instrument cards for clarity and conversion
area: ui
files:
  - dashboard/src/app/page.tsx
  - dashboard/src/app/landing/page.tsx
  - dashboard/src/components/landing/hero-section.tsx
  - dashboard/src/components/landing/pipeline-animation.tsx
---

## Problem

The homepage wastes a lot of vertical space and doesn't communicate what IndicAgent actually is. Current issues:
- Hero section is vague — doesn't explain the platform's value proposition clearly or compellingly
- Instrument cards are sparse and uninformative — don't convey what data/intelligence is available
- The primary action (getting into a symbol dashboard) is not obvious or compelling enough
- Users arriving at the homepage have no strong reason to click through
- Too much empty space relative to information density

## Solution

- **Hero rewrite:** Clear, punchy headline explaining what IndicAgent does (real-time market intelligence, I1–I8 pipeline, signals). One strong subheadline. Prominent CTA button ("View Live Dashboard" or similar).
- **Reduce wasted space:** Tighten vertical rhythm, remove padding bloat, make the page feel dense and purposeful.
- **Instrument cards uplift:** Show live data inline — current price, active signal count, regime, top setup. Cards should feel like windows into live intelligence, not just nav links.
- **Explain the platform:** Add a concise "What is IndicAgent?" section — 3–4 pillars (real-time indicators, pattern intelligence, signal generation, AI narrative). Brief, scannable, visual if possible.
- **Stronger CTA hierarchy:** Make the path to dashboard views unmistakable — primary button + instrument card click targets both lead directly to the live view.
