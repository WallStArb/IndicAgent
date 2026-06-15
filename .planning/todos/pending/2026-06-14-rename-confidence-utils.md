# TODO: Rename confidence_utils.py to confidence.py
Created: 2026-06-14
Phase: Capture from Phase 125 D-05
Status: pending

## What
`confidence_utils.py` uses the retired word "Utils" (naming system §3 retired words list).
Correct name: `src/intelligence/trading/confidence.py`

## Why deferred
39 import sites across the codebase. Requires grep-and-replace across all callers.
Out of scope for Phase 125 (which adds _validate_weights_sum to the file).

## How to do it
1. git mv src/intelligence/trading/confidence_utils.py src/intelligence/trading/confidence.py
2. grep -r "confidence_utils" src/ tests/ services/ to find all import sites
3. Update all imports in one commit
4. Update CLAUDE.md reference to the file
