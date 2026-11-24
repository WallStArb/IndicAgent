

## Unified design note

Unified design (2026-09-26): regimes are disclosure and continuous state variables, never gating (section 5.2), and the per-symbol HMM runs walk-forward only once todo 248 deploys in phase 186. Recheck this todo's remaining P0-P3 scope when phase 186 is planned; P4a/P4b stay gated.

## Status 2026-11-24 (todo consolidation pass)

Gate reworded: its trigger (recheck when phase 186 is planned) is past. 248 is completed and `regime_writer.py` is deleted (10e269b5d); the HMM is `src/intelligence/features/kernels/_hmm.py`, inside the rebuild closure. Deferred until after the corpus rerun, and only if a counted family reads HMM state; re-audit against `_hmm.py`. Every edit moves `rebuild_code_key`.
