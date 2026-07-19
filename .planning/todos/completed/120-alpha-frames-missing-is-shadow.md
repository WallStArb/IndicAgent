---
status: completed
priority: P2
filed: 2026-07-14
closed: 2026-07-19
source: found while finishing todo 011 (alpha_events.is_shadow wiring) during a
  corpus-rebuild idle window
---

## Resolution

Migration 236: `ALTER TABLE alpha_frames ADD COLUMN is_shadow BOOLEAN NOT NULL DEFAULT
TRUE`. No backfill needed -- `alpha_frames` had 0 rows at migration time (truncated ahead
of the in-flight 143.1-07 corpus rebuild; `AlphaFrameWriter` runs downstream of
`alpha_publisher`, which hasn't run yet this rebuild cycle). Updated
`AlphaFrameWriter._PENDING_SQL`/`_INSERT_SQL` to select and write `ae.is_shadow` from the
joined `alpha_events` row at frame-creation time, not re-read from the
`alpha.publisher.is_shadow` APR flag later (a frame's shadow status must not drift if the
flag changes after the frame is written). Applied to the live DB. Regression test added to
`tests/unit/test_alpha_frame_writer.py`.

# `alpha_frames` has no `is_shadow` column — the actual Phase 144 promotion-gate
# measurement surface can't distinguish shadow vs. live once promotion happens

Todo 011 added `alpha_events.is_shadow` (migration 231) and wired `alpha_publisher.py`
to stamp it from the `alpha.publisher.is_shadow` APR flag — done 2026-07-14. Todo
011's own "Promotion Gate" section, written 2026-06-28 before Phase 142B existed,
describes the gate criteria as running "on `trade_frames` WHERE `is_shadow` = TRUE" —
`trade_frames` is the archived v2.x SLA table name; the real measurement surface today
is `alpha_frames` (Phase 142B, `AlphaFrameWriter`/`CounterfactualTracker`).

`alpha_frames` has no `is_shadow` column. `AlphaFrameWriter._PENDING_SQL` reads every
`alpha_events` row regardless of shadow status and writes one frame per row — correct
today (100% of `alpha_events` is shadow, nothing to distinguish), but once an operator
flips `alpha.publisher.is_shadow` to `false` at Phase 144 promotion, `alpha_frames` will
silently mix pre-promotion shadow frames and post-promotion live frames in the same
table with no column to separate them. Any future query computing "shadow-record
performance" (todo 011's own promotion-gate math: mean/Sharpe/drawdown of
`counterfactual_pnl_r`) or "live performance" against `alpha_frames` would need this
distinction and currently can't get it.

**What to do:** add `alpha_frames.is_shadow` (propagated from the joined `alpha_events`
row at write time, not re-read from APR — a frame's shadow status is fixed at the
moment its parent event was emitted, it must not drift if the APR flag changes later).
Touches: a new migration, `AlphaFrameWriter._PENDING_SQL`'s SELECT + INSERT column list,
and probably a backfill of the column for the existing `alpha_frames` rows (join back to
`alpha_events.is_shadow` by `event_id`+`bar_ts`, all of which are currently `TRUE`
anyway). Not urgent — no live promotion has happened, so every row today is
unambiguously shadow — but should land before Phase 144's promotion gate is ever
exercised, or the gate math has no way to isolate the pre-promotion shadow window from
whatever comes after.
