# Owner action sheet

**Status:** open items only, 2026-11-25. Each item is the owner's to run or decide; strike it here when done and record the outcome in the todo or ledger entry it names. The Massive dates live in `docs/plans/2026-11-15-massive-plan-lapse-deadlines.md` and are not repeated; this sheet adds the commands and the other owner items. Decisions waiting on the owner stay listed in `.planning/STATE.md`.
**Author:** Claude (indicagent-3c) on the lead's brief; recommendations marked "lead" are the lead's, the rest are drafted for the lead to confirm.

| # | Item | Deadline | Kind |
|---|---|---|---|
| 1 | Install the split feed auditor timer (todo 649) | before the Massive lapse, about 2026-12-10 | sudo steps |
| 2 | Renew or lapse the Massive plan (todo 600) | 2026-12-10, final capture about 2026-12-07 | spend decision |
| 3 | Alert credentials for the DIMM alerts | before the next heavy run you leave unattended | credentials |
| 4 | Cooling and the move from 4 to 8 workers | none; gates the worker count | hardware |
| 5 | Ledger 2026-11-23b veto, todos 547 and 586 | none; blocks nothing running | rulings |

## 1. Split feed auditor timer (todo 649)

Why: after the plan lapses, `massive_reference` stops supplying split rows for active names (about 3 a month), so the nightly restatement flag and a human would be the only alarm. The auditor reads the Alpaca corporate-actions feed daily, compares it with `corporate_action_current`, and writes candidate row files to `logs/split_candidates/`. It never writes `corporate_action`; apply and review stay manual.

State checked 2026-11-25: unit and timer are in `production/systemd/`, not installed (`systemctl is-enabled indicagent-split-feed-auditor.timer` reports not-found); its five `infra.split_feed_auditor.*` keys are live in `config_state` (migration 612).

```bash
cd /home/bg/dev/indicagent
sudo cp production/systemd/indicagent-split-feed-auditor.service production/systemd/indicagent-split-feed-auditor.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now indicagent-split-feed-auditor.timer
sudo systemctl start indicagent-split-feed-auditor.service   # one run now, do not wait for 07:45 UTC
```

Verify: `systemctl list-timers --all | grep split-feed` shows the next 07:45 UTC; `systemctl status indicagent-split-feed-auditor.service` reads `status=0/SUCCESS`; `tail logs/split_feed_auditor.log` shows the run; a flagged split leaves a CSV in `logs/split_candidates/`. Tell the lead when the first scheduled run is clean, which closes todo 649. Rollback: `sudo systemctl disable --now indicagent-split-feed-auditor.timer`.

Recommendation: install now. It is read-only against the database and the only cost is one API call a day.

## 2. Massive plan (todo 600)

Decide renew or lapse by 2026-12-10; read the exact lapse date off the Massive account page and tell the lead so the doc's "about" can be replaced. The lead runs the final capture and verification about 2026-12-07 (commands: deadlines doc, item 9; the capture is a lead job, not yours). Also decide whether to keep or drop the HX370 copy of the archive (STATE).

Verify: the lead records the lapse date, the final manifest key count and the two `--verify` exit codes in todo 600.

Lead recommendation: lapse after the capture is done and verified. Everything the research path reads is on disk twice and ETag-verifiable, the forward tail is Alpaca (median volume ratio to Massive 0.99993 over 2026), and renewal buys a second witness, not a data need. Renew only if one more month is trivially cheap and a named consumer needs data after 2026-12-10. The price is not in the repo, so you supply it.

## 3. Alert credentials

State: Alertmanager's only receiver is a no-op (`production/alertmanager.yml`, since 2026-08-15), so every alert, including the loaded DIMM rules (`DimmTemperatureHigh` above 90 C for 2 minutes, `DimmTemperatureCritical` above 100 C for 1 minute, `DimmSensorMissing`), fires in Prometheus and reaches nobody. DiskSpaceCritical was lost this way on 2026-08-13.

Steps (the file's own comment has them): create a Telegram bot with @BotFather, send it a message, read the integer `chat_id` from `https://api.telegram.org/bot<token>/getUpdates`, then restore the `telegram_configs` block in `production/alertmanager.yml` with those values. Give the lead the token and chat id through the channel you trust, or put the token in a file the config reads with `bot_token_file`; do not commit either, and note that `production/` has no ignore rule for a token file, so name it in `.gitignore` in the same commit. Then `cd production && docker compose up -d alertmanager`.

Verify: `docker logs indicagent-alertmanager` shows no config error (a zero `chat_id` crash-loops it). Send one test alert and confirm the message arrives: `curl -XPOST -H 'Content-Type: application/json' http://localhost:9093/api/v2/alerts -d '[{"labels":{"alertname":"OwnerTest","severity":"warning"}}]'`.

Recommendation: do this before the next unattended heavy run. The software cap and the 60 C start gate cannot page you.

## 4. Cooling

State: on 2026-11-23 a 16-worker run took the DIMMs to 114 to 118 C against a critical 85 C and corrupted memory (ledger 2026-11-24b; `docs/operations/operations-infrastructure.md`, host thermal cap). Software is in place: boost off, `balance_performance` (`indicagent-host-thermal-cap.service`), a 20-second DIMM watchdog, a 60 C start gate (`GATE_C` in `scripts/ops/guarded_run_common.sh`) and 4 workers. The last sample in `logs/family10_dimm_temp.log` (2026-11-25 12:47Z, a live run) read 44 C.

Order of work (lead): clean the unit and the fan path; add airflow over the SODIMMs; then lower the BIOS power limit; then repaste the CPU. Change one thing at a time so a reading can be attributed. Keep the software cap, the 4 workers and the 60 C gate through all of it.

Verify: run a counted or battery job at 4 workers and read `max_c` in `logs/family10_dimm_temp.log` for its whole duration. Only when both DIMM sensors stay under 85 C for a full run is the move to 8 workers allowed (`WORKERS=8`, the launcher default is 4). Never 16.

Recommendation: no deadline, but until a run holds under 85 C the throughput stays at 4 workers.

## 5. Rulings

Ledger 2026-11-23b (veto reserved, nothing for you to do unless you object): the phrase "reversal_21 pooled replication" is retired because no document defined it. R-1 is a non-gating, non-independent sub-period disclosure (read once, ledger 2026-11-23c, no look charged). R-2 is the one confirmation on the book's own unsearched forward span from 2025-12-24 after a book containing `reversal_21` is frozen; none exists yet. R-3 (a disjoint-name panel) is rejected for now. Veto means telling the lead which of R-1 and R-2 you reject. Recommendation: no veto; it is the honest accounting of what was counted.

Todo 547 (S1 drift on the momentum members): the standing PM ruling of 2026-10-31 is option (b), hold the whole family until the rebuilt S1 vintage and a fresh preregistration; you retain a veto. The open call in STATE is whether instead to certify the reversal members and book now and hold `reversal_5_skip1` and the two momentum members. The horizon-tied lag fix moves to todo 669 with 586, one statistic change and one rebind. Recommendation: keep (b); a book certified on a drifted target risks a false verdict in the ledger, and the family waits on 669 anyway.

Todo 586 (persistent battery cells): not a separate owner ruling. Its ten failing gating cells close when 669's statistic fix passes them. The branch `wip/586-persistence-statistic` is an unpushed older attempt; recommendation: leave it unlanded, and after 669 lands archive-tag it and delete it, as was done for the 674 option-c branch.
