---
created: 2026-03-06T22:05:00.000Z
title: Refine AI narrative panel visual design and readability
area: ui
files:
  - dashboard/src/components/narrative-panel.tsx
---

## Problem

The I8 AI narrative panel on the dashboard surfaces LLM-generated analysis but the visual presentation hasn't been refined. The raw narrative text can be dense and hard to scan quickly. There's no visual hierarchy distinguishing key takeaways from supporting detail, and the panel doesn't communicate the narrative source (per-signal vs group synthesis), confidence, or staleness clearly.

## Solution

- Improve typography and layout: structured sections (bias, key levels, setup context) instead of a wall of text
- Surface metadata visually: model used (qwen3.5:9b vs phi4-mini), narrative age/staleness, whether it's per-signal or group synthesis
- Consider highlighting key terms (direction bias, setup type, price levels) inline
- Add visual indicator when narrative is stale (e.g. > 1 TF period old)
- Review whether group narratives (`narratives:group:GROUP_NAME`) should surface differently from per-symbol narratives
