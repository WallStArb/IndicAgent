---
phase: 187-research-core-recipe-book-selection-construction
plan: 10
status: complete
completed: 2026-10-28
commits: [0db42e443, a0fcd6c60]
requirements: [R-187-13]
---

# 187-10 summary: pod books

- Task 1 (0db42e443): `PodBookSpec` (kind `pod_book`) names two or more member books, each
  pinned by `run_id` and the recorded series' content hash (`pod.series_sha256`); its canonical
  form embeds each member book and so each family, so editing any of them moves the pod hash.
  `pod.pod_series` sums the members' D_s on the sessions every member tested, counts what each
  dropped, and returns no series for disjoint calendars; nothing is filled.
- Task 2 (a0fcd6c60): `run_pod` reads each pin through `PostgresLedger.pinned_run`, refuses
  before the ledger counts anything unless every pin is a completed, powered, E17 book test of
  the member spec's current hash on this vintage with exactly the pinned series, no run is
  pinned twice, the members share at least two sessions and the HAC statistic is defined; then
  it records one `pod_book` attempt with its summed series and headline columns. Real runs a
  spec once; exploration may repeat. `run_spec.py` dispatches it (no synthetic mode);
  `select_books.horizon_sessions` reads a pod's horizon from its member books; glossary `pod book`.

Deviations: the amendment's `informed_by = member run_ids` is not possible (the column is one
uuid meaning the single attempt that prompted this one). Member run_ids and series hashes are in
the spec (so in `spec_hash`) and in `evidence.members`; identity lineage is `concept_parent`.
A fresh Claude reviewer (Codex and AGY were out of quota) found `select_books` crashing on a pod
row, three refusals or terminal-status gaps after `start_runs`, and unchecked statistic and
duplicate pins; all fixed. Verification: full unit suite, the ledger integration test on
`indicagent_test`, repro_frozen bit-identical.

Open: no real pod spec is authored or run (a pre-registration act, and build-first holds).
