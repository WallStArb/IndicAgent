# Remove dead `--warmup` flag from run_historical_pipeline.py

**Status:** pending (code cleanup, non-blocking)
**Created:** 2026-06-16
**Trigger:** Anytime after the 2026-06-16 8-worker rebuild completes (or in a fresh context)

## Finding
The `--warmup` double-pass (added Phase 124-01, commit 651cc5ef) is a **provable no-op** for its stated purpose ("populates the per-symbol I6 cache so no cold-start NULL values remain for the signal pass"):

- `plugin_states` and `intelligence_cache` are **local variables** inside `replay_symbol()` (lines 1618, 1622), re-initialized on every call.
- Pass 1 (skip_signals=True) builds these caches, but they are discarded when Pass 1 returns.
- Pass 2 (skip_signals=False) starts with fresh empty caches — identical cold-start progression to a single pass.
- Therefore Pass 2 gets **zero benefit** from Pass 1. The warmup just writes the same features twice and forces `--workers 1`.

Cold-start within a single pass is already correctly handled by:
1. The chronological event merge (lower TFs sort before higher TFs at equal timestamp — line 1642-1647), so higher-TF bars always have lower-TF intelligence context.
2. The `min_bars_for_tf()` warmup guard (line 1667) skips genuinely cold early bars.

## Confirmed safe
- No external consumers of `--warmup` / `do_warmup` (grep across production/scripts, services/, src/ — only run_historical_pipeline.py references it).
- The 2026-06-16 rebuild was relaunched at `--workers 8` WITHOUT `--warmup`; single-pass parallel mode emits signals with valid CTF immediately (verified: I7 framing warnings appear in log within seconds).

## Removal plan
1. Delete the `--warmup` argparse argument (line ~2029) and its `--replay-only` validation (line ~2041).
2. Delete the two-pass warmup loop in the `workers == 1` branch (line ~2440-2477) — single-worker path becomes a plain single pass.
3. Delete the "parallel mode skips warmup" NOTE (line ~2485).
4. Sweep: `grep -rn "warmup\|--warmup" tests/ docs/ production/` for dangling references; update docs.
5. Run done-coding SOP (simplify → review → pytest tests/unit/ → commit).

## Why this matters (no technical debt)
Renaissance principle: ruthlessly eliminate complexity. A no-op flag that forces single-threading and doubles compute is exactly the kind of dead complexity to remove. Keeping it risks a future operator re-discovering `--warmup`, thinking it provides correctness, and running a multi-day single-worker rebuild for nothing (which is what happened 2026-06-16).
