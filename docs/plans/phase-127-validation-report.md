# Phase 127 — Validation Report (Plan 02)

**Date:** 2026-06-17
**Corpus:** rebuild via `lifecycle_replay --workers 8` (source of truth per `127-RECONCILIATION.md`)
**Methodology:** measure what is measurable on a no-counterfactual-outcome corpus; name what is not. Do NOT substitute a proxy for signal quality.

---

## Executive summary

The corpus is **structurally clean** (zero orphans, deterministic content-addressed IDs,
distinct rows, full symbol/setup breadth) but carries **one material data-quality gap**:
`signal_events.context_features` and `ctf_score` are **100% NULL**. This is the
headline finding and blocks trusting the corpus for any context-conditional ML until
understood. Two further operational findings (post-commit crash marker; ~42% signals
still `pending`) are recorded below.

---

## 1. Integrity — PASS

| Check | Result |
|-------|--------|
| orphan signal_events (no frame) | **0** |
| orphan trade_frames (no parent event) | **0** |
| future-dated signals | not run (replay is historical by construction) |
| distinct signal_id | 1,036,513 / 1,036,513 (no duplicates) |

Integrity gates pass. Every detection row has ≥1 frame; no dangling frames.

## 2. Deterministic IDs — PASS (resolves replay-architecture uuid4 concern)

| ID | Generator | Empirical proof |
|----|-----------|-----------------|
| `signal_id` | `make_signal_id()` = `sha256(...).hexdigest()[:32]` | UUID version nibble (pos 15) uniform 0-f, ~6.2% each — **not** uuid4 (would be 100% '4') |
| `frame_id` | `uuid5(signal_id:entry_type)` | version nibble 100% '5' |
| `execution_id` | `uuid5(signal_id:'zone'\|'market')` | uuid5 by construction |

No uuid4 `signal_id` generation path exists in `src/` or `production/` (grep-confirmed).
The "random UUID" finding from the 2026-06-11 replay-architecture review is **resolved**;
memory `replay-architecture` updated. The corpus is reproducible.

## 3. Corpus volume

| Table | Rows |
|-------|------|
| signal_events | 1,036,513 |
| trade_frames | 1,036,513 |
| trade_executions | 1,063,798 |
| distinct setups firing | 30 (of 36 `trad_*`) |
| symbols covered | 114 |

