---
status: pending
priority: P1
filed: 2026-09-04
updated: 2026-09-04
source: docs/reference/ refresh pass, batch 4 (plugins/services/README) — surfaced as a side finding, not a documentation issue itself
---

# `indicagent-bar-replay.service`'s `ExecStart` references a module that doesn't exist — `services.bar_replay_provider_agent` should be `services.bar_replay_provider`

## What

`production/systemd/indicagent-bar-replay.service`'s `ExecStart` line is:

```
ExecStart=/home/bg/dev/indicagent/.venv/bin/python -m services.bar_replay_provider_agent
```

`services/bar_replay_provider_agent.py` does not exist anywhere in the repo (confirmed via
`find . -iname "*bar_replay_provider_agent*"`, zero results). The real file is
`services/bar_replay_provider.py`, which has a proper `if __name__ == "__main__":` entrypoint
(`sys.exit(asyncio.run(BarReplayProvider().main()))`) — this is almost certainly a stale
`ExecStart` left behind by an earlier `_agent.py` → bare-filename rename sweep (this project
retired the `_agent` suffix convention for most services; see CLAUDE.md's "Oneshot `_agent.py`
exceptions" note, which lists 4 intentional survivors and `bar_replay_provider_agent` is not
one of them) that missed this one unit file.

## Impact

Currently latent, not active: `systemctl is-enabled`/`is-active indicagent-bar-replay` both
confirm `disabled`/`inactive`. If this unit is ever started (manually or via a future enable),
it will fail immediately with `ModuleNotFoundError: No module named
'services.bar_replay_provider_agent'` — a silent-until-invoked bug, exactly the kind of thing
that wastes an on-call session later if nobody remembers this todo exists.

## Fix

One-line change to `production/systemd/indicagent-bar-replay.service`:

```
ExecStart=/home/bg/dev/indicagent/.venv/bin/python -m services.bar_replay_provider
```

Then `sudo systemctl daemon-reload` to pick up the change. No code change needed — the real
file and its entrypoint are already correct.

## Verification

- `find . -iname "*bar_replay_provider_agent*"` → zero results (confirms the module referenced
  in `ExecStart` doesn't exist).
- `ls services/bar_replay_provider.py` → exists, has `if __name__ == "__main__":` block.
- `systemctl is-enabled indicagent-bar-replay` → `disabled`; `is-active` → `inactive` (confirms
  latent, not an active incident).
