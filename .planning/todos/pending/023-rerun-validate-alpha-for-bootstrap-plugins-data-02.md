---
created: 2026-03-22T19:00:00.000Z
title: Re-run validate_alpha.py for DerivOsc and AC Osc (DATA-02)
area: data-quality
files:
  - production/scripts/validate_alpha.py
  - src/intelligence/patterns/
---

## Problem

DATA-02 (v2.0 REQUIREMENTS) was deferred: `validate_alpha.py --promote` could not be re-run for bootstrap-promoted plugins DerivOsc and AC Osc because N < 30 resolved outcomes exist. These plugins were promoted via bootstrap policy at launch and need statistical validation once data accumulates.

## Solution

Wait until N ≥ 30 resolved signal outcomes for `DerivOsc` and `ACOsc` plugins, then:

```bash
.venv/bin/python production/scripts/validate_alpha.py --plugin DerivativeOscillatorPlugin
.venv/bin/python production/scripts/validate_alpha.py --plugin ACOscillatorPlugin
```

Gate: Pearson r > 0, p < 0.05, N ≥ 30 per (plugin, tf, regime_type) slice.

If gate fails → demote plugin from live to shadow mode (add `IS_SHADOW=True`).

## Context

- Tracked as v2.0 audit gap (data accumulation gate, not a code gap)
- Check `signal_ledger` resolved count: `SELECT plugin_name, count(*) FROM signal_ledger WHERE plugin_name IN ('trad_DerivativeOscillator','trad_ACOscillator') AND outcome IS NOT NULL GROUP BY plugin_name;`