Note: 6 of 36 setups emitted **zero** signals. Some may be the legitimate emission-gate
rejections on low-priced/small-tick instruments (SI/NG/HG/CL/FX — checklist finding #8);
others may indicate coverage gaps. Flagged for investigation, not assumed.

## 4. ⚠️ HEADLINE: context_features + ctf_score are 100% NULL

```
total=1,036,513   cold_start(context_features NULL/'{}')=1,036,513 (100%)
ctf_score NULL=1,036,513 (100%)   ctf_confirmed NULL=1,036,513 (100%)
context_features coverage = 0.000%
```

**Every** signal_event is cold-start with no CTF/confluence annotation. This means:
- SC-02 (>99% context_features coverage on non-cold-start) is **vacuous** here — there
  are zero non-cold-start signals to measure.
- The ECL/CTF extrinsic-confidence vectors that the v2.10 architecture treats as
  annotations are entirely absent from this corpus.

This contradicts the rebuild checklist's expectation ("ctf_score NULL should be ~0
except genuinely-pending") and the `warmup-noop-finding` memory's claim that "a single
cold pass produces valid CTF for all non-guarded bars." **One of these is wrong.** Two
candidate root causes to investigate (ordered):
1. The replay signal-emission path does not attach `context_features`/`ctf_score` to
   `signal_events` even when I6 computes them (write-path gap, not compute).
2. Cold-start is genuinely NOT handled in single-pass replay — the `--warmup` no-op
   finding assumed it was, but the data shows otherwise. If so, the warmup removal was
   premature and the cold-start-correction problem is still open.

**Status:** NOT resolved by this report. This is the top follow-up. It determines whether
the corpus is usable for context-conditional ML or needs a re-emission that populates the
ECL fields. (Note: the pre-rebuild baseline in 127-01-SUMMARY showed the same ~100%
cold-start pattern, so this is persistent, not introduced by the rebuild.)

## 5. Lifecycle outcomes — PARTIAL

```
signal_events.status:  expired=604,252   pending=431,442   active=819
trade_executions.exit_reason:
  stop_loss=539,114   ttl_expired_ahead=244,503   ttl_expired_behind=120,722
  target_1=94,321     ttl_expired=65,138
```

- `lifecycle_replay` transitioned ~58% of signals to a terminal state (`expired`).
- **~42% remain `pending`** (431,442) — these correspond to the 431,719 frames with **0
  executions**. Either lifecycle evaluation did not reach them (TTL window closed first,
  or the replay stopped short) or they are legitimately never-activated. Worth confirming
  whether 42% pending is expected.
- `trade_executions.actual_pnl_r` is **989,502 non-null** (93%) — the executed branch IS
  populated by the simulated lifecycle, even though `counterfactual_pnl_r` (the ML target)
  is NULL (v2.11). See Plan 03 for the target-wiring implication.
- The 2-executions-per-frame pattern (459k frames) is **not duplication** — the two rows
  carry complementary `exit_reason`s (e.g. `stop_loss`+`target_1`, `ttl_expired_ahead`+
  `stop_loss`), i.e. the replay models both bracket branches. Intentional, not corruption.

## 6. Operational findings

- **`logs/REBUILD_STATUS = FAILED` is misleading.** The traceback shows Stage 2
  ("1036513 total signals inserted") completed and committed, then crashed in the
  *post-insert* `_assert_backfill_integrity` on a transient DB connection drop
  (`server closed the connection unexpectedly`). Data is intact (verified independently:
  0 orphans). The marker reflects a post-commit assertion crash, not data loss. Recommend
  the rebuild script set REBUILD_STATUS only after a successful integrity assert, or clear
  it on commit.
- **201,149 plugin errors across 14 plugins** on rolled-month contracts (NQU6/YMM6/RTYM6
  et al.) — non-fatal (per-plugin try/except; signals still produced). Checklist finding
  #1; needs root-causing (asset_class=None? schema mismatch on U6/M6 variants?).
- **`setup_performance` is empty (0 rows)** — wiped, not refreshed (no retrain this phase).
  Consistent with Plan 03 (SC-05 deferred). Do not mistake a future timestamp for Phase
  127 calibration.

## 7. What could NOT be measured (named, not faked)

- **Signal quality / edge / calibration correlation** — no `counterfactual_pnl_r` outcome
  this phase (v2.11 dependency; see Plan 03). Any "fire-rate %" substituted for edge would
  be a proxy-as-target error.
- **context-conditional ML readiness** — blocked by finding #4 until context_features/
  ctf_score are understood.

---

## RCA Part VI — measured values

| Metric | Value | Notes |
|--------|-------|-------|
| signal_events | 1,036,513 | integrity-clean |
| trade_frames | 1,036,513 | 0 orphans |
| trade_executions | 1,063,798 | 2/frame bracket; 93% have actual_pnl_r |
| orphan rows | 0 / 0 | both directions |
| signal_id determinism | sha256 (verified) | uuid4 concern resolved |
| context_features coverage | 0.000% | **100% cold-start — finding #4** |
| ctf_score non-null | 0 | **100% NULL — finding #4** |
| counterfactual_pnl_r non-null | 0 | by design (v2.11) |
| actual_pnl_r non-null | 989,502 | lifecycle-executed branch |
| signals terminal (`expired`) | 604,252 (58%) | 431,442 still `pending` |
| distinct setups firing | 30 / 36 | 6 setups emitted zero |
| setup_performance rows | 0 | wiped, not refreshed |

**Acknowledgement:** Phase 127 produced a structurally clean, reproducible corpus, but
cannot validate context-conditional signal quality because (a) the counterfactual outcome
is absent by design (v2.11) and (b) the corpus's signal_events lack context_features/ctf
entirely (finding #4). The first is a planned deferral; the second is an open
data-quality question that must be resolved before ML materialization.

---

## Recommended follow-ups (priority order)

1. **Finding #4 — root-cause the 100% NULL context_features/ctf_score.** Write-path gap
   vs cold-start-not-handled. Determines corpus usability. This is the v2.10-critical item.
2. **Confirm ~42% `pending` is expected** (lifecycle replay coverage) or a short-run.
3. **Plugin errors on rolled-month contracts** (finding #1) — root-cause asset_class/
   schema mismatch.
4. **6 zero-emission setups** — emission-gate coverage gaps vs legitimate rejection.
5. **REBUILD_STATUS marker semantics** — set after successful assert, not on crash.
6. Restore services only after #1 is understood (the corpus currently lacks the context
   fields live writers would consume).

## Self-check
- Integrity + determinism: measured and PASS.
- context_features/ctf NULL: measured and SURFACED (not papered over).
- Signal quality: correctly NOT measured (no outcome target); named as deferred to v2.11.
- No proxy substituted for an unmeasurable quantity.

---

## Addendum — Corpus Rerun Audit (2026-06-17)

A second lifecycle_replay ran the same day (signals created 09:00-12:00 UTC, confirmed via
`created_at` distribution). This replaced the 1,036,513-signal corpus. The new corpus
resolves the headline finding (#4) but introduces a volume change that requires recording.

### Corpus comparison

| Metric | Original corpus | Rerun corpus |
|--------|----------------|--------------|
| `signal_events` | 1,036,513 | **537,171** |
| `trade_frames` | 1,036,513 | **537,171** |
| `trade_executions` | 1,063,798 | **775,204** |
| orphan signal_events | 0 | **0** |
| orphan trade_frames | 0 | **0** |
| `context_features` coverage | 0.000% | **100%** |
| `ctf_score` non-null | 0 | **518,464 (96.5%)** |
| signals `expired` | 604,252 (58%) | **531,350 (99.0%)** |
| signals `pending` | 431,442 (42%) | **5,750 (1.1%)** |
| distinct setups firing | 30 / 36 | **30 / 36** |
| symbols covered | 114 | **106** |

Finding #4 (100% NULL context_features) is **resolved** in the rerun corpus. The 42%
pending backlog is also resolved (1.1% pending = tail of today's date range, expected).

### Plugin coverage — 6 silent TIER_I7 plugins

Same 30 of 36 plugins emit signals. The 6 with zero emissions:

| Plugin | Cause |
|--------|-------|
| `trad_POCRejection` | Known crash: `float(NoneType)` in `trade_framer.py:343` (todo filed 2026-06-17) |
| `trad_HVNRejection` | Same crash as POCRejection |
| `trad_MTFAlignment` | Multi-timeframe alignment data dependency |
| `trad_PrevDayLevelTest` | Prior-day level data absent on cold-start bars |
| `trad_AnchoredVWAPReversion` | Anchor event dependency |
| `trad_CrossAssetDivergence` | Cross-asset context data dependency |

POC/HVN are fixable crashes (one-line None guard in `_get_htf_vp()`). The other four are
structural/data-availability constraints, not bugs.

### Symbol coverage gaps

**10 OHLCV symbols with 0 signals:** EURUSD, EWZ, FXI, GDXJ, ITB, USO, VLUE, VXK6, VXM6,
ZNM6. These appear to be recently-added instruments not included in the rerun's replay scope.

**19 symbols in signal_events absent from OHLCV:** All expired/rolled futures (ESU6, ESZ6,
NQU6/Z6, RTYU6/Z6, YMU6/Z6, ZBU6/Z6, ZCU6, ZFU6/Z6, ZSU6, ZTU6/Z6, ZWU6). Expected --
OHLCV for expired months pruned after roll.

### Open items (rerun-specific)

1. **POC/HVN crash fix** (`trade_framer.py:343` None guard) + targeted re-replay with
   `--setups trad_POCRejection,trad_HVNRejection`. Bug todo: `.planning/todos/pending/2026-06-17-poc-hvn-rejection-float-nonetype.md`.
2. **Volume drop explanation** (1,036,513 → 537,171) -- rerun parameters not recorded;
   likely narrower date window or symbol scope. Investigate before next corpus decision.
3. **`setup_performance`** -- still empty; requires 30+ signals per setup post-CounterfactualTracker (v2.11).
4. **`counterfactual_pnl_r`** -- 0 non-null; v2.11 dependency unchanged.
