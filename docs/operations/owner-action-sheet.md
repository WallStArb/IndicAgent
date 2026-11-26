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
| 6 | Open owner questions in one list (addendum 2026-11-25) | none; items 6.1 and 6.4 gate promotion and the sweep | rulings |
| 7 | Run the two auditor timers as bg (todo 479) | before the next 06:00 UTC timer run | sudo steps |
| 8 | Todo 383 upstream feedback and todo 509 `shadow_registry` | none | rulings |

## 1. Split feed auditor timer (todo 649)

Why: after the plan lapses, `massive_reference` stops supplying split rows for active names (about 3 a month), so the nightly restatement flag and a human would be the only alarm. The auditor reads the Alpaca corporate-actions feed daily, compares it with `corporate_action_current`, and writes candidate row files to `logs/split_candidates/`. It never writes `corporate_action`; apply and review stay manual.

Done 2026-11-26 (lead, with the owner's standing sudo permission): unit and timer installed and enabled (next fire 07:45 UTC daily), one run made now: exit 0, 74 feed splits, 2 recorded, 72 inactive ignored, 0 candidates, 0 unseen, 0 overdue. Nothing further here; the commands below are kept for a reinstall.

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

Decided 2026-11-26: lapse, and the HX370 copy is dropped. Still open for you: read the exact lapse date off the Massive account page; read the exact lapse date off the Massive account page and tell the lead so the doc's "about" can be replaced. The lead runs the final capture and verification about 2026-12-07 (commands: deadlines doc, item 9; the capture is a lead job, not yours). Also decide whether to keep or drop the HX370 copy of the archive (STATE).

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

## 6. Open owner questions in one list (addendum 2026-11-25)

Each row is a decision or veto that stays with the owner; the recommendation is the lead's (indicagent-46) as stated in the cited record, and a veto means telling the lead. Nothing here blocks a running job.

| # | Question | Lead recommendation | Evidence |
|---|---|---|---|
| 6.1 | Todo 547: certify the reversal members and book now, or hold the S1-dependent set. The S1 drift reaches family 10 as well as the daily residual family: both read S1 vintage_1 (`factor_spec: vintage_1` in `research/specs/family10_volume_shock_h5.yaml`), so the choice covers both. | Hold both until the rebuilt S1 vintage and a fresh preregistration (option b, the 2026-10-31 PM decision recorded in todo 547). Nothing is certified or promoted meanwhile. | `.planning/todos/pending/547-*`; ledger 2026-11-25b (StepM read: `reversal_21` adjusted p 0.0150 and 0.0050, `volume_shock_1_50` primary 0.0325); `docs/research/draft-ledger-2026-11-25d-lane-g-cuts.md` (both cuts) |
| 6.2 | Todo 586: persistent-predictor battery cells. | No ruling needed: it closes when todo 669's statistic fix passes the ten cells; leave `wip/586-persistence-statistic` unlanded and archive it after 669. | `.planning/todos/pending/586-*`; item 5 above |
| 6.3 | Ledger 2026-11-23b: R-1 (non-gating sub-period disclosure) and R-2 (single forward confirmation from 2025-12-24 after a book is frozen), the retired phrase "pooled replication", R-3 rejected. | No veto. The R-1 reads are in (ledger 2026-11-23c for `reversal_21`; `volume_shock_1_50` in ledger 2026-11-25f and 2026-11-25g: primary last sub-period mean about zero, core last sub-period negative). | ledger 2026-11-23b, 2026-11-23c, 2026-11-25f |
| 6.4 | Draft 2026-11-25c: the IC sweep recorder leaves regime-origin columns out of the sweep (regime columns stay testable through S0 with the batch check). The lead writes the ledger entry only after you confirm it in the lead's session. | Confirm: a sweep cannot check batch provenance, so a lookahead-labelled regime column could enter undetected; no threshold, spec or counted look changes. | `docs/research/draft-ledger-2026-11-25c-sweep-regime-columns.md` |
| 6.5 | Ledger 2026-11-25e: `session_coverage` is judged up to the last delivered 1d session, not the last completed one (todo 675; veto window open). | No veto: it removes a wall-clock dependence from the data gate (pilot run 0e020c5a stopped on it), changes no stored value or counted result, and lands after the pilot passes its data gate, with a rebuild-pin check before and after. | ledger 2026-11-25e; `.planning/todos/pending/675-*` |

## 7. Auditor units as bg (todo 479)

Why: `indicagent-regime-coverage-auditor.service` and `indicagent-feature-parity-auditor.service` ran as root and left a root-owned `logs/regime_coverage_auditor.log`, which breaks a user-run import of the service module and its unit test with a `PermissionError`. Commit 2b0f849de adds `User=bg` to both units in the repo; the installed copies still run as root until copied.

```bash
cd /home/bg/dev/indicagent
sudo cp production/systemd/indicagent-regime-coverage-auditor.service production/systemd/indicagent-feature-parity-auditor.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo chown bg:bg logs/regime_coverage_auditor.log
```

Verify: `systemctl show -p User indicagent-regime-coverage-auditor.service` prints `User=bg`; `ls -l logs/regime_coverage_auditor.log` shows bg as owner; `.venv/bin/python -c "import services.regime_coverage_auditor"` exits 0.

## 8. Two small rulings (2026-11-26)

- Todo 383 (GSD `state.planned-phase` no-op, gap-checker's bare CONTEXT.md, `phase.add` reusing a number): the upstream feedback is outward-facing and yours to send. Recommendation: close the todo without sending; it is tooling outside the research machine.
- Todo 509: `shadow_registry` has 36 rows and no code reader. Recommendation: keep the table until the first book freeze (no cost, and the sealed shadow runner may want its shape), then drop it with a tombstone if still unread.
