# The full run (T6)

What this measures, most important first: whether one command can run for 2 to 3 hours here, how much Claude allowance a run uses, and how the engine's waiting behaves against LinkedIn's real limit. It has never met that limit before, so report what happens rather than fixing it.

`PROBE` and `ENGINE` are the paths given in `SKILL.md`. Everything goes in `<TEST-folder-path>/_probe-run/`. To run the engine's Python, set `PYTHONPATH` to `ENGINE/python/vendor`.

1. Run `python3 "PROBE" env --master "<TEST-folder-path>"`. If it answers `REFUSED`, stop here: this run must never start in a real folder. Then look at the `T5-write` row in `probe-report.jsonl`: if `ready_for_full_run` is not `true`, stop and tell the colleague to ask Yuwei for a test copy made with `make_test_copy.py`.
2. Ask the colleague which Master to test, to note the figures on Claude's usage page (Settings, Usage), to plug in the computer, and to keep the Claude app open.
3. In the background, start a timer that touches no network, so that a long-command problem cannot be mistaken for a LinkedIn one:
   `python3 "PROBE" longrun --master "<TEST-folder-path>" --label timer --seconds 10800`
4. Read `A1-regole-ricerca.md`, `A4-regole-registrazione.md` and that Master's A2 and A3 from the config folder.
5. Export the history:
   `python3 "ENGINE/python/sync_export.py" export-history --dir "<TEST-folder-path>" --out "<TEST-folder-path>/_probe-run/history.csv"`
6. Write `_probe-run/run.json` from A2 and A3, with the fields of `PipelineConfig` in the engine: `topK` 200, `cooldownMinutes` 20, `maxCooldowns` 12. No `recencyDays` and no derogations.
7. In the background, run the search:
   `python3 "PROBE" longrun --master "<TEST-folder-path>" --label discover -- node "ENGINE/lib/cli.js" discover --config "<TEST-folder-path>/_probe-run/run.json" --out "<TEST-folder-path>/_probe-run" --history "<TEST-folder-path>/_probe-run/history.csv"`
   This takes from minutes to about 2 hours, depending on how soon LinkedIn makes it wait.
8. Do not poll. Each look uses the allowance this test is measuring. Look at `probe-report.jsonl` at most once every 30 minutes, for a `T6-discover` row. If `T6-discover-start` is there with no `T6-discover` and `longrun-discover.heartbeat` has stopped growing, the command was killed: tell the colleague, and run the same command with the label `discover-2` and `--resume` added after `discover`.
9. In the same way, read the postings:
   `python3 "PROBE" longrun --master "<TEST-folder-path>" --label read -- node "ENGINE/lib/cli.js" read --cards "<TEST-folder-path>/_probe-run/cards.json" --out "<TEST-folder-path>/_probe-run" --top 60 --cooldown-minutes 20`
   If `read-report.json` shows `empty` above 0, report that: those pages held no posting.
10. Judge each posting that was read against A1 and the A2, and write `_probe-run/verdicts.json`. Copy each URL from `descriptions.json`; never compose one.
11. Do not run `stage` or `append`. Nothing from this run goes into a Review file.
12. Wait for the `T6-timer` row, then report: every `T6-*` row, `sources` (with `health.events429` and `cooldowns`) and `counters` from `run-report.json`, `read-report.json`, and how many postings you judged. Ask the colleague to note the usage figures again.
