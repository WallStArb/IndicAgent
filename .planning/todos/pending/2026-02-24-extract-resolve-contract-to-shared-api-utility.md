---
created: 2026-02-24T20:52:53.602Z
title: Extract resolve_contract to shared API utility
area: api
files:
  - src/api/routes/features.py:31-41
  - src/api/routes/sse.py
  - src/api/dependencies.py
---

## Problem

`_resolve_contract()` (maps base symbol "ES" → active contract "ESH6") is copy-pasted in both `features.py` and `sse.py`. The comment in `features.py` even says "same as sse.py". Any change to contract resolution logic (e.g. when H6 rolls to M6) must be updated in two places.

## Solution

Move to `src/api/dependencies.py` or a new `src/api/utils.py` as a module-level function. Both routes import it from there. Tiny change, no logic changes needed.
