# BIOS iGPU memory reservation is eating ~8-10GB of RAM

**Found:** 2026-07-01, while investigating why `regime_writer` runs at 6 workers instead of 12.

32GB DDR5 physically installed (confirmed 2x16GB SODIMM via `dmidecode -t memory`), but
`free -h` only reports 22GB total to the OS. The gap is consistent with a BIOS-level iGPU
memory carve-out (invisible to Linux — reserved before boot, doesn't show in `free`,
`docker stats`, or any process listing).

This server runs headless (no iGPU workload — Ollama uses ROCm/discrete path, not the iGPU).
The 2026-06-27 throttle of `infra.regime_writer.workers` from 12 → 6 (config_history reason:
"OOM kill at 12 workers... exhausting 22GB RAM on this host") was tuned against an artificially
low ceiling.

**Action:** Reboot into BIOS, disable/minimize iGPU memory reservation (set to e.g. 512MB-1GB
if it can't be fully disabled), confirm `free -h` reports closer to 32GB. Then reconsider bumping
`infra.regime_writer.workers` back toward 12 with real headroom.

**Blocked on:** physical/IPMI reboot access — cannot be done via Claude Code remotely.

---

**Resolved 2026-07-01.** User applied the BIOS fix. `free -h` now reports 29GB total (up from
22GB) — carve-out shrank substantially though not fully eliminated (~3GB still unaccounted for
against the 32GB physically installed; not worth chasing further, headroom is now sufficient).

`infra.regime_writer.workers` was already back at 12 in `config_state` by the time this was
verified (bumped during today's corpus-rebuild debugging, before this BIOS fix landed) — the
final successful regime_writer run today (2026-07-01, completed 11:52 EDT, 4,571,051 rows
updated, zero failed cells) already validated 12 workers on the recovered memory. No further
config change needed.
